import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field

from desk.config import Config
from desk.db import connect


@dataclass
class SnapshotVersion:
    snapshot_id: str
    snap: dict
    positions: list[dict]
    position_at: list[str | None]
    first_seen: str
    last_seen: str
    alive: bool = True


@dataclass
class _State:
    snapshots: dict[str, tuple[dict, str | None]] = field(default_factory=dict)
    positions: dict[str, tuple[dict, str | None]] = field(default_factory=dict)
    by_snapshot: dict[str, set[str]] = field(default_factory=dict)


def sid(value) -> str:
    return "" if value is None else str(value)


def open_mirror(cfg: Config) -> sqlite3.Connection | None:
    if not cfg.mirror_db.exists():
        return None
    return connect(cfg.mirror_db, readonly=True)


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def current_rows(conn: sqlite3.Connection, tbl: str) -> Iterator[dict]:
    if not has_table(conn, "rows"):
        return
    for r in conn.execute("SELECT json FROM rows WHERE tbl=?", (tbl,)):
        try:
            yield json.loads(r["json"])
        except ValueError:
            continue


def _history(conn: sqlite3.Connection) -> Iterator[sqlite3.Row]:
    if has_table(conn, "row_history"):
        yield from conn.execute("SELECT tbl, id, json, at, pulled_at, op FROM row_history WHERE tbl IN ('snapshots', 'positions') ORDER BY seq")
        return
    if has_table(conn, "rows"):
        yield from conn.execute(
            "SELECT tbl, id, json, at, '' AS pulled_at, 'upsert' AS op FROM rows WHERE tbl IN ('snapshots', 'positions') ORDER BY tbl DESC, id"
        )


def snapshot_versions(conn: sqlite3.Connection) -> dict[str, SnapshotVersion]:
    state = _State()
    seen: dict[str, SnapshotVersion] = {}
    dirty: set[str] = set()
    doc_key: dict[str, str] = {}
    pull: str | None = None

    def capture(stamp: str) -> None:
        for s in dirty:
            if s in state.snapshots:
                snap, _ = state.snapshots[s]
                ids = sorted(state.by_snapshot.get(s, ()))
                rows = [state.positions[i] for i in ids]
                prev = seen.get(s)
                seen[s] = SnapshotVersion(
                    snapshot_id=s,
                    snap=snap,
                    positions=[p for p, _ in rows],
                    position_at=[a for _, a in rows],
                    first_seen=prev.first_seen if prev else stamp,
                    last_seen=stamp,
                )
            elif s in seen:
                seen[s].alive = False
        dirty.clear()

    for r in _history(conn):
        if pull is not None and r["pulled_at"] != pull:
            capture(pull)
        pull = r["pulled_at"]
        if r["tbl"] == "snapshots":
            if r["op"] == "delete" or r["json"] is None:
                key = doc_key.pop(r["id"], r["id"])
                state.snapshots.pop(key, None)
                dirty.add(key)
                continue
            snap = json.loads(r["json"])
            key = sid(snap.get("id", r["id"]))
            doc_key[r["id"]] = key
            state.snapshots[key] = (snap, r["at"])
            dirty.add(key)
            continue
        old = state.positions.pop(r["id"], None)
        if old is not None:
            owner = sid(old[0].get("snapshotId"))
            state.by_snapshot.get(owner, set()).discard(r["id"])
            dirty.add(owner)
        if r["op"] == "delete" or r["json"] is None:
            continue
        pos = json.loads(r["json"])
        owner = sid(pos.get("snapshotId"))
        state.positions[r["id"]] = (pos, r["at"])
        state.by_snapshot.setdefault(owner, set()).add(r["id"])
        dirty.add(owner)
    if pull is not None:
        capture(pull)
    return seen


def closes(conn: sqlite3.Connection) -> dict[str, dict[str, tuple[float, float | None]]]:
    out: dict[str, dict[str, tuple[float, float | None]]] = {}
    for doc in current_rows(conn, "priceCloses"):
        symbol = str(doc.get("symbol") or "").upper()
        if not symbol:
            continue
        series = out.setdefault(symbol, {})
        for row in doc.get("rows") or []:
            if not isinstance(row, list | tuple) or len(row) < 2 or row[1] is None:
                continue
            adj = row[2] if len(row) > 2 else None
            series[str(row[0])[:10]] = (float(row[1]), None if adj is None else float(adj))
    return out
