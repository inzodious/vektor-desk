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
from desk.engine.lab.data import EXPORT_SCHEMA, PLAN_FILE, PUBLIC_COVERAGE, PUBLIC_ROLE, PUBLIC_SIZES, data_path, held_path, load, plan_path
from desk.engine.lab.runner import process_queue
from desk.engine.lab.sim import pick, simulate
from desk.engine.lab.spec import HINDSIGHT, PUBLIC_EXITS, SCREEN_HINDSIGHT, SETS, SIZE_WORDS, SpecError, local_only, parse, resolve, variants
from desk.engine.market import LIBRARY_FUNDS
from desk.worker import store

NOW = datetime(2025, 1, 2, 5, 55, tzinfo=UTC)
BAR = f"{shelf.NOTE} {shelf.BAR_NOTE.format(trials=2)}"
FUNDS = ("SPY", "VTI", "VXUS", "AGG", "QQQ", "IWM", *SETS["sector_etfs"], "FTEC", *LIBRARY_FUNDS)
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
COVERED = {"as_of": "2013-06-28", "tests_from": "2014-01-02", "listed": 8, "priced": 8, "loading": 0, "missing": 0, "stopped": 0, "pct": 100.0, "enough": True}
ON_THE_LIST = "Tested on the 8 largest US companies of mid-2013, a list that owes nothing to what you hold. All 8 have prices."
SIZES = {s: [1e9 * (i + 1), "2013-06-28"] for i, s in enumerate(STOCKS)}
NEW_SCREENS = ("lib-stock-dip-hold", "lib-core-stock-picks", "lib-ten-largest", "lib-ten-beaten")
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
        kind, role = ("etf", "benchmark") if sym in FUNDS else ("stock", PUBLIC_ROLE if sym in STOCKS else "small_cap")
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
    conn.execute("INSERT INTO settings VALUES (?, ?)", (PUBLIC_COVERAGE, json.dumps(COVERED)))
    conn.execute("INSERT INTO settings VALUES (?, ?)", (PUBLIC_SIZES, json.dumps(SIZES)))
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
    for gone in ("NLR", "GRID", "ICLN", "UFO"):
        del data.series[gone]
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
    ids = [r["id"] for r in view["rows"]]
    looked = shelf.rows(cfg, [*ids, "lib-not-yet", ids[0]])
    assert list(looked) == [*ids, "lib-not-yet"] and all(tuple(v) == shelf.LOOKUP for v in looked.values())
    for r in view["rows"]:
        assert looked[r["id"]] == {k: r[k] for k in shelf.LOOKUP}
        if r["type"] != "rule":
            assert r["backs"] == {"held_up": "yes", "within_noise": "no_edge", "fell_short": "no"}.get(r["verdict"])
    unknown = {"id": "lib-not-yet", "status": "not_run", "outdated": False}
    assert looked["lib-not-yet"] == {k: unknown.get(k) for k in shelf.LOOKUP}
    assert set(shelf._latest(cfg, only=ids[:2])[0]) == set(ids[:2]) and shelf._latest(cfg, only=[])[0] == {}


PUBLISHED = (
    "lib-buy-hold-sp500",
    "lib-buy-hold-total-world",
    "lib-60-40",
    "lib-risk-parity",
    "lib-trend-200d",
    "lib-vol-cap",
    "lib-dual-momentum",
    "lib-sector-momentum-12-1",
    "lib-sector-rotation",
    "lib-sector-low-vol",
    "lib-stock-momentum",
    "lib-stock-low-vol",
    "lib-size-small",
    "lib-momentum-top-tenth",
    "lib-value-tilt",
    "lib-profitability-tilt",
    "lib-quality-tilt",
    "lib-industry-momentum",
    "lib-industry-low-vol",
    "lib-three-fund",
    "lib-permanent",
    "lib-all-weather",
    "lib-trend-five",
    "lib-golden-cross",
    "lib-asset-momentum",
    "lib-equal-sectors",
    "lib-equal-weight-500",
    "lib-dividend-growers",
    "lib-small-value-fund",
    "lib-value-momentum",
    "lib-small-reversal",
    "lib-plan-mix",
    "lib-as-held",
    "lib-safe-mix",
    "lib-tech-tilt",
    "lib-dip-only",
    "lib-dip-sectors",
    "lib-dip-reserve",
    "lib-margin-dip",
    "lib-lump-sum-spread",
    "lib-deposit-steering",
    "lib-rebalance-bands",
    "lib-rebalance-bands-plan",
    "lib-harvest",
    "lib-core-satellite",
    "lib-themes-equal",
    "lib-as-held-capped",
    "lib-margin-paydown",
    "lib-trend-dip",
    "lib-sector-momentum-uptrend",
    "lib-calm-winners",
    "lib-breakout-vol-cap",
    "lib-discount-day",
    "insider-momentum-filter",
    "drift-insider-confirmed",
    "lib-momentum-calm",
    "lib-drawdown-stop",
    "lib-down-week",
    "lib-canary",
    "lib-credit-canary",
    "lib-tech-tilt-vol-target",
    "lib-discount-day-uptrend",
    *NEW_SCREENS,
)


