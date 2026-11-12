import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk.config import Config
from desk.runlock import run_dir, running

COOLDOWN = timedelta(minutes=5)
PICKUP_SECONDS = 5
ALIVE_WITHIN = timedelta(seconds=90)
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SECRETISH = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
SAID_MAX = 300
KEEP_RUNS = 10
FIELD_MAX = 80
SPOKEN = ("skipped", "error", "ready", "detail")

REFRESHES = {
    "mirror": ["freshness", "holdings", "value"],
    "engine-daily": ["holdings", "value", "closes"],
    "engine-backfill": ["closes"],
    "engine-research": ["research"],
    "engine-lots": ["shares"],
    "engine-review": ["reviews"],
    "agents-run-debrief": ["debrief"],
    "agents-run-plans": ["plans"],
}
STAGE_ORDER = ("mirror", "engine", "review", "desks", "paper", "overnight")
STAGES = {
    "mirror": "mirror",
    "engine-daily": "engine",
    "engine-review": "review",
    "agents-run-plan_keeper": "desks",
    "agents-run-debrief": "desks",
    "agents-run-plans": "desks",
    "engine-paper": "paper",
}


# ---- Names ----


def job_name(pkg: str, command: list[str], name: str | None = None) -> str:
    if name:
        raw = f"{pkg}-{name}"
    else:
        words = list(command)
        if "-m" in words:
            words = words[words.index("-m") + 1 :]
        if words and words[0].startswith("desk."):
            words[0] = words[0].split(".", 1)[1]
        raw = "-".join(w.lstrip("-") for w in words[:4])
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")[:64]
    return slug or pkg


def job_title(name: str) -> str:
    words = name.replace("_", " ").split("-")
    return " ".join(words).capitalize()


# ---- Files ----


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def stamp(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_stamp(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def plain(text: object) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    return SECRETISH.sub("…", " ".join(text.split()))[:SAID_MAX]


def _short(value: object) -> str:
    if isinstance(value, dict):
        return f"{len(value)} fields"
    if isinstance(value, list):
        return f"{len(value)} items"
    text = value if isinstance(value, str) else json.dumps(value)
    text = " ".join(text.split())
    return text if len(text) <= FIELD_MAX else f"{text[:FIELD_MAX]}…"


def fields(said: dict) -> str | None:
    out = ""
    for key, value in said.items():
        if key in SPOKEN:
            continue
        more = f"{out}; {key}: {_short(value)}" if out else f"{key}: {_short(value)}"
        if len(more) > SAID_MAX - 2:
            out += "; …"
            break
        out = more
    return plain(out)


def last_words(line: str) -> dict:
    whole = plain(line)
    try:
        said = json.loads(line)
    except ValueError:
        if line.strip().startswith(("{", "[")) or line.strip().endswith(("}", "]")):
            return {"error": whole}
        return {"error": whole, "detail": whole, "said": whole} if whole else {}
    if not isinstance(said, dict):
        return {"said": _short(said)}
    skipped = said.get("skipped")
    words = {key: plain(said.get(key)) for key in ("error", "ready", "detail")}
    return {"skipped": plain(skipped) if isinstance(skipped, str) else None, **words, "said": fields(said)}


def state_dir(cfg: Config) -> Path:
    return run_dir(cfg) / "jobs"


def requests_dir(cfg: Config) -> Path:
    return run_dir(cfg) / "requests"


def alive_file(cfg: Config) -> Path:
    return run_dir(cfg) / "scheduler.alive"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True))
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def history_file(cfg: Config, name: str) -> Path:
    return run_dir(cfg) / "jobs-history" / f"{name}.json"


def runs(cfg: Config, name: str) -> list[dict]:
    kept = (_read(history_file(cfg, name)) or {}).get("runs")
    return [r for r in kept if isinstance(r, dict)] if isinstance(kept, list) else []


