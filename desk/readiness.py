import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk import jobrun, memory, review_health, startrun
from desk.config import Config
from desk.packages import seam
from desk.runlock import running

KINDS = ("day", "week", "month", "year")
START = {"kind": "start", "label": "Start the desk"}
MIXES_AFTER = ("engine-daily", "Run the numbers now")
PASS_HEADERS = (b"host", b"cookie", b"authorization", b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host")
HORIZON_DAYS = 40


@dataclass(frozen=True)
class Section:
    key: str
    probe: str
    ready: Callable[[object], bool]
    job: str = ""
    label: str = "Run it now"
    empty: str = "Nothing here yet."
    needs: tuple[str, ...] = ()
    desk: str = ""
    quiet: str = ""
    link: tuple[str, str] | None = None
    note: bool = False


def _has(*path: str) -> Callable[[object], bool]:
    def check(body: object) -> bool:
        for part in path:
            body = body.get(part) if isinstance(body, dict) else None
        return bool(body)

    return check


def _review(kind: str) -> Section:
    return Section(
        f"results.{kind}",
        "/api/engine/reviews/index",
        _has("kinds", kind),
        job="engine-review",
        label="Write it now",
        empty=f"No {kind} review yet: the results review hasn't run.",
        needs=("bridge.value",),
        quiet=f"The review ran, but there isn't enough history for a {kind} review yet.",
    )


SECTIONS = (
    Section(
        "bridge.value",
        "/api/engine/value",
        _has("series"),
        job="engine-daily",
        label="Run the numbers now",
        empty="No value history yet: today's numbers haven't run.",
        needs=("accounts",),
    ),
    Section(
        "bridge.brief",
        "/api/agents/brief",
        _has("summary"),
        job="agents-run-plan_keeper",
        label="Write it now",
        empty="No brief yet: the Plan keeper hasn't written one.",
        needs=("bridge.value",),
        desk="plan_keeper",
    ),
    *(_review(kind) for kind in KINDS),
    Section(
        "results.debrief",
        "/api/engine/reviews?kind=day",
        _has("debrief"),
        job="agents-run-debrief",
        label="Write it now",
        empty="No debrief yet: the Debrief desk hasn't read the latest review.",
        needs=("results.day",),
        desk="debrief",
    ),
    Section(
        "portfolio.holdings",
        "/api/engine/holdings",
        _has("rows"),
        job="engine-daily",
        label="Run the numbers now",
        empty="No holdings yet: today's numbers haven't run.",
        needs=("accounts",),
    ),
    Section(
        "portfolio.stock_plans",
        "/api/decisions/plans",
        _has("items"),
        job="agents-run-plans",
        label="Draft them now",
        empty="No stock plans yet: the Plan desk hasn't drafted any.",
        needs=("portfolio.holdings",),
        desk="plans",
        quiet="The Plan desk ran and had nothing to draft. You can write one yourself on this page.",
    ),
    Section(
        "portfolio.risk",
        "/api/engine/lookthrough",
        _has("as_of"),
        job="engine-daily",
        label="Run the numbers now",
        empty="No risk picture yet: today's numbers haven't run.",
        needs=("accounts",),
    ),
    Section(
        "portfolio.tax",
        "/api/engine/metrics?ids=tax.*",
        _has("metrics"),
        job="engine-daily",
        label="Run the numbers now",
        empty="No tax picture yet: today's numbers haven't run.",
        needs=("accounts",),
    ),
    Section(
        "strategies.race",
        "/api/engine/lab/leaderboard",
        _has("rows"),
        job="engine-paper",
        label="Run the paper race now",
        empty="No strategies are paper trading yet.",
        needs=("bridge.value",),
        note=True,
    ),
    Section(
        "strategies.mixes",
        "/api/engine/bands",
        lambda body: isinstance(body, dict) and body.get("status") not in (None, "not_ready"),
        job="engine-french",
        label="Fetch market history now",
        empty="No mixes yet: they need the monthly market history.",
        needs=("bridge.value",),
    ),
    Section(
        "strategies.habits",
        "/api/engine/patterns",
        _has("as_of"),
        job="engine-daily",
        label="Run the numbers now",
        empty="No habits yet: today's numbers haven't run.",
        needs=("accounts",),
    ),
    Section(
        "decisions.queue",
        "/api/decisions/queue",
        _has("count"),
        job="agents-run-plan_keeper",
        label="Check the plan now",
        empty="Nothing to decide yet: the Plan keeper hasn't run.",
        needs=("bridge.value",),
        desk="plan_keeper",
        quiet="ready",
    ),
    Section(
        "decisions.journal",
        "/api/decisions/journal",
        _has("count"),
        empty="Nothing logged yet. What you approve or pass lands here.",
        link=("/decisions", "Open the queue"),
    ),
    Section(
        "research.feed",
        "/api/agents/dossiers",
        bool,
        job="agents-run-research",
        label="Research now",
        empty="No dossiers yet: the Research desk hasn't run.",
        needs=("portfolio.holdings",),
        desk="research",
        quiet="The Research desk ran and wrote nothing new.",
    ),
    Section("research.boards", "", lambda body: True),
    Section(
        "settings.risk_check",
        "/api/decisions/risk",
        _has("current"),
        empty="You haven't answered the risk check yet.",
        link=("/settings/risk", "Answer it"),
    ),
)
BY_KEY = {s.key: s for s in SECTIONS}


# ---- Reading the app's own answers ----


async def fetch(app, path: str, headers: list[tuple[bytes, bytes]]) -> object:
    parts = urlsplit(path)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parts.path,
        "raw_path": parts.path.encode(),
        "query_string": parts.query.encode(),
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("readiness", 80),
    }
    state = {"status": 0, "body": bytearray()}

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["body"].extend(message.get("body", b""))

    try:
        await app(scope, receive, send)
        return json.loads(bytes(state["body"])) if state["status"] == 200 else None
    except Exception:  # noqa: BLE001
        return None


