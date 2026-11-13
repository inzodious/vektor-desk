import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from desk.agents.schema import SCHEMA
from desk.config import Config
from desk.db import desk_conn

ALL = "*"
GUARD = "~first_run_guard"
GUARD_UNTIL = ("plan_keeper", "tax")
COUNTED = ("ok", "failed", "timeout", "running")
STALE_RUN_MINUTES = 2
STALE_REQUEST_MINUTES = 10


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


def note_run(cfg: Config, run_id: int, note: str) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET note=? WHERE id=?", (note, run_id))


def last_run(cfg: Config, desk: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE desk=? ORDER BY id DESC LIMIT 1", (desk,)).fetchone()
    return dict(row) if row else None


LANES = {
    None: "",
    "pass": " AND id IN (SELECT run_id FROM agent_holding_tries WHERE run_id IS NOT NULL)",
    "desk": " AND id NOT IN (SELECT run_id FROM agent_holding_tries WHERE run_id IS NOT NULL)",
    "scheduled": " AND trigger IN ('schedule','retry')",
    "asked": " AND trigger NOT IN ('schedule','retry')",
}


def week_usage(cfg: Config, desk: str, now: datetime | None = None, lane: str | None = None) -> dict:
    since = ((now or datetime.now(UTC)) - timedelta(days=7)).isoformat(timespec="seconds")
    marks = ",".join("?" * len(COUNTED))
    with db(cfg) as conn:
        row = conn.execute(
            f"SELECT count(*) AS runs, coalesce(sum(turns),0) AS turns, coalesce(sum(input_tokens+output_tokens+cache_tokens),0) AS tokens "
            f"FROM agent_runs WHERE desk=? AND started_at>=? AND status IN ({marks}){LANES[lane]}",
            (desk, since, *COUNTED),
        ).fetchone()
    return {"runs": row["runs"], "turns": row["turns"], "tokens": row["tokens"]}


def counted_starts(cfg: Config, desk: str, since: datetime, lane: str | None = None) -> list[datetime]:
    marks = ",".join("?" * len(COUNTED))
    with db(cfg) as conn:
        rows = conn.execute(
            f"SELECT started_at FROM agent_runs WHERE desk=? AND started_at>=? AND status IN ({marks}){LANES[lane]} ORDER BY started_at, id",
            (desk, since.isoformat(timespec="seconds"), *COUNTED),
        ).fetchall()
    return [datetime.fromisoformat(r["started_at"]) for r in rows]


def runs_since(cfg: Config, desk: str, hours: float, now: datetime | None = None) -> int:
    since = ((now or datetime.now(UTC)) - timedelta(hours=hours)).isoformat(timespec="seconds")
    marks = ",".join("?" * len(COUNTED))
    with db(cfg) as conn:
        row = conn.execute(f"SELECT count(*) AS n FROM agent_runs WHERE desk=? AND started_at>=? AND status IN ({marks})", (desk, since, *COUNTED)).fetchone()
    return int(row["n"])


def is_enabled(cfg: Config, desk: str) -> bool:
    with db(cfg) as conn:
        rows = {r["desk"]: bool(r["enabled"]) for r in conn.execute("SELECT desk, enabled FROM agent_settings WHERE desk IN (?,?)", (ALL, desk))}
    return rows.get(ALL, True) and rows.get(desk, True)


def guard_on(cfg: Config) -> bool:
    with db(cfg) as conn:
        row = conn.execute("SELECT enabled FROM agent_settings WHERE desk=?", (GUARD,)).fetchone()
    if row is not None and not row["enabled"]:
        return False
    return any(n == 0 for n in ok_runs(cfg, GUARD_UNTIL).values())


def set_guard(cfg: Config, on: bool) -> None:
    set_enabled(cfg, GUARD, on)


def recover(cfg: Config, lock_free: bool, now: datetime | None = None) -> dict:
    if not lock_free:
        return {"runs": 0, "requests": 0}
    now = now or datetime.now(UTC)
    runs_before = (now - timedelta(minutes=STALE_RUN_MINUTES)).isoformat(timespec="seconds")
    reqs_before = (now - timedelta(minutes=STALE_REQUEST_MINUTES)).isoformat(timespec="seconds")
    stamp = now.isoformat(timespec="seconds")
    with db(cfg) as conn:
        runs = conn.execute(
            "UPDATE agent_runs SET status='failed', finished_at=?, note='Interrupted: the process stopped before the run finished.' "
            "WHERE status='running' AND started_at < ?",
            (stamp, runs_before),
        ).rowcount
        requests = conn.execute(
            "UPDATE agent_requests SET status='queued', run_now=0, started_at=NULL, note='Interrupted; queued again for tonight.' "
            "WHERE status='running' AND started_at < ? AND coalesce(note, '') NOT LIKE 'Interrupted%'",
            (reqs_before,),
        ).rowcount
        requests += conn.execute(
            "UPDATE agent_requests SET status='failed', finished_at=?, note='Interrupted twice; not retried.' WHERE status='running' AND started_at < ?",
            (stamp, reqs_before),
        ).rowcount
    return {"runs": runs, "requests": requests}


def app_switch(cfg: Config, desk: str) -> bool | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT enabled FROM agent_settings WHERE desk=?", (desk,)).fetchone()
    return None if row is None else bool(row["enabled"])


def clear_enabled(cfg: Config, desk: str) -> None:
    with db(cfg) as conn:
        conn.execute("DELETE FROM agent_settings WHERE desk=?", (desk,))


def ok_runs(cfg: Config, desks: tuple[str, ...]) -> dict[str, int]:
    marks = ",".join("?" * len(desks))
    with db(cfg) as conn:
        rows = conn.execute(f"SELECT desk, count(*) AS n FROM agent_runs WHERE status='ok' AND desk IN ({marks}) GROUP BY desk", desks).fetchall()
    found = {r["desk"]: r["n"] for r in rows}
    return {d: found.get(d, 0) for d in desks}


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


def save_dossier(cfg: Config, symbol: str, run_id: int, dossier: str, at: str | None = None) -> None:
    with db(cfg) as conn:
        conn.execute("INSERT INTO agent_dossiers (symbol, run_id, dossier, created_at) VALUES (?,?,?,?)", (symbol, run_id, dossier, at or now_iso()))


def start_try(cfg: Config, symbol: str, at: str | None = None) -> int:
    with db(cfg) as conn:
        cur = conn.execute("INSERT INTO agent_holding_tries (symbol, status, started_at) VALUES (?,?,?)", (symbol, "running", at or now_iso()))
        return int(cur.lastrowid)


def finish_try(cfg: Config, try_id: int, status: str, note: str | None = None, run_id: int | None = None, at: str | None = None) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_holding_tries SET status=?, note=?, run_id=?, finished_at=? WHERE id=?", (status, note, run_id, at or now_iso(), try_id))


def last_tries(cfg: Config) -> dict[str, dict]:
    with db(cfg) as conn:
        rows = conn.execute(
            "SELECT t.* FROM agent_holding_tries t JOIN (SELECT symbol, max(id) AS id FROM agent_holding_tries GROUP BY symbol) m ON m.id = t.id"
        ).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def misses_since(cfg: Config, since: str) -> dict[str, int]:
    with db(cfg) as conn:
        rows = conn.execute(
            "SELECT symbol, count(*) AS n FROM agent_holding_tries t WHERE started_at>=? AND status NOT IN ('ok','running') "
            "AND started_at > coalesce((SELECT max(o.started_at) FROM agent_holding_tries o WHERE o.symbol=t.symbol AND o.status='ok'), '') GROUP BY symbol",
            (since,),
        ).fetchall()
    return {r["symbol"]: r["n"] for r in rows}


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
        for row in conn.execute(f"SELECT * FROM agent_requests WHERE {where} ORDER BY run_now DESC, id LIMIT 5").fetchall():
            claimed = conn.execute("UPDATE agent_requests SET status='running', started_at=? WHERE id=? AND status='queued'", (now_iso(), row["id"]))
            if claimed.rowcount == 1:
                conn.commit()
                return dict(row)
    return None


def finish_request(cfg: Config, request_id: int, status: str, *, run_id: int | None = None, answer: str | None = None, note: str | None = None) -> None:
    with db(cfg) as conn:
        conn.execute(
            "UPDATE agent_requests SET status=?, finished_at=?, run_id=?, answer=?, note=? WHERE id=?",
            (status, now_iso(), run_id, answer, note, request_id),
        )


def requeue(cfg: Config, request_id: int, note: str) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_requests SET status='queued', run_now=0, started_at=NULL, note=? WHERE id=?", (note, request_id))


def release(cfg: Config, request_id: int) -> None:
    with db(cfg) as conn:
        conn.execute("UPDATE agent_requests SET status='queued', started_at=NULL WHERE id=? AND status='running'", (request_id,))


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


def trigger_seen(cfg: Config, as_of: str, kind: str, scope_id: str) -> bool:
    with db(cfg) as conn:
        return conn.execute("SELECT 1 FROM agent_triggers_seen WHERE as_of=? AND kind=? AND scope_id=?", (as_of, kind, scope_id)).fetchone() is not None


def pin_steps(cfg: Config, symbol: str, steps: list[dict]) -> None:
    with db(cfg) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_plan_pins (symbol, step_id, step, created_at, delivered_at) VALUES (?,?,?,?,NULL)",
            [(symbol, str(s["id"]), json.dumps(s, sort_keys=True), now_iso()) for s in steps],
        )


