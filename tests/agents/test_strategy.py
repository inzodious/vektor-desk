import json
from dataclasses import dataclass, field

from desk.agents import briefs, console, store
from desk.agents.adapter import FakeAdapter
from desk.agents.jobs import JOBS
from desk.agents.pipeline import run_proposal_desk
from desk.agents.sources import NotReady
from desk.agents.strategy import queue_dir, queue_reviews, run_strategy_desk
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer, proposal

SPEC = {
    "id": "value-momentum-etf",
    "version": 1,
    "parent_id": None,
    "title": "Cheap sectors with momentum",
    "hypothesis": "Sector funds that are cheap and trending outperform the plan mix.",
    "predicted_effect": "+1.5 points a year over 10 years",
    "universe": {"type": "fund_list", "rule": "US sector ETFs listed before each start date"},
    "signals": [{"metric_id": "ret", "window": "126d", "transform": "rank"}],
    "entry": "top 3 by rank",
    "exit": "falls out of top 5",
    "rebalance": "monthly",
    "sizing": "equal",
    "params": {"top_n": {"min": 2, "max": 5}},
    "constraints": {"long_only": True, "margin": False, "max_position_pct": 35, "max_turnover": 4},
    "success_criteria": {"excess_vs_plan_pts": 1.0, "max_drawdown_pct": 35},
    "horizons": [5, 10],
}


@dataclass
class FakeLab:
    ready: bool = True
    views: dict = field(default_factory=dict)
    pending: list = field(default_factory=list)
    eligible_rows: list = field(default_factory=list)

    def _check(self):
        if not self.ready:
            raise NotReady("lab not built")

    def grammar(self):
        self._check()
        return {"sizing": "equal, inverse_vol or rank"}

    def features(self, cfg):
        self._check()
        return [{"metric_id": "ret", "window_options": ["21d", "126d"], "transforms": ["rank"], "description": "total return"}]

    def desk_view(self, cfg, strategy_id):
        self._check()
        return self.views.get(strategy_id, {"strategy_id": strategy_id, "folds": [], "tear_sheet": None})

    def pending_reviews(self, cfg):
        self._check()
        return self.pending

    def eligible(self, cfg):
        self._check()
        return self.eligible_rows


def experiment_answer(**over):
    exp = {"spec": SPEC, "grid": {"top_n": [2, 3, 4]}, "date_range": {"start": "2014-01-01", "end": "2024-12-31"}, "seed": 7, "trial_budget": 50}
    return {
        "summary": "Queued a sector test.",
        "memo": "Testing whether cheap, trending sectors beat the plan.",
        "action": "experiment",
        "experiment": exp,
    } | over


def test_strategy_schema_forbids_margin_and_requires_grid():
    schema = briefs.schema_file("strategy")
    exp = schema["properties"]["experiment"]
    assert "grid" in exp["required"]
    assert exp["properties"]["spec"]["properties"]["constraints"]["properties"]["margin"] == {"const": False}


def test_experiment_is_queued_with_runner_provenance(cfg):
    fake = FakeAdapter({"strategy": experiment_answer(experiment=experiment_answer()["experiment"] | {"written_at": "1999", "model": "fake"})})
    report = run_strategy_desk(cfg, question="Do cheap trending sectors win?", lab=FakeLab(), decisions=FakeDecisions(), adapter=fake)
    assert report.status == "ok" and report.queued.parent == queue_dir(cfg)
    assert report.queued.name.endswith("-value-momentum-etf-v1-experiment.json")
    body = json.loads(report.queued.read_text())
    assert body["request"] == "experiment" and body["grid"] == {"top_n": [2, 3, 4]}
    assert (body["desk"], body["model"], body["effort"], body["run_id"]) == ("strategy", "opus", "xhigh", report.outcome.run_id)
    assert body["written_at"] != "1999"
    assert not list(queue_dir(cfg).glob(".*.tmp"))
    prompt = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert prompt["features"][0]["metric_id"] == "ret" and prompt["lab_result"] is None
    assert prompt["grammar"]["sizing"].startswith("equal")


def test_finalize_only_for_the_strategy_under_review(cfg):
    lab = FakeLab(views={"value-momentum-etf": {"strategy_id": "value-momentum-etf", "folds": [{"fold": 1, "excess": 0.4}], "tear_sheet": None}})
    good = {"summary": "Done tuning.", "memo": "Finalizing.", "action": "finalize", "finalize": {"strategy_id": "value-momentum-etf", "version": 2}}
    report = run_strategy_desk(cfg, strategy_id="value-momentum-etf", lab=lab, decisions=FakeDecisions(), adapter=FakeAdapter({"strategy": good}))
    assert json.loads(report.queued.read_text())["request"] == "finalize"
    wrong = good | {"finalize": {"strategy_id": "other", "version": 1}}
    report = run_strategy_desk(cfg, strategy_id="value-momentum-etf", lab=lab, decisions=FakeDecisions(), adapter=FakeAdapter({"strategy": wrong}))
    assert report.queued is None and "nothing queued" in report.note


