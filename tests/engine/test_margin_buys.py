from dataclasses import replace

from desk.db import connect
from desk.engine import __main__ as engine_main
from desk.engine.__main__ import run_holdings
from desk.engine.holdings import Anchor, settle
from tests.engine.helpers import closes_doc, position, snapshot
from tests.engine.test_broker import FRI, IND, IND_NUM, MON, THU, WED, computed, drop, export, txn

COVER = {"ind": ("2026-01-01", "2026-12-31")}


def anchor(day, shares, cash, account="ind", symbol="ROKT"):
    rows = {(account, symbol): {"shares": shares, "value": shares * 30.0, "cost": None, "is_cash": False}}
    if cash is not None:
        rows[(account, "SPAXX")] = {"shares": cash, "value": cash, "cost": None, "is_cash": True}
    return Anchor(day, f"{day}T21:00", day, rows, "ok")


def buy(day, usd, qty, account="ind", symbol="ROKT"):
    return {"date": day, "accountKey": account, "kind": "buy", "symbol": symbol, "quantity": qty, "amount": -usd, "core": False}


def cash_row(day, kind, usd, account="ind"):
    return {"date": day, "accountKey": account, "kind": kind, "symbol": None, "quantity": None, "amount": usd, "core": False}


# ---- Settle ----


def test_an_unsettled_margin_buy_becomes_a_debit_not_a_deposit():
    a, b = anchor(MON, 10, 100.0), anchor(WED, 20, 250.0)
    activity = {WED: [cash_row(WED, "deposit", 150.0), buy(WED, 360.0, 10)]}
    notes = settle([a, b], activity, COVER)
    assert notes == [{"account": "ind", "date": WED, "amount": 360.0, "debit": 110.0}]
    assert b.rows[("ind", "SPAXX")]["shares"] == -110.0 and b.rows[("ind", "SPAXX")]["value"] == 250.0 and b.rows[("ind", "SPAXX")]["modelled"] is True


def test_the_debit_carries_until_money_comes_in_or_shares_are_sold():
    a, b, c, d = anchor(MON, 10, 100.0), anchor(WED, 20, 250.0), anchor(THU, 20, 0.0), anchor(FRI, 20, 0.0)
    activity = {WED: [cash_row(WED, "deposit", 150.0), buy(WED, 360.0, 10)], FRI: [cash_row(FRI, "deposit", 110.0)]}
    notes = settle([a, b, c, d], activity, COVER)
    assert [(n["date"], n["amount"], n["debit"]) for n in notes] == [(WED, 360.0, 110.0), (THU, 110.0, 110.0)]
    assert c.rows[("ind", "SPAXX")]["shares"] == -110.0 and d.rows[("ind", "SPAXX")]["shares"] == 0.0 and "modelled" not in d.rows[("ind", "SPAXX")]
    partial = [anchor(MON, 10, 100.0), anchor(WED, 20, 250.0), anchor(FRI, 20, 0.0)]
    settle(partial, {WED: activity[WED], FRI: [cash_row(FRI, "deposit", 60.0)]}, COVER)
    assert partial[2].rows[("ind", "SPAXX")]["shares"] == -50.0


def test_settled_cash_buys_and_unexplained_gaps_are_left_alone():
    settled = [anchor(MON, 10, 500.0), anchor(WED, 20, 140.0)]
    assert settle(settled, {WED: [buy(WED, 360.0, 10)]}, COVER) == [] and settled[1].rows[("ind", "SPAXX")]["shares"] == 140.0
    early = [anchor(MON, 10, 100.0), anchor(WED, 10, 100.0)]
    assert settle(early, {WED: [buy(WED, 360.0, 10)]}, COVER) == [] and early[1].rows[("ind", "SPAXX")]["shares"] == 100.0
    uncovered = [anchor(MON, 10, 100.0), anchor(WED, 20, 100.0)]
    assert settle(uncovered, {WED: [buy(WED, 360.0, 10)]}, {}) == []
    assert settle([anchor(MON, 10, 100.0), anchor(WED, 20, 100.0)], {WED: [buy(WED, 360.0, 10)]}, {"ind": ("2026-01-01", MON)}) == []
    gift = [anchor(MON, 10, 100.0), anchor(WED, 10, 900.0)]
    assert settle(gift, {}, COVER) == [] and gift[1].rows[("ind", "SPAXX")]["shares"] == 900.0
    capped = [anchor(MON, 10, 100.0), anchor(WED, 20, 900.0)]
    assert settle(capped, {WED: [buy(WED, 360.0, 10)]}, COVER)[0]["amount"] == 360.0 and capped[1].rows[("ind", "SPAXX")]["shares"] == 540.0
    shown = [anchor(MON, 10, 100.0), anchor(WED, 20, -260.0)]
    assert settle(shown, {WED: [buy(WED, 360.0, 10)]}, COVER) == [] and shown[1].rows[("ind", "SPAXX")]["shares"] == -260.0
    bare = [anchor(MON, 10, 0.0), anchor(WED, 20, None)]
    assert settle(bare, {WED: [buy(WED, 360.0, 10)]}, COVER)[0]["debit"] == 360.0 and bare[1].rows[("ind", "CASH")]["shares"] == -360.0


