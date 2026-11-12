import gzip
import json
import os
import random
import sqlite3
from array import array
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from desk import scheduler
from desk.agents.sources import RealLab
from desk.db import connect
from desk.engine import gate, kinds, lab, schema
from desk.engine.__main__ import run_holdings, run_lab_export
from desk.engine.lab import __main__ as lab_main
from desk.engine.lab import library as features
from desk.engine.lab import paper, runner, simcache, stats
from desk.engine.lab.data import EXPORT_SCHEMA, Series, data_path, export, ledger_path, load
from desk.engine.lab.runner import ledger, process_queue
from desk.engine.lab.sim import _year_tax, simulate
from desk.engine.lab.spec import SETS, SpecError, parse, resolve, variants
from desk.worker import registry, store
from desk.worker.__main__ import apply as worker_apply
from tests.engine.test_preflight import seed

NOW = datetime(2025, 1, 2, 7, 0, tzinfo=UTC)
SECTORS = SETS["sector_etfs"]
SPEC = {
    "id": "sector-momentum",
    "version": 1,
    "parent_id": None,
    "title": "Sector momentum",
    "hypothesis": "Sectors that led over six months keep leading for a month.",
    "predicted_effect": "+1 point a year",
    "universe": {"type": "fund_list", "rule": "US sector ETFs listed before each start date"},
    "signals": [{"metric_id": "ret", "window": "{lookback}d", "transform": "rank"}],
    "entry": "top {top_n} by rank",
    "exit": "falls out of top 5",
    "rebalance": "monthly",
    "sizing": "equal",
    "params": {"top_n": {"min": 1, "max": 4, "default": 3}, "lookback": {"min": 21, "max": 252, "default": 126}},
    "constraints": {"long_only": True, "margin": False, "max_position_pct": 100, "max_turnover": 30},
    "success_criteria": {"excess_vs_plan_pts": 0.0, "max_drawdown_pct": 60},
    "horizons": [3, 5],
}


def weekdays(start: str, end: str) -> list[str]:
    out, d, e = [], date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def market(end="2024-12-31", seed_=11, trend=0.0009):
    rng = random.Random(seed_)
    days = weekdays("2012-01-02", end)
    paths = {}
    for k, sym in enumerate(("SPY", *SECTORS)):
        px, rows, drift = 100.0, [], 0.0
        for i, d in enumerate(days):
            if i % 126 == 0:
                drift = rng.choice((-trend, 0.0, trend)) if sym != "SPY" else 0.0003
            r = drift + rng.gauss(0, 0.01)
            op = px * (1 + rng.gauss(0, 0.002))
            px *= 1 + r
            rows.append((sym, d, op, px, px, 1e6))
        paths[sym] = rows
        if k == 0:
            continue
    return days, paths


def write_lab_db(cfg, end="2024-12-31", drop=()):
    days, paths = market(end)
    path = data_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    for sym, rows in paths.items():
        rows = rows[: len(rows) - 400] if sym in drop else rows
        conn.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT INTO symbols VALUES (?, 'fund', 'benchmark', ?, ?)", (sym, rows[0][1], rows[-1][1]))
    conn.executemany("INSERT INTO macro VALUES ('DGS3MO', ?, 2.0)", [(d,) for d in days[::5]])
    conn.execute("INSERT INTO plan_mix VALUES ('SPY', 1.0)")
    conn.execute("INSERT INTO settings VALUES ('marginal_rate_pct', '24')")
    conn.commit()
    conn.close()
    return days


def queue(cfg, body, name):
    folder = cfg.data_dir / "lab" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(body))


def experiment(spec=SPEC, grid=None, **over):
    return {
        "request": "experiment",
        "spec": spec,
        "grid": grid if grid is not None else {"top_n": [1, 3], "lookback": [63, 126]},
        "date_range": {"start": "2012-01-02", "end": "2024-12-31"},
        "seed": 7,
        "trial_budget": 50,
        "analyses": ["param_sensitivity", "regime_split", "turnover_cost", "factor_regression"],
        "model": "opus",
        "written_at": "2026-11-07T12:00:00+00:00",
    } | over


# ---- Features ----