def test_a_row_id_once_published_is_never_dropped_or_renamed():
    assert len(PUBLISHED) == len(set(PUBLISHED)) == 66 and not set(PUBLISHED) - shelf.IDS
    assert len(shelf.IDS) == len(shelf.LIBRARY)


def test_a_row_is_looked_up_by_id_before_anything_ran(stocked):
    out = shelf.rows(stocked, ["lib-harvest", "lib-average-down"])
    assert (out["lib-harvest"]["status"], out["lib-harvest"]["title"], out["lib-harvest"]["type"]) == ("waiting", "Tax-loss harvesting", "rule")
    assert out["lib-harvest"]["line"] is None and out["lib-harvest"]["backs"] is None and out["lib-average-down"]["status"] == "not_run"
    assert shelf.rows(stocked, []) == {}


def test_only_a_current_result_on_firm_ground_backs_a_step():
    base = {"status": "tested", "outdated": False, "thin_coverage": False, "leans_on_hindsight": False, "hindsight": False, "yardstick": False, "rule": None}
    verdicts = ("held_up", "within_noise", "fell_short", "inconclusive", None)
    assert [shelf._backs(base | {"verdict": v}) for v in verdicts] == ["yes", "no_edge", "no", None, None]
    for flag in ("outdated", "thin_coverage", "leans_on_hindsight", "hindsight", "yardstick"):
        assert shelf._backs(base | {"verdict": "held_up", flag: True}) is None
    assert shelf._backs(base | {"verdict": "held_up", "status": "waiting"}) is None
    rule = {"p5_pts": -1.0, "p50_pts": 0.4, "p95_pts": 2.0, "share_better": 0.7, "share_worse": 0.2}
    within = base | {"verdict": "within_noise"}
    assert shelf._backs(within | {"rule": rule}) == "yes"
    assert shelf._backs(within | {"rule": rule | {"share_better": 0.2, "share_worse": 0.7}}) == "no"
    assert shelf._backs(within | {"rule": rule | {"share_better": 0.4, "share_worse": 0.4}}) == "no_edge"
    assert shelf._backs(within | {"rule": rule | {"share_better": 0.4, "share_worse": None}}) == "no_edge"
    assert shelf._backs(within | {"rule": {"p5_pts": 0.0, "p50_pts": 0.02, "p95_pts": 0.04, "share_better": 0.9, "share_worse": 0.0}}) == "no_edge"
    assert shelf._backs(base | {"verdict": "fell_short", "rule": rule}) == "no" and shelf._backs(base | {"verdict": "held_up", "rule": rule}) == "yes"


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
    assert view["note"] == BAR and "cash" not in view["note"] and view["self_check"] == {"gap_pts": first["gap_pts"], "level": True}
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
    assert view["counts"]["yardstick"] == 0 and view["counts"]["outdated"] == 0 and view["note"] == BAR


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
    assert view["note"] == f"{BAR} {shelf.HINDSIGHT_NOTE}" and sum(r["hindsight"] for r in view["rows"]) == 1
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


# ---- Grammar added for the wider library ----


