import json
import random
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from desk.agents.sources import RealLab
from desk.db import connect
from desk.engine import gate, lab, schema
from desk.engine.__main__ import run_holdings, run_lab_export
from desk.engine.lab import library as features
from desk.engine.lab import paper, runner, stats
from desk.engine.lab.data import EXPORT_SCHEMA, Series, data_path, ledger_path, load
from desk.engine.lab.runner import ledger, process_queue
from desk.engine.lab.sim import _year_tax, simulate
from desk.engine.lab.spec import SETS, SpecError, parse, resolve, variants
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
