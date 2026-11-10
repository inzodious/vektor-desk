from datetime import UTC, datetime

from desk.agents.desks import DESKS
from desk.config import Config
from desk.notify import publish

FAILED = {"failed": "failed", "timeout": "timed out", "busy": "couldn't get a turn", "deferred": "hit the usage limit twice"}


def _title(desk: str) -> str:
    return DESKS[desk].title if desk in DESKS else desk.replace("_", " ").title()


def _first_line(text: str | None, limit: int = 140) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:limit]


def _send(cfg: Config, *args, **kwargs) -> bool:
    try:
        return publish(*args, cfg=cfg, **kwargs)
    except Exception:
        return False


def run_failed(cfg: Config, desk: str, status: str, run_id: int, note: str | None = None) -> bool:
    if desk not in DESKS or status not in FAILED:
        return False
    day = datetime.now(UTC).date().isoformat()
    body = f"Run {run_id} {FAILED[status]}. {_first_line(note)}".strip()
    return _send(cfg, "ops", f"{_title(desk)} {FAILED[status]}", body, "default", tags=["robot"], click="/settings", key=f"agents:{desk}:{status}:{day}")


def answer_ready(cfg: Config, request: dict, answer: str) -> bool:
    desk = request["desk"]
    where = "/lab" if desk == "strategy" else "/research"
    asked = request.get("source") == "console"
    title = f"{_title(desk)} answered" if asked else f"{_title(desk)} has a new note"
    body = _first_line(answer) or _first_line(request.get("question"))
    return _send(cfg, "research", title, body, "default", tags=["memo"], click=where, key=f"agents:request:{request['id']}")


def dossier_ready(cfg: Config, symbol: str, run_id: int, summary: str = "") -> bool:
    body = _first_line(summary) or "The research desk updated this dossier."
    return _send(cfg, "research", f"Dossier ready: {symbol}", body, "low", tags=["memo"], click="/research", key=f"agents:dossier:{symbol}:{run_id}")


def debrief_ready(cfg: Config, kind: str, end: str, headline: str) -> bool:
    body = _first_line(headline) or "The debrief for this period is ready."
    priority = "low" if kind == "day" else "default"
    return _send(cfg, "research", f"{kind.title()} review: {end}", body, priority, tags=["memo"], click="/results", key=f"agents:debrief:{kind}:{end}")