def test_a_market_wide_switch_sends_the_whole_strategy_to_cash(stocked):
    data = load(data_path(stocked))
    spec = parse(spec_of("lib-canary"), data)
    v = resolve(spec, {})
    assert [f[4] for f in spec.filters] == ["EEM", "AGG"]
    days = data.calendar[300::21]
    held = {d: pick(data, spec, v, d, set()) for d in days}
    assert {str(sorted(w.items())) for w in held.values()} == {"[]", "[('SPY', 1.0)]"}
    for d, w in held.items():
        up = [data.series[s].adj[data.series[s].index[d]] / data.series[s].adj[data.series[s].index[d] - 126] - 1 >= 0 for s in ("EEM", "AGG")]
        assert bool(w) == all(up)
    calm = parse(spec_of("lib-momentum-calm"), data)
    picks = [pick(data, calm, resolve(calm, {}), d, set()) for d in days]
    assert all(len(w) in (0, 3) for w in picks) and any(picks)
    with pytest.raises(SpecError, match="NOPE has no price history"):
        parse(spec_of("lib-canary") | {"filters": [{"metric_id": "ret", "window": "126d", "min": 0, "symbol": "NOPE"}]}, data)


def test_the_golden_cross_compares_the_50_day_average_with_the_long_one(stocked):
    data = load(data_path(stocked))
    s = data.series["SPY"]
    i = 600
    fast, slow = sum(s.adj[i - 49 : i + 1]) / 50, sum(s.adj[i - 199 : i + 1]) / 200
    assert sim.features.value("ma_cross", s, i, 200) == pytest.approx(fast / slow - 1)
    assert sim.features.value("ma_cross", s, i, 50) is None and sim.features.value("ma_cross", s, 150, 200) is None
    spec = parse(spec_of("lib-golden-cross"), data)
    for d in data.calendar[300::21]:
        above = sim.features.value("ma_cross", s, s.index[d], 200) >= 0
        assert bool(pick(data, spec, resolve(spec, {}), d, set())) == above


def test_a_volatility_target_only_ever_scales_down(stocked):
    data = load(data_path(stocked))
    raw = spec_of("lib-tech-tilt-vol-target")
    spec = parse(raw, data)
    plain = parse(raw | {"sizing": {"method": "fixed", "weights": raw["sizing"]["weights"]}}, data)
    assert spec.vol_target == 0.15 and plain.vol_target is None and "hotter than 15% a year" in spec.caveats[-1]
    totals = []
    for d in data.calendar[300::21]:
        full, scaled = pick(data, plain, resolve(plain, {}), d, set()), pick(data, spec, resolve(spec, {}), d, set())
        ratio = {round(scaled[k] / full[k], 9) for k in full}
        assert len(ratio) == 1 and 0 < ratio.pop() <= 1
        totals.append(sum(scaled.values()))
    assert max(totals) == pytest.approx(1.0) or max(totals) < 1.0
    hot = parse(raw | {"sizing": {"method": "fixed", "weights": raw["sizing"]["weights"], "vol_target": 0.02}}, data)
    d = data.calendar[400]
    w = pick(data, hot, resolve(hot, {}), d, set())
    rets = [
        sum(w[k] * (data.series[k].adj[data.series[k].index[d] - j] / data.series[k].adj[data.series[k].index[d] - j - 1] - 1) for k in w) for j in range(63)
    ]
    mean = sum(rets) / 63
    assert (sum((r - mean) ** 2 for r in rets) / 62 * 252) ** 0.5 == pytest.approx(0.02)
    with pytest.raises(SpecError, match="vol_target"):
        parse(raw | {"sizing": {"method": "fixed", "weights": raw["sizing"]["weights"], "vol_target": 5}}, data)


