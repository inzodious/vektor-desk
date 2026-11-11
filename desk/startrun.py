import json
import os
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk import jobrun, memory, review_health
from desk.config import Config
from desk.db import connect
from desk.packages import seam
from desk.runlock import run_dir

CREW = "/settings/crew"
DATA = "/settings/data"
BOX = "/settings/box"
RETRIES = 1
ADOPT_SLACK = timedelta(seconds=30)


@dataclass(frozen=True)
class Step:
    id: str
    job: str
    title: str
    desk: str = ""


STEPS = (
    Step("accounts", "mirror", "Pull your accounts"),
    Step("prices", "engine-backfill", "Fetch price history"),
    Step("numbers", "engine-daily", "Run today's numbers"),
    Step("market", "engine-french", "Fetch market history"),
    Step("review", "engine-review", "Write the results review"),
    Step("discounts", "engine-discounts", "Scan for discounts"),
    Step("plan_keeper", "agents-run-plan_keeper", "Check your plan", "plan_keeper"),
    Step("debrief", "agents-run-debrief", "Write the debrief", "debrief"),
    Step("plans", "agents-run-plans", "Draft your stock plans", "plans"),
    Step("paper", "engine-paper", "Run the paper race"),
)
BY_ID = {s.id: s for s in STEPS}
NEEDS_ACCOUNTS = ("prices", "numbers")
NEEDS_NUMBERS = ("review", "discounts", "plan_keeper", "debrief", "plans", "paper")
FIXES = (
    ("ALPACA", {"label": "Add the Alpaca paper keys", "to": DATA}),
    ("FINNHUB", {"label": "Add the Finnhub key", "to": DATA}),
    ("token", {"label": "Check the Claude token", "to": DATA}),
    ("Switched off", {"label": "Switch it on", "to": CREW}),
    ("guard", {"label": "Lift the guard", "to": CREW}),
)
DESK_FAILED = ("failed", "timeout")


# ---- Files ----


def folder(cfg: Config) -> Path:
    return run_dir(cfg) / "start"


def chain_file(cfg: Config) -> Path:
    return folder(cfg) / "chain.json"


def request_file(cfg: Config) -> Path:
    return folder(cfg) / "request.json"


def load(cfg: Config) -> dict | None:
    return jobrun._read(chain_file(cfg))


def save(cfg: Config, chain: dict) -> None:
    jobrun._write(chain_file(cfg), chain)


def take_request(cfg: Config) -> dict | None:
    path = request_file(cfg)
    req = jobrun._read(path)
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    return req or {}


# ---- Facts ----


@dataclass
class Facts:
    accounts: bool = False
    numbers: bool = False
    closes_ok: bool = False
    market: bool = False
    reviews: bool = False
    claude: str = "unknown"
    crew: dict | None = None


def _desk(cfg: Config) -> sqlite3.Connection | None:
    if not cfg.desk_db.exists():
        return None
    try:
        return connect(cfg.desk_db, readonly=True)
    except sqlite3.Error:
        return None


def engine_health(cfg: Config) -> dict:
    conn = _desk(cfg)
    if conn is None:
        return {"as_of": None, "checks": {}}
    try:
        day = conn.execute("SELECT max(as_of) FROM data_health").fetchone()[0]
        checks = {r["check_name"]: r["status"] for r in conn.execute("SELECT check_name, status FROM data_health WHERE as_of=?", (day,))} if day else {}
        return {"as_of": day, "checks": checks}
    except sqlite3.Error:
        return {"as_of": None, "checks": {}}
    finally:
        conn.close()


def rows(cfg: Config, table: str) -> int:
    conn = _desk(cfg)
    if conn is None:
        return 0
    try:
        return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]  # noqa: S608
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def crew(cfg: Config, now: datetime) -> dict | None:
    try:
        mod = seam("agents", "status")
        return mod.crew(cfg, now) if mod is not None else None
    except Exception:  # noqa: BLE001
        return None


