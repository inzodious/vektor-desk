import json
import random
import sqlite3

import pytest

from desk.engine import lab
from desk.engine.lab import rulebook as rules
from desk.engine.lab.data import EXPORT_SCHEMA, PLAN_FILE, data_path, load
from desk.engine.lab.runner import process_queue
from tests.engine.test_lab import NOW, queue, weekdays

VERDICTS = ("helps", "hurts", "no_clear_edge", "inconclusive")


def rules_lab(cfg, start="2010-01-04", end="2024-12-31"):
    rng = random.Random(9)
    days = weekdays(start, end)
    path = data_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    a = b = 100.0
    rows = []
    for d in days:
        a *= 1 + 0.0003 + rng.gauss(0, 0.006)
        shock = -0.004 if "2015-01" <= d[:7] <= "2015-12" or "2020-02" <= d[:7] <= "2020-04" else 0.0006
        b *= 1 + shock + rng.gauss(0, 0.012)
        rows += [("AAA", d, a, a, a, 1e6), ("BBB", d, b, b, b, 1e6)]
    conn.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO symbols VALUES (?, 'fund', 'plan', ?, ?)", [("AAA", days[0], days[-1]), ("BBB", days[0], days[-1])])
    path.with_name(PLAN_FILE).write_text(json.dumps({"weights": {"AAA": 0.6, "BBB": 0.4}}))
    conn.execute("INSERT INTO settings VALUES ('marginal_rate_pct', '24')")
    conn.commit()
    conn.close()
    return load(path)


def test_rule_requests_are_checked(cfg):
    data = rules_lab(cfg, start="2023-01-02", end="2023-03-31")
    cases = [
        ({"id": "x", "rule": "market_timing"}, "rule must be one of"),
        ({"id": "x", "rule": "margin", "params": {"dip_pct": 20, "borrow_pct": 10, "rate_pct": [6, 8]}}, "fact, not a dial"),
        ({"id": "x", "rule": "margin", "params": {"dip_pct": 20}}, "needs params.borrow_pct"),
        ({"id": "x", "rule": "harvest", "params": {"threshold_usd": 500}, "account": "HSA"}, "taxable account"),
        ({"id": "x", "rule": "rebalance_band", "params": {"band_pts": 5}, "mix": {"AAA": 0.5, "NVDA": 0.5}}, "no bars"),
        ({"id": "x", "rule": "rebalance_band", "params": {"band_pts": list(range(1, 15))}}, "grid cap"),
        ({"id": "x", "rule": "rebalance_band", "params": {"band_pts": 90}}, "between"),
    ]
    for raw, words in cases:
        with pytest.raises(rules.RuleError) as e:
            rules.parse(raw, data)
        assert words in str(e.value)
    rule = rules.parse({"id": "x", "rule": "rebalance_band", "params": {"band_pts": [3, 10]}}, data)
    assert rule.mix == {"AAA": 0.6, "BBB": 0.4} and [v["band_pts"] for v in rule.variants] == [3.0, 10.0] and rule.taxable


def test_baseline_never_sells_and_pays_tax_once_at_the_end(cfg):
    data = rules_lab(cfg)
    rule = rules.parse({"id": "x", "rule": "deposit_steering"}, data)
    base = rules._baseline(data, rule, "2016-01-04", "2019-12-31", 0.24)
    assert base.contributed == 10_000 + 1_000 * 47
    assert base.taxes > 0 and base.after_liq < base.equity[-1] and base.interest == 0 and base.margin_calls == 0
    assert base.trades == 2 * 48 + 2


def test_rebalance_band_runs_every_start_month(cfg):
    data = rules_lab(cfg)
    body = rules.evaluate(data, rules.parse({"id": "band", "rule": "rebalance_band", "params": {"band_pts": [2, 25]}, "horizons": [5]}, data))
    tight, loose = body["variants"]
    assert body["windows"]["holdout_start"] == "2022-12-31" and body["trials"] == 2
    assert tight["horizons"][0]["starts"] == 96 and tight["full"]["turnover_per_year"] > loose["full"]["turnover_per_year"]
    assert tight["full_diff_pts"] != 0 and tight["full"]["taxes"] != loose["full"]["taxes"]
    assert loose["full_diff_pts"] == pytest.approx(0.0, abs=1e-9)
    assert tight["verdict"] in VERDICTS and body["verdict"] in VERDICTS and body["best"] in ({"band_pts": 2.0}, {"band_pts": 25.0})