async def answers(request: Request, paths: list[str]) -> dict[str, object]:
    headers = [(k, v) for k, v in request.scope.get("headers", []) if k in PASS_HEADERS]
    bodies = await asyncio.gather(*(fetch(request.app, p, headers) for p in paths))
    return dict(zip(paths, bodies, strict=True))


# ---- When the schedule would get to it ----


def next_due(jobs: list, name: str, now: datetime, zone: ZoneInfo) -> datetime | None:
    local = now.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    best = None
    for job in jobs:
        if job.name != name:
            continue
        minutes, hours = sorted(job.spec[0]), sorted(job.spec[1])
        for offset in range(HORIZON_DAYS):
            day = (local + timedelta(days=offset)).date()
            found = next((t for h in hours for m in minutes if (t := datetime.combine(day, time(h, m), tzinfo=zone)) >= local and job.due(t)), None)
            if found is not None:
                best = found if best is None else min(best, found)
                break
    return best


def when_text(t: datetime, now: datetime, zone: ZoneInfo) -> str:
    local, today = t.astimezone(zone), now.astimezone(zone).date()
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    gap = (local.date() - today).days
    day = "today" if gap == 0 else "tomorrow" if gap == 1 else local.strftime("%a") if gap < 7 else f"{local.strftime('%b')} {local.day}"
    return f"{day} at {clock}"


# ---- The map ----


def _row(key: str, state: str, why: str | None = None, action: dict | None = None, due: datetime | None = None, now: datetime | None = None, zone=None) -> dict:
    return {
        "key": key,
        "state": state,
        "why": why,
        "action": action,
        "next_auto": jobrun.stamp(due) if due else None,
        "next_auto_text": when_text(due, now, zone) if due else None,
    }


def _first(text: object) -> str | None:
    words = jobrun.plain(text)
    return words.split(". ")[0].rstrip(".") + "." if words else None


