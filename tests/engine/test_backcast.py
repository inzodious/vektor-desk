import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from desk.db import connect
from desk.engine import __main__ as engine_main
from desk.engine import core, review
from desk.engine.__main__ import run_holdings
from desk.engine.backfill import past_gaps, sync_roles
from desk.engine.holdings import Anchor, Prices, apply_activity, backcast
from desk.engine.returns import twr_index
from desk.engine.source import open_mirror
from tests.engine.helpers import closes_doc, position, snapshot
from tests.engine.test_broker import FRI, HSA, HSA_NUM, IND, IND_NUM, drop, export, txn

START, FIRST = "2026-10-05", "2026-10-29"
NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
LEVELS = {"2026-10-05": 25, "2026-10-12": 26, "2026-10-19": 28, "2026-10-26": 29, "2026-11-02": 30, "2026-11-03": 31, "2026-11-04": 36, "2026-11-06": 37}
VALUES = [428.0] * 5 + [438.0] * 3 + [738.0] * 2 + [788.0] * 3 + [808.0] * 2 + [828.0] * 2 + [830.0]


def weekdays(lo=START, hi=FRI):
    out, d = [], date.fromisoformat(lo)
    while d.isoformat() <= hi:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def rokt_closes():
    out, px = [], None
    for d in weekdays():
        px = LEVELS.get(d, px)
        out.append([d, px, px])
    return out


def history():
    return [
        txn(IND_NUM, "2026-10-12", "Sell", symbol="OLDY", qty=-5, net=100, price=20, dw="D"),
        txn(IND_NUM, "2026-10-15", "Deposit", net=300, dw="D", desc="Electronic Funds Transfer Received (Cash)"),
        txn(IND_NUM, "2026-10-20", "Buy", symbol="ROKT", qty=10, net=280, price=28),
        txn(IND_NUM, "2026-10-28", "Dividend Paid", symbol="SPAXX", net=2, dw="D", sec="Mutual Fund"),
        txn(IND_NUM, "2026-10-28", "Dividend reinvest", symbol="SPAXX", qty=2, net=2, sec="Mutual Fund"),
    ]


def hsa_file():
    rows = [txn(HSA_NUM, "2026-10-22", "Other Cash", net=20, dw="D", desc="PARTIC CONTR CURRENT HSA CONTRIBUTION CURRENT YEAR CONTRIB (Cash)")]
    return {"config": {"yearsBack": 2, "accounts": [HSA_NUM]}, "fetchLog": [{"range": f"2026-10-19 → {FRI}", "status": 200}], "transactions": rows}


def seed(mirror):
    mirror.put("snapshots", 1, snapshot(1, f"{FIRST}T21:00", 830.0, 3))
    mirror.put("positions", 1, position(1, 1, IND, "ROKT", 20.0, 580.0, 530.0))
    mirror.put("positions", 2, position(2, 1, IND, "SPAXX", 200.0, 200.0, cash=True))
    mirror.put("positions", 3, position(3, 1, HSA, "SPAXX", 50.0, 50.0, cash=True))
    mirror.put("snapshots", 2, snapshot(2, f"{FRI}T21:00", 990.0, 3))
    mirror.put("positions", 4, position(4, 2, IND, "ROKT", 20.0, 740.0, 530.0))
    mirror.put("positions", 5, position(5, 2, IND, "SPAXX", 200.0, 200.0, cash=True))
    mirror.put("positions", 6, position(6, 2, HSA, "SPAXX", 50.0, 50.0, cash=True))
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, rokt_closes()))
    mirror.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {"funds": [{"ticker": "FXAIX", "target_weight": 1.0}]}})
    mirror.pull(f"{FRI}T22:00:00+00:00")


def computed(cfg):
    mirror, desk = open_mirror(cfg), connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=NOW)
        core.store(desk, out)
        reviewed = review.run(cfg, mirror, desk, now=NOW)
    finally:
        desk.close()
        mirror.close()
    return out, reviewed


def imported(cfg):
    drop(cfg, "history.json", export(history(), start=START, end=FRI))
    drop(cfg, "hsa.json", hsa_file())
    assert engine_main.run_history(cfg)["ok"]
    return run_holdings(cfg)