def test_harvest_books_losses_and_the_ordinary_offset(cfg):
    data = rules_lab(cfg)
    rule = rules.parse({"id": "h", "rule": "harvest", "params": {"threshold_usd": 300}, "horizons": [5]}, data)
    out = rules.simulate(data, rule, rule.variants[0], "2014-06-02", "2016-06-30", rate=0.24)
    base = rules._baseline(data, rule, "2014-06-02", "2016-06-30", 0.24)
    assert out.harvested > 300 and out.benefits > 0 and base.harvested == 0
    assert out.contributed == base.contributed


def test_margin_borrows_in_a_dip_and_pays_interest(cfg):
    data = rules_lab(cfg)
    rule = rules.parse({"id": "m", "rule": "margin", "params": {"dip_pct": 8, "borrow_pct": 20, "rate_pct": 9}, "horizons": [5]}, data)
    out = rules.simulate(data, rule, rule.variants[0], "2014-06-02", "2017-06-30", rate=0.24)
    base = rules._baseline(data, rule, "2014-06-02", "2017-06-30", 0.24)
    assert out.interest > 0 and base.interest == 0 and out.contributed == base.contributed


def test_paying_the_debit_first_is_measured_against_leaving_it(cfg):
    data = rules_lab(cfg)
    raw = {"id": "p", "rule": "paydown", "params": {"debit_pct": 10, "rate_pct": 12}, "horizons": [5], "mix": {"AAA": 1.0}}
    rule = rules.parse(raw, data)
    assert rule.variants == [{"debit_pct": 10.0, "rate_pct": 12.0}] and any("same margin debit" in c for c in rule.caveats)
    out = rules.simulate(data, rule, rule.variants[0], "2014-06-02", "2017-06-30", rate=0.24)
    base = rules._baseline(data, rule, "2014-06-02", "2017-06-30", 0.24)
    assert out.contributed == base.contributed and 0 < out.interest < base.interest
    assert base.interest > 0.12 * 1000 * 3 and out.interest < 0.12 * 1000 / 12 + 1
    free = rules.parse(raw | {"params": {"debit_pct": 10, "rate_pct": 0}}, data)
    costless = rules.simulate(data, free, free.variants[0], "2014-06-02", "2017-06-30", rate=0.24)
    kept = rules._baseline(data, free, "2014-06-02", "2017-06-30", 0.24)
    assert costless.interest == kept.interest == 0 and kept.after_liq > costless.after_liq
    body = rules.evaluate(data, rule)
    assert body["trials"] == 1 and body["baseline"]["description"].startswith("Same starting debit") and body["verdict"] in ("helps", "hurts", "no_clear_edge")
    with pytest.raises(rules.RuleError, match="a fact, not a dial"):
        rules.parse(raw | {"params": {"debit_pct": [10, 20], "rate_pct": 12}}, data)
    with pytest.raises(rules.RuleError, match="needs params.debit_pct"):
        rules.parse(raw | {"params": {"rate_pct": 12}}, data)


def test_rule_queue_view_and_api(cfg, app_client):
    rules_lab(cfg)
    queue(cfg, {"request": "rule", "id": "steer", "rule": "deposit_steering", "horizons": [5, 10], "model": "m"}, "001-rule.json")
    queue(cfg, {"request": "rule", "id": "bad", "rule": "lottery"}, "002-rule.json")
    done = process_queue(cfg, now=NOW)["done"]
    assert [d["status"] for d in done] == ["rule", "rejected"]
    view = lab.desk_view(cfg, "steer")
    assert view["kind"] == "rule" and view["status"] in VERDICTS
    body = view["rule"]
    assert {h["years"] for h in body["variants"][0]["horizons"]} == {5, 10} and body["baseline"]["full"]["contributed"] > 0
    assert lab.desk_view(cfg, "bad")["rejected"]
    client = app_client(packages=["engine"])
    listed = client.get("/api/lab/strategies").json()
    assert [r["id"] for r in listed["rules"]] == ["steer"] and listed["grammar"]["rule"]["rules"]["margin"] == ["dip_pct", "borrow_pct", "rate_pct"]
    assert client.get("/api/lab/strategies/steer").json()["kind"] == "rule"
