import importlib
import json
import os
import secrets
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk import jobrun
from desk.config import Config
from desk.runlock import run_dir

START = time(23, 30)
FRESH_UNTIL = time(3, 0)
END = time(6, 30)
EVENING_FROM = time(16, 0)
EVENING = {"mirror": 10, "engine-daily": 20, "engine-review": 30, "engine-discounts": 40, "agents-run-plan_keeper": 50, "agents-run-debrief": 60}
RETRIES = 2
RESTARTS = 6
GAP_MAX = timedelta(minutes=10)
GAP_AFTER = timedelta(seconds=60)
HOST_SILENT = timedelta(minutes=20)
BEAT = timedelta(minutes=3)
READY_CALLS = ("desk.engine.lab.shelf", "desk.opportunities")
READY_MAX = 120
OPEN = ("waiting", "running")
RAN_OUT = "The night ran out before its turn."
ALERT_TOPIC = "research"


# ---- The night ----


def local(cfg: Config, now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(cfg.timezone))


def night_of(at: datetime) -> str | None:
    if at.time() >= START:
        return at.date().isoformat()
    if at.time() < END:
        return (at.date() - timedelta(days=1)).isoformat()
    return None


def fresh(at: datetime) -> bool:
    return at.time() >= START or at.time() < FRESH_UNTIL


def evening_from(cfg: Config, night: str) -> datetime:
    return datetime.combine(date.fromisoformat(night), EVENING_FROM, ZoneInfo(cfg.timezone))


def build() -> str:
    return os.environ.get("DESK_BUILD") or "dev"


# ---- Files ----


def folder(cfg: Config) -> Path:
    return run_dir(cfg) / "overnight"


def chain_file(cfg: Config) -> Path:
    return folder(cfg) / "chain.json"


def load(cfg: Config) -> dict | None:
    chain = jobrun._read(chain_file(cfg))
    return chain if chain and isinstance(chain.get("steps"), list) else None


def save(cfg: Config, chain: dict, now: datetime) -> None:
    chain["beat"] = jobrun.stamp(now)
    jobrun._write(chain_file(cfg), chain)


def live_since(cfg: Config, now: datetime, write: bool = True) -> datetime:
    path = folder(cfg) / "build.json"
    seen = jobrun._read(path) or {}
    since = jobrun.parse_stamp(seen.get("since"))
    if seen.get("build") == build() and since is not None:
        return since
    if write:
        jobrun._write(path, {"build": build(), "since": jobrun.stamp(now)})
    return now


def active(cfg: Config) -> bool:
    return (load(cfg) or {}).get("state") == "running"


def covers(cfg: Config, name: str, now: datetime) -> bool:
    chain = load(cfg)
    if chain is None or chain.get("night") != night_of(local(cfg, now)):
        return False
    step = next((s for s in chain["steps"] if s["job"] == name and s["kind"] == "night"), None)
    if step is None:
        return False
    beat = jobrun.parse_stamp(chain.get("beat"))
    alive = beat is not None and now - beat <= BEAT
    return step["state"] == "ok" or (step["state"] in OPEN and alive)


# ---- Steps ----


def order(jobs: list) -> list[tuple[int, str, str, str]]:
    rows: dict[str, tuple[int, str, str, str]] = {}
    for job in jobs:
        place = getattr(job, "overnight", None)
        if place is None and job.name in EVENING:
            rows.setdefault(job.name, (EVENING[job.name], job.name, job.title, "evening"))
        elif place is not None and (job.name not in rows or rows[job.name][3] == "evening" or place < rows[job.name][0]):
            rows[job.name] = (int(place), job.name, job.title, "night")
    return sorted(rows.values())


def blank(row: tuple[int, str, str, str]) -> dict:
    place, name, title, kind = row
    return {
        "id": name,
        "job": name,
        "title": title,
        "order": place,
        "kind": kind,
        "state": "waiting",
        "detail": None,
        "ready": None,
        "started_at": None,
        "finished_at": None,
        "request_id": None,
        "adopted": False,
        "tries": 0,
    }


def new_chain(night: str, jobs: list, now: datetime, restarts: int = 0, started_at: str | None = None) -> dict:
    return {
        "night": night,
        "build": build(),
        "state": "running",
        "started_at": started_at or jobrun.stamp(now),
        "finished_at": None,
        "restarts": restarts,
        "gap_from": None,
        "steps": [blank(row) for row in order(jobs)],
    }


def _close(step: dict, state: str, detail: str | None, now: datetime, ready: str | None = None) -> None:
    step.update(state=state, detail=detail, ready=ready, finished_at=jobrun.stamp(now))


