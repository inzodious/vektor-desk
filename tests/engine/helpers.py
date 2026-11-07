import json

from desk.mirror import store as mirror_store
from desk.mirror.firestore import Row
from desk.mirror.store import MirrorStore


class MirrorBuilder:
    def __init__(self, path, monkeypatch):
        self.store = MirrorStore(path)
        self.monkeypatch = monkeypatch
        self.tables: dict[str, dict[str, Row]] = {}

    def put(self, tbl, rid, row, at="2026-11-02T13:00:00.000000Z"):
        self.tables.setdefault(tbl, {})[str(rid)] = Row(id=str(rid), json=json.dumps(row), at=at)

    def drop(self, tbl, rid):
        self.tables.get(tbl, {}).pop(str(rid), None)

    def pull(self, stamp):
        self.monkeypatch.setattr(mirror_store, "now_iso", lambda: stamp)
        self.store.apply({t: list(rows.values()) for t, rows in self.tables.items()})

    def close(self):
        self.store.close()


def snapshot(sid, as_of, total, count, source="sync"):
    return {"id": sid, "asOf": as_of, "total": total, "positionCount": count, "source": source}


def position(pid, sid, account, symbol, qty, value, cost=None, cash=False):
    return {"id": pid, "snapshotId": sid, "accountKey": account, "symbol": symbol, "quantity": qty, "value": value, "cost": cost, "isCash": cash}


def closes_doc(symbol, year, rows):
    return {"symbol": symbol, "year": year, "rows": rows}