def test_single_stocks_over_the_cap_are_trimmed_and_the_rest_carries_the_difference(stocked):
    from desk.engine.lab.spec import cap_stocks

    assert cap_stocks({"A": 0.5, "B": 0.3, "F": 0.2}, {"A", "B"}, 0.1) == ({"A": 0.1, "B": 0.1, "F": pytest.approx(0.8)}, ["A", "B"])
    spread, names = cap_stocks({"A": 0.4, "B": 0.09, "F": 0.51}, {"A", "B"}, 0.1)
    assert names == ["A", "B"] and spread == {"A": 0.1, "B": 0.1, "F": pytest.approx(0.8)}
    assert cap_stocks({"A": 0.6, "B": 0.4}, {"A", "B"}, 0.1) == ({"A": 0.1, "B": 0.1}, ["A", "B"])
    assert cap_stocks({"F": 0.7, "G": 0.3}, set(), 0.1) == ({"F": 0.7, "G": 0.3}, [])
    data = load(data_path(stocked))
    raw = spec_of("lib-as-held-capped")
    capped = parse(raw, data)
    assert capped.weights == pytest.approx({"SPY": 0.5 + 0.2 * 0.5 / 0.7, "STK0": 0.1, "FTEC": 0.2 + 0.2 * 0.2 / 0.7}) and capped.rebalance == "Q"
    assert capped.caveats[0] == "STK0 trimmed to 10% each; the difference is spread across the other holdings in proportion." and HINDSIGHT in capped.caveats
    entry = next(e for e in shelf.LIBRARY if e["id"] == "lib-as-held-capped")
    assert entry["hindsight"] and local_only(raw) and shelf.request(entry, "2025-01-02T00:00:00+00:00")["spec"]["parent_id"] == shelf.HINDSIGHT_FAMILY
    with pytest.raises(SpecError, match="cap_stocks_pct"):
        parse(raw | {"universe": raw["universe"] | {"cap_stocks_pct": 0}}, data)


def test_a_yearly_refresh_falls_every_252_sessions_from_the_start_of_the_test(stocked):
    data = load(data_path(stocked))
    cal = data.calendar[320:1120]
    assert sorted(sim.signal_days(cal, "Y")) == [cal[251], cal[503], cal[755]]
    for sid in ("lib-ten-beaten", "lib-ten-largest"):
        spec = parse(spec_of(sid), data)
        res = simulate(data, spec, resolve(spec, {}), cal[0], cal[-1])
        assert spec.rebalance == "Y" and sorted({t[0] for t in res.trades}) == [cal[0], cal[252], cal[504], cal[756]] and res.rebalances == 4
    with pytest.raises(SpecError, match="weekly, monthly, quarterly or yearly"):
        parse(spec_of("lib-ten-beaten") | {"rebalance": "daily"}, data)


def test_company_size_is_the_list_float_moved_by_price_and_the_largest_are_picked(stocked):
    data = load(data_path(stocked))
    s = data.series["STK3"]
    value = sim.features.value
    assert data.size_base("STK3") == (4e9, "2013-06-28") and data.size_base("SPY") is None
    assert value("size", s, 500, 252, data.size_base("STK3")) == pytest.approx(4e9 * s.adj[500] / s.adj[0])
    assert value("size", s, 500, 252, (4e9, s.dates[100])) == pytest.approx(4e9 * s.adj[500] / s.adj[100])
    assert value("size", s, 50, 252, (4e9, s.dates[100])) is None and value("size", s, 500, 252, None) is None
    spec = parse(spec_of("lib-ten-largest") | {"entry": {"top_n": 3}}, data)
    assert spec.caveats == [ON_THE_LIST, PUBLIC_EXITS, SIZE_WORDS]
    day = data.calendar[700]
    size = {sym: SIZES[sym][0] * data.series[sym].adj[data.series[sym].index[day]] / data.series[sym].adj[0] for sym in STOCKS}
    assert pick(data, spec, resolve(spec, {}), day, set()) == {sym: pytest.approx(1 / 3) for sym in sorted(size, key=size.get)[-3:]}
    with pytest.raises(SpecError, match="size feature needs a screen universe"):
        parse(spec_of("lib-sector-momentum-12-1") | {"signals": [{"metric_id": "size", "window": "252d", "transform": "rank"}]}, data)
    del data.settings[PUBLIC_SIZES]
    with pytest.raises(SpecError, match="company sizes are not in the lab's data yet") as refused:
        parse(spec_of("lib-ten-largest"), data)
    assert shelf.plain([str(refused.value)]) == "Company sizes have not reached the lab yet. This runs the night after the next lab export."
    assert parse(spec_of("lib-ten-beaten"), data).rebalance == "Y"


