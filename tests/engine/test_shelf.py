import json
import random
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from desk.api.app import create_app
from desk.engine import kinds, lab
from desk.engine.jobs import JOBS
from desk.engine.lab import rulebook, runner, shelf, sim, simcache
from desk.engine.lab.data import EXPORT_SCHEMA, PLAN_FILE, data_path, held_path, load, plan_path
from desk.engine.lab.runner import process_queue
from desk.engine.lab.sim import pick, simulate
from desk.engine.lab.spec import HINDSIGHT, SETS, SpecError, local_only, parse, resolve, variants
from desk.worker import store

NOW = datetime(2025, 1, 2, 5, 55, tzinfo=UTC)
FUNDS = ("SPY", "VTI", "VXUS", "AGG", "QQQ", "IWM", *SETS["sector_etfs"], "IVV", "FTEC")
STOCKS = tuple(f"STK{i}" for i in range(8))
SMALLS = tuple(f"SML{i}" for i in range(6))
FRENCH = (
    ("size_deciles", ("Lo 10", "Dec 2", "Hi 10")),
    ("momentum_deciles", ("Lo PRIOR", "PRIOR 2", "Hi PRIOR")),
    ("value_deciles", ("Lo 10", "Dec 2", "Hi 10")),
    ("profitability_deciles", ("Lo 10", "Dec 2", "Hi 10")),
    ("investment_deciles", ("Lo 10", "Dec 2", "Hi 10")),
    ("industry_12", tuple(f"Ind{i}" for i in range(12))),
    ("industry_49", tuple(f"I{i}" for i in range(49))),
)
SUBSET = ("lib-60-40", "lib-vol-cap", "lib-size-small", "lib-trend-dip", "lib-plan-mix", "insider-momentum-filter", "lib-dip-reserve", "lib-lump-sum-spread")


def weekdays(start: str, end: str) -> list[str]:
    out, d, e = [], date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture(scope="module")
def lab_file(tmp_path_factory):
    rng = random.Random(5)
    days = weekdays("2014-01-02", "2024-12-31")
    path = tmp_path_factory.mktemp("shelf") / "lab.db"
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    for sym in (*FUNDS, *STOCKS, *SMALLS):
        px, rows, drift = 100.0, [], 0.0
        vol = 0.004 if sym == "AGG" else (0.02 if sym not in FUNDS else 0.01)
        for i, d in enumerate(days):
            if i % 126 == 0:
                drift = rng.choice((-0.0006, 0.0003, 0.0009))
            px *= 1 + drift + rng.gauss(0, vol)
            rows.append((sym, d, px * (1 + rng.gauss(0, 0.002)), px, px, 5e6))
        conn.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        kind, role = ("etf", "benchmark") if sym in FUNDS else ("stock", "universe" if sym in STOCKS else "small_cap")
        conn.execute("INSERT INTO symbols VALUES (?, ?, ?, ?, ?)", (sym, kind, role, days[0], days[-1]))
    months = sorted({d[:7] for d in days})
    conn.executemany("INSERT INTO smallcap VALUES (?, ?)", [(s, m) for s in SMALLS for m in months])
    conn.executemany("INSERT INTO insider VALUES (?, ?, ?, ?)", [(rng.choice(SMALLS), rng.choice(days), rng.randrange(9), 5e4) for _ in range(900)])
    conn.executemany("INSERT INTO earnings VALUES (?, ?, ?)", [(s, d, rng.gauss(0, 0.02)) for s in SMALLS for d in days[40::63]])
    series = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom", "rf")
    conn.executemany("INSERT INTO factors VALUES (?, ?, ?)", [(ser, d, 0.01 if ser == "rf" else rng.gauss(0.03, 1.0)) for ser in series for d in days])
    for set_name, names in FRENCH:
        conn.executemany("INSERT INTO french VALUES (?, ?, ?, ?)", [(set_name, n, d, rng.gauss(0.04, 1.0)) for n in names for d in days])
    conn.executemany("INSERT INTO macro VALUES ('DGS3MO', ?, 2.0)", [(d,) for d in days[::5]])
    path.with_name(PLAN_FILE).write_text(json.dumps({"weights": {"SPY": 0.6, "VXUS": 0.2, "AGG": 0.2}}))
    conn.execute("INSERT INTO settings VALUES ('marginal_rate_pct', '24')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def stocked(cfg, lab_file):
    path = data_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lab_file.read_bytes())
    held_path(cfg).write_text(json.dumps({"as_of": "2024-12-31", "covered": 0.88, "weights": {"SPY": 0.5, "STK0": 0.3, "FTEC": 0.2}}))
    plan_path(cfg).write_bytes(lab_file.with_name(PLAN_FILE).read_bytes())
    return cfg


def spec_of(sid: str) -> dict:
    return shelf.request(next(e for e in shelf.LIBRARY if e["id"] == sid), "2025-01-02T00:00:00+00:00")["spec"]


# ---- The library itself ----


