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


def save_brief(cfg: Config, run_id: int, desk: str, as_of: str | None, digest: str, version: str, summary: str, answer: str) -> None:
    with db(cfg) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_briefs (run_id, desk, as_of, digest, profile_version, summary, answer, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, desk, as_of, digest, version, summary, answer, now_iso()),
        )


def last_digest(cfg: Config, desk: str) -> str | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT digest FROM agent_briefs WHERE desk=? ORDER BY run_id DESC LIMIT 1", (desk,)).fetchone()
    return row["digest"] if row else None


def latest_brief(cfg: Config, desk: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute(
            "SELECT run_id, desk, as_of, profile_version, summary, created_at FROM agent_briefs WHERE desk=? ORDER BY run_id DESC LIMIT 1", (desk,)
        ).fetchone()
    return dict(row) if row else None


def runs(cfg: Config, desk: str | None = None, limit: int = 50) -> list[dict]:
    with db(cfg) as conn:
        if desk:
            rows = conn.execute("SELECT * FROM agent_runs WHERE desk=? ORDER BY id DESC LIMIT ?", (desk, limit))
        else:
            rows = conn.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def save_dossier(cfg: Config, symbol: str, run_id: int, dossier: str) -> None:
    with db(cfg) as conn:
        conn.execute("INSERT INTO agent_dossiers (symbol, run_id, dossier, created_at) VALUES (?,?,?,?)", (symbol, run_id, dossier, now_iso()))


def latest_dossier(cfg: Config, symbol: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_dossiers WHERE symbol=? ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
    return dict(row) if row else None


def dossier_ages(cfg: Config) -> dict[str, str]:
    with db(cfg) as conn:
        return {r["symbol"]: r["at"] for r in conn.execute("SELECT symbol, max(created_at) AS at FROM agent_dossiers GROUP BY symbol")}


def dossier_list(cfg: Config) -> list[dict]:
    with db(cfg) as conn:
        rows = conn.execute(
            "SELECT d.symbol, d.run_id, d.created_at, d.dossier FROM agent_dossiers d "
            "JOIN (SELECT symbol, max(id) AS id FROM agent_dossiers GROUP BY symbol) m ON m.id = d.id ORDER BY d.symbol"
        )
        return [dict(r) for r in rows]


def add_request(cfg: Config, desk: str, question: str, *, symbol: str | None = None, run_now: bool = False, source: str = "console") -> int:
    with db(cfg) as conn:
        cur = conn.execute(
            "INSERT INTO agent_requests (desk, question, symbol, run_now, source, created_at) VALUES (?,?,?,?,?,?)",
            (desk, question, symbol, int(run_now), source, now_iso()),
        )
        return int(cur.lastrowid)


def next_request(cfg: Config, *, now_only: bool) -> dict | None:
    where = "status='queued'" + (" AND run_now=1" if now_only else "")
    with db(cfg) as conn:
        row = conn.execute(f"SELECT * FROM agent_requests WHERE {where} ORDER BY run_now DESC, id LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE agent_requests SET status='running', started_at=? WHERE id=?", (now_iso(), row["id"]))
    return dict(row)


def finish_request(cfg: Config, request_id: int, status: str, *, run_id: int | None = None, answer: str | None = None, note: str | None = None) -> None:
    with db(cfg) as conn:
        conn.execute(
            "UPDATE agent_requests SET status=?, finished_at=?, run_id=?, answer=?, note=? WHERE id=?",
            (status, now_iso(), run_id, answer, note, request_id),
        )


def requeue(cfg: Config, request_id: int, note: str) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_requests SET status='queued', run_now=0, started_at=NULL, note=? WHERE id=?", (note, request_id))


def get_request(cfg: Config, request_id: int) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_requests WHERE id=?", (request_id,)).fetchone()
    return dict(row) if row else None


def requests(cfg: Config, limit: int = 50) -> list[dict]:
    with db(cfg) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM agent_requests ORDER BY id DESC LIMIT ?", (limit,))]


def mark_trigger(cfg: Config, as_of: str, kind: str, scope_id: str) -> bool:
    with db(cfg) as conn:
        cur = conn.execute("INSERT OR IGNORE INTO agent_triggers_seen (as_of, kind, scope_id) VALUES (?,?,?)", (as_of, kind, scope_id))
        return cur.rowcount == 1


def link_trigger(cfg: Config, as_of: str, kind: str, scope_id: str, request_id: int) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_triggers_seen SET request_id=? WHERE as_of=? AND kind=? AND scope_id=?", (request_id, as_of, kind, scope_id))