def test_money_not_in_a_pick_waits_in_the_named_fund(stocked):
    data = load(data_path(stocked))
    raw = spec_of("lib-core-stock-picks")
    spec = parse(raw, data)
    v = resolve(spec, {})
    cal = data.calendar[600:800]
    picks = pick(data, spec, v, data.calendar[599], set())
    assert spec.idle == "SPY" and len(picks) == 5 and set(picks.values()) == {0.04}
    res = simulate(data, spec, v, cal[0], cal[-1])
    first = {t[1]: round(t[3] * t[4] / sim.START_CASH, 6) for t in res.trades if t[0] == cal[0]}
    assert first == {"SPY": 0.8} | dict.fromkeys(picks, 0.04)
    assert all(t[1] == "SPY" or t[1] in STOCKS for t in res.trades) and len({t[0] for t in res.trades}) == res.rebalances > 5
    never = raw | {"filters": [{"metric_id": "dd", "window": "252d", "max": -0.99}]}
    spec = parse(never, data)
    res = simulate(data, spec, resolve(spec, {}), cal[0], cal[-1])
    assert (res.trades[0][1], res.trades[0][2], round(res.trades[0][3] * res.trades[0][4] / sim.START_CASH, 6)) == ("SPY", "buy", 1.0)
    assert {t[1] for t in res.trades} == {"SPY"} and sum(t[3] * t[4] for t in res.trades[1:]) < 0.001 * sim.START_CASH
    spec = parse(never | {"sizing": "equal"}, data)
    assert spec.idle is None and simulate(data, spec, resolve(spec, {}), cal[0], cal[-1]).trades == []
    with pytest.raises(SpecError, match="sizing idle must be a fund with price history in the lab; STK1 is not"):
        parse(raw | {"sizing": {"method": "equal", "idle": "STK1"}}, data)
    mix = spec_of("lib-60-40")
    with pytest.raises(SpecError, match="idle cannot be combined with fixed weights"):
        parse(mix | {"sizing": mix["sizing"] | {"idle": "SPY"}}, data)


def test_a_holding_bought_for_a_fixed_time_is_left_alone_until_the_time_is_up(stocked):
    data = load(data_path(stocked))
    raw = spec_of("lib-stock-dip-hold") | {"filters": [{"metric_id": "dd", "window": "252d", "max": -0.15}]}
    spec = parse(raw, data)
    v = resolve(spec, {})
    cal = data.calendar[520:1800]
    assert v.hold_days == 252 and spec.exit == {"hold_rank": None, "hold_days": 252}
    res = simulate(data, spec, v, cal[0], cal[-1])
    at = {d: i for i, d in enumerate(cal)}
    by = {sym: [(at[t[0]], t[2]) for t in res.trades if t[1] == sym] for sym in STOCKS}
    buys = [(i, later) for moves in by.values() for n, (i, side) in enumerate(moves) if side == "buy" for later, _ in moves[n + 1 : n + 2]]
    assert buys and all(later - i >= 252 for i, later in buys)
    assert any(side == "sell" for moves in by.values() for _, side in moves) and any(i > 0 for moves in by.values() for i, _ in moves)
    assert {t[1] for t in res.trades} - set(STOCKS) == {"SPY"}
    held = pick(data, spec, v, cal[300], {"STK1", "SPY"}, {"STK1": cal[100]})
    assert held["STK1"] is None and "SPY" not in held
    assert pick(data, spec, v, cal[400], {"STK1", "SPY"}, {"STK1": cal[100]}).get("STK1", 0.0) is not None
    tight = parse(raw | {"entry": {"top_n": 2}, "sizing": "equal", "account": "ira"}, data)
    res = simulate(data, tight, resolve(tight, {}), cal[0], cal[-1])
    assert len(res.trades) > 4 and res.cash >= -res.costs - 1 and res.taxes == 0
    for exit_, words in (
        ({"hold_days": 252, "hold_rank": 5}, "cannot go with hold_rank"),
        ({"hold_days": 5}, "from 21 to 1260"),
        ({"hold_days": True}, "whole number of trading days"),
    ):
        with pytest.raises(SpecError, match=words):
            parse(raw | {"exit": exit_}, data)
    with pytest.raises(SpecError, match="hold_days needs signals to pick from"):
        parse(spec_of("lib-60-40") | {"exit": {"hold_days": 252}}, data)


