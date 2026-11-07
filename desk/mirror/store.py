import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from desk.db import connect
from desk.mirror.firestore import TABLE_NAME, FirestoreReader, MirrorError, Row

FULL_EVERY = timedelta(days=7)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
  tbl TEXT NOT NULL,
  id TEXT NOT NULL,
  json TEXT NOT NULL,
  at TEXT,
  PRIMARY KEY (tbl, id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS row_history (
  seq INTEGER PRIMARY KEY,
  tbl TEXT NOT NULL,
  id TEXT NOT NULL,
  json TEXT,
  at TEXT,
  pulled_at TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('upsert', 'delete'))
);
CREATE INDEX IF NOT EXISTS row_history_key ON row_history (tbl, id, seq);
CREATE INDEX IF NOT EXISTS row_history_pulled ON row_history (pulled_at);
CREATE TABLE IF NOT EXISTS tables (
  tbl TEXT PRIMARY KEY,
  rows INTEGER NOT NULL,
  mirrored_at TEXT NOT NULL,
  full_at TEXT,
  max_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  tables INTEGER,
  full_tables INTEGER,
  rows INTEGER,
  read INTEGER,
  changed INTEGER,
  skipped INTEGER,
  seconds REAL,
  error TEXT
);
"""


class MirrorRefused(MirrorError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MirrorStore:
    def __init__(self, path: Path):
        self.path = path
        self.conn = connect(path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def counts(self) -> dict[str, int]:
        return {r["tbl"]: r["rows"] for r in self.conn.execute("SELECT tbl, rows FROM tables")}

    def table_info(self, tbl: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tables WHERE tbl=?", (tbl,)).fetchone()

    def start_run(self) -> int:
        with self.conn:
            return self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),)).lastrowid

    def finish_run(self, run_id: int, *, ok: bool, error: str | None = None, **stats) -> None:
        cols = ("tables", "full_tables", "rows", "read", "changed", "skipped", "seconds")
        with self.conn:
            self.conn.execute(
                f"UPDATE runs SET finished_at=?, ok=?, error=?, {', '.join(f'{c}=?' for c in cols)} WHERE id=?",
                (now_iso(), int(ok), error, *(stats.get(c) for c in cols), run_id),
            )

    def apply(self, full: dict[str, list[Row]], delta: dict[str, list[Row]] | None = None, *, prune: Iterable[str] = ()) -> dict[str, int]:
        delta = delta or {}
        everything = sum(self.counts().values())
        before = sum(n for t, n in self.counts().items() if t in full)
        if full and before and not sum(len(v) for v in full.values()):
            raise MirrorRefused("Firestore returned no rows at all; keeping the last good mirror. Check DESK_UID and the service account.")
        stamp = now_iso()
        changed = 0
        with self.conn:
            for tbl, rows in full.items():
                changed += self._write(tbl, rows, stamp, replace=True)
            for tbl, rows in delta.items():
                changed += self._write(tbl, rows, stamp, replace=False)
            for tbl in prune:
                changed += self._write(tbl, [], stamp, replace=True)
                self.conn.execute("DELETE FROM tables WHERE tbl=?", (tbl,))
                self.conn.execute(f'DROP VIEW IF EXISTS "ev_{tbl}"')
            after = sum(self.counts().values())
            if everything and not after:
                raise MirrorRefused("This pull would empty the mirror; keeping the last good copy. Check DESK_UID and the service account.")
        return {"rows": after, "changed": changed}

    def _write(self, tbl: str, rows: list[Row], stamp: str, *, replace: bool) -> int:
        if not TABLE_NAME.match(tbl):
            raise MirrorError(f"Refusing odd table name {tbl!r}.")
        old = {r["id"]: r["json"] for r in self.conn.execute("SELECT id, json FROM rows WHERE tbl=?", (tbl,))}
        new = {r.id: r for r in rows}
        history = [(tbl, r.id, r.json, r.at, stamp, "upsert") for r in new.values() if old.get(r.id) != r.json]
        if replace:
            history += [(tbl, rid, None, None, stamp, "delete") for rid in old if rid not in new]
            self.conn.execute("DELETE FROM rows WHERE tbl=?", (tbl,))
        self.conn.executemany("INSERT INTO row_history (tbl, id, json, at, pulled_at, op) VALUES (?, ?, ?, ?, ?, ?)", history)
        self.conn.executemany(
            "INSERT INTO rows (tbl, id, json, at) VALUES (?, ?, ?, ?) ON CONFLICT(tbl, id) DO UPDATE SET json=excluded.json, at=excluded.at",
            ((tbl, r.id, r.json, r.at) for r in new.values()),
        )
        count = self.conn.execute("SELECT count(*) FROM rows WHERE tbl=?", (tbl,)).fetchone()[0]
        max_at = self.conn.execute("SELECT max(at) FROM rows WHERE tbl=?", (tbl,)).fetchone()[0]
        self.conn.execute(
            """INSERT INTO tables (tbl, rows, mirrored_at, full_at, max_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tbl) DO UPDATE SET rows=excluded.rows, mirrored_at=excluded.mirrored_at,
               full_at=coalesce(excluded.full_at, tables.full_at), max_at=excluded.max_at""",
            (tbl, count, stamp, stamp if replace else None, max_at),
        )
        self.conn.execute(f"CREATE VIEW IF NOT EXISTS \"ev_{tbl}\" AS SELECT id, json, at FROM rows WHERE tbl = '{tbl}'")
        return len(history)


def valid_rows(rows: Iterable[Row]) -> tuple[list[Row], int]:
    good: list[Row] = []
    skipped = 0
    for r in rows:
        try:
            json.loads(r.json)
        except ValueError:
            skipped += 1
            continue
        good.append(r)
    return good, skipped


def needs_full(info: sqlite3.Row | None, now: datetime) -> bool:
    if info is None or not info["full_at"] or not info["max_at"]:
        return True
    return now - datetime.fromisoformat(info["full_at"]) >= FULL_EVERY


def run_mirror(
    reader: FirestoreReader,
    store: MirrorStore,
    *,
    tables: Iterable[str] = (),
    fallback: Iterable[str] = (),
    full: bool = False,
    now: datetime | None = None,
) -> dict:
    started = time.monotonic()
    now = now or datetime.now(UTC)
    run_id = store.start_run()
    try:
        chosen = list(tables)
        prune: list[str] = []
        if not chosen:
            try:
                chosen = reader.tables()
                prune = [t for t in store.counts() if t not in chosen]
            except MirrorError as e:
                if e.status not in (403, 404):
                    raise
                chosen = list(fallback)
        whole: dict[str, list[Row]] = {}
        delta: dict[str, list[Row]] = {}
        skipped = 0
        for tbl in chosen:
            info = store.table_info(tbl)
            if full or needs_full(info, now):
                whole[tbl], bad = valid_rows(reader.rows(tbl))
            else:
                delta[tbl], bad = valid_rows(reader.changed(tbl, info["max_at"]))
            skipped += bad
        applied = store.apply(whole, delta, prune=prune)
        read = sum(len(v) for v in whole.values()) + sum(len(v) for v in delta.values())
        stats = {"tables": len(chosen), "full_tables": len(whole), "read": read, "skipped": skipped, **applied}
        seconds = round(time.monotonic() - started, 2)
        store.finish_run(run_id, ok=True, seconds=seconds, **stats)
        return {"ok": True, **stats, "seconds": seconds}
    except (MirrorError, sqlite3.Error, OSError) as e:
        store.finish_run(run_id, ok=False, seconds=round(time.monotonic() - started, 2), error=str(e))
        raise