def unpin_step(cfg: Config, symbol: str, step_id: str) -> bool:
    with db(cfg) as conn:
        return conn.execute("DELETE FROM agent_plan_pins WHERE symbol=? AND step_id=?", (symbol, step_id)).rowcount == 1


def pinned_steps(cfg: Config, symbol: str | None = None) -> list[dict]:
    where, args = ("WHERE symbol=?", (symbol,)) if symbol else ("", ())
    with db(cfg) as conn:
        rows = conn.execute(f"SELECT symbol, step, delivered_at FROM agent_plan_pins {where} ORDER BY symbol, created_at, step_id", args).fetchall()
    return [{"symbol": r["symbol"], "delivered": r["delivered_at"] is not None} | json.loads(r["step"]) for r in rows]


def pins_delivered(cfg: Config, symbol: str, step_ids: list[str]) -> None:
    with db(cfg) as conn:
        conn.executemany(
            "UPDATE agent_plan_pins SET delivered_at=? WHERE symbol=? AND step_id=? AND delivered_at IS NULL", [(now_iso(), symbol, sid) for sid in step_ids]
        )


# ---- Limits and retries ----


def runs_between(cfg: Config, since: datetime, until: datetime) -> list[dict]:
    span = (since.isoformat(timespec="seconds"), until.isoformat(timespec="seconds"))
    with db(cfg) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM agent_runs WHERE started_at>=? AND started_at<? ORDER BY id", span)]