def facts(cfg: Config, now: datetime | None = None, with_crew: bool = True) -> Facts:
    from desk.status import mirror_status, token_status

    now = now or jobrun.now_utc()
    health = engine_health(cfg)
    mirror = mirror_status(cfg, now)
    return Facts(
        accounts=bool(mirror.get("last_ok")),
        numbers=health["as_of"] is not None,
        closes_ok=health["checks"].get("closes") == "ok",
        market=rows(cfg, "french_returns") > 0,
        reviews=bool(review_health.packs(cfg)),
        claude=token_status(cfg, now.date())["state"],
        crew=crew(cfg, now) if with_crew else None,
    )


# ---- Decisions ----


def _crew_row(f: Facts, desk: str) -> dict | None:
    return next((d for d in (f.crew or {}).get("desks", []) if d.get("desk") == desk), None)


def desk_block(step: Step, f: Facts) -> tuple[str, dict] | None:
    if f.claude == "expired":
        return "The Claude token has expired, so no desk can write.", {"label": "Renew the token", "to": DATA}
    if f.crew is None:
        return None
    if not f.crew.get("enabled"):
        return "All desks are switched off.", {"label": "Switch the desks on", "to": CREW}
    row = _crew_row(f, step.desk)
    if row is None:
        return None
    if not row.get("enabled"):
        return f"The {row.get('title') or step.desk} is switched off.", {"label": "Switch it on", "to": CREW}
    if row.get("guarded"):
        return f"The first-run guard is holding the {row.get('title') or step.desk} back.", {"label": "Lift the guard", "to": CREW}
    return None


def skip_reason(step: Step, f: Facts) -> tuple[str, dict | None] | None:
    if step.id in NEEDS_ACCOUNTS and not f.accounts:
        return "It needs your accounts first, and the pull hasn't worked yet.", {"label": "Check the connection", "to": BOX}
    if step.id in NEEDS_NUMBERS and not f.numbers:
        return "It needs today's numbers first.", None
    if step.id == "prices" and f.closes_ok:
        return "Price history is already complete.", None
    if step.id == "market" and f.market:
        return "Market history is already here.", None
    if step.desk:
        blocked = desk_block(step, f)
        if blocked:
            return blocked
        if step.id == "debrief" and not f.reviews:
            return "It needs the results review first.", None
    return None


def fix_for(text: str | None) -> dict | None:
    return next((fix for word, fix in FIXES if word.lower() in (text or "").lower()), None)


def outcome(step: Step, run: dict | None, f: Facts, since: datetime | None) -> tuple[str, str | None, dict | None]:
    run = run or {}
    result = run.get("result")
    if result == "skipped":
        return "skipped", "Another run of this was already going; it finishes on its own.", None
    if result != "ok":
        said = run.get("error")
        words = f"It stopped: {said}" if said else "It stopped with an error. Settings, Box, Export logs shows why."
        return "failed", words, fix_for(said) or {"label": "Open Box", "to": BOX}
    if run.get("note"):
        return "skipped", run["note"], fix_for(run["note"])
    last = (_crew_row(f, step.desk) or {}).get("last_run") if step.desk else None
    began = review_health.parse((last or {}).get("started_at"))
    if last and began is not None and since is not None and began >= since - ADOPT_SLACK and last.get("status") not in (None, "ok", "running"):
        state = "failed" if last["status"] in DESK_FAILED else "skipped"
        words = jobrun.plain(last.get("note")) or f"The desk ended {last['status']}."
        return state, words, fix_for(words) or ({"label": "Open the crew", "to": CREW} if state == "failed" else None)
    return "ok", None, None


# ---- Chain ----


def blank(step: Step) -> dict:
    return {
        "id": step.id,
        "job": step.job,
        "title": step.title,
        "state": "waiting",
        "detail": None,
        "fix": None,
        "started_at": None,
        "finished_at": None,
        "request_id": None,
        "adopted": False,
        "tries": 0,
    }