# ---- Through the engine ----


def seed(mirror):
    mirror.put("snapshots", 1, snapshot(1, f"{MON}T21:00", 400.0, 2))
    mirror.put("positions", 1, position(1, 1, IND, "ROKT", 10.0, 300.0, 300.0))
    mirror.put("positions", 2, position(2, 1, IND, "SPAXX", 100.0, 100.0, cash=True))
    mirror.put("snapshots", 2, snapshot(2, f"{WED}T21:00", 970.0, 2))
    mirror.put("positions", 3, position(3, 2, IND, "ROKT", 20.0, 720.0, 660.0))
    mirror.put("positions", 4, position(4, 2, IND, "SPAXX", 250.0, 250.0, cash=True))
    mirror.put("snapshots", 3, snapshot(3, f"{FRI}T21:00", 740.0, 2))
    mirror.put("positions", 5, position(5, 3, IND, "ROKT", 20.0, 740.0, 660.0))
    mirror.put("positions", 6, position(6, 3, IND, "SPAXX", 0.0, 0.0, cash=True))
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [[MON, 30, 30], ["2026-11-03", 31, 31], [WED, 36, 36], [THU, 36, 36], [FRI, 37, 37]]))
    mirror.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {"funds": [{"ticker": "FXAIX", "target_weight": 1.0}]}})
    mirror.pull(f"{FRI}T22:00:00+00:00")


def test_the_engine_books_a_margin_buy_as_debt(cfg, mirror):
    seed(mirror)
    rows = [txn(IND_NUM, WED, "Deposit", net=150, dw="D"), txn(IND_NUM, WED, "Buy", symbol="ROKT", qty=10, net=360, price=36, margin=True)]
    drop(cfg, "history.json", export(rows, start="2026-09-01", end=FRI))
    assert engine_main.run_history(cfg)["ok"]
    held = run_holdings(cfg)
    assert [(n["date"], n["debit"]) for n in held["margin_modelled"]] == [(WED, 110.0), (FRI, 110.0)]
    conn = connect(cfg.desk_db, readonly=True)
    cash = {r["date"]: (r["value"], r["reported_value"], r["quality"]) for r in conn.execute("SELECT * FROM holdings_daily WHERE symbol='SPAXX' ORDER BY date")}
    conn.close()
    assert cash[WED] == (-110.0, 250.0, "modelled") and cash[THU][0] == -110.0 and cash[FRI] == (-110.0, 0.0, "modelled")
    out = computed(replace(cfg, stale_hours=48))
    debit = next(m for m in out.metrics if m[0] == "margin.debit")
    assert (debit[5], debit[8]) == (110.0, "modelled") and out.implied == {}
    value = {m[4]: m[5] for m in out.metrics if m[0] == "value.market" and m[1] == "portfolio"}
    assert list(value.values()) == [630.0]
    conn = connect(cfg.desk_db, readonly=True)
    flows = [(r["date"], r["amount"]) for r in conn.execute("SELECT date, amount FROM cash_flows WHERE external_portfolio=1")]
    conn.close()
    assert flows == [(WED, 150.0)]


def test_without_history_the_same_gap_stays_money_in(cfg, mirror):
    seed(mirror)
    mirror.put("activity", "a1", {"date": WED, "accountKey": IND, "kind": "buy", "symbol": "ROKT", "quantity": 10, "amount": -360.0, "core": False})
    mirror.pull(f"{FRI}T22:30:00+00:00")
    assert run_holdings(cfg)["margin_modelled"] == []
    out = computed(cfg)
    assert out.implied and next(m for m in out.metrics if m[0] == "margin.debit")[5] == 0.0