def build(cfg: Config, jobs: list, bodies: dict[str, object], now: datetime | None = None, known: startrun.Facts | None = None) -> dict:
    now = now or jobrun.now_utc()
    zone = ZoneInfo(cfg.timezone)
    known = known or startrun.facts(cfg, now)
    start = startrun.describe(cfg, jobs, now, known)
    names = {j.name for j in jobs}
    chain_jobs = {s.job for s in startrun.STEPS}
    held = {r["job"] for r in running(cfg)}
    turns = {w["job"] for w in memory.waiting(cfg)}
    entries = jobrun.catalogue(jobs)
    reviews = review_health.reviews_status(cfg, now)
    rows: dict[str, dict] = {}

    def desk_ran_ok(desk: str) -> bool:
        return ((startrun._crew_row(known, desk) or {}).get("last_run") or {}).get("status") == "ok"

    def solve(s: Section) -> dict:
        body = bodies.get(s.probe) if s.probe else None
        if s.ready(body):
            if s.key.startswith("results.") and s.key != "results.debrief" and reviews["state"] in ("stale", "failing"):
                why = "The last review is behind: " + ("the latest run failed." if reviews["state"] == "failing" else "today's run hasn't happened.")
                return _row(s.key, "stale", why, {"kind": "job", "job": s.job, "label": "Write it now"}, next_due(jobs, s.job, now, zone), now, zone)
            return _row(s.key, "ready")
        if s.link:
            return _row(s.key, "blocked" if s.key.startswith("settings.") else "empty", s.empty, {"kind": "link", "to": s.link[0], "label": s.link[1]})
        for need in s.needs:
            if need == "accounts":
                if not known.accounts:
                    return _row(s.key, "empty", "Your accounts haven't been pulled yet.", dict(START))
                continue
            other = rows[need] if need in rows else solve(BY_KEY[need])
            if other["state"] not in ("ready", "stale"):
                return _row(s.key, other["state"], f"It needs {NEED_WORDS.get(need, 'an earlier step')} first.", other["action"])
        if s.job not in names:
            return _row(s.key, "empty", s.empty, dict(START) if start["needs_start"] else {"kind": "link", "to": startrun.BOX, "label": "Open Box"})
        if s.desk:
            blocked = startrun.desk_block(startrun.Step(s.key, s.job, s.key, s.desk), known)
            if blocked:
                return _row(s.key, "blocked", blocked[0], {"kind": "link", "to": blocked[1]["to"], "label": blocked[1]["label"]})
        job, label = MIXES_AFTER if s.key == "strategies.mixes" and known.market and MIXES_AFTER[0] in names else (s.job, s.label)
        due = next_due(jobs, job, now, zone)
        if start["needs_start"] and job in chain_jobs:
            return _row(s.key, "empty", s.empty, dict(START), due, now, zone)
        action = {"kind": "job", "job": job, "label": label}
        if entries[job].locks & held:
            return _row(s.key, "empty", "It's running now. This fills in when it finishes.", action, due, now, zone)
        if job in turns:
            return _row(s.key, "empty", "It's waiting for its turn: low-memory mode runs heavy jobs one at a time.", action, due, now, zone)
        run = jobrun.last_run(cfg, job) or {}
        said = _first(body.get("note")) if s.note and isinstance(body, dict) else None
        if run.get("result") == "failed":
            why = f"The last try stopped: {run['error']}" if run.get("error") else "The last try stopped with an error."
            return _row(s.key, "empty", why, action | {"label": "Try again"}, due, now, zone)
        ran = desk_ran_ok(s.desk) if s.desk else run.get("result") == "ok" and not run.get("note")
        if ran and s.quiet == "ready":
            return _row(s.key, "ready")
        if run.get("result") == "ok" and run.get("note"):
            fix = startrun.fix_for(run["note"])
            link = {"kind": "link", "to": fix["to"], "label": fix["label"]} if fix else None
            return _row(s.key, "blocked" if link else "empty", run["note"], link or action, None if link else due, now, zone)
        return _row(s.key, "empty", said or (s.quiet if ran and s.quiet else s.empty), action, due, now, zone)

    for section in SECTIONS:
        rows[section.key] = solve(section)
    return {
        "now": jobrun.stamp(now),
        "start": {"state": start["state"], "needs_start": start["needs_start"]},
        "memory": start["memory"],
        "sections": [rows[s.key] for s in SECTIONS],
    }


NEED_WORDS = {
    "bridge.value": "today's numbers",
    "results.day": "the results review",
    "portfolio.holdings": "your holdings",
}


def overrides(cfg: Config, report: dict) -> dict:
    for pkg in ("engine", "agents", "decisions"):
        try:
            mod = seam(pkg, "readiness")
            extra = mod.sections(cfg) if mod is not None else {}
        except Exception:  # noqa: BLE001
            extra = {}
        for row in report["sections"]:
            if isinstance(extra.get(row["key"]), dict):
                row.update({k: v for k, v in extra[row["key"]].items() if k in ("state", "why", "action", "next_auto", "next_auto_text")})
    return report


# ---- API ----

router = APIRouter()


@router.get("/api/readiness")
async def get_readiness(request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    paths = sorted({s.probe for s in SECTIONS if s.probe})
    bodies = await answers(request, paths)
    report = await asyncio.to_thread(lambda: overrides(cfg, build(cfg, jobrun._jobs(request), bodies)))
    return JSONResponse(report, headers={"Cache-Control": "no-store"})