def test_strategy_not_ready_and_yaml_switch(cfg):
    assert run_strategy_desk(cfg, question="x", lab=FakeLab(ready=False), decisions=FakeDecisions(), adapter=FakeAdapter()).status == "not_ready"
    off = FakeDecisions(profile_data={"agents": {"enabled": True, "desks": {"strategy": False}}})
    assert run_strategy_desk(cfg, question="x", lab=FakeLab(), decisions=off, adapter=FakeAdapter()).status == "disabled"


def test_lab_reviews_queue_one_request_each(cfg):
    pending = [
        {"strategy_id": "value-momentum-etf", "version": 1, "kind": "experiment", "result_at": "2026-11-08T06:00:00Z"},
        {"strategy_id": "value-momentum-etf", "version": 1, "kind": "finalize", "result_at": "2026-11-08T06:00:00Z"},
        {"strategy_id": "low-vol", "version": 1, "kind": "rejected", "result_at": "2026-11-08T06:00:00Z"},
    ]
    lab = FakeLab(pending=pending)
    made = queue_reviews(cfg, lab)
    assert len(made) == 3 and queue_reviews(cfg, lab) == []
    req, fin, bounced = (store.get_request(cfg, r) for r in made)
    assert (req["desk"], req["symbol"], req["source"], req["run_now"]) == ("strategy", "value-momentum-etf", "lab", 0)
    assert "finalized" in fin["question"] and "fix the request" in bounced["question"]
    assert queue_reviews(cfg, FakeLab(ready=False)) == []


def test_console_routes_strategy_requests(cfg):
    rid = console.ask(cfg, "strategy", "Test a low-volatility tilt.", run_now=True)
    fake = FakeAdapter({"strategy": experiment_answer()})
    tally = console.process_queue(cfg, now_only=True, lab=FakeLab(), decisions=FakeDecisions(), adapter=fake)
    assert tally.done == 1
    row = store.get_request(cfg, rid)
    assert "Sent to the lab as" in row["answer"] and "Testing whether" in row["answer"]


def test_scout_sees_eligible_strategies_and_gets_a_skeptic(cfg):
    buy = proposal(
        kind="buy", bear_case="Theme could fade.", sources=[{"url": "https://www.sec.gov/x", "title": "x"}, {"url": "https://example.com/y", "title": "y"}]
    )
    lab = FakeLab(eligible_rows=[{"strategy_id": "value-momentum-etf", "title": "Cheap sectors", "summary": "passed"}])
    fake = FakeAdapter({"scout": answer(buy), "skeptic": {"verdict": "pass", "counter_case": "Small, inside the cap."}})
    report = run_proposal_desk(cfg, "scout", engine=FakeEngine(SLICE), decisions=FakeDecisions(), adapter=fake, lab=lab)
    prompt = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert prompt["eligible_strategies"][0]["strategy_id"] == "value-momentum-etf"
    assert report.skeptic == [{"verdict": "pass", "counter_case": "Small, inside the cap."}]
    empty = run_proposal_desk(
        cfg, "scout", engine=FakeEngine(SLICE), decisions=FakeDecisions(), adapter=FakeAdapter({"scout": answer()}), lab=FakeLab(ready=False), trigger="console"
    )
    assert empty.status == "ok"


def test_all_desks_live_and_lab_job():
    assert ("30 6 * * *", "python -m desk.agents lab-reviews") in JOBS
    assert ("0 3 * * 0", "python -m desk.agents run scout") in JOBS
    assert not any(c.endswith("run strategy") for _, c in JOBS)


def test_rule_requests_are_queued_without_a_version(cfg):
    rule = {"id": "band-test", "rule": "rebalance_band", "params": {"band_pts": [3, 5, 10]}, "horizons": [5, 10], "mix": None, "account": None}
    answer = {"summary": "Testing bands.", "memo": "Does a wider band cost much?", "action": "rule", "rule": rule}
    report = run_strategy_desk(cfg, question="Is a 5 point band right?", lab=FakeLab(), decisions=FakeDecisions(), adapter=FakeAdapter({"strategy": answer}))
    assert report.queued.name.endswith("-band-test-rule.json")
    body = json.loads(report.queued.read_text())
    assert body["request"] == "rule" and body["params"] == {"band_pts": [3, 5, 10]} and "mix" not in body and body["desk"] == "strategy"
    schema = briefs.schema_file("strategy")
    assert "rule" in schema["properties"]["action"]["enum"] and schema["properties"]["rule"]["properties"]["rule"]["enum"][-1] == "margin"


def test_rule_results_queue_a_review(cfg):
    lab = FakeLab(pending=[{"strategy_id": "band-test", "version": 0, "kind": "rule", "result_at": "2026-11-08T06:00:00Z"}])
    req = store.get_request(cfg, queue_reviews(cfg, lab)[0])
    assert "Rule test results are in for band-test" in req["question"]