def outcome(run: dict | None) -> tuple[str, str | None, str | None]:
    run = run or {}
    if run.get("result") == "skipped":
        return "skipped", "Another run of this was already going; it finishes on its own.", None
    if run.get("result") != "ok":
        said = run.get("error")
        return "failed", f"It stopped: {said}" if said else "It stopped with an error. Settings, Box, Export logs shows why.", None
    if run.get("note"):
        return "skipped", run["note"], None
    ready = jobrun.plain(run.get("ready"))
    return "ok", None, ready[:READY_MAX] if ready else None


def evening_skip(cfg: Config, name: str, since: datetime, evening: datetime) -> str | None:
    if since < evening:
        return "No new version went live since this evening's run."
    run = jobrun.last_run(cfg, name) or {}
    began = jobrun.parse_stamp(run.get("started"))
    if run.get("result") == "ok" and run.get("finished") and began is not None and began >= since:
        return "It already ran on the version that is live."
    return None


def host_seen(cfg: Config) -> datetime | None:
    try:
        return jobrun.parse_stamp((run_dir(cfg) / "box" / "host.alive").read_text().strip())
    except OSError:
        return None


def hold_for_host(cfg: Config, since: datetime | None, now: datetime) -> bool:
    seen = host_seen(cfg)
    if since is None or seen is None or now - seen > HOST_SILENT or now - since > GAP_MAX:
        return False
    return seen - since < GAP_AFTER


def _settle(cfg: Config, chain: dict, step: dict, now: datetime) -> bool:
    run = jobrun.last_run(cfg, step["job"]) or {}
    mine = step["adopted"] or run.get("request_id") == step["request_id"]
    if not mine or not run.get("finished"):
        if step["tries"] <= RETRIES:
            step.update(state="waiting", adopted=False, request_id=None)
            return False
        _close(step, "failed", "The desk restarted while this was running, more than once.", now)
        return True
    state, detail, ready = outcome(run)
    _close(step, state, detail, now, ready)
    chain["gap_from"] = jobrun.stamp(now)
    return True


def _finish(chain: dict, now: datetime) -> None:
    chain.update(state="done", finished_at=jobrun.stamp(now), gap_from=None)


def _run_out(cfg: Config, chain: dict, busy: Callable[[str], bool], now: datetime) -> None:
    for step in chain["steps"]:
        if step["state"] == "waiting":
            _close(step, "skipped", RAN_OUT, now)
    step = next((s for s in chain["steps"] if s["state"] == "running"), None)
    if step is not None:
        if busy(step["job"]):
            return
        if not _settle(cfg, chain, step, now):
            _close(step, "skipped", RAN_OUT, now)
    _finish(chain, now)


def _carry_on(chain: dict, jobs: list) -> None:
    chain["build"] = build()
    known = {s["job"] for s in chain["steps"]}
    added = [blank(row) for row in order(jobs) if row[1] not in known]
    if added:
        chain["steps"] = sorted(chain["steps"] + added, key=lambda s: (s["order"], s["job"]))
        chain.update(state="running", finished_at=None)


def advance(cfg: Config, jobs: list, start: Callable[[object, str], object], busy: Callable[[str], bool], now: datetime | None = None) -> dict | None:
    now = now or jobrun.now_utc()
    at = local(cfg, now)
    night = night_of(at)
    since = live_since(cfg, now)
    chain = load(cfg)
    if chain is not None and chain["state"] == "running" and chain["night"] != night:
        _run_out(cfg, chain, busy, now)
        save(cfg, chain, now)
        if chain["state"] == "running":
            return chain
    if night is None:
        return chain
    if chain is None or chain["night"] != night:
        chain = new_chain(night, jobs, now)
    elif chain["build"] != build():
        if fresh(at) and chain["restarts"] < RESTARTS:
            chain = new_chain(night, jobs, now, chain["restarts"] + 1, chain["started_at"])
        else:
            _carry_on(chain, jobs)
    if chain["state"] != "running":
        save(cfg, chain, now)
        return chain
    by_name: dict[str, object] = {}
    for job in jobs:
        by_name.setdefault(job.name, job)
    evening = evening_from(cfg, night)
    while True:
        step = next((s for s in chain["steps"] if s["state"] in OPEN), None)
        if step is None:
            _finish(chain, now)
            break
        job = by_name.get(step["job"])
        if step["state"] == "running":
            if busy(step["job"]):
                break
            _settle(cfg, chain, step, now)
            continue
        if job is None:
            _close(step, "skipped", "This desk doesn't schedule that job.", now)
            continue
        why = evening_skip(cfg, step["job"], since, evening) if step["kind"] == "evening" else None
        if why is not None:
            _close(step, "skipped", why, now)
            continue
        if hold_for_host(cfg, jobrun.parse_stamp(chain.get("gap_from")), now):
            break
        chain["gap_from"] = None
        step.update(state="running", started_at=jobrun.stamp(now), tries=step["tries"] + 1)
        if busy(step["job"]):
            step["adopted"] = True
        else:
            step["request_id"] = secrets.token_hex(6)
            start(job, step["request_id"])
        break
    save(cfg, chain, now)
    return chain