def test_features_by_hand():
    adj = [100.0, 110.0, 99.0, 121.0, 120.0, 132.0]
    s = Series([f"d{i}" for i in range(6)], adj, adj, [None] * 6)
    assert features.value("ret", s, 5, 5) == pytest.approx(0.32)
    assert features.value("ret", s, 4, 5) is None
    assert features.value("dd", s, 4, 3) == pytest.approx(120 / 121 - 1)
    assert features.value("range_52w", s, 5, 5) == pytest.approx(1.0)
    assert features.value("ma_gap", s, 5, 2) == pytest.approx(132 / 126 - 1)
    assert features.value("vol", s, 5, 5) > 0
    assert features.window_days("6m") == 126 and features.window_days("1y") == 252
    with pytest.raises(ValueError):
        features.window_days("tomorrow")
    assert features.transform("rank", {"a": 3.0, "b": 1.0}) == {"b": 0.5, "a": 1.0}
    assert features.transform("inverse_rank", {"a": 3.0, "b": 1.0}) == {"a": 0.5, "b": 1.0}
    assert {f["metric_id"] for f in lab.features(None)} >= {"ret", "vol", "ret_skip"}


# ---- Specs ----


def test_desk_style_spec_parses_and_resolves(cfg):
    write_lab_db(cfg)
    data = load(data_path(cfg))
    spec = parse(SPEC, data, model="opus")
    assert spec.universe["symbols"] == list(SECTORS) and spec.rebalance == "M" and spec.taxable
    v = resolve(spec, {"top_n": 2, "lookback": 63})
    assert (v.top_n, v.hold_rank, v.windows) == (2, 5, [63])
    picks = variants(spec, {"top_n": [1, 2, 3, 4], "lookback": [21, 63, 126]}, 5, seed=3)
    assert len(picks) == 5 and picks == variants(spec, {"top_n": [1, 2, 3, 4], "lookback": [21, 63, 126]}, 5, seed=3)
    with pytest.raises(SpecError):
        variants(spec, {"top_n": [9]}, 10, 1)


def test_bad_specs_are_rejected_with_reasons(cfg):
    write_lab_db(cfg)
    data = load(data_path(cfg))
    bad = SPEC | {
        "universe": {"type": "fund_list", "symbols": ["NVDA", "XLK"]},
        "signals": [{"metric_id": "astrology", "window": "63d", "transform": "rank"}],
        "constraints": SPEC["constraints"] | {"margin": True},
    }
    with pytest.raises(SpecError) as e:
        parse(bad, data)
    text = " ".join(e.value.problems)
    assert "NVDA" in text and "astrology" in text and "margin" in text


# ---- Simulator ----


def test_simulator_trades_next_open_with_costs_taxes_and_delisting(cfg):
    write_lab_db(cfg, drop=("XLE",))
    data = load(data_path(cfg))
    spec = parse(SPEC | {"exit": "rebalance"}, data)
    res = simulate(data, spec, resolve(spec, {"top_n": 3, "lookback": 63}), "2014-01-02", "2018-12-31")
    first = res.trades[0]
    signal_day = max(d for d in data.calendar if d < first[0])
    assert signal_day[:7] != first[0][:7] and first[5] == pytest.approx(first[3] * first[4] * 5 / 10_000, abs=1e-4)
    assert res.costs > 0 and res.taxes > 0 and res.rebalances > 40
    late = simulate(data, spec, resolve(spec, {"top_n": 11, "lookback": 21}), "2022-06-01", "2024-12-31")
    assert "XLE" in late.delisted
    assert _year_tax({"st": 1000.0, "lt": -400.0}, 0.0, 0.24) == (pytest.approx(144.0), 0.0)
    assert _year_tax({"st": -500.0, "lt": 0.0}, -100.0, 0.24) == (0.0, -600.0)


# ---- Statistics ----


def test_deflated_sharpe_and_pbo():
    assert stats.deflated_sharpe(0.1, 2, 0.001, 1000, 0, 3) > stats.deflated_sharpe(0.1, 200, 0.001, 1000, 0, 3)
    rng = random.Random(5)
    noise = [[rng.gauss(0, 0.01) for _ in range(500)] for _ in range(12)]
    assert 0.2 < stats.pbo(noise) < 0.9
    strong = [[0.002 + x for x in noise[0]]] + noise[1:]
    assert stats.pbo(strong) < 0.1
    assert stats.pbo(noise[:1]) is None


# ---- The loop ----