def test_the_four_new_screens_run_on_the_public_stock_list_and_report_against_the_sp500(stocked, monkeypatch):
    cfg = stocked
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in NEW_SCREENS))
    monkeypatch.setattr(shelf, "IDS", frozenset(NEW_SCREENS))
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    rows = {r["id"]: r for r in shelf.view(cfg)["rows"]}
    assert set(rows) == set(NEW_SCREENS)
    for row in rows.values():
        assert row["status"] == "tested" and row["kind"] == "practical" and row["benchmark"] == shelf.SPY and row["caveats"][:2] == [ON_THE_LIST, PUBLIC_EXITS]
        assert row["verdict"] in ("held_up", "within_noise", "fell_short") and "S&P 500 (SPY)" in row["line"] and not row["leans_on_hindsight"]
    assert SIZE_WORDS in rows["lib-ten-largest"]["caveats"] and SIZE_WORDS not in rows["lib-ten-beaten"]["caveats"]


def test_every_row_says_what_it_is_measured_against_and_the_note_says_how_the_luck_bar_counts(stocked, monkeypatch):
    cfg = stocked
    view = shelf.view(cfg)
    assert view["note"] == shelf.NOTE and "Each row names what it is measured against" in shelf.NOTE
    assert all(r["benchmark"] and r["benchmark_words"] == shelf.BENCH_WORDS[r["benchmark"]] and r["benchmark_words"].endswith(".") for r in view["rows"])
    legend = {b["name"]: b for b in view["benchmarks"]}
    assert sum(b["rows"] for b in view["benchmarks"]) == len(shelf.LIBRARY) and legend[shelf.SPY]["rows"] > len(shelf.LIBRARY) / 2
    assert legend[shelf.SPY]["words"] == "The S&P 500 index fund SPY, bought and held with dividends reinvested."
    ids = ("lib-three-fund", "lib-asset-momentum")
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ids))
    monkeypatch.setattr(shelf, "IDS", frozenset(ids))
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    after = shelf.view(cfg)
    assert after["trials"] == 3 and after["note"] == f"{shelf.NOTE} {shelf.BAR_NOTE.format(trials=3)}"
    assert "all 3 variants tried across the library" in after["note"] and {r["noise"]["trials"] for r in after["rows"]} == {3}


def restamp(cfg, change):
    conn = sqlite3.connect(shelf.ledger_path(cfg))
    with conn:
        for sid, body in conn.execute("SELECT strategy_id, body FROM lab_results").fetchall():
            old = json.loads(body)
            change(old)
            conn.execute("UPDATE lab_results SET body=? WHERE strategy_id=?", (json.dumps(old), sid))
    conn.close()


def before_the_public_list(body):
    body.pop(PUBLIC_COVERAGE, None)
    body["caveats"] = [c for c in body.get("caveats") or [] if c not in (ON_THE_LIST, PUBLIC_EXITS)]


def test_stock_screen_rows_say_what_list_they_ran_on_and_only_a_result_from_before_it_leans_on_hindsight(stocked, monkeypatch):
    cfg = stocked
    data = load(data_path(cfg))
    screens = [e["id"] for e in shelf.LIBRARY if (e.get("spec") or {}).get("universe", {}).get("type") == "screen"]
    assert len(screens) == 10
    for sid in screens:
        spec = parse(spec_of(sid), data)
        assert spec.caveats[:2] == [ON_THE_LIST, PUBLIC_EXITS] and SCREEN_HINDSIGHT not in spec.caveats and "survivorship" not in " ".join(spec.caveats)
        assert spec.start == "2014-01-02"
    assert ON_THE_LIST not in parse(spec_of("lib-three-fund"), data).caveats
    ids = ("lib-stock-momentum", "lib-three-fund")
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ids))
    monkeypatch.setattr(shelf, "IDS", frozenset(ids))
    waiting = {r["id"]: r for r in shelf.view(cfg)["rows"]}["lib-stock-momentum"]
    assert not waiting["leans_on_hindsight"] and not waiting["thin_coverage"] and not waiting["research_only"]
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    rows = {r["id"]: r for r in shelf.view(cfg)["rows"]}
    screen, mix = rows["lib-stock-momentum"], rows["lib-three-fund"]
    assert screen["status"] == "tested" and screen["caveats"][:2] == [ON_THE_LIST, PUBLIC_EXITS] and not screen["leans_on_hindsight"]
    assert not screen["thin_coverage"] and "wipe" not in PUBLIC_EXITS and "last price" in PUBLIC_EXITS
    assert "hindsight" not in screen["line"] and "S&P 500 (SPY)" in screen["line"] and not screen["research_only"]
    restamp(cfg, before_the_public_list)
    rows = {r["id"]: r for r in shelf.view(cfg)["rows"]}
    screen, mix = rows["lib-stock-momentum"], rows["lib-three-fund"]
    assert screen["leans_on_hindsight"] and screen["caveats"][0] == SCREEN_HINDSIGHT and screen["caveats"].count(SCREEN_HINDSIGHT) == 1
    assert screen["line"].endswith(shelf.LEAN_WORDS) and "S&P 500 (SPY)" in screen["line"]
    assert not mix["leans_on_hindsight"] and SCREEN_HINDSIGHT not in mix["caveats"] and "hindsight" not in mix["line"]