def test_the_library_covers_the_kinds_with_a_plain_line_each():
    assert len(shelf.LIBRARY) >= 30 and len(shelf.IDS) == len(shelf.LIBRARY)
    by_kind = {k: [e for e in shelf.LIBRARY if e["kind"] == k] for k, _ in shelf.KINDS}
    assert len(by_kind["classic"]) >= 12 and len(by_kind["practical"]) >= 8 and len(by_kind["novel"]) >= 6
    for e in shelf.LIBRARY:
        assert e["family"] and e["benchmark"] and e["title"] and 20 <= len(e["description"]) <= 140 and e["description"].endswith(".")
    assert sum(e["type"] == "experiment" for e in shelf.LIBRARY) >= 25


def test_every_entry_is_a_valid_request_on_lab_data(stocked):
    data = load(data_path(stocked))
    for entry in shelf.LIBRARY:
        req = shelf.request(entry, "2025-01-02T00:00:00+00:00")
        if entry["type"] == "rule":
            assert rulebook.parse({k: v for k, v in req.items() if k not in ("request", "written_at")}, data).variants
            continue
        spec = parse(req["spec"], data, model="library")
        assert spec.parent_id == (shelf.HINDSIGHT_FAMILY if entry.get("hindsight") else shelf.FAMILY)
        assert 1 <= len(variants(spec, req["grid"], req["trial_budget"], req["seed"])) <= 4
        assert runner.windows(data, req.get("date_range") or {}, spec.universe.get("kind"))["folds"]


# ---- Grammar: fixed mixes, filters, named French portfolios ----


def test_a_fixed_mix_holds_its_weights_and_drops_funds_without_history(stocked):
    data = load(data_path(stocked))
    spec = parse(spec_of("lib-60-40"), data)
    day = data.calendar[400]
    assert pick(data, spec, resolve(spec, {}), day, set()) == {"SPY": 0.6, "AGG": 0.4}
    raw = spec_of("lib-safe-mix")
    safe = parse(raw, data)
    assert set(safe.weights) == {"IVV", "FTEC", "VXUS"} and sum(safe.weights.values()) == pytest.approx(1.0) and "scaled up" in safe.caveats[0]
    with pytest.raises(SpecError, match="most of this mix"):
        parse(raw | {"universe": {"type": "fund_list", "symbols": ["GRID", "UFO"]}, "sizing": {"weights": {"GRID": 1, "UFO": 1}}}, data)
    with pytest.raises(SpecError, match="not funds"):
        parse(raw | {"universe": {"type": "fund_list", "symbols": ["STK1", "SPY"]}, "sizing": {"weights": {"STK1": 1, "SPY": 1}}}, data)
    plan = parse(spec_of("lib-plan-mix"), data)
    assert plan.weights == pytest.approx({"SPY": 0.6, "VXUS": 0.2, "AGG": 0.2})


def test_filters_keep_a_holding_out_until_it_qualifies(stocked):
    data = load(data_path(stocked))
    spec = parse(spec_of("lib-dip-only"), data)
    v = resolve(spec, {})
    s = data.series["SPY"]
    held = [d for d in data.calendar[300::21] if pick(data, spec, v, d, set())]
    assert held and len(held) < len(data.calendar[300::21])
    for d in held:
        i = s.index[d]
        assert s.adj[i] / max(s.adj[i - 251 : i + 1]) - 1 <= -0.10
    with pytest.raises(SpecError, match="min, a max or both"):
        parse(spec_of("lib-dip-only") | {"filters": [{"metric_id": "dd", "window": "252d"}]}, data)
    with pytest.raises(SpecError, match="feature library"):
        parse(spec_of("lib-dip-only") | {"filters": [{"metric_id": "nope", "window": "252d", "max": 0}]}, data)


def test_named_french_portfolios_need_no_signal(stocked):
    data = load(data_path(stocked))
    spec = parse(spec_of("lib-momentum-top-tenth"), data)
    assert pick(data, spec, resolve(spec, {}), data.calendar_for("french")[300], set()) == {"FF.momentum_deciles.Hi PRIOR": 1.0}
    with pytest.raises(SpecError, match="no portfolio starting with"):
        parse(spec_of("lib-size-small") | {"universe": {"type": "french", "set": "size_deciles", "members": ["zz"]}}, data)
    with pytest.raises(SpecError, match="at least one signal"):
        parse(spec_of("lib-sector-rotation") | {"signals": []}, data)


# ---- Deposit rules ----