def test_experiment_finalize_paper_and_views(cfg, app_client):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-sector-momentum-v1-experiment.json")
    queue(cfg, experiment(spec=SPEC | {"universe": {"type": "fund_list", "symbols": ["NVDA"]}, "id": "pick-nvda"}), "002-pick-nvda-v1-experiment.json")
    done = process_queue(cfg, now=NOW)["done"]
    assert [d["status"] for d in done] == ["experiment", "rejected"]
    assert process_queue(cfg, now=NOW)["done"] == []
    view = lab.desk_view(cfg, "sector-momentum")
    assert view["status"] == "lab" and len(view["folds"]) >= 5 and "final" not in view
    sheet = view["tear_sheet"]
    assert sheet["variants"] == 4 and sheet["trials_family"] == 4 and sheet["windows"]["holdout_start"] == "2022-12-31"
    assert 0 <= sheet["pbo"] <= 1 and sheet["deflated_sharpe"] is not None
    assert {h["years"] for h in sheet["horizons"]} == {3, 5}
    assert set(view["analyses"]) == {"param_sensitivity", "regime_split", "turnover_cost", "factor_regression"}
    assert all("holdout" not in json.dumps(f) for f in view["folds"])
    assert lab.desk_view(cfg, "pick-nvda")["rejected"]
    reviews = lab.pending_reviews(cfg, now=NOW)
    assert {(r["strategy_id"], r["kind"]) for r in reviews} == {("sector-momentum", "experiment"), ("pick-nvda", "rejected")}
    assert RealLab().features(cfg) and RealLab().desk_view(cfg, "sector-momentum")["version"] == 1

    changed = SPEC | {"title": "Sector momentum, edited"}
    queue(cfg, experiment(spec=changed), "003-sector-momentum-v1-experiment.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "004-sector-momentum-v1-finalize.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "005-sector-momentum-v1-finalize.json")
    done = process_queue(cfg, now=NOW)["done"]
    assert [d["status"] for d in done] == ["rejected", "finalize", "rejected"]
    final = lab.desk_view(cfg, "sector-momentum")["final"]
    assert final["verdict"] in ("pass", "fail", "inconclusive") and final["holdout"]["start"] >= "2022-12-30"
    assert final["post_cutoff"]["cutoff"] == "2026-06-30" and final["post_cutoff"]["days"] == 0
    assert final["bars"]["factor"] is None and set(final["bars"]) >= {"excess_interval", "deflated_sharpe", "pbo", "holdout"}
    conn = ledger(cfg)
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM strategy_trials")}
    conn.close()
    assert kinds == {"train", "test", "full", "holdout"}

    client = app_client(packages=["engine"])
    listed = client.get("/api/lab/strategies").json()
    assert [s["id"] for s in listed["strategies"]] == ["sector-momentum"] and listed["grammar"]["entry"]
    assert listed["strategies"][0]["hypothesis"] == SPEC["hypothesis"] and "spec" not in listed["strategies"][0]
    detail = client.get("/api/lab/strategies/sector-momentum").json()
    assert detail["final"]["verdict"] == final["verdict"] and set(detail["spec"]) == {*lab.SPEC_FIELDS, "written_at", "model"}
    assert (
        detail["spec"]["title"] == SPEC["title"] and detail["spec"]["predicted_effect"] == SPEC["predicted_effect"] and detail["spec"]["entry"] == SPEC["entry"]
    )
    assert detail["spec"]["model"] and detail["spec"]["written_at"]
    assert lab.desk_view(cfg, "pick-nvda")["spec"] is None
    assert client.get("/api/lab/strategies/nobody").status_code == 404


