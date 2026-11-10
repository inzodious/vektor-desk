import json
import random
from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.engine import bands, catalog, paper_exec, schema
from tests.engine.test_core import computed
from tests.engine.test_fi import PREFS
from tests.engine.test_lane import PRE, FakeAlpaca
from tests.engine.test_preflight import seed

REG = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


# ---- Catalog ----


def test_proxies_fold_mutual_funds_into_etfs():
    w, notes = catalog.proxied({"FXAIX": 0.6, "FTIHX": 0.2, "ABCDX": 0.1, "84679P": 0.1}, {"84679P": "unknown"})
    assert w == {"IVV": 0.8, "VXUS": 0.2}
    assert "FXAIX trades as IVV" in notes and "ABCDX has no ETF twin, so it trades as IVV" in notes and any(n.startswith("84679P") for n in notes)


def test_held_mix_keeps_asts_and_leaves_margin_out():
    rows = [
        {"symbol": "FXAIX", "value": 600.0, "is_cash": False},
        {"symbol": "ASTS", "value": 400.0, "is_cash": False},
        {"symbol": "CORE", "value": -200.0, "is_cash": True},
    ]
    w, cash, notes = catalog.held_mix(rows)
    assert w == {"FXAIX": 0.6, "ASTS": 0.4} and cash == 0.0 and "margin debit" in notes[0]
    w, cash, _ = catalog.held_mix(rows[:2] + [{"symbol": "SPAXX", "value": 250.0, "is_cash": True}])
    assert cash == pytest.approx(0.2)
    made = catalog.mixes(w, cash, safe={"FXAIX": 0.8, "VXUS": 0.2})
    assert list(made) == ["safe-mix", "as-held", "tech-tilt", "dip-buy"]
    assert made["as-held"]["weights"] == {"IVV": 0.6, "ASTS": 0.4} and made["dip-buy"]["cash"] == 0.2
    built_in = catalog.mixes({}, 0.0)
    assert list(built_in) == ["safe-mix", "tech-tilt", "dip-buy"] and built_in["dip-buy"]["weights"] == built_in["safe-mix"]["weights"]
    assert built_in["safe-mix"]["weights"] == {"IVV": 0.4, "SCHD": 0.2, "VXUS": 0.1, "FTEC": 0.1, "NLR": 0.05, "GRID": 0.05, "ICLN": 0.05, "UFO": 0.05}
    assert (
        built_in["safe-mix"]["notes"] == [catalog.SAFE_NOTE, "FTIHX trades as VXUS", "FXAIX trades as IVV"]
        and built_in["safe-mix"]["source"] == catalog.SAFE_MIX
    )


def test_dip_deploys_a_third_at_each_drop_and_refills_at_a_new_high():
    d = catalog.Dip()
    got = [round(d.step(x), 4) for x in (100, 96, 94, 89, 79, 85, 100, 101)]
    assert got == [0.2, 0.2, 0.1333, 0.0667, 0.0, 0.0, 0.2, 0.2]
    assert catalog.dip_cash([100, 90, 95]) == pytest.approx(0.2 / 3)


