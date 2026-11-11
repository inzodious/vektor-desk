import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from desk import memory
from desk.config import Config
from desk.jobrun import _read, _write, now_utc, parse_stamp, stamp
from desk.runlock import run_dir
from desk.worker import build

PICKUP_SECONDS = 300
ALIVE_WITHIN = timedelta(minutes=12)
STALE_RUN = timedelta(hours=2)


@dataclass(frozen=True)
class Action:
    name: str
    title: str
    cooldown: timedelta
    what: str


ACTIONS = {
    a.name: a
    for a in (
        Action("redeploy", "Redeploy", timedelta(minutes=5), "Recreates the containers on the live images, so edited settings take effect"),
        Action("status", "Status", timedelta(minutes=1), "What's live, what's on GitHub, container health, backups"),
        Action("check", "Check", timedelta(minutes=2), "Claude sign-in, Firestore, addresses, Alpaca paper, a test phone alert"),
        Action("backup", "Back up now", timedelta(minutes=30), "Copies every database and the inbox to the backup pool"),
        Action("restore-test", "Restore drill", timedelta(minutes=30), "Unpacks the newest backup into a scratch folder and checks every database"),
        Action("logs", "Export logs", timedelta(minutes=1), "Redacted service logs into data/run/logs"),
        Action(
            "update-script",
            "Update box script",
            timedelta(minutes=5),
            "Copies main's deploy.sh over the one the cron jobs run, once the checkout is clean, at main and the script parses",
        ),
        Action("deploy-now", "Deploy now", timedelta(minutes=5), "Pulls main, backs up and restarts on it; also retries a commit auto-deploy is holding back"),
        Action(
            "apply-compose",
            "Apply compose",
            timedelta(minutes=10),
            "Backs up, then gives TrueNAS main's compose.yaml, unless the change widens what containers can do",
        ),
        Action(
            "approve-builder",
            "Approve builder",
            timedelta(minutes=1),
            "Trusts the builders listed in main's deploy/builders.txt, so the box takes the images they sign instead of building its own",
        ),
    )
}


# ---- Files ----


def box_dir(cfg: Config) -> Path:
    return run_dir(cfg) / "box"


def requests_dir(cfg: Config) -> Path:
    return box_dir(cfg) / "requests"


def host_alive(cfg: Config, now: datetime) -> bool:
    try:
        seen = parse_stamp((box_dir(cfg) / "host.alive").read_text().strip())
    except OSError:
        return False
    return seen is not None and now - seen <= ALIVE_WITHIN


def last_run(cfg: Config, name: str) -> dict | None:
    return _read(box_dir(cfg) / f"{name}.json")


def cooldown_until(cfg: Config, action: Action) -> datetime | None:
    last = parse_stamp((_read(requests_dir(cfg) / f"{action.name}.last") or {}).get("requested_at"))
    return last + action.cooldown if last else None


def compose_state(cfg: Config) -> dict | None:
    state = _read(box_dir(cfg) / "compose.json")
    if state is None:
        return None
    text = state.pop("compose", None)
    return state | {"copy_available": isinstance(text, str)}


def compose_text(cfg: Config) -> str | None:
    text = (_read(box_dir(cfg) / "compose.json") or {}).get("compose")
    return text if isinstance(text, str) else None


def is_running(run: dict | None, now: datetime) -> bool:
    if not run or run.get("finished"):
        return False
    started = parse_stamp(run.get("started"))
    return started is not None and now - started <= STALE_RUN


def log_request(cfg: Config, entry: dict) -> None:
    path = run_dir(cfg) / "box-requests.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


# ---- State ----


