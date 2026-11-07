import json

import pytest

from desk.agents import console, store
from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import holdings, run_proposal_desk
from desk.agents.sources import RealEngine, RealTriggers
from desk.engine.__main__ import run_holdings
from tests.agents.agent_fakes import FakeDecisions, proposal
from tests.agents.test_console import FakeTriggers, research_answer
from tests.engine.helpers import MirrorBuilder
from tests.engine.test_brief import run_core
from tests.engine.test_preflight import seed


@pytest.fixture
def engine(cfg, monkeypatch):
    builder = MirrorBuilder(cfg.mirror_db, monkeypatch)
    seed(builder)
    run_holdings(cfg)
    run_core(cfg)
    yield cfg
    builder.close()


def brief_value(prompt, key):
    body = json.loads(prompt.split("\n\n", 1)[1])
    return next(i["value"] for items in body["brief"]["sections"].values() for i in items if i.get("key") == key)


def test_plan_keeper_cites_real_engine_keys(cfg, engine):

    def keeper(prompt):
        cash = brief_value(prompt, "cash.ready:all:now")
        good = proposal(numbers_used=[{"field": "cash.ready:all:now", "value": cash}])
        bad = proposal(title="Wrong", numbers_used=[{"field": "cash.ready:all:now", "value": cash + 500}])
        return {"summary": "Cash is ready.", "proposals": [good, bad]}

    decisions = FakeDecisions()
    report = run_proposal_desk(cfg, "plan_keeper", engine=RealEngine(), decisions=decisions, adapter=FakeAdapter({"plan_keeper": keeper}))
    assert report.status == "ok" and len(report.created) == 1 and len(report.rejected) == 1
    assert store.latest_brief(cfg, "plan_keeper")["as_of"]
    again = run_proposal_desk(cfg, "plan_keeper", engine=RealEngine(), decisions=decisions, adapter=FakeAdapter({"plan_keeper": keeper}))
    assert again.status == "unchanged"


def test_research_rotates_real_holdings_only(cfg, engine):
    slice_ = RealEngine().desk_slice(cfg, "research")
    assert holdings(slice_) == ["ACME", "FXAIX"]
    report = run_proposal_desk(cfg, "research", engine=RealEngine(), decisions=FakeDecisions(), adapter=FakeAdapter({"research": research_answer}))
    assert report.symbol == "ACME"


def test_real_triggers_route_to_desks(cfg, engine):
    kinds = {r["kind"] for r in RealTriggers().today(cfg)}
    assert {"concentration", "rule_breach"} <= kinds
    made = [store.get_request(cfg, r) for r in console.process_triggers(cfg)]
    routed = {(r["desk"], r["run_now"]) for r in made}
    assert ("plan_keeper", 1) in routed and ("risk", 1) in routed
    assert console.process_triggers(cfg) == []


def test_deposit_landed_queues_plan_keeper_tonight(cfg):
    rows = [{"as_of": "2026-12-02", "kind": "deposit_landed", "scope_id": "d1", "detail": "{}"}]
    req = store.get_request(cfg, console.process_triggers(cfg, FakeTriggers(rows))[0])
    assert (req["desk"], req["run_now"], req["source"]) == ("plan_keeper", 0, "trigger")


def test_dry_run_on_the_real_engine(engine, monkeypatch, capsys):
    from desk.agents.__main__ import main

    monkeypatch.setenv("DESK_DATA_DIR", str(engine.data_dir))
    assert main(["dry-run", "tax", "--question", "Any harvest room?"]) == 0
    out = capsys.readouterr().out
    assert "health" in out and "lots" in out and "Any harvest room?" in out and "## Prompt" in out
    assert store.runs(engine) == []