def test_holding_back_deposits_costs_when_the_dip_never_comes(stocked):
    data = load(data_path(stocked))
    never = rulebook.parse({"id": "x", "rule": "dip_reserve", "params": {"hold_pct": 50, "dip_pct": 60}, "mix": {"SPY": 1.0}}, data)
    out = rulebook.simulate(data, never, never.variants[0], "2014-02-03", "2022-02-01", rate=0.24)
    base = rulebook._baseline(data, never, "2014-02-03", "2022-02-01", 0.24)
    assert out.contributed == base.contributed and out.trades == base.trades
    assert (out.after_liq < base.after_liq) == (data.series["SPY"].adj[data.series["SPY"].at("2022-02-01")] > data.series["SPY"].adj[30])
    often = rulebook.parse({"id": "x", "rule": "dip_reserve", "params": {"hold_pct": 50, "dip_pct": 5}, "mix": {"SPY": 1.0}}, data)
    assert rulebook.simulate(data, often, often.variants[0], "2014-02-03", "2022-02-01", rate=0.24).trades > base.trades


def test_a_lump_sum_can_be_spread_over_months(stocked):
    data = load(data_path(stocked))
    rule = rulebook.parse({"id": "x", "rule": "spread", "params": {"months": 6}, "mix": {"SPY": 1.0}, "deposit_monthly": 0, "start_value": 12000}, data)
    out = rulebook.simulate(data, rule, rule.variants[0], "2014-02-03", "2016-02-01", rate=0.24)
    base = rulebook._baseline(data, rule, "2014-02-03", "2016-02-01", 0.24)
    assert out.contributed == base.contributed == 12000 and base.trades == 2 and out.trades == 7
    with pytest.raises(rulebook.RuleError, match="start_value above zero"):
        rulebook.parse({"id": "x", "rule": "spread", "params": {"months": 6}, "mix": {"SPY": 1.0}, "start_value": 0}, data)


def rule_body(horizon: dict, verdict: str = "no_clear_edge") -> dict:
    params = {"band_pts": 10.0}
    return {
        "variants": [{"params": params, "horizons": [{"years": 5, "starts": 0}, {"years": 10, "starts": 14, **horizon}]}],
        "best": params,
        "verdict": verdict,
    }


def test_a_start_month_the_rule_did_not_change_is_not_counted_as_worse():
    entry = next(e for e in shelf.LIBRARY if e["id"] == "lib-rebalance-bands-plan")
    stored = {"p5_pts": -0.6, "p50_pts": 0.0, "p95_pts": -0.0, "share_better": 0.0}
    old = shelf._rule_row(entry, rule_body(stored))
    assert old["verdict"] == "within_noise" and "worse" not in old["line"] and "+0.0" not in old["line"] and "-0.0" not in old["line"]
    assert old["line"] == (
        "No clear edge: a typical 0.0 points of the money put in over 10 years against the same deposits, invested plainly; "
        "never ahead, and no different in at least half of 14 start months."
    )
    counted = shelf._rule_row(entry, rule_body(stored | {"share_worse": 0.2857}))
    assert counted["line"].endswith("ahead in 0%, behind in 29% and no different in 71% of 14 start months.") and counted["rule"]["share_worse"] == 0.2857
    flat = shelf._rule_row(entry, rule_body(stored | {"p5_pts": -0.04, "share_worse": 0.0714}, verdict="hurts"))
    assert flat["verdict"] == "within_noise" and flat["line"].startswith(
        "No difference: within a tenth of a point of the same deposits, invested plainly in nearly every one of 14 start months over 10 years."
    )
    clear = shelf._rule_row(entry, rule_body({"p5_pts": -9.0, "p50_pts": -5.37, "p95_pts": -2.1, "share_better": 0.0, "share_worse": 1.0}, verdict="hurts"))
    assert (
        clear["verdict"] == "fell_short"
        and clear["line"].startswith("Hurt: a typical -5.4 points")
        and clear["line"].endswith("ahead in 0% and behind in 100% of 14 start months.")
    )
    earlier = shelf._rule_row(entry, rule_body({"p5_pts": -2.6, "p50_pts": 2.44, "p95_pts": 5.3, "share_better": 0.7857}))
    assert earlier["line"].endswith(
        "a typical +2.4 points of the money put in over 10 years against the same deposits, invested plainly; ahead in 79% of 14 start months."
    )
    assert rulebook._quantiles([0.0, 0.0, -1.0, 2.0]) | {"mean_pts": 0} == {
        "starts": 4,
        "mean_pts": 0,
        "p5_pts": -1.0,
        "p50_pts": 0.0,
        "p95_pts": 0.0,
        "share_better": 0.25,
        "share_worse": 0.25,
    }


# ---- Queue and results ----


