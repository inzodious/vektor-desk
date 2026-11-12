import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from desk.config import Config
from desk.db import desk_conn
from desk.decisions.schema import SCHEMA, apply


def now_iso(at: datetime | None = None) -> str:
    return (at or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")


def new_id(at: datetime | None = None) -> str:
    stamp = (at or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d%H%M%S")
    return f"d_{stamp}_{secrets.token_hex(3)}"


def dumps(value) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))


def loads(text: str | None):
    return None if text is None else json.loads(text)


def has_mirror(conn: sqlite3.Connection) -> bool:
    return any(r[1] == "mirror" for r in conn.execute("PRAGMA database_list"))


def open_db(cfg: Config) -> sqlite3.Connection:
    conn = desk_conn(cfg)
    conn.executescript(SCHEMA)
    apply(conn)
    return conn


@contextmanager
def session(cfg: Config) -> Iterator[sqlite3.Connection]:
    conn = open_db(cfg)
    try:
        yield conn
    finally:
        conn.close()


def log_event(conn: sqlite3.Connection, decision_id: str, event: str, *, reason: str | None = None, detail=None, at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO decision_events (decision_id, at, event, reason, detail) VALUES (?, ?, ?, ?, ?)",
        (decision_id, at or now_iso(), event, reason, dumps(detail)),
    )
