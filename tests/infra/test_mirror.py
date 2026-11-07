import json
from datetime import UTC, datetime, timedelta

import pytest

from desk.config import DEFAULT_TABLES
from desk.db import connect
from desk.mirror import FirestoreReader, MirrorError, MirrorRefused, MirrorStore, run_mirror
from desk.mirror.firestore import norm_ts
from tests.fakes import FakeFirestore, Res, doc


def seed():
    return {
        "snapshots": [doc("snapshots", "1", {"id": 1, "asOf": "2026-11-06T16:00", "total": 100.0})],
        "positions": [doc("positions", str(i), {"id": i, "snapshotId": 1, "symbol": f"S{i}", "value": i * 10.0}) for i in range(1, 6)],
        "prices": [doc("prices", "board", {"quotes": {}, "ranges": {}})],
    }


def test_reader_pages_and_parses():
    fake = FakeFirestore(seed(), page=2)
    reader = FirestoreReader("demo-project", "user-1", fake)
    rows = list(reader.rows("positions"))
    assert [r.id for r in rows] == ["1", "2", "3", "4", "5"]
    assert json.loads(rows[0].json)["symbol"] == "S1"
    assert rows[0].at == "2026-11-07T13:00:00.000000Z"
    assert sum(1 for c in fake.calls if c[0] == "GET") == 3
    assert all(c[0] in ("GET", "POST") for c in fake.calls)


def test_reader_rejects_odd_tables():
    reader = FirestoreReader("demo-project", "user-1", FakeFirestore({}))
    with pytest.raises(MirrorError):
        list(reader.rows("../users"))


def test_reader_needs_settings():
    with pytest.raises(MirrorError):
        FirestoreReader("", "user-1", FakeFirestore({}))


def test_reader_raises_on_http_error():
    class Broken(FakeFirestore):
        def get(self, url, params=None, timeout=None):
            return Res(403, {})

    with pytest.raises(MirrorError) as e:
        list(FirestoreReader("p", "u", Broken({})).rows("positions"))
    assert e.value.status == 403


def test_mirror_writes_rows_views_and_runs(cfg):
    store = MirrorStore(cfg.mirror_db)
    result = run_mirror(FirestoreReader("p", "u", FakeFirestore(seed())), store)
    store.close()
    assert result["ok"] and result["tables"] == 3 and result["rows"] == 7 and result["changed"] == 7 and result["read"] == 7
    conn = connect(cfg.mirror_db, readonly=True)
    assert conn.execute("SELECT count(*) FROM ev_positions").fetchone()[0] == 5
    assert conn.execute("SELECT rows FROM tables WHERE tbl='prices'").fetchone()[0] == 1
    assert conn.execute("SELECT ok FROM runs ORDER BY id DESC").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_history_appends_only_changes(cfg):
    data = seed()
    store = MirrorStore(cfg.mirror_db)
    run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store)
    again = run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store)
    assert again["changed"] == 0
    data["positions"][0] = doc("positions", "1", {"id": 1, "snapshotId": 1, "symbol": "S1", "value": 99.0})
    data["positions"].pop()
    third = run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store, full=True)
    assert third["changed"] == 2
    ops = store.conn.execute("SELECT id, op FROM row_history WHERE tbl='positions' AND seq > 7 ORDER BY seq").fetchall()
    assert [(r["id"], r["op"]) for r in ops] == [("1", "upsert"), ("5", "delete")]
    assert store.conn.execute("SELECT count(*) FROM rows WHERE tbl='positions'").fetchone()[0] == 4
    store.close()


def test_prunes_tables_gone_from_firestore(cfg):
    data = seed()
    store = MirrorStore(cfg.mirror_db)
    run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store)
    del data["prices"]
    run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store)
    assert "prices" not in store.counts()
    assert store.conn.execute("SELECT count(*) FROM sqlite_master WHERE name='ev_prices'").fetchone()[0] == 0
    store.close()


def test_refuses_to_wipe_a_good_mirror(cfg):
    store = MirrorStore(cfg.mirror_db)
    run_mirror(FirestoreReader("p", "u", FakeFirestore(seed())), store)
    with pytest.raises(MirrorRefused):
        run_mirror(FirestoreReader("p", "u", FakeFirestore({"positions": []})), store, tables=["positions"], full=True)
    with pytest.raises(MirrorRefused):
        run_mirror(FirestoreReader("p", "u", FakeFirestore({})), store)
    assert store.counts() == {"positions": 5, "prices": 1, "snapshots": 1}
    last = store.conn.execute("SELECT ok, error FROM runs ORDER BY id DESC").fetchone()
    assert last["ok"] == 0 and "last good" in last["error"]
    store.close()


def test_falls_back_to_known_tables_when_listing_is_refused(cfg):
    store = MirrorStore(cfg.mirror_db)
    fake = FakeFirestore(seed(), list_status=403)
    result = run_mirror(FirestoreReader("p", "u", fake), store, fallback=DEFAULT_TABLES)
    assert result["tables"] == len(DEFAULT_TABLES)
    assert store.counts()["positions"] == 5
    store.close()


def test_skips_unparsable_rows(cfg):
    data = seed()
    data["positions"].append({"name": "x/positions/bad", "fields": {"json": {"stringValue": "{nope"}}})
    store = MirrorStore(cfg.mirror_db)
    result = run_mirror(FirestoreReader("p", "u", FakeFirestore(data, page=10)), store)
    assert result["skipped"] == 1 and store.counts()["positions"] == 5
    store.close()


def test_incremental_reads_only_changed_rows_then_weekly_full(cfg):
    data = seed()
    store = MirrorStore(cfg.mirror_db)
    first = run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store)
    assert first["full_tables"] == 3
    data["positions"][1] = doc("positions", "2", {"id": 2, "snapshotId": 1, "symbol": "S2", "value": 21.0}, at="2026-11-07T22:00:00.5Z")
    data["positions"].append(doc("positions", "6", {"id": 6, "snapshotId": 1, "symbol": "S6", "value": 60.0}, at="2026-11-07T22:00:01Z"))
    data["positions"].pop(0)
    fake = FakeFirestore(data)
    second = run_mirror(FirestoreReader("p", "u", fake), store)
    assert second["full_tables"] == 0 and second["changed"] == 2
    assert not any(c[0] == "GET" for c in fake.calls)
    assert store.counts()["positions"] == 6
    assert store.table_info("positions")["max_at"] == "2026-11-07T22:00:01.000000Z"
    later = datetime.now(UTC) + timedelta(days=8)
    third = run_mirror(FirestoreReader("p", "u", FakeFirestore(data)), store, now=later)
    assert third["full_tables"] == 3 and store.counts()["positions"] == 5
    store.close()


def test_timestamps_sort_whatever_firestore_precision():
    assert norm_ts("2026-11-07T13:00:00Z") < norm_ts("2026-11-07T13:00:00.5Z") < norm_ts("2026-11-07T13:00:01Z")