def test_the_library_is_queued_once_run_and_reported_out_of_sample_only(stocked, monkeypatch):
    cfg = stocked
    before = shelf.view(cfg)
    assert (
        before["counts"]["waiting"] == len(shelf.LIBRARY) and before["as_of"] is None and all(r["reason"] for r in before["rows"]) and shelf.ready(cfg) is None
    )
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in SUBSET))
    monkeypatch.setattr(shelf, "IDS", frozenset(SUBSET))
    assert shelf.queue_missing(cfg, now=NOW) == {"queued": 8, "of": 8}
    assert shelf.queue_missing(cfg, now=NOW + timedelta(hours=1)) == {"queued": 0, "of": 8}
    names = sorted(p.name for p in simcache.queue_dir(cfg).glob("*.json"))
    assert [n.rsplit("-", 1)[1] for n in names] == ["experiment.json"] * 6 + ["rule.json"] * 2
    assert {r["status"] for r in shelf.view(cfg)["rows"]} == {"waiting"} and "Queued for tonight" in shelf.view(cfg)["rows"][0]["reason"]
    out = process_queue(cfg, now=NOW)
    assert {d["status"] for d in out["done"]} == {"experiment", "rule"}
    assert shelf.queue_missing(cfg, now=NOW + timedelta(days=1)) == {"queued": 0, "of": 8}
    view = shelf.view(cfg)
    assert view["counts"]["tested"] == 8 and view["as_of"] == NOW.isoformat(timespec="seconds") and view["trials"] >= 7
    assert sum(view["counts"][k] for k in ("held_up", "within_noise", "fell_short", "inconclusive")) == 8
    kinds_seen = [r["kind"] for r in view["rows"]]
    assert kinds_seen == sorted(kinds_seen, key=["classic", "practical", "novel"].index)
    for r in view["rows"]:
        assert r["verdict"] in shelf.ORDER and r["line"].endswith(".") and r["reason"] is None
        text = json.dumps(r)
        assert "train" not in text and "full" not in text and "in_sample" not in text
        if r["type"] == "rule":
            assert r["rule"]["starts"] > 0 and r["out_of_sample"] is None
            assert r["rule"]["share_better"] + r["rule"]["share_worse"] <= 1.0001 and "worse" not in r["line"]
            continue
        x, band = r["out_of_sample"]["excess_pts"], r["noise"]["band_pts"]
        assert r["noise"]["trials"] == view["trials"] and band >= 0 and 0 <= r["noise"]["luck"] <= 1 and r["outdated"] is False
        if not round(x, 1):
            assert r["verdict"] == "within_noise" and r["line"].startswith("Level with ")
            continue
        assert band > 0
        assert r["verdict"] == ("fell_short" if x <= 0 else "held_up" if x >= band and (r["pbo"] is None or r["pbo"] < runner.PBO_BAR) else "within_noise")
    assert next(r for r in view["rows"] if r["id"] == "lib-size-small")["research_only"] is True
    assert shelf.ready(cfg) == f"8 strategies tested, {view['counts']['held_up']} held up out of sample"
    assert lab.pending_reviews(cfg, now=NOW) == []
    assert all(s["library"] for s in lab.strategies(cfg) if s["kind"] == "strategy")
    with TestClient(create_app(cfg)) as client:
        assert client.get("/api/lab/library").json()["counts"] == view["counts"]


def test_an_entry_the_lab_refused_is_explained_and_tried_again_the_next_evening(stocked, monkeypatch):
    cfg = stocked
    conn = sqlite3.connect(data_path(cfg))
    conn.execute("DELETE FROM smallcap")
    conn.commit()
    conn.close()
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] == "insider-momentum-filter"))
    monkeypatch.setattr(shelf, "IDS", frozenset({"insider-momentum-filter"}))
    assert shelf.queue_missing(cfg, now=NOW)["queued"] == 1
    process_queue(cfg, now=NOW)
    (row,) = shelf.view(cfg)["rows"]
    assert row["status"] == "not_run" and row["verdict"] is None
    assert row["reason"] == "Small-company price history is still loading. This runs once that finishes."
    assert shelf.queue_missing(cfg, now=NOW + timedelta(hours=11))["queued"] == 0
    assert shelf.queue_missing(cfg, now=NOW + timedelta(days=1))["queued"] == 1
    assert shelf.view(cfg)["rows"][0]["status"] == "waiting"


BOX = ("lib-plan-mix", "lib-safe-mix", "lib-tech-tilt", "lib-rebalance-bands-plan")