# ---- Rolling back ----


def anchor(rows):
    held = {k: {"shares": sh, "value": sh * px, "cost": None, "is_cash": px == 1.0 and k[1] == "SPAXX"} for k, (sh, px) in rows.items()}
    return Anchor("s1", f"{FIRST}T21:00", FIRST, held, "ok")


def act(day, account, kind, symbol=None, qty=None, amount=0.0):
    return {"date": day, "accountKey": account, "kind": kind, "symbol": symbol, "quantity": qty, "amount": amount, "core": symbol == "SPAXX"}


def prices(symbol="ROKT"):
    return Prices({symbol: {d: (px, px) for d, px, _ in rokt_closes()}})


def test_core_cash_income_moves_cash_and_its_reinvestment_does_not():
    held = {("ind", "SPAXX"): {"shares": 100.0, "value": 100.0, "cost": None, "is_cash": True}}
    rows = [act("2026-10-28", "ind", "dividend", "SPAXX", amount=2.0), act("2026-10-28", "ind", "reinvest", "SPAXX", qty=2, amount=-2.0)]
    apply_activity(held, rows)
    assert held[("ind", "SPAXX")]["shares"] == 102.0
    apply_activity(held, rows, sign=-1.0)
    assert held[("ind", "SPAXX")]["shares"] == 100.0


def test_backcast_undoes_activity_from_the_first_snapshot():
    first = anchor({("ind", "ROKT"): (20, 29.0), ("ind", "SPAXX"): (200, 1.0), ("alp", "ROKT"): (3, 29.0)})
    activity = {
        "2026-10-12": [act("2026-10-12", "ind", "sell", "OLDY", -5, 100.0)],
        "2026-10-20": [act("2026-10-20", "ind", "buy", "ROKT", 10, -280.0), act("2026-10-20", "alp", "buy", "ROKT", 3, -84.0)],
        "2026-11-03": [act("2026-11-03", "ind", "buy", "ROKT", 5, -155.0)],
    }
    rows, note = backcast(first, activity, {"ind": (START, FRI)}, prices())
    by = {(r[0], r[1], r[2]): r for r in rows}
    assert note == {"from": START, "days": 18, "accounts": {"ind": START}, "left_out": ["alp"], "unknown": [], "unpriced": ["OLDY"]}
    assert by[("2026-10-28", "ind", "ROKT")][3:6] == (20, 29, 580.0) and by[("2026-10-28", "ind", "SPAXX")][5] == 200.0
    assert by[("2026-10-19", "ind", "ROKT")][3:6] == (10, 28, 280.0) and by[("2026-10-19", "ind", "SPAXX")][5] == 480.0
    assert by[("2026-10-09", "ind", "OLDY")][3:6] == (5, 20.0, 100.0) and by[("2026-10-09", "ind", "OLDY")][11] == "modelled"
    assert by[("2026-10-09", "ind", "SPAXX")][5] == 380.0 and ("2026-10-12", "ind", "OLDY") not in by
    assert {r[9] for r in rows} == {"history"} and {r[11] for r in rows if r[2] != "OLDY"} == {"pro_forma"} and not [r for r in rows if r[1] == "alp"]
    assert all(r[6] is None and r[7] is None and r[10] == first.as_of for r in rows)


def test_backcast_flags_what_the_history_cannot_explain():
    short = anchor({("ind", "ROKT"): (5, 29.0), ("ind", "SPAXX"): (100, 1.0)})
    activity = {"2026-10-20": [act("2026-10-20", "ind", "buy", "ROKT", 10, -280.0)], "2026-10-13": [act("2026-10-13", "ind", "withdrawal", amount=-500.0)]}
    rows, note = backcast(short, activity, {"ind": (START, FRI)}, prices())
    by = {(r[0], r[1], r[2]): r for r in rows}
    assert note["unknown"] == [{"account": "ind", "symbol": "ROKT", "on_or_before": "2026-10-19"}]
    assert (
        ("2026-10-19", "ind", "ROKT") not in by
        and by[("2026-10-19", "ind", "SPAXX")][11] == "modelled"
        and by[("2026-10-20", "ind", "SPAXX")][11] == "pro_forma"
    )
    owed = anchor({("ind", "ROKT"): (20, 29.0), ("ind", "SPAXX"): (100, 1.0)})
    rows, _ = backcast(owed, {"2026-10-20": [act("2026-10-20", "ind", "deposit", amount=400.0)]}, {"ind": (START, FRI)}, prices())
    by = {(r[0], r[1], r[2]): r for r in rows}
    assert by[("2026-10-19", "ind", "SPAXX")][5] == -300.0 and by[("2026-10-19", "ind", "SPAXX")][11] == "modelled"
    assert by[("2026-10-19", "ind", "ROKT")][11] == "pro_forma"


