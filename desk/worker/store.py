import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from desk import jobrun
from desk.config import Config
from desk.worker import ASLEEP_AFTER, MAX_ATTEMPTS, home, snapshots

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  added_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  key TEXT,
  inputs TEXT NOT NULL,
  snapshots TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'returned', 'done', 'failed')),
  queued_at TEXT NOT NULL,
  leased_at TEXT,
  worker_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  finished_at TEXT,
  seconds REAL,
  peak_mb INTEGER,
  note TEXT,
  error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_open ON jobs (kind, key) WHERE key IS NOT NULL AND state IN ('queued', 'leased', 'returned');
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state, queued_at);
"""
PREFIX = "dwk_"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$")
ID = re.compile(r"^[0-9a-f]{12}$")
MAX_WORKERS = 4
KEEP_DONE = timedelta(days=7)
OPEN = ("queued", "leased", "returned")


# ---- Files ----


def db_path(cfg: Config) -> Path:
    return home(cfg) / "queue.db"


def results_dir(cfg: Config) -> Path:
    return home(cfg) / "results"


def result_path(cfg: Config, job_id: str) -> Path:
    return results_dir(cfg) / f"{job_id}.json.gz"


def beat_path(cfg: Config, worker_id: str) -> Path:
    return home(cfg) / "beats" / f"{worker_id}.json"


@contextmanager
def open_db(cfg: Config):
    path = db_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()


@contextmanager
def writing(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# ---- Workers ----


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def add_worker(cfg: Config, name: str, now: datetime | None = None) -> dict:
    name = " ".join(str(name or "").split())
    if not NAME.match(name):
        raise ValueError("A worker's name is 1 to 32 letters, digits, spaces, dashes or underscores.")
    key = PREFIX + secrets.token_urlsafe(32)
    row = {"id": secrets.token_hex(6), "name": name, "added_at": jobrun.stamp(now or jobrun.now_utc())}
    with open_db(cfg) as conn, writing(conn):
        live = conn.execute("SELECT count(*) FROM workers WHERE revoked_at IS NULL").fetchone()[0]
        if live >= MAX_WORKERS:
            raise OverflowError(f"There are already {MAX_WORKERS} workers. Remove one first.")
        if conn.execute("SELECT 1 FROM workers WHERE revoked_at IS NULL AND lower(name) = lower(?)", (name,)).fetchone():
            raise ValueError(f"There is already a worker called {name}.")
        conn.execute("INSERT INTO workers (id, name, key_hash, added_at) VALUES (?, ?, ?, ?)", (row["id"], name, _hash(key), row["added_at"]))
    return row | {"key": key}


def remove_worker(cfg: Config, worker_id: str, now: datetime | None = None) -> bool:
    with open_db(cfg) as conn, writing(conn):
        done = conn.execute(
            "UPDATE workers SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (jobrun.stamp(now or jobrun.now_utc()), worker_id)
        ).rowcount
        conn.execute("UPDATE jobs SET state = 'queued', worker_id = NULL, leased_at = NULL WHERE state = 'leased' AND worker_id = ?", (worker_id,))
    beat_path(cfg, worker_id).unlink(missing_ok=True)
    return bool(done)


def worker_for(cfg: Config, key: str | None) -> dict | None:
    if not key or not key.startswith(PREFIX) or len(key) > 128:
        return None
    digest = _hash(key)
    with open_db(cfg) as conn:
        row = conn.execute("SELECT id, name, key_hash FROM workers WHERE key_hash = ? AND revoked_at IS NULL", (digest,)).fetchone()
    if row is None or not hmac.compare_digest(row["key_hash"], digest):
        return None
    return {"id": row["id"], "name": row["name"]}


def label(value: object) -> str | None:
    return re.sub(r"[^A-Za-z0-9._-]", "", str(value))[:64] or None if value else None


def beat(cfg: Config, worker_id: str, said: dict, now: datetime | None = None) -> dict:
    row = {
        "at": jobrun.stamp(now or jobrun.now_utc()),
        "build": label(said.get("build")),
        "host": label(said.get("host")),
        "code": label(said.get("code")),
        "job_id": said.get("job_id") if isinstance(said.get("job_id"), str) and ID.match(said["job_id"]) else None,
    }
    jobrun._write(beat_path(cfg, worker_id), row)
    return row


def last_beat(cfg: Config, worker_id: str) -> dict | None:
    return jobrun._read(beat_path(cfg, worker_id))


def worker_state(seen: dict | None, now: datetime) -> str:
    at = jobrun.parse_stamp((seen or {}).get("at"))
    if at is None:
        return "never"
    return "online" if now - at <= timedelta(seconds=ASLEEP_AFTER) else "asleep"


def workers(cfg: Config, now: datetime | None = None) -> list[dict]:
    now = now or jobrun.now_utc()
    with open_db(cfg) as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, name, added_at FROM workers WHERE revoked_at IS NULL ORDER BY added_at")]
    for row in rows:
        seen = last_beat(cfg, row["id"])
        row.update(state=worker_state(seen, now), last_seen=(seen or {}).get("at"), build=(seen or {}).get("build"), host=(seen or {}).get("host"))
        row["job_id"] = (seen or {}).get("job_id") if row["state"] == "online" else None
    return rows


# ---- Jobs ----


def _job(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["inputs"] = json.loads(job["inputs"])
    job["snapshots"] = json.loads(job["snapshots"])
    return job


def get(cfg: Config, job_id: str) -> dict | None:
    if not ID.match(job_id or ""):
        return None
    with open_db(cfg) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row) if row else None


def enqueue(cfg: Config, kind: str, inputs: dict, copies: list[dict], key: str | None = None, again: bool = False, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    snapshots.allowed(cfg, [str(c.get("name")) for c in copies])
    with open_db(cfg) as conn, writing(conn):
        if key is not None:
            states = OPEN if again else (*OPEN, "done")
            marks = ", ".join("?" for _ in states)
            same = conn.execute(f"SELECT * FROM jobs WHERE kind = ? AND key = ? AND state IN ({marks}) ORDER BY rowid DESC", (kind, key, *states)).fetchone()
            if same is not None:
                return _job(same) | {"new": False}
        job_id = secrets.token_hex(6)
        conn.execute(
            "INSERT INTO jobs (id, kind, key, inputs, snapshots, state, queued_at) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
            (job_id, kind, key, json.dumps(inputs, sort_keys=True), json.dumps(copies, sort_keys=True), jobrun.stamp(now)),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row) | {"new": True}


def _release(conn: sqlite3.Connection, cfg: Config, now: datetime) -> None:
    limit = timedelta(seconds=ASLEEP_AFTER)
    for row in conn.execute("SELECT id, worker_id, leased_at, attempts FROM jobs WHERE state = 'leased'").fetchall():
        seen = last_beat(cfg, row["worker_id"] or "")
        at = jobrun.parse_stamp((seen or {}).get("at"))
        leased = jobrun.parse_stamp(row["leased_at"])
        beating = at is not None and now - at <= limit and (seen.get("job_id") == row["id"] or (leased is not None and now - leased <= limit))
        if beating:
            continue
        if row["attempts"] >= MAX_ATTEMPTS:
            conn.execute(
                "UPDATE jobs SET state = 'failed', finished_at = ?, error = ? WHERE id = ?",
                (jobrun.stamp(now), f"It was started {row['attempts']} times and the worker went quiet each time.", row["id"]),
            )
        else:
            conn.execute("UPDATE jobs SET state = 'queued', worker_id = NULL, leased_at = NULL WHERE id = ?", (row["id"],))


def lease(cfg: Config, worker_id: str, known: set[str], now: datetime | None = None) -> dict | None:
    now = now or jobrun.now_utc()
    with open_db(cfg) as conn, writing(conn):
        _release(conn, cfg, now)
        for mine in conn.execute("SELECT * FROM jobs WHERE state = 'leased' AND worker_id = ? ORDER BY leased_at", (worker_id,)).fetchall():
            if mine["attempts"] >= MAX_ATTEMPTS:
                conn.execute(
                    "UPDATE jobs SET state = 'failed', finished_at = ?, error = ? WHERE id = ?",
                    (jobrun.stamp(now), f"It was started {mine['attempts']} times and never finished.", mine["id"]),
                )
                continue
            conn.execute("UPDATE jobs SET leased_at = ?, attempts = attempts + 1 WHERE id = ?", (jobrun.stamp(now), mine["id"]))
            return _job(conn.execute("SELECT * FROM jobs WHERE id = ?", (mine["id"],)).fetchone())
        for row in conn.execute("SELECT * FROM jobs WHERE state = 'queued' ORDER BY rowid").fetchall():
            why = None
            if row["kind"] not in known:
                why = "This build of the desk doesn't know that kind of job any more."
            elif any(c.get("name") not in snapshots.sources(cfg) for c in json.loads(row["snapshots"])):
                why = snapshots.REFUSED
            elif any(snapshots.path_of(cfg, str(c.get("sha256"))) is None for c in json.loads(row["snapshots"])):
                why = "The database copy it was queued with is gone, so it can't be sent to a worker."
            if why:
                conn.execute("UPDATE jobs SET state = 'failed', finished_at = ?, error = ? WHERE id = ?", (jobrun.stamp(now), why, row["id"]))
                continue
            conn.execute(
                "UPDATE jobs SET state = 'leased', worker_id = ?, leased_at = ?, attempts = attempts + 1 WHERE id = ?",
                (worker_id, jobrun.stamp(now), row["id"]),
            )
            return _job(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())
    return None


def returned(cfg: Config, job_id: str, ok: bool, seconds: float | None, peak_mb: int | None, error: str | None, now: datetime | None = None) -> str:
    now = now or jobrun.now_utc()
    with open_db(cfg) as conn, writing(conn):
        row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return "unknown"
        if row["state"] not in ("queued", "leased"):
            return "already"
        if ok:
            conn.execute("UPDATE jobs SET state = 'returned', seconds = ?, peak_mb = ? WHERE id = ?", (seconds, peak_mb, job_id))
        else:
            conn.execute(
                "UPDATE jobs SET state = 'failed', finished_at = ?, seconds = ?, peak_mb = ?, error = ? WHERE id = ?",
                (jobrun.stamp(now), seconds, peak_mb, jobrun.plain(error) or "The worker said it failed, without a reason.", job_id),
            )
    return "returned" if ok else "failed"


def finish(cfg: Config, job_id: str, note: str | None = None, error: str | None = None, now: datetime | None = None) -> None:
    now = now or jobrun.now_utc()
    with open_db(cfg) as conn, writing(conn):
        conn.execute(
            "UPDATE jobs SET state = ?, finished_at = ?, note = ?, error = ? WHERE id = ? AND state = 'returned'",
            ("failed" if error else "done", jobrun.stamp(now), jobrun.plain(note), jobrun.plain(error), job_id),
        )
    result_path(cfg, job_id).unlink(missing_ok=True)


def in_state(cfg: Config, state: str) -> list[dict]:
    with open_db(cfg) as conn:
        return [_job(r) for r in conn.execute("SELECT * FROM jobs WHERE state = ? ORDER BY rowid", (state,))]


def tidy(cfg: Config, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    with open_db(cfg) as conn, writing(conn):
        _release(conn, cfg, now)
        old = conn.execute("DELETE FROM jobs WHERE state IN ('done', 'failed') AND finished_at < ?", (jobrun.stamp(now - KEEP_DONE),)).rowcount
        keep = set()
        for row in conn.execute(f"SELECT snapshots FROM jobs WHERE state IN ({', '.join('?' for _ in OPEN)})", OPEN):
            keep.update(str(c.get("sha256")) for c in json.loads(row["snapshots"]))
        live = {r["id"] for r in conn.execute("SELECT id FROM jobs WHERE state = 'returned'")}
    folder = results_dir(cfg)
    for path in folder.glob("*.json.gz") if folder.is_dir() else []:
        if path.name.removesuffix(".json.gz") not in live:
            path.unlink(missing_ok=True)
    return {"forgotten": old, "copies_removed": len(snapshots.prune(cfg, keep))}


def recent(cfg: Config, limit: int = 30) -> list[dict]:
    with open_db(cfg) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY CASE WHEN state IN ('queued', 'leased', 'returned') THEN 0 ELSE 1 END,"
            " coalesce(finished_at, queued_at) DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_job(r) for r in rows]