def desk(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


def bars(conn, symbol, closes, start=(2026, 10, 1)):
    from datetime import date, timedelta

    d = date(*start)
    rows = []
    for px in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append((symbol, d.isoformat(), px, px, px, px, px))
        d += timedelta(days=1)
    with conn:
        conn.executemany("INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def test_sync_versions_fixed_mixes_and_follows_the_book(cfg):
    conn = desk(cfg)
    first = catalog.mixes({"FXAIX": 1.0}, 0.0, safe={"FXAIX": 0.8, "VXUS": 0.2})
    out = catalog.sync(conn, first, now=REG)
    assert sorted(out["registered"]) == ["as-held@1", "dip-buy@1", "safe-mix@1", "tech-tilt@1"] and "FTEC" in out["symbols"]
    assert {r[0] for r in conn.execute("SELECT symbol FROM market_symbols")} >= {"IVV", "VXUS", "FTEC", "SMH"}
    assert catalog.sync(conn, first, now=REG)["registered"] == []
    second = catalog.mixes({"FXAIX": 0.5, "ASTS": 0.5}, 0.0, safe={"FXAIX": 0.6, "VXUS": 0.4})
    assert sorted(catalog.sync(conn, second, now=REG)["registered"]) == ["dip-buy@2", "safe-mix@2"]
    rows = {(r["id"], r["version"]): r["retired_at"] for r in conn.execute("SELECT * FROM catalog_strategies")}
    assert rows[("safe-mix", 1)] and rows[("safe-mix", 2)] is None and ("as-held", 2) not in rows
    assert catalog.latest(conn)["as-held"]["mix"]["weights"] == {"IVV": 0.5, "ASTS": 0.5}
    conn.close()


def test_a_mix_is_judged_at_its_checkpoint_not_every_night(cfg):
    conn = desk(cfg)
    tilt = {"weights": dict(catalog.TECH_TILT), "cash": 0.0, "notes": [], "source": dict(catalog.TECH_TILT)}
    catalog.sync(conn, {"tech-tilt": tilt, "safe-mix": tilt}, now=REG)
    closes = [100.0 + 0.05 * i + (0.4 if i % 2 else -0.4) for i in range(150)]
    bars(conn, "IVV", closes, start=(2026, 11, 5))
    days = [r[0] for r in conn.execute("SELECT date FROM price_bars WHERE symbol='IVV' ORDER BY date")]
    rows = []
    for i, (d, px) in enumerate(zip(days, closes, strict=True)):
        near = 1000.0 * px / closes[0] * (1 + (0.002 if i % 3 else -0.004)) - 0.03 * i
        far = 1000.0 * px / closes[0] * (1 + (0.002 if i % 3 else -0.004)) - 1.6 * i
        rows += [("tech-tilt", 1, d, 0.0, near, near), ("safe-mix", 1, d, 0.0, far, far)]
    with conn:
        conn.executemany("INSERT INTO paper_ledger_daily VALUES (?, ?, ?, ?, ?, ?)", [r for r in rows if r[2] > days[0]])
    prices = {"IVV": 100.0, "VXUS": 50.0, "FTEC": 200.0, "SMH": 250.0}
    out = {r["strategy_id"]: r for r in catalog.rebuild(conn, 1000.0, prices.get, now=datetime(2027, 6, 2, 13, 0, tzinfo=UTC))}
    near = dict(conn.execute("SELECT * FROM paper_portfolios WHERE strategy_id='tech-tilt'").fetchone())
    gate = json.loads(near["summary"])["gate"]
    assert near["days"] > 182 and near["excess_pts"] < 0
    assert out["tech-tilt"]["status"] == "paper" and out["tech-tilt"]["targets"] == 4
    assert gate["verdict"]["verdict"] == "unproven" and gate["verdict"]["reason"] == "noise" and gate["verdict"]["as_of"] == "2027-05-06"
    assert gate["min_events"] is None and gate["next_checkpoint"] == {"day": 273, "on": "2027-08-05"}
    assert out["safe-mix"]["status"] == "retired" and out["safe-mix"]["targets"] == 0
    with conn:
        conn.execute("UPDATE paper_ledger_daily SET value = value * 2 WHERE strategy_id='safe-mix' AND date=?", (days[-1],))
    again = {r["strategy_id"]: r for r in catalog.rebuild(conn, 1000.0, prices.get, now=datetime(2027, 6, 3, 13, 0, tzinfo=UTC))}
    assert again["safe-mix"]["status"] == "retired" and again["tech-tilt"]["status"] == "paper"
    assert conn.execute("SELECT count(*) FROM paper_verdicts").fetchone()[0] == 2
    conn.close()


def test_rebuild_writes_targets_and_retires_old_versions(cfg):
    conn = desk(cfg)
    catalog.sync(conn, catalog.mixes({}, 0.0, safe={"FXAIX": 0.8, "VXUS": 0.2}), now=REG)
    catalog.sync(conn, catalog.mixes({}, 0.0, safe={"FXAIX": 0.5, "VXUS": 0.5}), now=REG)
    for sym, px in (("IVV", 100.0), ("VXUS", 50.0), ("FTEC", 200.0), ("SMH", 250.0)):
        bars(conn, sym, [px * 0.9, px])
    prices = {"IVV": 100.0, "VXUS": 50.0, "FTEC": 200.0, "SMH": 250.0}
    out = {(r["strategy_id"], r["version"]): r for r in catalog.rebuild(conn, 1000.0, prices.get, now=PRE)}
    assert out[("safe-mix", 1)]["status"] == "retired" and out[("safe-mix", 1)]["targets"] == 0
    pos = {r["symbol"]: r["value"] for r in conn.execute("SELECT * FROM paper_positions WHERE strategy_id='safe-mix' AND version=2")}
    assert pos == {"IVV": 500.0, "VXUS": 500.0}
    dip = {r["symbol"]: r["value"] for r in conn.execute("SELECT * FROM paper_positions WHERE strategy_id='dip-buy' AND version=2")}
    assert sum(dip.values()) == pytest.approx(800.0)
    row = dict(conn.execute("SELECT * FROM paper_portfolios WHERE strategy_id='tech-tilt'").fetchone())
    summary = json.loads(row["summary"])
    assert row["started"] == "2026-11-05" and row["status"] == "paper" and summary["kind"] == "mix" and summary["benchmark"] == "IVV"
    conn.close()


def test_the_executor_buys_each_mix_into_its_own_sleeve(cfg, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "paper-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "paper-secret")
    for k in ("ALPACA_BASE_URL", "DESK_PAPER_EXECUTE", "DESK_PAPER_BUDGET", "DESK_PAPER_MAX_STRATEGIES"):
        monkeypatch.delenv(k, raising=False)
    conn = desk(cfg)
    catalog.sync(conn, catalog.mixes({}, 0.0, safe={"FXAIX": 1.0}), now=REG)
    for sym, px in (("IVV", 100.0), ("VXUS", 50.0), ("FTEC", 200.0), ("SMH", 250.0)):
        bars(conn, sym, [px])
    broker = FakeAlpaca()
    result = paper_exec.run(conn, broker, now=PRE)
    assert result["ok"] and {r["strategy_id"] for r in result["catalog"]} == {"safe-mix", "tech-tilt", "dip-buy"}
    legs = {(r["strategy_id"], r["symbol"]): r["qty"] for r in conn.execute("SELECT * FROM paper_legs")}
    assert legs[("safe-mix", "IVV")] == 9 and legs[("dip-buy", "IVV")] == 7 and legs[("tech-tilt", "FTEC")] == 1
    assert {o["symbol"] for o in broker.sent} == {"IVV", "FTEC", "VXUS"} and ("tech-tilt", "SMH") not in legs
    assert {b.kind for b in paper_exec.books(conn, 1000.0).values()} == {"mix"}
    conn.close()


# ---- Bands ----


def test_constant_history_gives_closed_form_bands():
    hist = [(f"19{50 + i // 12}-{i % 12 + 1:02d}-01", 0.01, 0.0) for i in range(240)]
    mix = {"weights": {"IVV": 1.0}, "cash": 0.0}
    sim = bands.simulate(
        hist, {"beta": 1.0, "resid": []}, mix, start=1000.0, deposit=0.0, goal=None, goal_month=None, fee_pct=0.0, inflation=0.0, real=False, paths=20
    )
    one = sim["bands"][0]
    assert one["p10"] == one["p90"] == pytest.approx(1000 * 1.01**12, abs=0.01) and one["chance_loss"] == 0.0
    assert sim["worst_year_p10_pct"] == pytest.approx((1.01**12 - 1) * 100, abs=1e-3) and sim["drawdown_10y"]["p50"] == 0.0 and sim["chance_fi"] is None
    half = bands.simulate(
        hist,
        {"beta": 1.0, "resid": []},
        mix | {"cash": 0.5},
        start=1000.0,
        deposit=0.0,
        goal=1000.0,
        goal_month=1,
        fee_pct=0.0,
        inflation=0.0,
        real=False,
        paths=5,
    )
    assert half["bands"][0]["p50"] == pytest.approx(1000 * 1.005**12, abs=0.01) and half["chance_fi"] == 1.0


def flat(months=240, mr=0.01, rf=0.0):
    return [(f"19{50 + i // 12}-{i % 12 + 1:02d}-01", mr, rf) for i in range(months)]


COMMON = {"goal": None, "goal_month": None, "inflation": 0.0, "real": False, "paths": 5}


def test_a_hold_drifts_while_rebalance_and_trim_pull_it_back():
    pair = [bands.sleeve("FAST", {"beta": 2.0}, start=0.5), bands.sleeve("CASH", {"beta": 0.0}, start=0.5, deposit=1.0)]
    run = {"start": 1000.0, "deposit": 0.0, "watch": (0,), "horizons": (1, 5)} | COMMON
    hold = bands.walk(flat(), pair, **run)["bands"][0]
    assert hold["p50"] == pytest.approx(500 * 1.02**12 + 500, abs=0.01)
    assert hold["weights"]["FAST"]["p50"] == pytest.approx(500 * 1.02**12 / (500 * 1.02**12 + 500) * 100, abs=0.01)
    again = bands.walk(flat(), pair, policy="rebalance", **run)["bands"][0]
    assert again["p50"] == pytest.approx(1000 * 1.01**12, abs=0.01) and again["weights"]["FAST"]["p50"] == 50.0
    trim = bands.walk(flat(), pair, policy="trim", cap=0.5, **run)["bands"][0]
    assert trim["p50"] == again["p50"] and trim["weights"]["FAST"]["p50"] == 50.0
    loose = bands.walk(flat(), pair, policy="trim", cap=0.9, **run)["bands"][0]
    assert loose["p50"] == hold["p50"]


def test_new_money_goes_to_its_own_sleeve_and_shrinks_the_hold():
    pair = [bands.sleeve("FAST", {"beta": 2.0}, start=1.0), bands.sleeve("new-money", {"beta": 0.0}, deposit=1.0)]
    one = bands.walk(flat(), pair, start=1000.0, deposit=100.0, watch=(0,), horizons=(1,), **COMMON)["bands"][0]
    assert one["p50"] == pytest.approx(1000 * 1.02**12 + 1200, abs=0.01) and one["contributed"] == 2200.0
    assert one["weights"]["FAST"]["p50"] == pytest.approx(1000 * 1.02**12 / (1000 * 1.02**12 + 1200) * 100, abs=0.01)


def test_time_to_fi_falls_as_the_deposit_rises():
    def months(deposit, goal=3000.0, rate=0.01):
        v, m = 1000.0, 0
        while v < goal:
            v, m = v * (1 + rate) + deposit, m + 1
        return m

    mix = {"weights": {"IVV": 1.0}, "cash": 0.0}
    run = {"start": 1000.0, "deposit": 50.0, "goal": 3000.0, "goal_month": 24, "fee_pct": 0.0, "inflation": 0.0, "real": False, "paths": 5}
    sim = bands.simulate(flat(600), {"beta": 1.0, "resid": []}, mix, ladder=(0.0, 50.0, 200.0, 25.0), **run)
    got = {x["deposit"]: x for x in sim["fi_time"]}
    assert list(got) == [0.0, 25.0, 50.0, 200.0]
    assert [got[d]["years_p50"] for d in got] == [round(months(d) / 12, 2) for d in got]
    assert got[50.0]["years_p50"] == sim["fi_years"]["p50"] == got[50.0]["years_p10"] == got[50.0]["years_p90"]
    assert [got[d]["chance_by_target"] for d in got] == [0.0, 0.0, 0.0, 1.0] and sim["chance_fi"] == 0.0
    far = bands.simulate(flat(600), {"beta": 1.0, "resid": []}, mix, ladder=(50.0,), **(run | {"goal": 1e12}))
    assert far["fi_time"][0]["years_p50"] is None and far["fi_years"]["p50"] is None


def test_the_lower_return_case_takes_points_off_the_stock_premium():
    mix = {"weights": {"IVV": 1.0}, "cash": 0.0}
    run = {"start": 1000.0, "deposit": 0.0, "goal": None, "goal_month": None, "fee_pct": 0.0, "inflation": 0.0, "real": False, "paths": 5}
    low = bands.simulate(flat(), {"beta": 1.0, "resid": []}, mix, premium_cut_pts=12.0, **run)
    assert low["bands"][0]["p50"] == pytest.approx(1000.0, abs=0.01)
    half = bands.simulate(flat(), {"beta": 0.5, "resid": []}, mix, premium_cut_pts=12.0, **run)
    assert half["bands"][0]["p50"] == pytest.approx(1000.0, abs=0.01)
    fee = bands.simulate(flat(), {"beta": 1.0, "resid": []}, mix, **(run | {"fee_pct": 12.0}))
    assert fee["bands"][0]["p50"] == pytest.approx(1000.0, abs=0.01)


def test_every_mix_pays_its_funds_fees():
    assert catalog.expense_pct("FXAIX", {"FXAIX": 0.02}) == 0.02 and catalog.expense_pct("FXAIX") == 0.015
    assert catalog.expense_pct("SWISX") == catalog.EXPENSE_PCT["SCHF"] and catalog.expense_pct("ACME") == 0.0
    assert catalog.mix_fee(catalog.TECH_TILT) == pytest.approx(0.5 * 0.03 + 0.3 * 0.08 + 0.1 * 0.35 + 0.1 * 0.05)
    assert catalog.mix_fee({"ACME": 0.5, "SMH": 0.5}) == pytest.approx(0.175) and catalog.mix_fee({}) == 0.0


def test_fit_recovers_beta_and_stats_read_the_record():
    rng = random.Random(4)
    hist = []
    for i in range(120):
        m = rng.gauss(0.008, 0.045)
        hist.append((f"20{10 + i // 12}-{i % 12 + 1:02d}", 0.001 + 1.3 * (m - 0.001) + rng.gauss(0, 0.01), m, 0.001))
    model = bands.fit(hist)
    assert model["beta"] == pytest.approx(1.3, abs=0.08) and len(model["resid"]) == 120
    bt = bands.backtest(hist, {"weights": {"X": 1.0}, "cash": 0.0})
    assert bt["months"] == 120 and bt["max_drawdown_pct"] < 0 and bt["sharpe"] is not None and 0 < bt["hit_rate"] < 1 and bt["start"] == "2010-01"
    assert bands.fit(hist[:20]) is None


def test_fit_badge_follows_the_risk_profile(monkeypatch):
    ladder = list(bands.LADDER)
    assert bands.rank(-8.0, ladder) == 1 and bands.rank(-30.0, ladder) == 4 and bands.rank(-80.0, ladder) == 5
    assert bands.fit_to(-30.0, None, ladder) is None
    from desk.decisions import risk as profile_risk

    monkeypatch.setattr(profile_risk, "current", lambda cfg: {"band": 3, "label": "Moderate", "worst_year_loss_pct": -25, "version": 1})
    lad, prof, source = bands.ladder_and_profile(object())
    assert source == "profile" and lad[0] == {"band": 1, "label": "Conservative", "worst_year_loss_pct": 10.0} and prof["band"] == 3
    assert [bands.fit_to(x, prof, lad) for x in (-30.0, -20.0, -8.0)] == ["above", "fits", "below"]


def market_months(conn, seed_=7):
    rng = random.Random(seed_)
    rows, mkt = [], []
    for i in range(1200):
        y, m = 1926 + i // 12, i % 12 + 1
        r = rng.gauss(0.0085, 0.045)
        rows += [("mkt_rf_m", f"{y}-{m:02d}-01", (r - 0.003) * 100), ("rf_m", f"{y}-{m:02d}-01", 0.3)]
        mkt.append((f"{y}-{m:02d}", r))
    with conn:
        conn.executemany("INSERT OR REPLACE INTO factors_daily VALUES (?, ?, ?)", rows)
    return mkt


def priced(conn, mkt, symbol, beta, noise, since="2008-01", seed_=1):
    rng = random.Random(seed_)
    px, rows = 100.0, []
    for month, r in mkt:
        if month < since:
            continue
        px *= 1 + 0.003 + beta * (r - 0.003) + rng.gauss(0, noise)
        rows.append((symbol, f"{month}-27", px, px, px, px, px))
    with conn:
        conn.executemany("INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def test_as_held_is_split_into_its_single_stocks_and_the_rest():
    mkt = {f"20{10 + i // 12}-{i % 12 + 1:02d}": (0.01, 0.002) for i in range(60)}
    rets = {s: {m: 0.01 for m in mkt} for s in ("IVV", "ACME", "NVDA")} | {"NEWCO": {m: 0.01 for m in sorted(mkt)[-12:]}}
    mix = {"weights": {"IVV": 0.6, "ACME": 0.3, "NVDA": 0.01, "NEWCO": 0.09}, "cash": 0.1, "source": {"FXAIX": 0.6, "ACME": 0.3, "NVDA": 0.01, "NEWCO": 0.09}}
    kinds = {"ACME": "stock", "NVDA": "stock", "NEWCO": "stock", "IVV": "fund"}
    safe = {"model": {"beta": 0.9}, "fee_pct": 0.04, "to": "safe-mix"}
    sleeves, notes = bands.held_sleeves(mix, rets, mkt, kinds, set(), {"FXAIX": 0.02}, safe)
    rows = {r["id"]: r for r in bands.sleeve_rows(sleeves)}
    assert list(rows) == ["ACME", "rest", "cash", "new-money"] and rows["rest"]["holds"] == ["IVV", "NEWCO", "NVDA"]
    assert rows["ACME"]["weight"] == pytest.approx(0.27) and rows["rest"]["weight"] == pytest.approx(0.63) and rows["cash"]["weight"] == 0.1
    assert rows["rest"]["fee_pct"] == pytest.approx(0.6 * 0.02 / 0.7, abs=1e-4) and rows["ACME"]["fee_pct"] == 0.0
    assert rows["new-money"] == {"id": "new-money", "weight": 0.0, "beta": 0.9, "resid_vol_pct": 0.0, "fee_pct": 0.04, "months": None, "to": "safe-mix"}
    assert notes == ["NEWCO: under 36 months of prices, so modelled with the funds"]
    pinned, _ = bands.held_sleeves(mix, rets, mkt, {}, {"NVDA"}, {}, None)
    assert [s["id"] for s in pinned] == ["rest", "cash", "new-money"] and pinned[-1]["to"] == "rest"
    assert bands.held_sleeves(mix | {"weights": {"NEWCO": 1.0}}, rets, mkt, kinds, set(), {}, None) is None


def bands_body(cfg, mirror, monkeypatch, app_client):
    monkeypatch.setenv("DESK_BANDS_PATHS", "150")
    monkeypatch.setenv("DESK_MC_PATHS", "100")
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/bands").json()["status"] == "not_ready"
    with pytest.raises(bands.NotReady):
        bands.catalog(cfg)
    seed(mirror)
    mirror.put("prefs", "fi", PREFS)
    mirror.pull("2026-11-04T21:30:00+00:00")
    conn = desk(cfg)
    mkt = market_months(conn)
    for sym, beta, noise, i in (("IVV", 1.0, 0.002, 1), ("VXUS", 0.9, 0.02, 2), ("FTEC", 1.3, 0.03, 3), ("SMH", 1.6, 0.05, 4), ("ACME", 1.5, 0.12, 5)):
        priced(conn, mkt, sym, beta, noise, seed_=i)
    for i, sym in enumerate(("SCHD", "NLR", "GRID", "ICLN", "UFO"), start=6):
        priced(conn, mkt, sym, 0.9, 0.01, seed_=i)
    conn.close()
    computed(cfg)
    return client.get("/api/engine/bands").json()


def test_core_builds_bands_for_every_mix_and_serves_them(cfg, mirror, monkeypatch, app_client):
    body = bands_body(cfg, mirror, monkeypatch, app_client)
    assert (
        body["status"] == "ok"
        and body["book"] == "as-held"
        and body["horizons"] == [1, 5, 10, 20, 40]
        and body["ladder_source"] == "profile"
        and body["ladder"][0]["worst_year_loss_pct"] == 10
    )
    rows = {r["id"]: r for r in body["rows"]}
    assert set(rows) == {"safe-mix", "as-held", "tech-tilt", "dip-buy"} and all(r["status"] == "ok" for r in rows.values())
    safe, tech, held = rows["safe-mix"], rows["tech-tilt"], rows["as-held"]
    assert safe["model"]["beta"] == pytest.approx(0.98, abs=0.05) and tech["model"]["beta"] > safe["model"]["beta"]
    assert tech["worst_year_p10_pct"] < safe["worst_year_p10_pct"] and tech["risk_rank"] >= safe["risk_rank"]
    assert all(b["p10"] <= b["p50"] <= b["p90"] for b in safe["bands"]) and [b["years"] for b in safe["bands"]] == [1, 5, 10, 20, 40]
    assert "FXAIX trades as IVV" in held["proxy_note"] and held["priced_from"]["IVV"] == "IVV" and "ACME" in held["weights"]
    assert rows["dip-buy"]["cash"] == 0.2 and safe["chance_fi"] is not None and safe["fit"] is None
    assert safe["backtest"]["start"] == "2008-02" and safe["long_history"]["start"] == "1926-01"
    assert body["premium_cut_pts"] == 2.0 and body["fi_years_max"] == 40 and body["policy_years"] == [1, 5, 10, 20] and body["convictions"] == []
    assert body["monthly_deposit"] is None and body["deposit_ladder"] == [0.0, *bands.DEPOSIT_LADDER]
    assert all(r["fee_pct"] > 0 and r["lower"]["p50_value_10y"] < r["p50_value_10y"] for r in rows.values())
    assert tech["fee_pct"] == pytest.approx(catalog.mix_fee(catalog.TECH_TILT), abs=1e-4) and safe["policy"] == "rebalance"
    for r in rows.values():
        assert [x["deposit"] for x in r["fi_time"]] == body["deposit_ladder"] == [x["deposit"] for x in r["lower"]["fi_time"]]
        reached = [x["years_p50"] for x in r["fi_time"] if x["years_p50"] is not None]
        assert reached == sorted(reached, reverse=True) and r["fi_time"][-1]["years_p50"] is not None
        now = r["fi_time"][0]
        assert now["years_p50"] == r["fi_years"]["p50"] and now["chance_by_target"] == r["chance_fi"]
    assert held["policy"] == "hold" and held["new_money"] == "safe-mix" and [s["id"] for s in held["sleeves"]] == ["ACME", "rest", "cash", "new-money"]
    kept, topped = held, held["variants"][0]
    assert topped["id"] == "rebalanced" and [b["years"] for b in topped["bands"]] == [1, 5, 10, 20, 40]
    assert topped["bands"] != kept["bands"] and "variants" not in safe and "weights" not in kept["bands"][0] and "weights" not in topped["bands"][0]
    seam = bands.catalog(cfg)
    assert {tuple(r) for r in seam} == {bands.CATALOG_FIELDS} and len(seam) == 4
    conn = connect(cfg.desk_db)
    versions = {r[0] for r in conn.execute("SELECT id FROM catalog_strategies")}
    worst = conn.execute("SELECT count(*) FROM metric_values WHERE metric_id='bands.worst_year_p10'").fetchone()[0]
    conn.close()
    assert versions == set(rows) and worst == 4


def test_a_conviction_hold_gets_hold_rebalance_and_trim_side_by_side(cfg, mirror, monkeypatch, app_client):
    from desk.engine import core

    plain = core.rules_in_force

    def with_conviction(cfg, plan):
        rules, source = plain(cfg, plan)
        return [*rules, {"id": "acme", "kind": "conviction_hold", "symbols": ["ACME"], "params": {"band_min_pct": 2, "band_max_pct": 5}}], source

    monkeypatch.setattr(core, "rules_in_force", with_conviction)
    body = bands_body(cfg, mirror, monkeypatch, app_client)
    (acme,) = body["convictions"]
    held = next(r for r in body["rows"] if r["id"] == "as-held")
    assert acme["symbol"] == "ACME" and acme["status"] == "ok" and acme["band_max_pct"] == 5 and acme["weight_pct"] > 5
    assert acme["weight_pct"] == pytest.approx(held["sleeves"][0]["weight"] * 100, abs=0.01)
    hold, again, trim = acme["policies"]
    assert [p["id"] for p in acme["policies"]] == ["hold", "rebalance", "trim"] and all(p["rule"] for p in acme["policies"])
    assert all([b["years"] for b in p["bands"]] == [1, 5, 10, 20] for p in acme["policies"])
    assert hold["bands"] == [b | {"weight_pct": hold["bands"][i]["weight_pct"]} for i, b in enumerate(held["bands"][:4])]
    assert all(b["weight_pct"]["p50"] == acme["weight_pct"] for b in again["bands"])
    assert all(b["weight_pct"]["p90"] <= 5.0 for b in trim["bands"]) and hold["bands"][0]["weight_pct"]["p90"] > 5.0
    assert trim["worst_year_p10_pct"] > max(hold["worst_year_p10_pct"], again["worst_year_p10_pct"])
    assert trim["max_drawdown_pct"] > max(hold["max_drawdown_pct"], again["max_drawdown_pct"])


def test_paper_as_held_buys_once_and_then_holds(cfg, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "paper-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "paper-secret")
    for k in ("ALPACA_BASE_URL", "DESK_PAPER_EXECUTE", "DESK_PAPER_BUDGET", "DESK_PAPER_MAX_STRATEGIES"):
        monkeypatch.delenv(k, raising=False)
    conn = desk(cfg)
    catalog.sync(conn, catalog.mixes({"FXAIX": 0.5, "ACME": 0.5}, 0.0, {"ACME": "stock"}), now=REG)
    assert catalog.latest(conn)["as-held"]["mix"]["policy"] == "hold" and catalog.is_hold(conn, "as-held", 1) and not catalog.is_hold(conn, "tech-tilt", 1)
    for sym, px in (("IVV", 100.0), ("ACME", 20.0), ("VXUS", 50.0), ("FTEC", 200.0), ("SMH", 250.0)):
        bars(conn, sym, [px])
    broker = FakeAlpaca()
    paper_exec.run(conn, broker, now=PRE)
    first = {r["symbol"]: r["filled_qty"] for r in conn.execute("SELECT * FROM paper_legs WHERE strategy_id='as-held'")}
    assert first == {"IVV": 4.0, "ACME": 24.0} and catalog.held_shares(conn, "as-held", 1) == first
    catalog.sync(conn, catalog.mixes({"FXAIX": 0.9, "ACME": 0.1}, 0.0, {"ACME": "stock"}), now=REG)
    assert catalog.latest(conn)["as-held"]["version"] == 1 and catalog.latest(conn)["as-held"]["mix"]["weights"] == {"IVV": 0.9, "ACME": 0.1}
    bars(conn, "ACME", [20.0, 20.0, 20.0, 20.0, 40.0], start=(2026, 11, 2))
    later = PRE.replace(day=9)
    paper_exec.run(conn, broker, now=later)
    legs = {(r["date"], r["symbol"]) for r in conn.execute("SELECT * FROM paper_legs WHERE strategy_id='as-held'")}
    assert {d for d, _ in legs} == {"2026-11-06"}
    pos = {r["symbol"]: (r["shares"], r["value"]) for r in conn.execute("SELECT * FROM paper_positions WHERE strategy_id='as-held'")}
    assert pos == {"IVV": (4.0, 400.0), "ACME": (24.0, 960.0)}
    assert paper_exec.strategy_wants(conn, paper_exec.books(conn, 1000.0)[("as-held", 1)], lambda s: 100.0, None) == first
    conn.close()


# ---- Reward to risk on the leaderboard ----


def test_ratios_need_twenty_days_and_read_the_ledger():
    from datetime import date, timedelta

    from desk.engine import leaderboard

    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(120)]
    vals = [1000.0 * (1.001**i) * (0.99 if i % 10 == 5 else 1.0) for i in range(120)]
    got = leaderboard.ratios(days, vals)
    assert got["days"] == 120 and got["sharpe"] > 0 and got["sortino"] > got["sharpe"] and got["max_drawdown_pct"] == pytest.approx(-0.901, abs=0.001)
    assert got["calmar"] > 0 and 0.8 < got["hit_rate"] < 1 and got["ann_return_pct"] > 0
    assert leaderboard.ratios(days[:20], vals[:20]) is None
    flat = leaderboard.ratios(days[:30], vals[:30])
    assert flat["ann_return_pct"] is None and flat["calmar"] is None


def test_leaderboard_carries_reward_to_risk_and_backtests(cfg, mirror, monkeypatch, app_client):
    from desk.engine import leaderboard

    bands_body(cfg, mirror, monkeypatch, app_client)
    conn = connect(cfg.desk_db)
    for sym in ("IVV", "VXUS", "FTEC", "SMH"):
        bars(conn, sym, [100.0])
    catalog.rebuild(conn, 1000.0, lambda s: 100.0, now=PRE)
    with conn:
        conn.executemany(
            "INSERT INTO paper_ledger_daily VALUES ('safe-mix', 1, ?, 0, ?, ?)",
            [(f"2026-12-{d:02d}", 1000 + d * 2 - (5 if d % 4 == 0 else 0), 1000 + d * 2 - (5 if d % 4 == 0 else 0)) for d in range(1, 31)],
        )
    conn.close()
    body = app_client(packages=["engine"]).get("/api/engine/lab/leaderboard").json()
    rows = {r["id"]: r for r in body["rows"]}
    safe, tech = rows["safe-mix"], rows["tech-tilt"]
    assert safe["kind"] == "mix" and safe["benchmark"] == "IVV"
    assert safe["reward_risk"]["source"] == "sub_ledger" and safe["reward_risk"]["days"] == 30 and safe["reward_risk"]["sharpe"] is not None
    assert tech["reward_risk"]["source"] == "forward_record" and tech["reward_risk"]["max_drawdown_pct"] == 0.0
    assert safe["backtest"]["source"] == "bands" and safe["backtest"]["start"] == "2008-02" and set(leaderboard.RATIO_KEYS) <= set(safe["backtest"])