def test_paper_portfolio_steps_and_graduates(cfg, monkeypatch):
    write_lab_db(cfg)
    conn = ledger(cfg)
    conn.close()
    queue(cfg, experiment(grid={"top_n": [3], "lookback": [126]}), "001-exp.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "002-fin.json")
    process_queue(cfg, now=NOW)
    led = connect(ledger_path(cfg))
    with led:
        led.execute("UPDATE strategies SET status='paper'")
        row = led.execute("SELECT result_at, body FROM lab_results WHERE kind='finalize'").fetchone()
        body = json.loads(row["body"]) | {"paper_start": "2024-12-31", "params": {"top_n": 3, "lookback": 126}}
        led.execute("UPDATE lab_results SET body=? WHERE kind='finalize'", (json.dumps(body),))
    led.close()
    write_lab_db(cfg, end="2025-07-31")
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    first = paper.run(cfg, desk)["paper"][0]
    rows = desk.execute("SELECT count(*) FROM paper_trades").fetchone()[0]
    stored = [dict(r) for r in desk.execute("SELECT * FROM paper_verdicts")]
    assert first["days"] == 212 and rows > 0
    assert [(v["checkpoint"], v["as_of"]) for v in stored] == [(182, "2025-07-01")] and stored[0]["events"] == paper._buys(
        [tuple(r)[2:] for r in desk.execute("SELECT * FROM paper_trades")], "2025-07-01"
    )
    assert first["status"] == gate.STATUS[stored[0]["verdict"]]
    view = lab.desk_view(cfg, "sector-momentum")
    summary = json.loads(view["paper"]["summary"])
    assert view["paper"]["status"] == first["status"] and summary["benchmark"] == "SPY"
    upcoming = None if first["status"] == "retired" else {"day": 273, "on": "2025-09-30"}
    assert summary["gate"]["verdict"]["checkpoint"] == 182 and summary["gate"]["next_checkpoint"] == upcoming
    assert summary["gate"]["min_events"] == 30 and summary["gate"]["family_size"] == 1 and summary["gate"]["bars"] is (body["verdict"] == "pass")
    assert [e["strategy_id"] for e in lab.eligible(cfg)] == (["sector-momentum"] if first["status"] == "eligible" else [])
    write_lab_db(cfg, end="2025-08-29")
    again = paper.run(cfg, desk)["paper"][0]
    assert again["days"] == 241 and again["status"] == first["status"]
    assert [dict(r) for r in desk.execute("SELECT * FROM paper_verdicts")] == stored
    desk.close()


def test_trials_count_across_a_family_and_across_nights(cfg):
    write_lab_db(cfg)
    grid = {"top_n": [1, 3], "lookback": [63, 126]}
    queue(cfg, experiment(spec=SPEC | {"id": "drift-one"}, grid=grid), "001-drift-one.json")
    queue(cfg, experiment(), "002-sector-momentum.json")
    process_queue(cfg, now=NOW)
    queue(cfg, experiment(spec=SPEC | {"id": "drift-two", "rebalance": "quarterly"}, grid=grid), "003-drift-two.json")
    queue(
        cfg,
        experiment(spec=SPEC | {"id": "slow-drift", "parent_id": "drift-two", "rebalance": "weekly"}, grid={"top_n": [3], "lookback": [126]}),
        "004-slow.json",
    )
    process_queue(cfg, now=NOW + timedelta(days=1))
    sheets = {sid: lab.desk_view(cfg, sid)["tear_sheet"] for sid in ("drift-one", "drift-two", "slow-drift", "sector-momentum")}
    assert [sheets[sid]["trials_family"] for sid in ("drift-one", "drift-two", "slow-drift", "sector-momentum")] == [4, 8, 9, 4]
    conn = ledger(cfg)
    parents = {r["id"]: r["parent_id"] for r in conn.execute("SELECT id, parent_id FROM strategies")}
    assert parents == {"drift-one": None, "drift-two": "drift-one", "slow-drift": "drift-two", "sector-momentum": None}
    assert runner.family_ids(conn, "drift-one") == ["drift-one", "drift-two", "slow-drift"] and runner.family_ids(conn, "sector-momentum") == [
        "sector-momentum"
    ]
    assert runner.family_trials(conn, "insider-new") == 0 and runner.family_parent(conn, "insider-new") is None
    wide = runner.family_sharpe_var(conn, "drift-two")
    conn.close()
    assert wide > 0
    alone = SPEC | {"id": "solo-two", "rebalance": "quarterly"}
    queue(cfg, experiment(spec=alone, grid=grid), "005-solo.json")
    process_queue(cfg, now=NOW + timedelta(days=2))
    solo = lab.desk_view(cfg, "solo-two")["tear_sheet"]
    assert solo["trials_family"] == 4 and solo["deflated_sharpe"] >= sheets["drift-two"]["deflated_sharpe"]


def test_engine_export_writes_the_lab_copy(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        desk.executemany(
            "INSERT INTO price_bars (symbol, date, open, close, adj_close) VALUES ('SPY', ?, 99, 100, 100)", [(d,) for d in ("2026-11-02", "2026-11-03")]
        )
    desk.close()
    result = run_lab_export(cfg)
    assert result["ok"] and result["paper"] == []
    data = load(data_path(cfg))
    assert data.kinds["FXAIX"] == "fund" and data.kinds["ACME"] == "stock" and data.plan_mix == {"FXAIX": 0.8, "VXUS": 0.2}
    assert data.series["SPY"].open_adj[0] == 99 and data.end == "2026-11-03"


def test_lab_views_before_anything_ran(cfg):
    assert lab.strategies(cfg) == [] and lab.pending_reviews(cfg) == [] and lab.eligible(cfg) == []
    with pytest.raises(lab.NotReady):
        lab.desk_view(cfg, "x")
    with pytest.raises(lab.NotReady):
        process_queue_needs_data(cfg)


def process_queue_needs_data(cfg):
    folder = cfg.data_dir / "lab" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    return process_queue(cfg)


# ---- Memory: compact series, shared workers, streamed export ----


def test_loaded_series_are_compact_and_find_days_like_a_dict(cfg):
    days = write_lab_db(cfg, drop=("XLK",))
    conn = sqlite3.connect(data_path(cfg))
    conn.execute("DELETE FROM bars WHERE symbol='XLE' AND date=?", (days[10],))
    conn.commit()
    conn.close()
    data = load(data_path(cfg))
    spy, xle, xlk = data.series["SPY"], data.series["XLE"], data.series["XLK"]
    assert isinstance(spy.adj, array) and isinstance(spy.open_adj, array) and isinstance(spy.volume, array)
    assert spy.dates == days and spy.dates[5] is xle.dates[5] and len(spy.index) == len(days)
    assert spy.index[days[10]] == 10 and spy.index.get(days[-1]) == len(days) - 1 and days[3] in spy.index
    assert xle.index.get(days[10]) is None and xle.index[days[11]] == 10 and days[10] not in xle.index and len(xle.index) == len(days) - 1
    assert xlk.index.get(days[-1]) is None and xlk.index.get("1999-01-04") is None and xlk.index.get(days[-401]) == len(days) - 401
    assert list(xle.index) == xle.dates
    with pytest.raises(KeyError):
        xle.index[days[10]]


def test_workers_share_the_loaded_data_and_match_one_worker(cfg, monkeypatch):
    write_lab_db(cfg)
    data = load(data_path(cfg))
    spec = parse(SPEC, data)
    jobs = [({"top_n": n, "lookback": k}, "2015-01-02", "2017-12-29", 1.0) for n in (1, 2, 3) for k in (63, 126)]
    alone = runner._run_many(cfg, data, spec, jobs)
    monkeypatch.setenv("DESK_LAB_WORKERS", "3")
    monkeypatch.setattr(runner, "load", lambda path: pytest.fail("a worker reloaded the lab data"))
    assert runner._run_many(cfg, data, spec, jobs) == alone


def test_export_keeps_the_first_source_for_a_bar(cfg):
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.execute("INSERT INTO price_bars (symbol, date, open, close, adj_close, volume) VALUES ('IWM', '2026-11-02', 1, 2, 2, 10)")
        desk.execute("INSERT INTO prices_daily VALUES ('IWM', '2026-11-02', 9, 9, 'mirror')")
        desk.execute("INSERT INTO prices_daily VALUES ('IWM', '2026-11-03', 3, 3, 'mirror')")
        desk.executemany("INSERT INTO alpaca_bars VALUES ('IWM', ?, 7, 7, 7, 7, 7, 70, 7)", [("2026-11-03",), ("2026-11-04",)])
        desk.execute("INSERT INTO smallcap_months VALUES ('SMOL', '2026-11', 1e9, 1e6)")
        desk.execute("INSERT INTO alpaca_bars VALUES ('SMOL', '2026-11-04', 5, 5, 5, 5, 5, 50, 5)")
    result = export(cfg, desk, {}, {})
    desk.close()
    assert result["bars"] == 4 and result["small_caps"] == 1
    out = sqlite3.connect(data_path(cfg))
    got = out.execute("SELECT symbol, date, open, close, volume FROM bars ORDER BY symbol, date").fetchall()
    out.close()
    assert got == [
        ("IWM", "2026-11-02", 1.0, 2.0, 10.0),
        ("IWM", "2026-11-03", None, 3.0, None),
        ("IWM", "2026-11-04", 7.0, 7.0, 70.0),
        ("SMOL", "2026-11-04", 5.0, 5.0, 50.0),
    ]


# ---- Simulations as a repeatable job ----


def cached(cfg) -> list[str]:
    conn = sqlite3.connect(simcache.cache_path(cfg))
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT snapshot FROM sim_cache")]
    finally:
        conn.close()


def test_a_second_run_of_an_experiment_reuses_every_simulation(cfg, monkeypatch):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    first = process_queue(cfg, now=NOW)
    assert first["cache"]["computed"] > 0
    conn = ledger(cfg)
    body = conn.execute("SELECT body FROM lab_results WHERE kind='experiment'").fetchone()[0]
    trials = conn.execute("SELECT count(*) FROM strategy_trials").fetchone()[0]
    conn.execute("DELETE FROM queue_done")
    conn.commit()
    conn.close()
    monkeypatch.setattr(runner, "_job", lambda args: pytest.fail("a cached simulation was run again"))
    again = process_queue(cfg, now=NOW)
    assert again["cache"] == {"hits": first["cache"]["hits"] + first["cache"]["computed"], "computed": 0}
    conn = ledger(cfg)
    assert conn.execute("SELECT body FROM lab_results WHERE kind='experiment'").fetchone()[0] == body
    assert conn.execute("SELECT count(*) FROM strategy_trials").fetchone()[0] == trials
    conn.close()


def test_a_worker_result_is_checked_then_fills_the_cache(cfg, monkeypatch):
    write_lab_db(cfg)
    request = experiment()
    result = runner.sims(data_path(cfg), request)
    assert result["kind"] == "lab.sims" and result["status"] == "experiment" and result == runner.sims(data_path(cfg), request)
    assert not ledger_path(cfg).exists()
    assert all(simcache.problems(r, result["snapshot"], parse(SPEC).hash) is None for r in result["rows"])
    staged = simcache.stage(cfg, result)
    assert staged["ok"] and staged["rows"] == len(result["rows"]) and simcache.stage(cfg, result)["file"] == staged["file"]
    queue(cfg, request, "001-exp.json")
    calls = []
    real = runner._job
    monkeypatch.setattr(runner, "_job", lambda args: calls.append(args) or real(args))
    out = process_queue(cfg, now=NOW)
    assert out["sims"] == [{"file": staged["file"], "status": "stored", "rows": len(result["rows"]), "new": len(result["rows"])}]
    assert len(calls) == simcache.SPOT_CHECKS and out["cache"]["computed"] == 0 and out["cache"]["hits"] >= len(result["rows"])
    assert simcache.staged(cfg) == []
    conn = ledger(cfg)
    assert json.loads(conn.execute("SELECT body FROM lab_results WHERE kind='experiment'").fetchone()[0])["status"] == "ok"
    conn.close()


def test_worker_results_that_do_not_check_out_are_dropped(cfg):
    write_lab_db(cfg)
    request = experiment()
    good = runner.sims(data_path(cfg), request)
    bent = json.loads(json.dumps(good))
    bent["rows"][0]["rets"][3] += 0.01
    relabelled = json.loads(json.dumps(good))
    relabelled["rows"][0]["params"] = {"top_n": 4, "lookback": 21}
    for bad in (bent | {"rows": bent["rows"][:1]}, relabelled, good | {"snapshot": "0" * 64}, good | {"rows": [{"key": "x"}]}):
        assert simcache.stage(cfg, bad)["ok"]
    assert simcache.stage(cfg, {"kind": "other"}) == {"ok": False, "error": "not a lab.sims result"}
    (simcache.queue_dir(cfg) / "sims-junk.json.gz").write_bytes(b"not gzip")
    out = process_queue(cfg, now=NOW)
    assert sorted(s["status"] for s in out["sims"]) == ["mismatch", "rejected", "rejected", "stale", "unreadable"]
    assert cached(cfg) == []


def test_the_cache_is_dropped_when_the_lab_data_changes(cfg):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    process_queue(cfg, now=NOW)
    assert len(cached(cfg)) == 1
    write_lab_db(cfg, end="2025-01-03")
    queue(cfg, experiment(spec=SPEC | {"id": "other"}, grid={"top_n": [3], "lookback": [126]}), "002-exp.json")
    out = process_queue(cfg, now=NOW)
    assert out["cache"]["computed"] > 0 and cached(cfg) == [simcache.snapshot_hash(data_path(cfg))]
    assert not sqlite3.connect(ledger_path(cfg)).execute("SELECT 1 FROM sqlite_master WHERE name='sim_cache'").fetchone()


# ---- A worker on another machine ----


def worker_round(cfg):
    known = registry()
    job = store.lease(cfg, store.workers(cfg)[0]["id"], set(known))
    out = known[job["kind"]].run(job["inputs"], {"lab": data_path(cfg)})
    path = store.result_path(cfg, job["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(out, f)
    assert store.returned(cfg, job["id"], True, 1.0, 100, None) == "returned"
    return job, worker_apply(cfg)


def test_queued_experiments_go_to_an_online_worker_and_come_back_checked(cfg, monkeypatch):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "002-fin.json")
    assert kinds.offer_queue(cfg, now=NOW)["offered"] == 0 and not simcache.offers_path(cfg).exists()
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    assert kinds.offer_queue(cfg, now=NOW) == {"offered": 1, "wait_minutes": 10.0}
    assert kinds.offer_queue(cfg, now=NOW + timedelta(seconds=30))["offered"] == 0 and len(store.in_state(cfg, "queued")) == 1
    held = process_queue(cfg, now=NOW + timedelta(minutes=1))
    assert held == {"ok": True, "done": [], "waiting_for_worker": ["001-exp.json", "002-fin.json"]}
    job, applied = worker_round(cfg)
    assert applied["saved"] == 1 and store.get(cfg, job["id"])["state"] == "done" and len(simcache.staged(cfg)) == 1
    real, calls = runner._job, []
    monkeypatch.setattr(runner, "_job", lambda args: calls.append(args) or real(args))
    out = process_queue(cfg, now=NOW + timedelta(minutes=2))
    assert [d["status"] for d in out["done"]] == ["experiment", "finalize"] and out["sims"][0]["status"] == "stored" and "job" not in out["sims"][0]
    assert out["cache"]["computed"] == 0 and len(calls) == simcache.SPOT_CHECKS and "waiting_for_worker" not in out


def test_the_lab_stops_waiting_for_a_worker_that_never_answers(cfg):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    assert kinds.offer_queue(cfg, now=NOW)["offered"] == 1
    assert process_queue(cfg, now=NOW + timedelta(minutes=9))["waiting_for_worker"] == ["001-exp.json"]
    out = process_queue(cfg, now=NOW + timedelta(minutes=10))
    assert [d["status"] for d in out["done"]] == ["experiment"] and out["cache"]["computed"] > 0 and "waiting_for_worker" not in out


def test_offering_again_keeps_the_first_offer_time_and_adds_new_files(cfg):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    assert kinds.offer_queue(cfg, now=NOW)["offered"] == 1
    queue(cfg, experiment(seed=8), "002-exp.json")
    for minute in range(1, 10):
        store.beat(cfg, made["id"], {}, now=NOW + timedelta(minutes=minute))
        assert kinds.offer_queue(cfg, now=NOW + timedelta(minutes=minute))["offered"] == (1 if minute == 1 else 0)
    body = simcache.read_offers(cfg)
    assert body["online_at"] == (NOW + timedelta(minutes=9)).isoformat(timespec="seconds") and len(store.in_state(cfg, "queued")) == 2
    assert [e["at"] for e in body["files"].values()] == [NOW.isoformat(timespec="seconds"), (NOW + timedelta(minutes=1)).isoformat(timespec="seconds")]
    assert process_queue(cfg, now=NOW + timedelta(minutes=9, seconds=30))["waiting_for_worker"] == ["001-exp.json", "002-exp.json"]
    out = process_queue(cfg, now=NOW + timedelta(minutes=10))
    assert [d["file"] for d in out["done"]] == ["001-exp.json"] and out["waiting_for_worker"] == ["002-exp.json"]
    assert list(simcache.open_offers(cfg, simcache.snapshot_hash(data_path(cfg)), NOW + timedelta(minutes=10))) == ["002-exp.json"]


def stamp(cfg, name, at):
    os.utime(cfg.data_dir / "lab" / "queue" / name, (at.timestamp(), at.timestamp()))


def test_the_lab_holds_a_just_queued_experiment_while_a_worker_is_around(cfg, monkeypatch):
    write_lab_db(cfg)
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    assert kinds.offer_queue(cfg, now=NOW) == {"offered": 0, "wait_minutes": 10.0} and simcache.worker_seen(cfg, NOW + timedelta(minutes=5))
    queue(cfg, experiment(), "001-exp.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "002-fin.json")
    stamp(cfg, "001-exp.json", NOW + timedelta(seconds=20))
    stamp(cfg, "002-fin.json", NOW + timedelta(seconds=20))
    held = process_queue(cfg, now=NOW + timedelta(seconds=40))
    assert held == {"ok": True, "done": [], "waiting_for_worker": ["001-exp.json", "002-fin.json"]}
    store.beat(cfg, made["id"], {}, now=NOW + timedelta(minutes=1))
    assert kinds.offer_queue(cfg, now=NOW + timedelta(minutes=1))["offered"] == 1
    worker_round(cfg)
    real, calls = runner._job, []
    monkeypatch.setattr(runner, "_job", lambda args: calls.append(args) or real(args))
    out = process_queue(cfg, now=NOW + timedelta(minutes=2))
    assert [d["status"] for d in out["done"]] == ["experiment", "finalize"] and out["sims"][0]["status"] == "stored"
    assert out["cache"]["computed"] == 0 and len(calls) == simcache.SPOT_CHECKS


def test_the_short_hold_ends_by_itself_and_needs_a_worker(cfg, monkeypatch):
    write_lab_db(cfg)
    queue(cfg, experiment(), "001-exp.json")
    stamp(cfg, "001-exp.json", NOW)
    assert [d["status"] for d in process_queue(cfg, now=NOW + timedelta(seconds=30))["done"]] == ["experiment"]
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    kinds.offer_queue(cfg, now=NOW)
    queue(cfg, experiment(seed=8), "002-exp.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "003-fin.json")
    stamp(cfg, "002-exp.json", NOW + timedelta(minutes=1))
    stamp(cfg, "003-fin.json", NOW + timedelta(minutes=1))
    assert process_queue(cfg, now=NOW + timedelta(minutes=3, seconds=59))["waiting_for_worker"] == ["002-exp.json", "003-fin.json"]
    monkeypatch.setenv(simcache.WAIT_ENV, "0")
    assert not simcache.just_queued(cfg.data_dir / "lab" / "queue" / "002-exp.json", NOW + timedelta(minutes=1))
    monkeypatch.delenv(simcache.WAIT_ENV)
    out = process_queue(cfg, now=NOW + timedelta(minutes=4))
    assert [d["status"] for d in out["done"]] == ["experiment", "finalize"] and "waiting_for_worker" not in out
    queue(cfg, experiment(seed=9), "004-exp.json")
    stamp(cfg, "004-exp.json", NOW + timedelta(minutes=7))
    assert not simcache.worker_seen(cfg, NOW + timedelta(minutes=7)) and len(process_queue(cfg, now=NOW + timedelta(minutes=7))["done"]) == 1
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "005-fin.json")
    stamp(cfg, "005-fin.json", NOW + timedelta(minutes=8))
    kinds.offer_queue(cfg, now=NOW + timedelta(minutes=8))
    assert "waiting_for_worker" not in process_queue(cfg, now=NOW + timedelta(minutes=8))


def test_a_wait_that_straddles_the_end_of_the_lab_hours_is_finished(cfg, monkeypatch):
    inside, outside = datetime(2025, 1, 2, 5, 59, tzinfo=ZoneInfo(cfg.timezone)), datetime(2025, 1, 2, 6, 3, tzinfo=ZoneInfo(cfg.timezone))
    answers = iter(
        [
            {"ok": True, "done": [], "waiting_for_worker": ["001-exp.json"]},
            {"ok": True, "done": [], "waiting_for_worker": ["001-exp.json"]},
            {"ok": True, "done": [{}]},
        ]
    )
    monkeypatch.setattr(lab_main, "once", lambda cfg: next(answers))
    assert lab_main.tick(cfg, False, outside) == (None, False)
    result, holding = lab_main.tick(cfg, False, inside)
    assert holding and result["waiting_for_worker"]
    assert lab_main.tick(cfg, holding, outside)[1] is True
    assert lab_main.tick(cfg, True, outside) == ({"ok": True, "done": [{}]}, False)
    assert lab_main.tick(cfg, False, outside) == (None, False)


def test_the_offer_job_is_light_and_runs_through_the_lab_hours(cfg):
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    (entry,) = [e for e in JOBS if isinstance(e, dict) and e["command"].endswith("lab-offer")]
    assert entry == {"schedule": "* 1-5 * * *", "command": "python -m desk.engine lab-offer", "heavy": False, "title": "Lab work to the worker"}
    assert engine_main.run_lab_offer(cfg) == {"ok": True, "offered": 0, "note": "No worker is online, so the lab runs its queue itself."}
    (job,) = [j for j in scheduler.package_jobs(["engine"]) if j.name == "engine-lab-offer"]
    assert job.heavy is False and job.title == "Lab work to the worker"


def test_a_worker_result_is_staged_by_path_without_being_read(cfg, tmp_path):
    write_lab_db(cfg)
    result = tmp_path / "result.json.gz"
    with gzip.open(result, "wt", encoding="utf-8") as f:
        json.dump(runner.sims(data_path(cfg), experiment()), f)
    out = simcache.stage_file(cfg, result)
    assert out["ok"] and out["bytes"] == result.stat().st_size and [p.name for p in simcache.staged(cfg)] == [out["file"]] and result.exists()
    plain = tmp_path / "plain.json"
    plain.write_text("{}")
    assert simcache.stage_file(cfg, plain) == {"ok": False, "error": "the result is not a gzip file"}
    assert not simcache.stage_file(cfg, tmp_path / "missing.gz")["ok"]
    with pytest.raises(ValueError, match="not a gzip file"):
        kinds.accept(cfg, {}, plain)
    assert process_queue(cfg, now=NOW)["sims"][0]["status"] == "stored"


def test_a_large_worker_answer_is_cut_to_what_fits(cfg, monkeypatch):
    write_lab_db(cfg)
    whole = runner.sims(data_path(cfg), experiment())
    monkeypatch.setattr(simcache, "MAX_DAYS", 5000)
    part = runner.sims(data_path(cfg), experiment())
    assert part["partial"] and 0 < len(part["rows"]) < len(whole["rows"]) and "partial" not in whole
    assert sum(len(r["days"]) for r in part["rows"]) <= 5000 and all(r in whole["rows"] for r in part["rows"])