def steps_for(names: set[str]) -> list[dict]:
    return [blank(s) for s in STEPS if s.job in names]


def new_chain(req: dict, names: set[str], previous: dict | None, now: datetime) -> dict:
    return {
        "id": str(req.get("id") or secrets.token_hex(6))[:32],
        "state": "running",
        "started_at": jobrun.stamp(now),
        "finished_at": None,
        "result": None,
        "last_ok_at": (previous or {}).get("last_ok_at"),
        "steps": steps_for(names),
    }


def _close(step: dict, state: str, detail: str | None, fix: dict | None, now: datetime) -> None:
    step.update(state=state, detail=detail, fix=fix, finished_at=jobrun.stamp(now))


def advance(
    cfg: Config,
    jobs: list,
    start: Callable[[object, str], None],
    busy: Callable[[str], bool],
    now: datetime | None = None,
    get_facts: Callable[[Config, datetime], Facts] = facts,
) -> dict | None:
    now = now or jobrun.now_utc()
    by_name: dict[str, object] = {}
    for job in jobs:
        by_name.setdefault(job.name, job)
    chain = load(cfg)
    req = take_request(cfg)
    if req is not None and (chain is None or chain.get("state") != "running"):
        chain = new_chain(req, set(by_name), chain, now)
        save(cfg, chain)
    if chain is None or chain.get("state") != "running":
        return chain
    known: Facts | None = None
    while True:
        step = next((s for s in chain["steps"] if s["state"] in ("running", "waiting")), None)
        if step is None:
            failed = any(s["state"] == "failed" for s in chain["steps"])
            chain.update(state="done", finished_at=jobrun.stamp(now), result="partial" if failed else "ok")
            if not failed:
                chain["last_ok_at"] = chain["finished_at"]
            break
        spec = BY_ID[step["id"]]
        job = by_name.get(step["job"])
        if job is None:
            _close(step, "skipped", "This desk doesn't schedule that job.", None, now)
            continue
        if step["state"] == "running":
            if busy(step["job"]):
                break
            run = jobrun.last_run(cfg, step["job"]) or {}
            mine = step["adopted"] or run.get("request_id") == step["request_id"]
            if not mine or not run.get("finished"):
                if step["tries"] <= RETRIES:
                    step.update(state="waiting", adopted=False, request_id=None)
                    continue
                _close(step, "failed", "The desk restarted while this was running.", {"label": "Open Box", "to": BOX}, now)
                continue
            known = get_facts(cfg, now)
            state, detail, fix = outcome(spec, run, known, review_health.parse(step["started_at"]))
            _close(step, state, detail, fix, now)
            continue
        known = known or get_facts(cfg, now)
        why = skip_reason(spec, known)
        if why is not None:
            _close(step, "skipped", why[0], why[1], now)
            continue
        step.update(state="running", started_at=jobrun.stamp(now), tries=step["tries"] + 1)
        if busy(step["job"]):
            step["adopted"] = True
        else:
            step["request_id"] = secrets.token_hex(6)
            start(job, step["request_id"])
        break
    save(cfg, chain)
    return chain


# ---- What the app sees ----


def needs_you(step: dict) -> bool:
    return step["state"] == "failed" or (step["state"] == "skipped" and step.get("fix") is not None)


def summary(chain: dict) -> str | None:
    steps = chain["steps"]
    if chain["state"] == "running":
        at = next((i for i, s in enumerate(steps) if s["state"] in ("running", "waiting")), None)
        return f"Step {at + 1} of {len(steps)}: {steps[at]['title']}" if at is not None else "Finishing up"
    if chain["state"] != "done":
        return None
    done = sum(1 for s in steps if s["state"] in ("ok", "skipped") and not needs_you(s))
    need = sum(1 for s in steps if needs_you(s))
    return f"{done} of {len(steps)} steps done." + (f" {need} {'needs' if need == 1 else 'need'} you." if need else "")


