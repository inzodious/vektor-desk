from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.decisions.records import status_of
from desk.engine import core
from desk.engine.__main__ import run_holdings
from desk.engine.preflight import PreflightError, check_trade
from desk.engine.source import open_mirror
from desk.engine.tax import held_long, pick_lots, split_gain, wash_windows
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"
HSA = "hsa-2222"
NOW = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)


def flat(symbol, price):
    return closes_doc(symbol, 2026, [["2026-11-02", price, price], ["2026-11-03", price, price], ["2026-11-04", price, price]])


def seed(m, cash=300.0):
    plan = {
        "funds": [{"ticker": "FXAIX", "target_weight": 0.8}, {"ticker": "VXUS", "target_weight": 0.2}],
        "monthly_plan": [{"month": "2026-12", "contribution": 3000}],
    }
    m.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": plan})
    m.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 1000.0 + 200.0 + cash, 3))
    m.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0, 900.0))
    m.put("positions", 2, position(2, 1, IND, "ACME", 10, 200.0, 250.0))
    m.put("positions", 3, position(3, 1, IND, "SPAXX", cash, cash, cash=True))
    for sym, kind in (("ACME", "stock"), ("NEWCO", "stock"), ("FXAIX", "mutual_fund"), ("VXUS", "etf")):
        m.put("priceProfiles", sym, {"symbol": sym, "kind": kind})
    for sym, price in (("FXAIX", 200.0), ("ACME", 20.0), ("VXUS", 60.0), ("NEWCO", 10.0)):
        m.put("priceCloses", f"{sym}_2026", flat(sym, price))
    m.pull("2026-11-04T21:00:00+00:00")


def add_lots(cfg, lots, realized=()):
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        fid = desk.execute(
            "INSERT INTO lot_files (sha256, name, kind, as_of, imported_at, rows) VALUES ('a', 'lots.csv', 'lots', '2026-11-04', '2026-11-04', ?)", (len(lots),)
        ).lastrowid
        desk.executemany(
            "INSERT INTO lots (file_id, as_of, account, symbol, acquired, shares, cost, cost_per_share) VALUES (?, '2026-11-04', ?, ?, ?, ?, ?, ?)",
            [(fid, a, s, d, n, c, c / n) for a, s, d, n, c in lots],
        )
        if realized:
            rid = desk.execute(
                "INSERT INTO lot_files (sha256, name, kind, as_of, imported_at, rows) VALUES ('b', 'gl.csv', 'realized', '2026-11-04', '2026-11-04', ?)",
                (len(realized),),
            ).lastrowid
            desk.executemany(
                "INSERT INTO realized_lots (file_id, account, symbol, acquired, sold, shares, proceeds, cost, gain, term) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(rid, *r) for r in realized],
            )
    desk.close()


def lights(result):
    return {light["id"]: light for light in result["lights"]}


# ---- Lots and wash windows ----


def test_held_long_needs_more_than_a_year():
    assert held_long("2025-11-04", "2026-11-04") is False
    assert held_long("2025-11-04", "2026-11-05") is True
    assert held_long(None, "2026-11-05") is None


def test_lot_methods():
    lots = [
        {"acquired": "2024-01-02", "shares": 5, "cost_per_share": 30.0},
        {"acquired": "2026-10-01", "shares": 5, "cost_per_share": 10.0},
        {"acquired": "2025-06-01", "shares": 5, "cost_per_share": 25.0},
    ]
    high, _ = pick_lots(lots, 6, 20.0, "highest_cost", "2026-11-04")
    assert [p["acquired"] for p in high] == ["2024-01-02", "2025-06-01"] and high[1]["shares"] == 1
    fifo, _ = pick_lots(lots, 5, 20.0, "fifo", "2026-11-04")
    assert fifo[0]["acquired"] == "2024-01-02" and fifo[0]["gain"] == -50.0 and fifo[0]["term"] == "long"
    lifo, short = pick_lots(lots, 20, 20.0, "lifo", "2026-11-04")
    assert lifo[0]["acquired"] == "2026-10-01" and short == 5
    assert split_gain(lifo) == (50.0, -75.0)
    efficient, _ = pick_lots(lots, 5, 20.0, "tax_efficient", "2026-11-04")
    assert efficient[0]["acquired"] == "2024-01-02"


def test_wash_windows_from_loss_sales_and_buys():
    activity = [
        {"date": "2026-10-20", "accountKey": HSA, "kind": "buy", "symbol": "ACME", "amount": -100.0},
        {"date": "2026-09-01", "accountKey": IND, "kind": "buy", "symbol": "ACME", "amount": -100.0},
        {"date": "2026-10-21", "accountKey": IND, "kind": "buy", "symbol": "SPAXX", "amount": -100.0, "core": True},
    ]
    realized = [{"account": IND, "symbol": "VOO", "sold": "2026-10-25", "gain": -80.0}, {"account": IND, "symbol": "BND", "sold": "2026-10-25", "gain": 5.0}]
    windows = wash_windows(activity, realized, [], "2026-11-04")
    assert [(w["symbol"], w["kind"], w["clears"]) for w in windows] == [("ACME", "recent_buy", "2026-11-20"), ("VOO", "loss_sale", "2026-11-25")]


