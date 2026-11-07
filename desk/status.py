import json
import sqlite3
import sys
from datetime import UTC, date, datetime

from desk import __version__
from desk.config import Config
from desk.db import connect
from desk.runlock import running


def _age_hours(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    return round((now - datetime.fromisoformat(stamp)).total_seconds() / 3600, 1)


def mirror_status(cfg: Config, now: datetime) -> dict:
    if not cfg.mirror_db.exists():
        return {"state": "empty", "note": "The mirror hasn't run yet."}
    try:
        conn = connect(cfg.mirror_db, readonly=True)
    except sqlite3.Error as e:
        return {"state": "error", "note": str(e)}
    try:
        last = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        good = conn.execute("SELECT * FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
        tables = {r["tbl"]: r["rows"] for r in conn.execute("SELECT tbl, rows FROM tables ORDER BY tbl")}
    except sqlite3.Error as e:
        return {"state": "error", "note": str(e)}
    finally:
        conn.close()
    age = _age_hours(good["finished_at"] if good else None, now)
    if good is None:
        state = "error"
    elif last["ok"] == 0 and last["finished_at"]:
        state = "failing"
    elif age is not None and age > cfg.stale_hours:
        state = "stale"
    else:
        state = "ok"
    return {
        "state": state,
        "last_ok": good["finished_at"] if good else None,
        "age_hours": age,
        "last_error": last["error"] if last and not last["ok"] else None,
        "tables": tables,
    }


def token_status(cfg: Config, today: date) -> dict:
    if not cfg.claude_token_expires:
        return {"state": "unknown", "note": "Set DESK_CLAUDE_TOKEN_EXPIRES (YYYY-MM-DD) in desk.env."}
    expires = date.fromisoformat(cfg.claude_token_expires)
    days = (expires - today).days
    return {"state": "expired" if days < 0 else "renew" if days <= 30 else "ok", "expires": expires.isoformat(), "days_left": days}


def status(cfg: Config | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or Config.from_env()
    now = now or datetime.now(UTC)
    return {
        "version": __version__,
        "mirror": mirror_status(cfg, now),
        "claude_token": token_status(cfg, now.date()),
        "running": running(cfg),
    }


if __name__ == "__main__":
    json.dump(status(), sys.stdout, indent=2)
    print()