def record(cfg: Config, name: str, run: dict) -> None:
    _write(state_dir(cfg) / f"{name}.json", run)
    if not run.get("finished"):
        return
    try:
        _write(history_file(cfg, name), {"runs": [run, *runs(cfg, name)][:KEEP_RUNS]})
    except OSError:
        return


def last_run(cfg: Config, name: str) -> dict | None:
    return _read(state_dir(cfg) / f"{name}.json")


def heartbeat(cfg: Config) -> None:
    path = alive_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stamp(now_utc()))


def scheduler_alive(cfg: Config, now: datetime) -> bool:
    seen = parse_stamp(_read_text(alive_file(cfg)))
    return seen is not None and now - seen <= ALIVE_WITHIN


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def log_request(cfg: Config, entry: dict) -> None:
    path = run_dir(cfg) / "job-requests.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def take_requests(cfg: Config) -> list[tuple[str, dict]]:
    folder = requests_dir(cfg)
    taken = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        req = _read(path) or {}
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        taken.append((path.stem, req))
    return taken


# ---- Catalogue ----


@dataclass
class Entry:
    name: str
    title: str
    package: str
    schedules: list[str] = field(default_factory=list)
    locks: set[str] = field(default_factory=set)
    refreshes: list[str] = field(default_factory=list)
    stage: str | None = None


def catalogue(jobs: list) -> dict[str, Entry]:
    out: dict[str, Entry] = {}
    for job in jobs:
        entry = out.setdefault(job.name, Entry(job.name, job.title, job.package))
        if job.timing not in entry.schedules:
            entry.schedules.append(job.timing)
        entry.locks.update({job.lock, job.name} - {""})
        for check in getattr(job, "refreshes", None) or REFRESHES.get(job.name, []):
            if check not in entry.refreshes:
                entry.refreshes.append(check)
        stage = getattr(job, "stage", "") or STAGES.get(job.name) or ("overnight" if getattr(job, "overnight", None) is not None else None)
        if stage in STAGE_ORDER:
            entry.stage = stage
    return out


def describe(cfg: Config, jobs: list, now: datetime | None = None) -> dict:
    now = now or now_utc()
    from desk import memory

    held = {r["job"]: r.get("since") for r in running(cfg)}
    low = memory.low_memory(cfg, now)
    turns = _read(memory.waiting_file(cfg)) or {}
    why = memory.waiting_for(cfg) if turns else None
    rows = []
    for entry in catalogue(jobs).values():
        since = next((held[lock] for lock in sorted(entry.locks) if lock in held), None)
        is_running = any(lock in held for lock in entry.locks)
        pending = _read(requests_dir(cfg) / f"{entry.name}.json")
        turn = turns.get(entry.name) if isinstance(turns.get(entry.name), dict) else None
        until = cooldown_until(cfg, entry.name)
        cooling = until is not None and until > now
        rows.append(
            {
                "name": entry.name,
                "title": entry.title,
                "package": entry.package,
                "schedules": entry.schedules,
                "running": is_running,
                "running_since": since,
                "queued": pending is not None,
                "queued_at": (pending or {}).get("requested_at"),
                "waiting": turn is not None,
                "waiting_since": (turn or {}).get("since"),
                "waiting_for": why if turn is not None else None,
                "last_run": last_run(cfg, entry.name),
                "cooldown_until": stamp(until) if cooling else None,
                "can_run": not is_running and pending is None and turn is None and not cooling,
                "refreshes": entry.refreshes,
                "stage": entry.stage,
            }
        )
    return {
        "now": stamp(now),
        "scheduler_alive": scheduler_alive(cfg, now),
        "cooldown_seconds": int(COOLDOWN.total_seconds()),
        "pickup_seconds": PICKUP_SECONDS,
        "stages": list(STAGE_ORDER),
        "low_memory": {"on": bool(low.get("on")), "why": low.get("why")},
        "jobs": rows,
    }


def cooldown_until(cfg: Config, name: str) -> datetime | None:
    last = parse_stamp((_read(requests_dir(cfg) / f"{name}.last") or {}).get("requested_at"))
    return last + COOLDOWN if last else None