# ---- Preflight ----


def test_buy_that_closes_drift_is_clear_apart_from_old_drift(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    r = check_trade(cfg, {"kind": "buy", "symbol": "VXUS", "amount_usd": 300, "funding": "cash"}, now=NOW)
    lamps = lights(r)
    assert r["trade"]["account"] == IND and r["trade"]["shares"] == 5.0
    assert lamps["drift_after"]["status"] == "ok" and lamps["drift_after"]["before"] == 20.0 and lamps["drift_after"]["after"] == pytest.approx(13.3333)
    assert lamps["funding"]["status"] == "ok" and lamps["wash_sales"]["status"] == "ok" and lamps["concentration"]["status"] == "ok"
    assert lamps["plan_rules"]["status"] == "watch"
    assert r["status"] == "flagged" and status_of(r) == "flagged"


def test_margin_funded_buy_is_blocked_with_the_cost(cfg, mirror, monkeypatch):
    monkeypatch.setenv("DESK_MARGIN_RATE_PCT", "12")
    seed(mirror)
    run_holdings(cfg)
    r = check_trade(cfg, {"kind": "buy", "symbol": "ACME", "amount_usd": 500, "funding": "cash"}, now=NOW)
    lamps = lights(r)
    assert lamps["funding"]["status"] == "act" and "the other $200 goes on margin" in lamps["funding"]["detail"]
    assert "about $2 a month" in lamps["funding"]["detail"]
    assert lamps["plan_rules"]["status"] == "act" and "no-margin-buys" in lamps["plan_rules"]["detail"]
    assert r["status"] == "blocked" and status_of(r) == "blocked"
    m = {x["metric_id"]: x for x in r["metrics"]}
    assert m["margin.debit"]["before"] == 0 and m["margin.debit"]["after"] == 200.0 and m["margin.cost_month"]["after"] == 2.0


def test_new_single_stock_is_blocked(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    lamps = lights(check_trade(cfg, {"kind": "buy", "symbol": "NEWCO", "shares": 5}, now=NOW))
    assert lamps["concentration"]["status"] == "act" and "new single stock" in lamps["concentration"]["detail"]


def test_harvest_picks_lots_and_sets_the_wash_clear_date(cfg, mirror):
    seed(mirror)
    add_lots(cfg, [(IND, "ACME", "2025-01-10", 5, 150.0), (IND, "ACME", "2026-09-01", 5, 100.0), (IND, "FXAIX", "2024-01-02", 5, 900.0)])
    r = check_trade(cfg, {"kind": "harvest", "symbol": "ACME", "shares": 5}, now=NOW)
    lamps = lights(r)
    assert lamps["lots_tax"]["status"] == "ok" and lamps["lots_tax"]["after"] == -50.0
    assert r["tax"]["realized_lt"] == -50.0 and r["tax"]["realized_st"] == 0 and r["tax"]["lots"][0]["acquired"] == "2025-01-10"
    assert lamps["wash_sales"]["status"] == "ok" and r["tax"]["wash_clear_date"] == "2026-12-05" and r["tax"]["harvest_loss"] == 50.0
    assert lamps["plan_rules"]["status"] == "watch" and r["status"] == "flagged"


def test_loss_sale_after_a_recent_buy_is_a_wash(cfg, mirror):
    seed(mirror)
    mirror.put("activity", "a1", {"date": "2026-10-20", "accountKey": HSA, "kind": "buy", "symbol": "ACME", "quantity": 1, "amount": -20.0})
    mirror.pull("2026-11-04T21:30:00+00:00")
    add_lots(cfg, [(IND, "ACME", "2025-01-10", 10, 300.0)])
    lamps = lights(check_trade(cfg, {"kind": "sell", "symbol": "ACME", "shares": 10}, now=NOW))
    assert lamps["wash_sales"]["status"] == "act" and lamps["wash_sales"]["clears"] == "2026-11-20" and HSA in lamps["wash_sales"]["detail"]


def test_scheduled_deposit_into_the_same_fund_is_flagged(cfg, mirror):
    seed(mirror)
    add_lots(cfg, [(IND, "FXAIX", "2026-01-05", 5, 1100.0)])
    r = check_trade(cfg, {"kind": "harvest", "symbol": "FXAIX", "shares": 5}, now=NOW)
    lamps = lights(r)
    assert lamps["lots_tax"]["after"] == -100.0
    assert lamps["wash_sales"]["status"] == "watch" and "2026-12-01 deposit buys FXAIX" in lamps["wash_sales"]["detail"]


def test_buying_back_after_a_loss_sale(cfg, mirror):
    seed(mirror)
    add_lots(cfg, [(IND, "ACME", "2025-01-10", 10, 300.0)], realized=[(IND, "ACME", "2025-01-10", "2026-10-25", 4, 80.0, 160.0, -80.0, "long")])
    r = check_trade(cfg, {"kind": "buy", "symbol": "ACME", "amount_usd": 100}, now=NOW)
    lamps = lights(r)
    assert lamps["wash_sales"]["status"] == "act" and "$80 loss" in lamps["wash_sales"]["detail"] and r["tax"]["wash_clear_date"] == "2026-11-25"
    similar = lights(check_trade(cfg, {"kind": "buy", "symbol": "FXAIX", "amount_usd": 100}, now=NOW))
    assert similar["wash_sales"]["status"] == "ok"


def test_sale_without_lots_asks_for_an_export(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    r = check_trade(cfg, {"kind": "sell", "symbol": "ACME"}, now=NOW)
    assert r["trade"]["shares"] == 10 and lights(r)["lots_tax"]["status"] == "watch" and r["status"] == "flagged"


def test_bad_trades(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    with pytest.raises(PreflightError):
        check_trade(cfg, {"kind": "buy", "symbol": "ACME"}, now=NOW)
    with pytest.raises(PreflightError):
        check_trade(cfg, {"kind": "sell", "symbol": "VXUS", "shares": 1}, now=NOW)
    with pytest.raises(PreflightError):
        check_trade(cfg, {"kind": "buy", "symbol": "ZZZZ", "shares": 1}, now=NOW)
    assert check_trade(cfg, {"kind": "hold_off", "symbol": "ACME"}, now=NOW)["status"] == "clear"


def test_ticket_rows_are_stored_and_served(cfg, mirror, app_client):
    seed(mirror)
    run_holdings(cfg)
    check_trade(cfg, {"kind": "buy", "symbol": "VXUS", "amount_usd": 300}, ticket_id="t1", now=NOW)
    check_trade(cfg, {"kind": "buy", "symbol": "VXUS", "amount_usd": 120}, ticket_id="t1", now=NOW)
    client = app_client(packages=["engine"])
    rows = {r["metric_id"]: r for r in client.get("/api/engine/preflight", params={"ticket_id": "t1"}).json()["rows"]}
    assert len(rows) == 8 and rows["plan.drift_max"]["before"] == 20.0 and rows["plan.drift_max"]["after"] == pytest.approx(13.3333)
    assert rows["value.market"]["after"] == 1500.0
    body = client.post("/api/preflight", json={"kind": "buy", "symbol": "VXUS", "amount_usd": 300}).json()
    assert body["status"] in ("clear", "flagged") and len(body["lights"]) == 6
    assert client.post("/api/preflight", json={"kind": "buy", "symbol": "ACME"}).status_code == 400


def test_core_tax_metrics_and_wash_calendar(cfg, mirror, app_client):
    seed(mirror)
    mirror.put("activity", "a1", {"date": "2026-10-20", "accountKey": HSA, "kind": "buy", "symbol": "VXUS", "quantity": 1, "amount": -60.0})
    mirror.pull("2026-11-04T21:30:00+00:00")
    add_lots(
        cfg,
        [(IND, "ACME", "2025-01-10", 10, 600.0), (IND, "FXAIX", "2026-06-01", 5, 900.0)],
        realized=[
            (IND, "BND", "2025-01-10", "2026-03-02", 4, 300.0, 200.0, 100.0, "long"),
            (IND, "VOO", "2026-05-01", "2026-10-25", 1, 400.0, 480.0, -80.0, "short"),
        ],
    )
    mirror_conn, desk = open_mirror(cfg), connect(cfg.desk_db)
    try:
        core.store(desk, core.compute(cfg, mirror_conn, desk, now=NOW))
        m = {(r["metric_id"], r["scope_id"]): r["value"] for r in desk.execute("SELECT * FROM metric_values")}
    finally:
        desk.close()
        mirror_conn.close()
    assert m[("tax.realized_lt", "all")] == 100.0 and m[("tax.realized_st", "all")] == -80.0
    assert m[("tax.unrealized_lt", "all")] == -400.0 and m[("tax.unrealized_st", "all")] == 100.0
    assert m[("tax.harvestable", "ACME")] == 400.0 and m[("tax.harvestable", "all")] == 400.0
    assert m[("tax.wash_window", "VOO")] == 21 and m[("tax.wash_window", "VXUS")] == 16
    windows = app_client(packages=["engine"]).get("/api/engine/wash").json()["windows"]
    assert [(w["symbol"], w["kind"]) for w in windows] == [("VXUS", "recent_buy"), ("VOO", "loss_sale")]