def test_a_screen_can_read_held_up_only_on_a_well_covered_public_list(stocked, monkeypatch):
    cfg = stocked
    ids = ("lib-stock-momentum", "lib-three-fund")
    monkeypatch.setattr(shelf, "LIBRARY", tuple(e for e in shelf.LIBRARY if e["id"] in ids))
    monkeypatch.setattr(shelf, "IDS", frozenset(ids))
    shelf.queue_missing(cfg, now=NOW)
    process_queue(cfg, now=NOW)
    won = {
        "verdict": "held_up",
        "line": "Beat S&P 500 (SPY) by 6.1 points a year over 6 years out of sample, more than the 4.0 luck allows across the 3 variants tried.",
    }
    monkeypatch.setattr(shelf, "_experiment", lambda *a, **k: dict(won))
    view = shelf.view(cfg)
    rows = {r["id"]: r for r in view["rows"]}
    assert rows["lib-stock-momentum"]["verdict"] == "held_up" and rows["lib-stock-momentum"]["line"] == won["line"] and view["counts"]["held_up"] == 2
    restamp(cfg, lambda body: body.update({PUBLIC_COVERAGE: COVERED | {"priced": 7, "missing": 1, "pct": 87.5, "enough": False}}))
    view = shelf.view(cfg)
    rows = {r["id"]: r for r in view["rows"]}
    screen, mix = rows["lib-stock-momentum"], rows["lib-three-fund"]
    assert screen["verdict"] == "within_noise" and screen["thin_coverage"] and screen["research_only"] and not screen["leans_on_hindsight"]
    assert screen["line"] == (
        "Ahead, but too little of the stock list has prices: beat S&P 500 (SPY) by 6.1 points a year over 6 years out of sample, more than the 4.0 luck "
        "allows across the 3 variants tried. Not counted as held up until 90% of the list is priced."
    )
    assert mix["verdict"] == "held_up" and not mix["thin_coverage"] and view["counts"]["held_up"] == 1
    restamp(cfg, before_the_public_list)
    view = shelf.view(cfg)
    rows = {r["id"]: r for r in view["rows"]}
    screen, mix = rows["lib-stock-momentum"], rows["lib-three-fund"]
    assert screen["verdict"] == "within_noise" and mix["verdict"] == "held_up" and view["counts"]["held_up"] == 1
    assert screen["line"] == (
        "Ahead, but it leans on hindsight: beat S&P 500 (SPY) by 6.1 points a year over 6 years out of sample, more than the 4.0 luck allows "
        "across the 3 variants tried. Not counted as held up, because the stock list is small and includes names you hold or held."
    )
    assert mix["line"] == won["line"] and shelf.ready(cfg).endswith("1 held up out of sample")