def note_limit(cfg: Config, scope: str, seen_at: datetime, resets_at: datetime, run_id: int | None) -> bool:
    row = (scope, seen_at.isoformat(timespec="seconds"), resets_at.astimezone(UTC).isoformat(timespec="seconds"), run_id)
    with db(cfg) as conn:
        return conn.execute("INSERT OR IGNORE INTO agent_limits (scope, seen_at, resets_at, run_id) VALUES (?,?,?,?)", row).rowcount > 0


def limits(cfg: Config, scope: str | None = None, limit: int = 20) -> list[dict]:
    where, args = ("WHERE scope=?", (scope,)) if scope else ("", ())
    with db(cfg) as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM agent_limits {where} ORDER BY resets_at DESC, id DESC LIMIT ?", (*args, limit))]


def plan_retry(cfg: Config, desk: str, due_at: datetime, reason: str, run_id: int | None) -> dict:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_retries WHERE desk=? AND status='waiting' ORDER BY id DESC LIMIT 1", (desk,)).fetchone()
        if row is None:
            due = due_at.astimezone(UTC).isoformat(timespec="seconds")
            cur = conn.execute(
                "INSERT INTO agent_retries (desk, due_at, reason, run_id, created_at) VALUES (?,?,?,?,?)", (desk, due, reason, run_id, now_iso())
            )
            row = conn.execute("SELECT * FROM agent_retries WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def waiting_retry(cfg: Config, desk: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_retries WHERE desk=? AND status='waiting' ORDER BY id DESC LIMIT 1", (desk,)).fetchone()
    return dict(row) if row else None


def last_retry(cfg: Config, desk: str) -> dict | None:
    with db(cfg) as conn:
        row = conn.execute("SELECT * FROM agent_retries WHERE desk=? ORDER BY id DESC LIMIT 1", (desk,)).fetchone()
    return dict(row) if row else None


def retries(cfg: Config, status: str | None = None) -> list[dict]:
    where, args = ("WHERE status=?", (status,)) if status else ("", ())
    with db(cfg) as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM agent_retries {where} ORDER BY due_at, id", args)]


def mark_retry(cfg: Config, retry_id: int, status: str, note: str | None = None, at: datetime | None = None) -> None:
    ran = None if status == "waiting" else (at or datetime.now(UTC)).isoformat(timespec="seconds")
    with db(cfg) as conn:
        conn.execute("UPDATE agent_retries SET status=?, ran_at=?, note=? WHERE id=?", (status, ran, note, retry_id))