def test_backcast_needs_cover_up_to_the_first_snapshot():
    first = anchor({("ind", "ROKT"): (20, 29.0)})
    for cover in ({}, {"ind": (START, "2026-10-20")}, {"ind": (FIRST, FRI)}, {"hsa": (START, FRI)}):
        rows, note = backcast(first, {}, cover, prices())
        assert rows == [] and note["days"] == 0 and note["left_out"] == ["ind"]
    assert backcast(first, {}, {"ind": (START, FRI)}, Prices({}))[0] == []


# ---- Through the engine ----


def test_history_carries_the_series_back_before_the_first_snapshot(cfg, mirror):
    seed(mirror)
    plain = run_holdings(cfg)
    assert plain["first"] == FIRST and plain["backcast"]["days"] == 0
    result = imported(cfg)
    assert result["first"] == START and result["days"] == 18 + 7
    assert result["backcast"] == {"from": START, "days": 18, "accounts": {HSA: "2026-10-19", IND: START}, "left_out": [], "unknown": [], "unpriced": ["OLDY"]}
    out, _ = computed(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    series = {
        sid: conn.execute("SELECT date, value, quality FROM series_daily WHERE series_id=? AND scope='portfolio' ORDER BY date", (sid,)).fetchall()
        for sid in ("value", "twr_index")
    }
    back = [r for r in series["value"] if r["date"] < FIRST]
    assert [r["date"] for r in back] == weekdays(START, "2026-10-28") and [r["value"] for r in back] == VALUES
    assert [r["quality"] for r in back] == ["modelled"] * 5 + ["pro_forma"] * 13
    assert out.implied == {(HSA, "2026-10-19"): 30.0}
    flows = [0.0] * 18
    flows[8], flows[10], flows[13] = 300.0, 30.0, 20.0
    want = twr_index(VALUES, flows)
    got = [r["value"] for r in series["twr_index"]][:18]
    assert [g / got[0] for g in got] == pytest.approx([w / want[0] for w in want])
    assert got[17] / got[0] == pytest.approx((438 / 428) * (758 / 738) * (828 / 808) * (830 / 828))
    hsa = conn.execute("SELECT min(date) FROM series_daily WHERE series_id='value' AND scope='account' AND scope_id=?", (HSA,)).fetchone()[0]
    assert hsa == "2026-10-19" and past_gaps(conn) == ["OLDY", "ROKT"]
    conn.close()
    desk = connect(cfg.desk_db)
    sync_roles(desk, NOW)
    assert desk.execute("SELECT role, priority FROM market_symbols WHERE symbol='OLDY'").fetchone()[:] == ("past", 3)
    desk.close()


def test_review_redoes_closed_packs_the_backcast_reaches(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    _, before = computed(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    old = {(r["kind"], r["end"]): (r["final"], json.loads(r["pack"])) for r in conn.execute('SELECT kind, "end", final, pack FROM period_reviews')}
    conn.close()
    assert old[("week", "2026-10-30")][0] == 1 and old[("week", "2026-10-30")][1]["coverage"] == pytest.approx(
        {"full": False, "base": FIRST, "days": 1, "note": f"The desk's history starts {FIRST}, so this covers {FIRST} to 2026-10-30 only."}
    )
    imported(cfg)
    _, after = computed(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    new = {(r["kind"], r["end"]): json.loads(r["pack"]) for r in conn.execute('SELECT kind, "end", pack FROM period_reviews')}
    conn.close()
    week, month = new[("week", "2026-10-30")], new[("month", "2026-10-30")]
    assert week["coverage"]["full"] is True and week["coverage"]["base"] == "2026-10-23" and week["value"]["start"] == 808.0
    assert month["coverage"]["base"] == START and month["value"]["start"] == 428.0 and month["quality"] == "modelled"
    assert month["value"]["net_flows"] == 350.0 and month["value"]["gain_usd"] == pytest.approx(month["value"]["end"] - 428.0 - 350.0)
    assert new[("day", "2026-10-30")] == old[("day", "2026-10-30")][1] and after["kept"] == sum(1 for k, (final, _) in old.items() if final and k[0] == "day")
    assert after["kinds"]["week"] == before["kinds"]["week"] + 3 and ("day", "2026-10-06") in new and after["kinds"]["day"] == 18 + 1


def test_daily_fetches_missing_backcast_prices_once(cfg, mirror, monkeypatch):
    seed(mirror)
    drop(cfg, "history.json", export(history(), start=START, end=FRI))
    drop(cfg, "hsa.json", hsa_file())
    calls = []

    def fake_backfill(c, carried=True):
        calls.append(1)
        desk = connect(c.desk_db)
        sync_roles(desk, NOW)
        with desk:
            if carried:
                desk.executemany(
                    "INSERT INTO price_bars (symbol, date, open, high, low, close, adj_close) VALUES ('OLDY', ?, 21, 21, 21, 21, 21)",
                    [(d,) for d in weekdays(START, "2026-10-12")],
                )
            desk.execute("UPDATE market_symbols SET fetched_at=? WHERE symbol='OLDY'", (NOW.isoformat(),))
        desk.close()
        return {"ok": True, "fetched": ["OLDY"] if carried else [], "unpriced": [] if carried else ["OLDY"]}

    monkeypatch.setattr(engine_main, "run_core", lambda c: {"ok": True})
    monkeypatch.setattr(engine_main, "run_market_backfill", lambda c: fake_backfill(c, carried=False))
    first = engine_main.run_daily(cfg)
    assert first["backfill"]["fetched"] == [] and first["holdings"]["backcast"]["unpriced"] == ["OLDY"] and len(calls) == 1
    assert "backfill" not in engine_main.run_daily(cfg) and len(calls) == 1
    desk = connect(cfg.desk_db)
    with desk:
        desk.execute("DELETE FROM market_symbols WHERE symbol='OLDY'")
    desk.close()
    monkeypatch.setattr(engine_main, "run_market_backfill", fake_backfill)
    second = engine_main.run_daily(cfg)
    assert second["backfill"]["fetched"] == ["OLDY"] and second["holdings"]["backcast"]["unpriced"] == [] and len(calls) == 2
    conn = connect(cfg.desk_db, readonly=True)
    row = conn.execute("SELECT close, value, quality FROM holdings_daily WHERE date='2026-10-09' AND symbol='OLDY'").fetchone()
    conn.close()
    assert row[:] == (21.0, 105.0, "pro_forma")
    assert "backfill" not in engine_main.run_daily(cfg) and len(calls) == 2
    monkeypatch.setenv(engine_main.DRY_RUN, "1")
    assert engine_main._fill_backcast(cfg, {"backcast": {"unpriced": ["NEWY"]}}) is None


def test_a_frozen_pack_is_redone_only_when_the_backcast_moves_it():
    data = SimpleNamespace(days=["2026-10-05", "2026-10-30"], value={"2026-10-23": 808.0, "2026-10-30": 830.0}, index={"2026-10-23": 1.0, "2026-10-30": 1.05})
    old = {"base": "2026-10-23", "as_of": "2026-10-30", "full": 1, "v0": 808.0, "v1": 830.0, "pct": 5.0}
    assert review._revised(old, data, "2026-10-28") is False
    assert review._revised(old | {"v0": 800.0}, data, "2026-10-28") is True
    assert review._revised(old | {"pct": 4.2}, data, "2026-10-28") is True
    assert review._revised(old | {"pct": 4.2}, data, "2026-10-22") is False and review._revised(old | {"pct": 4.2}, data, None) is False
    assert review._revised(old | {"full": 0}, data, None) is True and review._revised(old | {"full": 0, "base": "2026-10-05"}, data, None) is False
    assert review._revised(old | {"base": None}, data, "2026-10-28") is False