def test_built_in_mixes_run_without_a_plan_when_their_funds_are_unlabelled(stocked, monkeypatch):
    cfg = stocked
    plan_path(cfg).unlink()
    conn = sqlite3.connect(data_path(cfg))
    conn.execute("UPDATE symbols SET kind='unknown' WHERE symbol IN ('IVV', 'FTEC')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in BOX))
    monkeypatch.setattr(shelf, "IDS", frozenset(BOX))
    runner.ledger_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    ledger = sqlite3.connect(runner.ledger_path(cfg))
    ledger.executescript(runner.LEDGER)
    for sid in BOX:
        old = {"strategy_id": sid, "version": 1, "kind": "rejected", "result_at": NOW.isoformat(), "problems": ['entry needs a top N, like {"top_n": 3}']}
        ledger.execute("INSERT INTO lab_results VALUES (?, 1, 'rejected', ?, ?)", (sid, old["result_at"], json.dumps(old)))
    ledger.commit()
    ledger.close()
    before = {r["id"]: r for r in shelf.view(cfg)["rows"]}
    assert all(r["status"] == "not_run" and "{" not in r["reason"] and "top_n" not in r["reason"] for r in before.values())
    later = NOW + timedelta(minutes=5)
    assert shelf.queue_missing(cfg, now=later) == {"queued": 4, "of": 4}
    process_queue(cfg, now=later)
    rows = {r["id"]: r for r in shelf.view(cfg)["rows"]}
    assert rows["lib-safe-mix"]["status"] == "tested" and rows["lib-tech-tilt"]["status"] == "tested"
    bands = rows["lib-rebalance-bands-plan"]
    assert bands["status"] == "tested" and bands["line"].startswith("Run on the built-in safe mix, as no plan of your own is loaded.")
    assert any("scaled up" in c for c in bands["caveats"])
    plan = rows["lib-plan-mix"]
    assert plan["status"] == "not_run" and plan["reason"].startswith("No plan of your own is loaded on the desk yet")
    assert shelf.queue_missing(cfg, now=later + timedelta(minutes=1))["queued"] == 0
    assert shelf.queue_missing(cfg, now=later + timedelta(hours=13))["queued"] == 1


PAIR = ("lib-buy-hold-sp500", "lib-60-40")


def test_the_sp500_row_reads_as_the_yardstick_when_there_is_no_plan_to_compare_it_with(stocked, monkeypatch):
    cfg = stocked
    plan_path(cfg).unlink()
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in PAIR))
    monkeypatch.setattr(shelf, "IDS", frozenset(PAIR))
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    view = shelf.view(cfg)
    first, other = view["rows"]
    assert first["id"] == "lib-buy-hold-sp500" and first["status"] == "tested" and first["yardstick"] and first["verdict"] is None
    assert first["line"] == "The yardstick most rows here are measured against. No plan of your own is loaded, so it is measured against itself."
    assert first["out_of_sample"]["excess_pts"] is None and first["out_of_sample"]["ann_return_pct"] is not None
    assert view["counts"]["tested"] == 2 and view["counts"]["yardstick"] == 1 and view["counts"]["fell_short"] == (other["verdict"] == "fell_short")
    assert other["yardstick"] is False and abs(first["gap_pts"]) < 0.05
    assert view["note"] == shelf.NOTE and "cash" not in view["note"] and view["self_check"] == {"gap_pts": first["gap_pts"], "level": True}
    ledger = sqlite3.connect(runner.ledger_path(cfg))
    ledger.execute("UPDATE lab_results SET body = json_set(body, '$.walk_forward.excess_pts', 0.6) WHERE strategy_id='lib-buy-hold-sp500'")
    ledger.commit()
    ledger.close()
    off = shelf.view(cfg)
    assert off["self_check"] == {"gap_pts": 0.6, "level": False} and off["rows"][0]["verdict"] is None
    assert off["note"].startswith(shelf.NOTE) and "should read level, but it is off by 0.6 points a year" in off["note"]


def test_a_strategy_is_invested_from_the_first_day_of_every_test_year(stocked):
    data = load(data_path(stocked))
    spec = parse(spec_of("lib-buy-hold-sp500"), data)
    year = simulate(data, spec, resolve(spec, {}), "2016-01-04", "2016-12-30")
    spy = data.series["SPY"]
    own = year.values[-1] / year.values[0]
    assert year.trades[0][0] == year.days[0] and own == pytest.approx(spy.adj[spy.index[year.days[-1]]] / spy.adj[spy.index[year.days[0]]], abs=2e-4)
    late = simulate(data, spec, resolve(spec, {}), "2016-01-04", "2016-12-30", enter=False)
    assert late.trades[0][0] > "2016-01-29" and late.values[10] == pytest.approx(late.values[0], rel=1e-3)


def test_a_row_level_with_its_benchmark_is_not_called_fell_short():
    entry = next(e for e in shelf.LIBRARY if e["id"] == "lib-60-40")

    def row(x):
        wf = {"days": 2520, "excess_pts": x, "start": "2015-01-02", "end": "2024-12-31"}
        return shelf._experiment(entry, {"walk_forward": wf, "noise": {"tracking_error_pct": 2.0, "obs": 2520}}, 1)

    assert row(-0.5)["verdict"] == "fell_short" and row(1.2)["verdict"] == "held_up" and row(0.3)["verdict"] == "within_noise"
    for x in (-0.04, 0.0, 0.04):
        level = row(x)
        assert level["verdict"] == "within_noise" and level["line"] == "Level with S&P 500 (SPY) over 10 years out of sample."


def test_with_a_plan_the_sp500_row_is_judged_against_it(stocked, monkeypatch):
    cfg = stocked
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in PAIR))
    monkeypatch.setattr(shelf, "IDS", frozenset(PAIR))
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    view = shelf.view(cfg)
    row = next(r for r in view["rows"] if r["id"] == "lib-buy-hold-sp500")
    assert row["verdict"] in ("held_up", "within_noise", "fell_short") and not row["yardstick"] and "Your plan's mix" in row["line"]
    assert view["counts"]["yardstick"] == 0 and view["counts"]["outdated"] == 0 and view["note"] == shelf.NOTE


