import json
from datetime import UTC, datetime

from desk.agents import console, store
from desk.agents.adapter import FakeAdapter
from desk.agents.sources import RealLab
from desk.agents.strategy import queue_reviews, run_strategy_desk
from desk.engine import lab
from desk.engine.lab.runner import process_queue
from tests.agents.agent_fakes import FakeDecisions
from tests.engine.test_lab import SPEC, write_lab_db
from tests.engine.test_rules import rules_lab

GRID = {"top_n": [1, 3], "lookback": [63, 126]}


def ask_lab(prompt_fn):
    def answer(prompt):
        return prompt_fn(json.loads(prompt.split("\n\n", 1)[1]))

    return FakeAdapter({"strategy": answer})


def experiment(body, spec=SPEC):
    assert body["grammar"]["entry"] and {f["metric_id"] for f in body["features"]} >= {"ret", "vol"}
    exp = {"spec": spec, "grid": GRID, "date_range": {"start": "2012-01-02", "end": "2024-12-31"}, "seed": 7, "trial_budget": 50}
    return {"summary": "Queued.", "memo": "Testing sector momentum.", "action": "experiment", "experiment": exp}


def test_strategy_desk_round_trip_through_the_real_lab(cfg):
    write_lab_db(cfg)
    report = run_strategy_desk(cfg, question="Does sector momentum beat the plan?", lab=RealLab(), decisions=FakeDecisions(), adapter=ask_lab(experiment))
    assert report.status == "ok" and report.queued
    assert [d["status"] for d in process_queue(cfg, now=datetime.now(UTC))["done"]] == ["experiment"]

    made = [store.get_request(cfg, r) for r in queue_reviews(cfg, RealLab())]
    assert [(r["desk"], r["symbol"]) for r in made] == [("strategy", "sector-momentum")]
    seen = {}

    def review(body):
        seen.update(body["lab_result"])
        return {"summary": "Done tuning.", "memo": "Finalizing v1.", "action": "finalize", "finalize": {"strategy_id": "sector-momentum", "version": 1}}

    store.requeue(cfg, made[0]["id"], "run now")
    console.process_queue(cfg, now_only=False, lab=RealLab(), decisions=FakeDecisions(), adapter=ask_lab(review))
    assert seen["status"] == "lab" and seen["folds"] and seen["tear_sheet"]["trials_family"] == 4 and "grammar" not in seen
    assert [d["status"] for d in process_queue(cfg, now=datetime.now(UTC))["done"]] == ["finalize"]
    assert lab.desk_view(cfg, "sector-momentum")["final"]["verdict"] in ("pass", "fail", "inconclusive")


def test_a_rejected_spec_comes_back_with_reasons(cfg):
    write_lab_db(cfg)
    bad = SPEC | {"id": "pick-nvda", "universe": {"type": "fund_list", "symbols": ["NVDA"]}}
    run_strategy_desk(cfg, question="NVDA only?", lab=RealLab(), decisions=FakeDecisions(), adapter=ask_lab(lambda b: experiment(b, bad)))
    assert [d["status"] for d in process_queue(cfg, now=datetime.now(UTC))["done"]] == ["rejected"]
    req = store.get_request(cfg, queue_reviews(cfg, RealLab())[0])
    assert "rejected" in req["question"]
    seen = {}
    run_strategy_desk(
        cfg,
        strategy_id="pick-nvda",
        lab=RealLab(),
        decisions=FakeDecisions(),
        adapter=ask_lab(lambda b: seen.update(b) or {"summary": "", "memo": "", "action": "none"}),
    )
    assert seen["lab_result"]["rejected"]


def test_rule_question_round_trip(cfg):
    rules_lab(cfg)

    def ask(body):
        assert body["grammar"]["rule"]["rules"]["rebalance_band"] == ["band_pts"]
        rule = {"id": "band-test", "rule": "rebalance_band", "params": {"band_pts": [3, 10]}, "horizons": [5, 10]}
        return {"summary": "Testing bands.", "memo": "Comparing bands.", "action": "rule", "rule": rule}

    run_strategy_desk(cfg, question="Is a 5 point band right?", lab=RealLab(), decisions=FakeDecisions(), adapter=ask_lab(ask))
    assert [d["status"] for d in process_queue(cfg, now=datetime.now(UTC))["done"]] == ["rule"]
    req = store.get_request(cfg, queue_reviews(cfg, RealLab())[0])
    assert req["symbol"] == "band-test" and "Rule test" in req["question"]
    seen = {}
    run_strategy_desk(
        cfg,
        strategy_id="band-test",
        lab=RealLab(),
        decisions=FakeDecisions(),
        adapter=ask_lab(lambda b: seen.update(b) or {"summary": "", "memo": "", "action": "none"}),
    )
    assert seen["lab_result"]["kind"] == "rule" and seen["lab_result"]["rule"]["baseline"]