# ---- Requests ----


def request_run(cfg: Config, jobs: list, name: str, client: str | None = None, now: datetime | None = None) -> tuple[int, dict]:
    now = now or now_utc()
    entries = catalogue(jobs)
    entry = entries.get(name) if NAME.match(name or "") else None

    def answer(code: int, outcome: str, body: dict) -> tuple[int, dict]:
        log_request(cfg, {"at": stamp(now), "job": name[:64], "client": client, "outcome": outcome})
        return code, body

    if entry is None:
        return answer(404, "unknown_job", {"ok": False, "error": "unknown_job", "message": f"No scheduled job called {name[:64]!r}."})
    held = {r["job"]: r.get("since") for r in running(cfg)}
    lock = next((lock for lock in sorted(entry.locks) if lock in held), None)
    if lock is not None:
        return answer(409, "running", {"ok": False, "error": "running", "message": f"{entry.title} is running now.", "since": held[lock]})
    folder = requests_dir(cfg)
    pending = _read(folder / f"{name}.json")
    if pending is not None:
        return answer(409, "queued", {"ok": False, "error": "queued", "message": f"{entry.title} is already queued.", "since": pending.get("requested_at")})
    turn = (_read(run_dir(cfg) / "waiting.json") or {}).get(name)
    if isinstance(turn, dict):
        return answer(409, "waiting", {"ok": False, "error": "waiting", "message": f"{entry.title} is waiting for its turn.", "since": turn.get("since")})
    until = cooldown_until(cfg, name)
    if until is not None and until > now:
        wait = int((until - now).total_seconds()) or 1
        return answer(
            429,
            "cooldown",
            {
                "ok": False,
                "error": "cooldown",
                "message": f"{entry.title} was asked for less than 5 minutes ago.",
                "cooldown_until": stamp(until),
                "retry_after": wait,
            },
        )
    if not scheduler_alive(cfg, now):
        return answer(
            503, "scheduler_down", {"ok": False, "error": "scheduler_down", "message": "The cron service isn't running, so nothing would pick this up."}
        )
    req = {"id": secrets.token_hex(6), "requested_at": stamp(now), "client": client}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(folder / f"{name}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        pending = _read(folder / f"{name}.json") or {}
        return answer(409, "queued", {"ok": False, "error": "queued", "message": f"{entry.title} is already queued.", "since": pending.get("requested_at")})
    with os.fdopen(fd, "w") as f:
        json.dump(req, f)
    _write(folder / f"{name}.last", req)
    return answer(
        202,
        "queued",
        {"ok": True, "job": name, "request_id": req["id"], "requested_at": req["requested_at"], "message": f"{entry.title} starts within a few seconds."},
    )


# ---- API ----

router = APIRouter()


def _jobs(request: Request) -> list:
    from desk.scheduler import all_jobs

    return all_jobs(getattr(request.app.state, "packages", None))


@router.get("/api/jobs")
def get_jobs(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg, _jobs(request)), headers={"Cache-Control": "no-store"})


@router.get("/api/jobs/{name}/runs")
def get_runs(name: str, request: Request) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    entry = catalogue(_jobs(request)).get(name) if NAME.match(name) else None
    if entry is None:
        body = {"ok": False, "error": "unknown_job", "message": f"No scheduled job called {name[:64]!r}."}
        return JSONResponse(body, status_code=404, headers=headers)
    kept = runs(request.app.state.cfg, name)
    return JSONResponse({"name": entry.name, "title": entry.title, "keeps": KEEP_RUNS, "runs": kept}, headers=headers)


@router.post("/api/jobs/{name}/run")
def run_job(name: str, request: Request) -> JSONResponse:
    client = request.client.host if request.client else None
    code, body = request_run(request.app.state.cfg, _jobs(request), name, client)
    headers = {"Cache-Control": "no-store"}
    if code == 429:
        headers["Retry-After"] = str(body["retry_after"])
    return JSONResponse(body, status_code=code, headers=headers)