def describe(cfg: Config, jobs: list, now: datetime | None = None, known: Facts | None = None) -> dict:
    now = now or jobrun.now_utc()
    names = {j.name for j in jobs}
    chain = load(cfg)
    pending = jobrun._read(request_file(cfg))
    if pending is not None and (chain is None or chain.get("state") != "running"):
        chain = new_chain(pending, names, chain, jobrun.parse_stamp(pending.get("requested_at")) or now)
    if chain is None:
        chain = {"state": "idle", "started_at": None, "finished_at": None, "result": None, "last_ok_at": None, "steps": steps_for(names)}
    alive = jobrun.scheduler_alive(cfg, now)
    running = chain["state"] == "running"
    blocked = None
    if running:
        blocked = {"error": "running", "message": "The desk is starting now."}
    elif not alive:
        blocked = {"error": "scheduler_down", "message": "The cron service isn't running, so nothing would pick this up."}
    if chain.get("last_ok_at"):
        needs = False
    else:
        known = known or facts(cfg, now, with_crew=False)
        needs = not (known.accounts and known.numbers and known.reviews)
    keep = ("id", "title", "state", "detail", "fix", "job", "started_at", "finished_at")
    box = memory.status(cfg, now)
    turns = {w["job"] for w in box["waiting"]}
    steps = [{k: s.get(k) for k in keep} for s in chain["steps"]]
    for step in steps:
        step["waiting"] = step["state"] == "running" and step["job"] in turns
        if step["waiting"]:
            step["detail"] = "Waiting for its turn: low-memory mode runs heavy jobs one at a time."
    return {
        "state": chain["state"],
        "needs_start": needs,
        "can_start": blocked is None,
        "blocked": blocked,
        "result": chain.get("result"),
        "summary": summary(chain),
        "started_at": chain.get("started_at"),
        "finished_at": chain.get("finished_at"),
        "last_ok_at": chain.get("last_ok_at"),
        "scheduler_alive": alive,
        "memory": {"state": box["state"], "low_memory": box["low_memory"]["on"], "killed": len(box["killed"]), "note": box["note"]},
        "steps": steps,
    }


def request_start(cfg: Config, jobs: list, client: str | None = None, now: datetime | None = None) -> tuple[int, dict]:
    now = now or jobrun.now_utc()

    def answer(code: int, outcome: str, body: dict) -> tuple[int, dict]:
        jobrun.log_request(cfg, {"at": jobrun.stamp(now), "job": "start", "client": client, "outcome": outcome})
        return code, body

    chain = load(cfg)
    if (chain or {}).get("state") == "running" or request_file(cfg).exists():
        return answer(409, "running", {"ok": False, "error": "running", "message": "The desk is already starting."} | describe(cfg, jobs, now))
    if not jobrun.scheduler_alive(cfg, now):
        return answer(
            503, "scheduler_down", {"ok": False, "error": "scheduler_down", "message": "The cron service isn't running, so nothing would pick this up."}
        )
    req = {"id": secrets.token_hex(6), "requested_at": jobrun.stamp(now), "client": client}
    folder(cfg).mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(request_file(cfg), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return answer(409, "running", {"ok": False, "error": "running", "message": "The desk is already starting."} | describe(cfg, jobs, now))
    with os.fdopen(fd, "w") as f:
        json.dump(req, f)
    return answer(202, "queued", {"ok": True} | describe(cfg, jobs, now))


# ---- API ----

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/start")
def get_start(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg, jobrun._jobs(request)), headers=NO_STORE)


@router.post("/api/start")
def post_start(request: Request) -> JSONResponse:
    client = request.client.host if request.client else None
    code, body = request_start(request.app.state.cfg, jobrun._jobs(request), client)
    return JSONResponse(body, status_code=code, headers=NO_STORE)