def test_a_result_from_an_older_revision_is_flagged_and_run_again(stocked, monkeypatch):
    cfg = stocked
    ids = ("lib-60-40", "lib-dip-reserve")
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ids))
    monkeypatch.setattr(shelf, "IDS", frozenset(ids))
    assert shelf.queue_missing(cfg, now=NOW) == {"queued": 2, "of": 2}
    process_queue(cfg, now=NOW)
    ledger = sqlite3.connect(runner.ledger_path(cfg))
    assert [r[0] for r in ledger.execute("SELECT json_extract(body, '$.library_rev') FROM lab_results")] == [shelf.REV, shelf.REV]
    trials = ledger.execute("SELECT count(*) FROM strategy_trials").fetchone()[0]
    ledger.execute("UPDATE lab_results SET body = json_remove(body, '$.library_rev')")
    ledger.commit()
    before = shelf.view(cfg)
    assert before["counts"]["outdated"] == 2 and all(r["outdated"] and r["status"] == "tested" for r in before["rows"])
    assert before["note"] == f"{shelf.NOTE} All of these {shelf.OUTDATED}"
    later = NOW + timedelta(minutes=5)
    assert shelf.queue_missing(cfg, now=later) == {"queued": 2, "of": 2}
    assert shelf.queue_missing(cfg, now=later + timedelta(minutes=1))["queued"] == 0
    waiting = shelf.view(cfg)
    assert all(r["status"] == "tested" and r["reason"] is None and r["outdated"] for r in waiting["rows"])
    process_queue(cfg, now=later)
    after = shelf.view(cfg)
    assert after["counts"]["outdated"] == 0 and after["note"] == shelf.NOTE and after["as_of"] == later.isoformat(timespec="seconds")
    assert after["trials"] == before["trials"] and after["self_check"] is None
    assert ledger.execute("SELECT count(DISTINCT strategy_id || params || window || kind) FROM strategy_trials").fetchone()[0] == trials
    ledger.close()
    assert shelf.queue_missing(cfg, now=later + timedelta(days=29))["queued"] == 0
    assert shelf.queue_missing(cfg, now=later + timedelta(days=31)) == {"queued": 2, "of": 2}
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e | {"rev": e["rev"] + (e["id"] == "lib-60-40")} for e in shelf.LIBRARY))
    bumped = {r["id"]: r["outdated"] for r in shelf.view(cfg)["rows"]}
    assert bumped == {"lib-60-40": True, "lib-dip-reserve": False}
    assert shelf.view(cfg)["note"] == f"{shelf.NOTE} Some of these {shelf.OUTDATED}"


def test_what_you_hold_today_is_shown_as_hindsight_and_never_judged(stocked, monkeypatch):
    cfg = stocked
    data = load(data_path(cfg))
    held = parse(spec_of("lib-as-held"), data)
    assert held.weights == pytest.approx({"SPY": 0.5, "STK0": 0.3, "FTEC": 0.2}) and held.rebalance == "Q"
    assert held.caveats[:3] == [HINDSIGHT, "Holdings as of 2024-12-31.", "Holdings with no market price history, about 12% of what is invested, are left out."]
    with pytest.raises(SpecError, match="not funds"):
        parse(spec_of("lib-60-40") | {"universe": {"type": "fund_list", "symbols": ["STK0", "SPY"]}, "sizing": {"weights": {"STK0": 1, "SPY": 1}}}, data)
    ids = ("lib-as-held", "lib-60-40", "lib-safe-mix")
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ids))
    monkeypatch.setattr(shelf, "IDS", frozenset(ids))
    assert shelf.queue_missing(cfg, now=NOW) == {"queued": 3, "of": 3}
    process_queue(cfg, now=NOW)
    view = shelf.view(cfg)
    row = next(r for r in view["rows"] if r["kind"] == "practical")
    assert row["id"] == "lib-as-held" and row["hindsight"] and row["status"] == "tested" and row["verdict"] is None and row["noise"] is None
    assert row["line"].startswith("From ") and ", today's mix would have run " in row["line"] and row["line"].endswith(shelf.HINDSIGHT_LINE)
    assert row["out_of_sample"]["excess_pts"] is not None and HINDSIGHT in row["caveats"]
    assert view["counts"]["hindsight"] == 1 and view["counts"]["tested"] == 3 and sum(view["counts"][v] for v in ("held_up", "within_noise", "fell_short")) == 2
    assert view["note"] == f"{shelf.NOTE} {shelf.HINDSIGHT_NOTE}" and sum(r["hindsight"] for r in view["rows"]) == 1
    assert shelf.queue_missing(cfg, now=NOW + timedelta(days=6))["queued"] == 0
    assert shelf.queue_missing(cfg, now=NOW + timedelta(days=8)) == {"queued": 1, "of": 3}
    ledger = sqlite3.connect(runner.ledger_path(cfg))
    families = dict(ledger.execute("SELECT id, parent_id FROM strategies"))
    assert families["lib-as-held"] == shelf.HINDSIGHT_FAMILY and families["lib-60-40"] == shelf.FAMILY
    assert (
        view["trials"]
        == ledger.execute("SELECT count(DISTINCT strategy_id || params) FROM strategy_trials WHERE kind='full' AND strategy_id != 'lib-as-held'").fetchone()[0]
    )
    ranked = spec_of("lib-as-held") | {"id": "held-ranked", "signals": [{"metric_id": "ret", "window": "{lookback}d"}], "entry": {"top_n": 2}}
    ranked |= {"params": {"lookback": {"min": 21, "max": 252, "default": 126}}}
    asked = {"request": "experiment", "spec": ranked, "grid": {"lookback": [63, 126]}, "seed": 7, "trial_budget": 4, "analyses": []}
    conn = runner.ledger(cfg)
    assert runner.run_experiment(None, conn, data, asked, now=NOW)["deploy_params"]
    monkeypatch.setattr(runner, "_bars", lambda *a: {"walk_forward": True, "holdout": True, "factor": None})
    final = runner.finalize(cfg, conn, data, {"strategy_id": "held-ranked", "version": 1}, now=NOW)
    conn.close()
    assert final["verdict"] == "pass" and final["paper_start"] is None
    assert ledger.execute("SELECT status FROM strategies WHERE id='held-ranked'").fetchone()[0] == "research"
    ledger.close()


