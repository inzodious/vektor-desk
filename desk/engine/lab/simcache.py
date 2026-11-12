import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from desk.config import Config

Run = namedtuple("Run", "params summary rets bench days")
KIND = "lab.sims"
CODE_FILES = ("data.py", "library.py", "sim.py", "spec.py", "stats.py")
SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_cache (
  key TEXT PRIMARY KEY,
  snapshot TEXT NOT NULL,
  body TEXT NOT NULL,
  stored_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sim_answers (
  job TEXT PRIMARY KEY,
  snapshot TEXT NOT NULL,
  at TEXT NOT NULL
) WITHOUT ROWID;
"""
STAGED = "sims-*.json.gz"
OFFERS = "offers.sims"
MAX_ROWS = 20_000
MAX_BYTES = 200_000_000
MAX_DAYS = 3_000_000
WAIT_ENV = "DESK_LAB_WORKER_WAIT_MIN"
WAIT_MIN = 10.0
GRACE_MIN = 3.0
SEEN_MIN = 6.0
GZIP_MAGIC = b"\x1f\x8b"
SPOT_CHECKS = 2
FIELDS = ("key", "params", "start", "end", "cost_mult", "summary", "rets", "bench", "days")


# ---- Keys ----


@cache
def code_hash() -> str:
    h = hashlib.sha256()
    for name in CODE_FILES:
        h.update((Path(__file__).parent / name).read_bytes())
    return h.hexdigest()


def snapshot_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _text(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def run_key(snapshot: str, spec_hash: str, job: tuple) -> str:
    params, start, end, cost_mult = job
    return hashlib.sha256(_canon([code_hash(), snapshot, spec_hash, params, start, end, float(cost_mult)]).encode()).hexdigest()


def job_key(snapshot: str, request: dict) -> str:
    return hashlib.sha256(_canon([code_hash(), snapshot, request]).encode()).hexdigest()


# ---- Rows ----


def row(key: str, job: tuple, run: Run) -> dict:
    params, start, end, cost_mult = job
    return {
        "key": key,
        "params": params,
        "start": start,
        "end": end,
        "cost_mult": float(cost_mult),
        "summary": run.summary,
        "rets": run.rets,
        "bench": run.bench,
        "days": run.days,
    }


def as_run(body: dict) -> Run:
    return Run(body["params"], body["summary"], body["rets"], body["bench"], body["days"])


def _numbers(xs) -> bool:
    return isinstance(xs, list) and all(x is None or (isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)) for x in xs)


def problems(body, snapshot: str, spec_hash: str) -> str | None:
    if not isinstance(body, dict) or any(k not in body for k in FIELDS):
        return "a row is missing fields"
    days, rets, bench = body["days"], body["rets"], body["bench"]
    if not isinstance(body["params"], dict) or not isinstance(body["summary"], dict):
        return "params and summary must be objects"
    if not isinstance(days, list) or not all(isinstance(d, str) for d in days) or days != sorted(set(days)):
        return "days must be distinct dates in order"
    if not _numbers(rets) or not _numbers(bench) or len(rets) != len(bench) or len(rets) != max(0, len(days) - 1):
        return "returns do not line up with the days"
    if days and not (str(body["start"]) <= days[0] and days[-1] <= str(body["end"])):
        return "days fall outside the window"
    try:
        key = run_key(snapshot, spec_hash, (body["params"], body["start"], body["end"], body["cost_mult"]))
    except (TypeError, ValueError):
        return "a row's inputs cannot be hashed"
    return None if key == body["key"] else "a row's key does not match its inputs"


# ---- Store ----


class Cache:
    def __init__(self, snapshot: str, conn: sqlite3.Connection | None = None, *, now: datetime | None = None):
        self.snapshot, self.conn, self.mem, self.answers = snapshot, conn, {}, set()
        self.stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        self.hits = self.misses = 0
        if conn is not None:
            conn.executescript(SCHEMA)

    def key(self, spec_hash: str, job: tuple) -> str:
        return run_key(self.snapshot, spec_hash, job)

    def get(self, keys: list[str]) -> dict[str, Run]:
        if self.conn is None:
            return {k: as_run(self.mem[k]) for k in keys if k in self.mem}
        out = {}
        for i in range(0, len(keys), 500):
            part = keys[i : i + 500]
            marks = ",".join("?" * len(part))
            for r in self.conn.execute(f"SELECT key, body FROM sim_cache WHERE snapshot=? AND key IN ({marks})", (self.snapshot, *part)):
                out[r[0]] = as_run(json.loads(r[1]))
        return out

    def put(self, rows: list[dict]) -> int:
        if self.conn is None:
            new = [r for r in rows if r["key"] not in self.mem]
            self.mem.update({r["key"]: r for r in new})
            return len(new)
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany("INSERT OR IGNORE INTO sim_cache VALUES (?, ?, ?, ?)", ((r["key"], self.snapshot, _text(r), self.stamp) for r in rows))
            return self.conn.total_changes - before

    def answer(self, job: str) -> None:
        if self.conn is None:
            self.answers.add(job)
            return
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO sim_answers VALUES (?, ?, ?)", (job, self.snapshot, self.stamp))

    def last_answer(self) -> str | None:
        if self.conn is None:
            return self.stamp if self.answers else None
        return self.conn.execute("SELECT max(at) FROM sim_answers WHERE snapshot=?", (self.snapshot,)).fetchone()[0]

    def answered(self, job: str) -> bool:
        if self.conn is None:
            return job in self.answers
        return self.conn.execute("SELECT 1 FROM sim_answers WHERE job=? AND snapshot=?", (job, self.snapshot)).fetchone() is not None

    def prune(self) -> int:
        if self.conn is None:
            return 0
        with self.conn:
            gone = self.conn.execute("DELETE FROM sim_cache WHERE snapshot != ?", (self.snapshot,)).rowcount
            self.conn.execute("DELETE FROM sim_answers WHERE snapshot != ?", (self.snapshot,))
        if gone:
            self.conn.execute("VACUUM")
        return gone

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def rows(self) -> list[dict]:
        return [self.mem[k] for k in sorted(self.mem)]


def cache_path(cfg: Config) -> Path:
    return cfg.data_dir / "lab" / "runs" / "simcache.db"


def open_cache(cfg: Config, snapshot: str, *, now: datetime | None = None) -> Cache:
    path = cache_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = Cache(snapshot, sqlite3.connect(path), now=now)
    cache.prune()
    return cache


# ---- Staging (the API side drops a worker's result; the lab validates and stores it) ----


def queue_dir(cfg: Config) -> Path:
    return cfg.data_dir / "lab" / "queue"


def stage(cfg: Config, result: dict) -> dict:
    rows = result.get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not isinstance(result.get("snapshot"), str) or not isinstance(result.get("request"), dict) or result.get("kind") != KIND:
        return {"ok": False, "error": "not a lab.sims result"}
    if len(rows) > MAX_ROWS:
        return {"ok": False, "error": f"more than {MAX_ROWS} rows"}
    blob = gzip.compress(_text({k: result[k] for k in ("kind", "snapshot", "request", "rows")}).encode(), mtime=0)
    if len(blob) > MAX_BYTES:
        return {"ok": False, "error": "the result is too large"}
    name = f"sims-{hashlib.sha256(blob).hexdigest()[:24]}.json.gz"
    folder = queue_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.tmp"
    tmp.write_bytes(blob)
    os.replace(tmp, folder / name)
    return {"ok": True, "file": name, "rows": len(rows)}


def stage_file(cfg: Config, path: Path) -> dict:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(2)
            digest = hashlib.file_digest(f, "sha256") if head == GZIP_MAGIC else None
    except OSError as e:
        return {"ok": False, "error": f"the result file cannot be read ({e.__class__.__name__})"}
    if digest is None:
        return {"ok": False, "error": "the result is not a gzip file"}
    if size > MAX_BYTES:
        return {"ok": False, "error": "the result is too large"}
    name = f"sims-{digest.hexdigest()[:24]}.json.gz"
    folder = queue_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.tmp"
    shutil.copyfile(path, tmp)
    os.replace(tmp, folder / name)
    return {"ok": True, "file": name, "bytes": size}


def staged(cfg: Config) -> list[Path]:
    folder = queue_dir(cfg)
    return sorted(folder.glob(STAGED)) if folder.exists() else []


def read_staged(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        body = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    return body if isinstance(body, dict) else None


# ---- Offers (the engine tells the lab which queued files a worker was asked to simulate) ----


def offers_path(cfg: Config) -> Path:
    return queue_dir(cfg) / OFFERS


def write_offers(cfg: Config, snapshot: str, files: dict[str, dict], now: datetime) -> None:
    path = offers_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{OFFERS}.tmp")
    tmp.write_text(_text({"snapshot": snapshot, "online_at": now.isoformat(timespec="seconds"), "files": files}))
    os.replace(tmp, path)


def read_offers(cfg: Config) -> dict:
    try:
        body = json.loads(offers_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) and isinstance(body.get("files"), dict) else {}


def wait_minutes() -> float:
    try:
        return max(0.0, float(os.environ.get(WAIT_ENV, "") or WAIT_MIN))
    except ValueError:
        return WAIT_MIN


def _within(text: object, now: datetime, minutes: float) -> bool:
    try:
        return timedelta(0) <= now - datetime.fromisoformat(str(text)) < timedelta(minutes=minutes)
    except (TypeError, ValueError):
        return False


def open_offers(cfg: Config, snapshot: str, now: datetime, progress: str | None = None) -> dict[str, str]:
    body = read_offers(cfg)
    if body.get("snapshot") != snapshot:
        return {}
    wait = wait_minutes()
    moving = _within(progress, now, wait)
    return {
        str(name): str(e["key"])
        for name, e in body["files"].items()
        if isinstance(e, dict) and e.get("key") and (_within(e.get("at"), now, wait) or (moving and str(e.get("at")) <= str(progress)))
    }


def worker_seen(cfg: Config, now: datetime) -> bool:
    return _within(read_offers(cfg).get("online_at"), now, SEEN_MIN)


def just_queued(path: Path, now: datetime) -> bool:
    try:
        age = now.timestamp() - path.stat().st_mtime
        return -60 < age < min(GRACE_MIN, wait_minutes()) * 60 and json.loads(path.read_text()).get("request") == "experiment"
    except (OSError, ValueError, AttributeError):
        return False