# ---- What is ready ----


def ready_lines(cfg: Config, chain: dict | None) -> list[str]:
    lines = [s["ready"] for s in (chain or {}).get("steps", []) if s.get("ready")]
    for path in READY_CALLS:
        try:
            said = importlib.import_module(path).ready(cfg)
        except Exception:  # noqa: BLE001, S112
            continue
        said = jobrun.plain(said)
        if said and said[:READY_MAX] not in lines:
            lines.append(said[:READY_MAX])
    return lines


def unfinished(chain: dict | None) -> list[dict]:
    rows = []
    for step in (chain or {}).get("steps", []):
        if step["state"] == "failed" or step["state"] in OPEN or (step["state"] == "skipped" and step.get("detail") == RAN_OUT):
            rows.append(step)
    return rows


def summary(chain: dict | None) -> str:
    if chain is None:
        return f"Tonight's run starts at {START:%H:%M}."
    steps = chain["steps"]
    if chain["state"] == "running":
        at = next((i for i, s in enumerate(steps) if s["state"] in OPEN), None)
        return f"Step {at + 1} of {len(steps)}: {steps[at]['title']}" if at is not None else "Finishing up"
    left = unfinished(chain)
    done = len(steps) - len(left)
    return f"{done} of {len(steps)} steps done." + (f" Not done: {', '.join(s['title'] for s in left[:3])}." if left else "")


def describe(cfg: Config, jobs: list, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    at = local(cfg, now)
    chain = load(cfg)
    night = night_of(at) or at.date().isoformat()
    if chain is None or (chain["night"] != night and chain["state"] != "running" and night_of(at) is not None):
        chain = None
    keep = ("id", "job", "title", "state", "detail", "ready", "started_at", "finished_at")
    steps = chain["steps"] if chain else [blank(row) for row in order(jobs)]
    return {
        "night": chain["night"] if chain else night,
        "state": chain["state"] if chain else "idle",
        "started_at": (chain or {}).get("started_at"),
        "finished_at": (chain or {}).get("finished_at"),
        "build": (chain or {}).get("build"),
        "restarts": (chain or {}).get("restarts", 0),
        "starts": f"{START:%H:%M}",
        "ends": f"{END:%H:%M}",
        "summary": summary(chain),
        "steps": [{k: s.get(k) for k in keep} for s in steps],
        "ready": ready_lines(cfg, chain),
    }


# ---- The morning alert ----


def alert_words(cfg: Config, now: datetime) -> tuple[str, str, str] | None:
    at = local(cfg, now)
    chain = load(cfg)
    last = (at.date() - timedelta(days=1)).isoformat()
    if chain is not None and chain["night"] != last:
        chain = None
    ready = ready_lines(cfg, chain)
    left = unfinished(chain)
    if not ready and chain is None:
        return None
    body = ". ".join(line.rstrip(".") for line in ready) + ("." if ready else "")
    if left:
        body = (body + " " if body else "") + f"Not done: {', '.join(s['title'] for s in left[:3])}."
    if not body:
        body = "The overnight run finished with nothing new to show."
    title = "Your desk is ready for this morning" if ready else "The overnight run didn't finish"
    return title, body, f"overnight-{last}"


def alert(cfg: Config, now: datetime | None = None) -> dict:
    from desk import notify

    words = alert_words(cfg, now or jobrun.now_utc())
    if words is None:
        return {"skipped": "No overnight run to report."}
    title, body, key = words
    sent = notify.publish(ALERT_TOPIC, title, body, tags=["sunrise"], click="/", key=key, cfg=cfg)
    return {"sent": sent, "title": title, "body": body}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = Config.from_env()
    if argv == ["alert"]:
        print(json.dumps(alert(cfg)))
        return 0
    if not argv:
        from desk.scheduler import all_jobs

        print(json.dumps(describe(cfg, all_jobs()), indent=2))
        return 0
    print("usage: python -m desk.overnight [alert]", file=sys.stderr)
    return 2


# ---- API ----

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/overnight")
def get_overnight(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg, jobrun._jobs(request)), headers=NO_STORE)


if __name__ == "__main__":
    sys.exit(main())