def describe(cfg: Config, now: datetime | None = None) -> dict:
    now = now or now_utc()
    rows = []
    for action in ACTIONS.values():
        run = last_run(cfg, action.name)
        running = is_running(run, now)
        pending = _read(requests_dir(cfg) / f"{action.name}.json")
        until = cooldown_until(cfg, action)
        cooling = until is not None and until > now
        rows.append(
            {
                "name": action.name,
                "title": action.title,
                "what": action.what,
                "cooldown_seconds": int(action.cooldown.total_seconds()),
                "running": running,
                "queued": pending is not None,
                "queued_at": (pending or {}).get("requested_at"),
                "last_run": run,
                "cooldown_until": stamp(until) if cooling else None,
                "can_run": not running and pending is None and not cooling,
            }
        )
    return {
        "now": stamp(now),
        "host_alive": host_alive(cfg, now),
        "pickup_seconds": PICKUP_SECONDS,
        "script": _read(box_dir(cfg) / "script.json"),
        "compose": compose_state(cfg),
        "memory": memory.status(cfg, now),
        "build": build.status(cfg, now),
        "actions": rows,
    }


def request_action(cfg: Config, name: str, client: str | None = None, now: datetime | None = None) -> tuple[int, dict]:
    now = now or now_utc()
    action = ACTIONS.get(name)

    def answer(code: int, outcome: str, body: dict) -> tuple[int, dict]:
        log_request(cfg, {"at": stamp(now), "action": name[:64], "client": client, "outcome": outcome})
        return code, body

    if action is None:
        return answer(404, "unknown_action", {"ok": False, "error": "unknown_action", "message": f"No box action called {name[:64]!r}."})
    run = last_run(cfg, name)
    if is_running(run, now):
        return answer(409, "running", {"ok": False, "error": "running", "message": f"{action.title} is running now.", "since": run.get("started")})
    folder = requests_dir(cfg)
    pending = _read(folder / f"{name}.json")
    if pending is not None:
        return answer(409, "queued", {"ok": False, "error": "queued", "message": f"{action.title} is already queued.", "since": pending.get("requested_at")})
    until = cooldown_until(cfg, action)
    if until is not None and until > now:
        wait = int((until - now).total_seconds()) or 1
        return answer(
            429,
            "cooldown",
            {
                "ok": False,
                "error": "cooldown",
                "message": f"{action.title} ran recently; try again later.",
                "cooldown_until": stamp(until),
                "retry_after": wait,
            },
        )
    if not host_alive(cfg, now):
        return answer(
            503,
            "host_down",
            {
                "ok": False,
                "error": "host_down",
                "message": "The box's auto-deploy job hasn't checked in, so nothing would pick this up. Copy deploy.sh again for the cron jobs.",
            },
        )
    req = {"id": secrets.token_hex(6), "requested_at": stamp(now)}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(folder / f"{name}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return answer(409, "queued", {"ok": False, "error": "queued", "message": f"{action.title} is already queued.", "since": None})
    with os.fdopen(fd, "w") as f:
        json.dump(req, f)
    _write(folder / f"{name}.last", req)
    return answer(
        202,
        "queued",
        {"ok": True, "action": name, "request_id": req["id"], "requested_at": req["requested_at"], "message": f"{action.title} starts within 5 minutes."},
    )


# ---- API ----

router = APIRouter()


@router.get("/api/box")
def get_box(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg), headers={"Cache-Control": "no-store"})


@router.get("/api/box/compose.yaml")
def get_compose(request: Request) -> Response:
    text = compose_text(request.app.state.cfg)
    if text is None:
        return JSONResponse({"ok": False, "error": "no_change", "message": "The box's compose already matches main."}, status_code=404)
    return PlainTextResponse(text, media_type="text/yaml", headers={"Cache-Control": "no-store"})


@router.post("/api/box/{name}/run")
def run_action(name: str, request: Request) -> JSONResponse:
    client = request.client.host if request.client else None
    code, body = request_action(request.app.state.cfg, name, client)
    headers = {"Cache-Control": "no-store"}
    if code == 429:
        headers["Retry-After"] = str(body["retry_after"])
    return JSONResponse(body, status_code=code, headers=headers)