def test_the_hindsight_line_says_ahead_behind_or_level_and_names_the_dates():
    entry = next(e for e in shelf.LIBRARY if e["id"] == "lib-as-held")

    def line(x):
        wf = {"days": 500, "excess_pts": x, "start": "2022-11-14", "end": "2024-11-08", "ann_return_pct": 9.0}
        return shelf._hindsight(entry, {"walk_forward": wf})["line"]

    assert line(3.24) == f"From Nov 2022 to Nov 2024, today's mix would have run 3.2 points a year ahead of S&P 500 (SPY). {shelf.HINDSIGHT_LINE}"
    assert line(-1.5).startswith("From Nov 2022 to Nov 2024, today's mix would have run 1.5 points a year behind S&P 500 (SPY).")
    assert "would have run level with S&P 500 (SPY)." in line(0.04)
    assert shelf._hindsight(entry, {"walk_forward": {}}) == {"verdict": None, "line": f"No record to show for today's mix yet. {shelf.HINDSIGHT_LINE}"}
    assert (
        shelf.plain(["there is no held mix in the lab data yet"])
        == "The desk has not sent the lab what you hold yet. This runs the night after the next lab export."
    )


def test_a_stock_in_the_plan_is_screened_and_costed_like_any_other_so_a_worker_agrees_with_the_box(stocked, tmp_path):
    cfg = stocked
    plan_path(cfg).write_text(json.dumps({"weights": {"SPY": 0.5, "STK0": 0.5}}))
    (tmp_path / "lab.db").write_bytes(data_path(cfg).read_bytes())
    box, worker = load(data_path(cfg)), load(tmp_path / "lab.db")
    assert box.plan_mix == {"SPY": 0.5, "STK0": 0.5} and worker.plan_mix == {}
    spec = parse(spec_of("lib-stock-momentum"), worker)
    day = box.calendar[400]
    assert "STK0" in sim.universe(box, spec, day) and sim.universe(box, spec, day) == sim.universe(worker, spec, day)
    at = box.series["STK0"].index.get(day)
    assert sim._bps(box, "STK0", at) == sim._bps(worker, "STK0", at) == sim.STOCK_BPS
    with pytest.raises(SpecError, match="STK0 are not funds"):
        parse(spec_of("lib-60-40") | {"universe": {"type": "fund_list", "symbols": ["SPY", "STK0"]}, "sizing": "equal"}, box)


def test_stock_screens_are_run_again_now_that_no_name_is_kept_out_for_being_his():
    screens = {e["id"] for e in shelf.LIBRARY if e["rev"] == shelf.SCREEN_REV}
    assert screens == {e["id"] for e in shelf.LIBRARY if e["type"] == "experiment" and e["spec"]["universe"].get("type") == "screen"}
    assert len(screens) == 5 and shelf.SCREEN_REV > shelf.MIX_REV
    seen = {"kind": "experiment", "rev": shelf.MIX_REV, "result_at": "2026-11-12T05:56:00+00:00", "body": None}
    assert all(shelf._outdated(e, seen) == (e["id"] in screens) for e in shelf.LIBRARY)


