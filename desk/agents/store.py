import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from desk.agents.schema import SCHEMA
from desk.config import Config
from desk.db import desk_conn

ALL = "*"
COUNTED = ("ok", "failed", "timeout", "running")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def db(cfg: Config) -> Iterator[sqlite3.Connection]:
    conn = desk_conn(cfg, mirror=False)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def start_run(cfg: Config, desk: str, *, trigger: str, model: str, effort: str, status: str = "running", note: str | None = None) -> int:
    with db(cfg) as conn:
        cur = conn.execute(
            "INSERT INTO agent_runs (desk, trigger, status, started_at, finished_at, model, effort, note) VALUES (?,?,?,?,?,?,?,?)",
            (desk, trigger, status, now_iso(), None if status == "running" else now_iso(), model, effort, note),
        )
        return int(cur.lastrowid)


def finish_run(cfg: Config, run_id: int, status: str, *, usage: dict | None = None, note: str | None = None) -> None:
    usage = usage or {}
    with db(cfg) as conn:
        conn.execute(
            "UPDATE agent_runs SET status=?, finished_at=?, turns=?, input_tokens=?, output_tokens=?, cache_tokens=?, duration_ms=?, cost_estimate=?, note=? "
            "WHERE id=?",
            (
                status,
                now_iso(),
                usage.get("turns", 0),
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_tokens", 0),
                usage.get("duration_ms", 0),
                usage.get("cost_estimate", 0.0),
                note,
                run_id,
            ),
        )


def last_run(cfg: Config, desk: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE desk=? ORDER BY id DESC LIMIT 1", (desk,)).fetchone()
    return dict(row) if row else None


def week_usage(cfg: Config, desk: str, now: datetime | None = None) -> dict:
    since = ((now or datetime.now(UTC)) - timedelta(days=7)).isoformat(timespec="seconds")
    marks = ",".join("?" * len(COUNTED))
    with db(cfg) as conn:
        row = conn.execute(
            f"SELECT count(*) AS runs, coalesce(sum(turns),0) AS turns, coalesce(sum(input_tokens+output_tokens+cache_tokens),0) AS tokens "
            f"FROM agent_runs WHERE desk=? AND started_at>=? AND status IN ({marks})",
            (desk, since, *COUNTED),
        ).fetchone()
    return {"runs": row["runs"], "turns": row["turns"], "tokens": row["tokens"]}


def is_enabled(cfg: Config, desk: str) -> bool:
    with db(cfg) as conn:
        rows = {r["desk"]: bool(r["enabled"]) for r in conn.execute("SELECT desk, enabled FROM agent_settings WHERE desk IN (?,?)", (ALL, desk))}
    return rows.get(ALL, True) and rows.get(desk, True)


def set_enabled(cfg: Config, desk: str, enabled: bool) -> None:
    with db(cfg) as conn:
        conn.execute(
            "INSERT INTO agent_settings (desk, enabled, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(desk) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
            (desk, int(enabled), now_iso()),
        )