def test_a_screen_waits_while_the_list_loads_and_a_result_from_mid_load_runs_again_the_next_night(stocked):
    cfg = stocked
    path = data_path(cfg)

    def cover(**change):
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(COVERED | change), PUBLIC_COVERAGE))
        conn.close()
        return load(path)

    raw = spec_of("lib-stock-momentum")
    with pytest.raises(SpecError, match="still loading its prices: 3 of 8 are in and 5 are on the way") as loading:
        parse(raw, cover(priced=3, loading=5, pct=37.5, enough=False))
    with pytest.raises(SpecError, match="has no prices in the lab yet") as empty:
        parse(raw, cover(priced=0, loading=8, pct=0.0, enough=False))
    still = "The public stock list is still loading its prices. This runs once that finishes."
    assert shelf.plain(loading.value.problems) == shelf.plain(empty.value.problems) == still
    thin = parse(raw, cover(priced=6, missing=2, pct=75.0, enough=False))
    assert thin.caveats[0] == (
        "Tested on the 8 largest US companies of mid-2013, a list that owes nothing to what you hold. 6 of them have prices. "
        "The 2 without were mostly bought or failed, so the result still leans to survivors by that much. "
        "That is under 90%, so this stays research only."
    )
    nearly = parse(raw, cover(listed=200, priced=187, loading=4, missing=9, pct=93.5))
    assert nearly.caveats[0] == (
        "Tested on the 200 largest US companies of mid-2013, a list that owes nothing to what you hold. 187 of them have prices. "
        "4 more are still loading. The 9 without were mostly bought or failed, so the result still leans to survivors by that much."
    )
    entry = next(e for e in shelf.LIBRARY if e["id"] == "lib-stock-momentum")
    seen = {"kind": "experiment", "rev": shelf.SCREEN_REV, "result_at": "2026-11-13T06:10:00+00:00", "loading": 4, "body": None}
    assert not shelf._due(entry, seen, datetime(2026, 11, 13, 18, 30, tzinfo=UTC), set())
    assert shelf._due(entry, seen, datetime(2026, 11, 14, 5, 55, tzinfo=UTC), set())
    assert not shelf._due(entry, seen | {"loading": 0}, datetime(2026, 11, 14, 5, 55, tzinfo=UTC), set())


def test_the_library_grew_and_each_kind_names_its_new_rows():
    by = {e["id"]: e for e in shelf.LIBRARY}
    assert len(shelf.LIBRARY) == 66 and len(by) == 66
    new = {
        "classic": ("lib-three-fund", "lib-permanent", "lib-all-weather", "lib-trend-five", "lib-golden-cross", "lib-asset-momentum")
        + ("lib-equal-sectors", "lib-equal-weight-500", "lib-dividend-growers", "lib-small-value-fund", "lib-value-momentum", "lib-small-reversal"),
        "practical": ("lib-core-satellite", "lib-themes-equal", "lib-as-held-capped", "lib-margin-paydown", *NEW_SCREENS),
        "novel": ("lib-momentum-calm", "lib-drawdown-stop", "lib-down-week", "lib-canary", "lib-credit-canary", "lib-tech-tilt-vol-target")
        + ("lib-discount-day-uptrend",),
    }
    assert all(by[sid]["kind"] == kind for kind, ids in new.items() for sid in ids)
    assert [e["id"] for e in shelf.LIBRARY if e.get("hindsight")] == ["lib-as-held", "lib-as-held-capped"]
    assert all(local_only(e["spec"]) for e in shelf.LIBRARY if e.get("hindsight"))


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


def test_stock_screens_are_run_again_on_the_public_stock_list():
    screens = {e["id"] for e in shelf.LIBRARY if e["rev"] == shelf.SCREEN_REV}
    assert screens == {e["id"] for e in shelf.LIBRARY if e["type"] == "experiment" and e["spec"]["universe"].get("type") == "screen"}
    assert len(screens) == 10 and shelf.SCREEN_REV == 5 > shelf.MIX_REV
    for rev in (shelf.MIX_REV, 4):
        seen = {"kind": "experiment", "rev": rev, "result_at": "2026-11-12T05:56:00+00:00", "body": None}
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
    from desk.engine.lab.data import LISTED_FUNDS, PUBLIC_FUNDS

    known = set(LISTED_FUNDS) | PUBLIC_FUNDS
    for entry in shelf.LIBRARY:
        body, spec = entry.get("body") or {}, entry.get("spec") or {}
        weights = (spec.get("sizing") or {}).get("weights") if isinstance(spec.get("sizing"), dict) else None
        named = (spec.get("universe") or {}).get("symbols") or []
        switches = [f["symbol"] for f in spec.get("filters") or [] if f.get("symbol")]
        for mix in (weights, body.get("mix"), body.get("mix_without_plan"), named, switches):
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
