from desk.db import connect
from desk.engine.__main__ import run_holdings
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"
HSA = "hsa-2222"


def seed_two_days(m):
    m.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 1500.0, 3))
    m.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0, 900.0))
    m.put("positions", 2, position(2, 1, IND, "SPAXX", 300, 300.0, cash=True))
    m.put("positions", 3, position(3, 1, HSA, "FXAIX", 1, 200.0, 150.0))
    m.put("priceCloses", "FXAIX_2026", closes_doc("FXAIX", 2026, [["2026-11-02", 200.0, 200.0], ["2026-11-03", 210.0, 210.0], ["2026-11-04", 220.0, 220.0]]))
    m.pull("2026-11-02T13:00:00+00:00")


def rows_on(cfg, day):
    conn = connect(cfg.desk_db, readonly=True)
    try:
        return {(r["account"], r["symbol"]): dict(r) for r in conn.execute("SELECT * FROM holdings_daily WHERE date=?", (day,))}
    finally:
        conn.close()


def test_snapshot_day_and_rolled_days_priced_by_closes(cfg, mirror):
    seed_two_days(mirror)
    result = run_holdings(cfg)
    assert result["ok"] and result["anchors"] == 1 and result["first"] == "2026-11-02" and result["last"] == "2026-11-04"
    day1 = rows_on(cfg, "2026-11-02")
    assert day1[(IND, "FXAIX")]["value"] == 1000.0 and day1[(IND, "FXAIX")]["source"] == "snapshot" and day1[(IND, "FXAIX")]["quality"] == "ok"
    assert day1[(IND, "SPAXX")]["value"] == 300.0 and day1[(IND, "SPAXX")]["is_cash"] == 1
    day3 = rows_on(cfg, "2026-11-04")
    assert day3[(IND, "FXAIX")]["value"] == 1100.0 and day3[(HSA, "FXAIX")]["value"] == 220.0
    assert day3[(IND, "FXAIX")]["source"] == "rolled" and day3[(IND, "FXAIX")]["quality"] == "pro_forma"


def test_activity_moves_shares_and_cash_between_snapshots(cfg, mirror):
    seed_two_days(mirror)
    mirror.put("activity", "a1", {"date": "2026-11-03", "accountKey": IND, "kind": "buy", "symbol": "FXAIX", "quantity": 1, "amount": -210.0, "core": False})
    mirror.put("activity", "a2", {"date": "2026-11-03", "accountKey": IND, "kind": "buy", "symbol": "SPAXX", "quantity": 1, "amount": 50.0, "core": True})
    mirror.put("activity", "a3", {"date": "2026-11-04", "accountKey": IND, "kind": "deposit", "symbol": None, "quantity": None, "amount": 500.0, "core": False})
    mirror.pull("2026-11-04T22:00:00+00:00")
    run_holdings(cfg)
    day2 = rows_on(cfg, "2026-11-03")
    assert day2[(IND, "FXAIX")]["shares"] == 6 and day2[(IND, "FXAIX")]["value"] == 1260.0
    assert day2[(IND, "SPAXX")]["value"] == 90.0
    day3 = rows_on(cfg, "2026-11-04")
    assert day3[(IND, "SPAXX")]["value"] == 590.0


def test_keeps_snapshots_escape_vektor_later_deletes(cfg, mirror):
    seed_two_days(mirror)
    mirror.put("snapshots", 2, snapshot(2, "2026-11-03T08:00", 1800.0, 2))
    mirror.put("positions", 10, position(10, 2, IND, "FXAIX", 8, 1680.0, 1500.0))
    mirror.put("positions", 11, position(11, 2, IND, "SPAXX", 120, 120.0, cash=True))
    mirror.pull("2026-11-03T13:00:00+00:00")
    for pid in (1, 2, 3):
        mirror.drop("positions", pid)
    mirror.drop("snapshots", 1)
    mirror.pull("2026-11-10T13:00:00+00:00")
    result = run_holdings(cfg)
    assert result["anchors"] == 2
    assert rows_on(cfg, "2026-11-02")[(IND, "FXAIX")]["shares"] == 5
    assert rows_on(cfg, "2026-11-03")[(IND, "FXAIX")]["shares"] == 8
    assert (HSA, "FXAIX") not in rows_on(cfg, "2026-11-03")
    conn = connect(cfg.desk_db, readonly=True)
    alive = dict(conn.execute("SELECT snapshot_id, alive FROM engine_snapshots").fetchall())
    conn.close()
    assert alive == {"1": 0, "2": 1}


def test_replaced_positions_that_linger_are_trimmed_by_count(cfg, mirror):
    seed_two_days(mirror)
    mirror.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 1300.0, 2), at="2026-11-02T15:00:00.000000Z")
    mirror.put("positions", 21, position(21, 1, IND, "FXAIX", 6, 1200.0), at="2026-11-02T15:00:00.000000Z")
    mirror.put("positions", 22, position(22, 1, IND, "SPAXX", 100, 100.0, cash=True), at="2026-11-02T15:00:00.000000Z")
    mirror.pull("2026-11-02T22:00:00+00:00")
    run_holdings(cfg)
    day1 = rows_on(cfg, "2026-11-02")
    assert day1[(IND, "FXAIX")]["shares"] == 6 and (HSA, "FXAIX") not in day1
    assert {r["quality"] for r in day1.values()} == {"trimmed"}


def test_total_mismatch_is_flagged(cfg, mirror):
    mirror.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 5000.0, 1))
    mirror.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0))
    mirror.pull("2026-11-02T13:00:00+00:00")
    run_holdings(cfg)
    assert rows_on(cfg, "2026-11-02")[(IND, "FXAIX")]["quality"] == "mismatch"


def test_missing_closes_fall_back_to_snapshot_price(cfg, mirror):
    mirror.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 300.0, 1))
    mirror.put("positions", 1, position(1, 1, IND, "ASML", 3, 300.0))
    mirror.pull("2026-11-02T13:00:00+00:00")
    run_holdings(cfg)
    row = rows_on(cfg, "2026-11-02")[(IND, "ASML")]
    assert row["close"] == 100.0 and row["value"] == 300.0 and row["quality"] == "pro_forma"


def test_no_mirror_and_empty_mirror(cfg, mirror):
    mirror.close()
    cfg.mirror_db.unlink()
    assert run_holdings(cfg)["ok"] is False
    from desk.mirror.store import MirrorStore

    MirrorStore(cfg.mirror_db).close()
    result = run_holdings(cfg)
    assert result["ok"] and result["rows"] == 0 and result["first"] is None


def test_rebuild_is_idempotent(cfg, mirror):
    seed_two_days(mirror)
    first = run_holdings(cfg)
    second = run_holdings(cfg)
    assert first["rows"] == second["rows"]
    conn = connect(cfg.desk_db, readonly=True)
    assert conn.execute("SELECT count(*) FROM engine_runs WHERE ok=1").fetchone()[0] == 2
    conn.close()


def test_api_holdings_and_value_series(cfg, mirror, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/holdings").json()["rows"] == []
    seed_two_days(mirror)
    run_holdings(cfg)
    body = client.get("/api/engine/holdings").json()
    assert body["date"] == "2026-11-04" and body["value"] == 1100.0 + 300.0 + 220.0 and body["quality"] == "pro_forma"
    assert client.get("/api/engine/holdings", params={"date": "2026-11-02"}).json()["quality"] == "ok"
    series = client.get("/api/engine/value", params={"account": IND}).json()["series"]
    assert [p["value"] for p in series] == [1300.0, 1350.0, 1400.0]
