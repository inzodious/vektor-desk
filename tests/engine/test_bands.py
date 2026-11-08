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
    made = catalog.mixes({"FXAIX": 0.8, "VXUS": 0.2}, w, cash)
    assert list(made) == ["safe-mix", "as-held", "tech-tilt", "dip-buy"]
    assert made["as-held"]["weights"] == {"IVV": 0.6, "ASTS": 0.4} and made["dip-buy"]["cash"] == 0.2


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
    first = catalog.mixes({"FXAIX": 0.8, "VXUS": 0.2}, {"FXAIX": 1.0}, 0.0)
    out = catalog.sync(conn, first, now=REG)
    assert sorted(out["registered"]) == ["as-held@1", "dip-buy@1", "safe-mix@1", "tech-tilt@1"] and "FTEC" in out["symbols"]
    assert {r[0] for r in conn.execute("SELECT symbol FROM market_symbols")} >= {"IVV", "VXUS", "FTEC", "SMH"}
    assert catalog.sync(conn, first, now=REG)["registered"] == []
    second = catalog.mixes({"FXAIX": 0.6, "VXUS": 0.4}, {"FXAIX": 0.5, "ASTS": 0.5}, 0.0)
    assert sorted(catalog.sync(conn, second, now=REG)["registered"]) == ["dip-buy@2", "safe-mix@2"]
    rows = {(r["id"], r["version"]): r["retired_at"] for r in conn.execute("SELECT * FROM catalog_strategies")}
    assert rows[("safe-mix", 1)] and rows[("safe-mix", 2)] is None and ("as-held", 2) not in rows
    assert catalog.latest(conn)["as-held"]["mix"]["weights"] == {"IVV": 0.5, "ASTS": 0.5}
    conn.close()


def test_rebuild_writes_targets_and_retires_old_versions(cfg):
    conn = desk(cfg)
    catalog.sync(conn, catalog.mixes({"FXAIX": 0.8, "VXUS": 0.2}, {}, 0.0), now=REG)
    catalog.sync(conn, catalog.mixes({"FXAIX": 0.5, "VXUS": 0.5}, {}, 0.0), now=REG)
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
    catalog.sync(conn, catalog.mixes({"FXAIX": 1.0}, {}, 0.0), now=REG)
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


def test_core_builds_bands_for_every_mix_and_serves_them(cfg, mirror, monkeypatch, app_client):
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
    conn.close()
    computed(cfg)
    body = client.get("/api/engine/bands").json()
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
    seam = bands.catalog(cfg)
    assert {tuple(r) for r in seam} == {bands.CATALOG_FIELDS} and len(seam) == 4
    conn = connect(cfg.desk_db)
    versions = {r[0] for r in conn.execute("SELECT id FROM catalog_strategies")}
    worst = conn.execute("SELECT count(*) FROM metric_values WHERE metric_id='bands.worst_year_p10'").fetchone()[0]
    conn.close()
    assert versions == set(rows) and worst == 4


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

    test_core_builds_bands_for_every_mix_and_serves_them(cfg, mirror, monkeypatch, app_client)
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