def test_mixes_that_held_cash_for_a_fund_not_yet_trading_are_run_again():
    again = {e["id"] for e in shelf.LIBRARY if e["rev"] == shelf.MIX_REV}
    assert again == {"lib-buy-hold-total-world", "lib-risk-parity", "lib-plan-mix", "lib-safe-mix", "lib-tech-tilt"} and shelf.MIX_REV > shelf.REV
    screens = {e["id"] for e in shelf.LIBRARY if e["rev"] == shelf.SCREEN_REV}
    seen = {"kind": "experiment", "rev": shelf.REV, "result_at": "2026-11-12T05:56:00+00:00", "body": None}
    assert all(shelf._outdated(e, seen) == (e["id"] in again | screens) for e in shelf.LIBRARY)
    short = "the walk-forward range 2021-04-01 to 2022-12-30 is 1.7 years; it needs 2.5 or more before the two-year holdout"
    assert shelf.plain([short]) == "Its funds have not all traded long enough to test before the two-year holdout."


def test_an_outdated_row_whose_rerun_left_no_result_waits_before_another_try():
    entry = {"id": "lib-60-40", "rev": 2}
    seen = {"kind": "experiment", "rev": 1, "result_at": "2026-11-12T05:56:00+00:00", "body": None}
    now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    made = "20261112T055500Z-03-lib-60-40-v1-experiment.json"
    tried = "20261112T084500Z-03-lib-60-40-v1-experiment.json"
    other = "20261112T084500Z-04-lib-60-40-plus-v1-experiment.json"
    assert shelf._due(entry, seen, now, set()) and shelf._due(entry, seen, now, {made}) and shelf._due(entry, seen, now, {made, other})
    assert not shelf._due(entry, seen, now, {made, tried})
    assert shelf._due(entry, seen, now + timedelta(hours=12), {made, tried})
    current = seen | {"rev": 2}
    assert not shelf._due(entry, current, now, {made}) and shelf._due(entry, current, now + timedelta(days=31), {made})


def test_every_fund_in_a_built_in_mix_is_known_to_the_lab():
    from desk.engine.lab.data import LISTED_FUNDS
    from desk.engine.market import BENCHMARKS

    known = set(LISTED_FUNDS) | set(BENCHMARKS)
    for entry in shelf.LIBRARY:
        body = entry.get("body") or {}
        weights = ((entry.get("spec") or {}).get("sizing") or {}).get("weights") if isinstance((entry.get("spec") or {}).get("sizing"), dict) else None
        for mix in (weights, body.get("mix"), body.get("mix_without_plan")):
            assert set(mix or {}) <= known, entry["id"]


def test_reasons_never_show_request_syntax():
    for problems in (["there is no plan mix in the lab data yet", 'entry needs a top N, for example {"top_n": 3}'], ["something new {x: 1}"], []):
        text = shelf.plain(problems)
        assert text and "{" not in text and "top_n" not in text


def test_a_build_that_lands_after_the_export_still_queues_the_library_that_night(stocked, monkeypatch):
    from desk.engine.__main__ import run_lab_offer

    cfg = stocked
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ("lib-60-40", "lib-harvest")))
    monkeypatch.setattr(shelf, "IDS", frozenset({"lib-60-40", "lib-harvest"}))
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {})
    first = run_lab_offer(cfg)
    assert first["library"] == {"queued": 2, "of": 2} and first["offered"] == 1
    again = run_lab_offer(cfg)
    assert "library" not in again and again["offered"] == 0 and len(list(simcache.queue_dir(cfg).glob("*.json"))) == 2


def test_the_export_queues_the_library_before_it_offers_and_never_waits_its_turn(stocked):
    from desk.engine.__main__ import run_lab_export

    cfg = stocked
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {})
    out = run_lab_export(cfg)
    experiments = sum(e["type"] == "experiment" and not local_only(e["spec"]) for e in shelf.LIBRARY)
    assert out["library"] == {"queued": len(shelf.LIBRARY), "of": len(shelf.LIBRARY)}
    assert out["worker"]["offered"] == experiments == len(store.in_state(cfg, "queued"))
    entry = next(e for e in JOBS if isinstance(e, dict) and e["command"].endswith("lab-export"))
    assert entry == {"schedule": "55 0 * * *", "command": "python -m desk.engine lab-export", "heavy": False}


def test_the_lab_keeps_waiting_while_the_worker_keeps_answering(stocked, monkeypatch):
    cfg = stocked
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ("lib-60-40", "lib-vol-cap")))
    monkeypatch.setattr(shelf, "IDS", frozenset({"lib-60-40", "lib-vol-cap"}))
    made = store.add_worker(cfg, "Horizon")
    store.beat(cfg, made["id"], {}, now=NOW)
    shelf.queue_missing(cfg, now=NOW)
    assert kinds.offer_queue(cfg, now=NOW)["offered"] == 2
    from tests.engine.test_lab import worker_round

    worker_round(cfg)
    first = process_queue(cfg, now=NOW + timedelta(minutes=9))
    assert len(first["done"]) == 1 and len(first["waiting_for_worker"]) == 1 and first["cache"]["computed"] == 0
    assert len(process_queue(cfg, now=NOW + timedelta(minutes=18))["waiting_for_worker"]) == 1
    late = process_queue(cfg, now=NOW + timedelta(minutes=19))
    assert len(late["done"]) == 1 and late["cache"]["computed"] > 0 and "waiting_for_worker" not in late
