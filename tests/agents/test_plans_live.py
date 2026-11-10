import json
from datetime import UTC, date, datetime

import pytest

from desk.agents import advisor, console, plans, store
from desk.agents.sources import RealAdvisor, RealPlanFacts, RealPlans
from desk.decisions import plans as record
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_advisor import FakeAdvisor
from tests.agents.test_plans import ON, PINS, SAT, WED, FakeFacts, FakeTriggers, Served, draft

NOW = datetime(2026, 11, 11, 23, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr("desk.agents.alerts.publish", lambda *a, **k: True)


def run(cfg, answer, today=WED, **kw):
    fake = Served({"plans": answer})
    report = plans.run_plan_desk(
        cfg,
        facts=FakeFacts(),
        plans=RealPlans(),
        decisions=FakeDecisions(profile_data=ON),
        adapter=fake,
        advice=FakeAdvisor(),
        triggers=FakeTriggers(),
        today=today,
        **kw,
    )
    return report, fake


def test_draft_lands_in_the_real_plan_record_and_is_never_approved(cfg):
    harvest = {"kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "lots": "highest_cost", "no_buy_days": 31, "note": "Size is your pick."}
    answer = draft()
    answer["plan"]["steps"].append(harvest | {"text": "", "when": None, "shares": None, "amount_usd": None})
    report, _ = run(cfg, answer)
    assert report.drafted == ["TICKA"] and not report.rejected
    plan = record.get_plan(cfg, "TICKA", now=NOW)
    assert (plan["status"], plan["author"], plan["model"], plan["version"]) == ("draft", "desk", "claude-opus-5-5", 1)
    assert plan["run_id"] == str(report.run_id) and plan["summary"] == "A small satellite; hold into earnings."
    assert [(s["kind"], s["by"]) for s in plan["steps"]] == [("hold", "desk"), ("add", "desk"), ("harvest", "desk")]
    assert plan["steps"][2]["shares"] is None and plan["steps"][2]["no_buy_days"] == 31
    assert record.approved_plans(cfg, now=NOW) == [] and RealAdvisor().actions(cfg) == []
    again, fake = run(cfg, answer, today=SAT)
    assert again.kept == ["TICKA"] and "same as the current plan" in again.answer
    assert json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["current_plan"]["status"] == "draft"


def test_his_steps_and_pins_survive_a_desk_redraft(cfg):
    run(cfg, draft())
    mine = record.get_plan(cfg, "TICKA", now=NOW)
    body = {k: mine[k] for k in plans.PLAN_FIELDS} | {"steps": [{"id": "my-trim", "kind": "trim", "when": "Above 12% of the book"}]}
    record.save_plan(cfg, "TICKA", body, approve=True, now=NOW)
    console.ask(cfg, "plans", json.dumps(PINS), symbol="TICKA")
    answer = draft(thesis="A new thesis after earnings.")
    answer["plan"]["steps"].append({"kind": "harvest", "text": "Harvest some.", "due": "2026-12-20", "when": None})
    report, fake = run(cfg, answer, today=SAT)
    assert report.drafted == ["TICKA"]
    sent = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert sent["current_plan"]["status"] == "approved" and sent["current_plan"]["steps"][0]["by"] == "you"
    plan = record.get_plan(cfg, "TICKA", now=NOW)
    assert plan["status"] == "draft" and plan["approved"]["thesis"] != plan["thesis"]
    assert {s["id"]: s["by"] for s in plan["steps"]} == {"harvest-2026": "desk", "margin-repay": "desk", "hold": "desk", "add": "desk", "my-trim": "you"}
    assert next(s for s in plan["steps"] if s["id"] == "harvest-2026")["shares"] == 40


def test_his_unapproved_draft_blocks_the_desk_without_a_call(cfg):
    run(cfg, draft())
    mine = record.get_plan(cfg, "TICKA", now=NOW)
    record.save_plan(cfg, "TICKA", {k: mine[k] for k in plans.PLAN_FIELDS} | {"thesis": "My own words."}, now=NOW)
    report, fake = run(cfg, draft(), today=SAT)
    assert report.waiting == ["TICKA"] and not fake.calls


def test_approved_steps_reach_the_plan_keeper_and_hold_buys(cfg):
    console.ask(cfg, "plans", json.dumps(PINS), symbol="TICKA")
    run(cfg, draft())
    record.approve_plan(cfg, "TICKA", now=NOW)
    view = advisor.gather(cfg, RealAdvisor())
    assert any(line.startswith("TICKA:") for line in view["planned_actions"])
    assert view["no_buy"]["TICKA"]["step_id"] == "harvest-2026"
    assert advisor.no_buy_until(view, "TICKA", "2026-11-11")


def test_bad_pins_are_refused_by_the_real_record(cfg):
    with pytest.raises(ValueError, match="shares"):
        console.ask(cfg, "plans", json.dumps({"steps": [{"kind": "repay", "due": "2026-11-18", "shares": 5}]}), symbol="TICKA")
    assert store.pinned_steps(cfg) == []


def test_runs_on_the_engines_real_plan_facts(cfg, monkeypatch):
    planfacts = pytest.importorskip("desk.engine.planfacts")
    seeded = pytest.importorskip("tests.engine.test_planfacts").seeded
    seeded(cfg, monkeypatch).close()
    zones = next(r for r in planfacts.facts(cfg) if r["symbol"] == "ACME")["zones"]
    answer = draft()
    answer["plan"]["add_rule"] |= {"zone_low": zones["add"]["low"], "zone_high": zones["add"]["high"]}
    answer["plan"]["trim_rule"] |= {"zone_low": zones["levels"]["high_52w"], "zone_high": 9999.0}
    fake = Served({"plans": answer})
    kw = {"facts": RealPlanFacts(), "plans": RealPlans(), "decisions": FakeDecisions(profile_data=ON), "adapter": fake, "advice": FakeAdvisor()}
    report = plans.run_plan_desk(cfg, triggers=FakeTriggers(), today=WED, **kw)
    assert report.drafted == ["ACME", "IVV", "SOLO"] and report.reasons["ACME"] == ["new", "discount", "band"]
    sent = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert sent["holding"]["kind"] == "stock" and sent["holding"]["band"]["status"] == "over" and sent["holding"]["accounts"] == ["ind"]
    plan = record.get_plan(cfg, "ACME", now=NOW)
    assert plan["add_rule"]["zone_low"] == zones["add"]["low"] and plan["trim_rule"]["zone_low"] == zones["levels"]["high_52w"]
    assert plan["trim_rule"]["zone_high"] is None
    again = plans.run_plan_desk(cfg, triggers=FakeTriggers(), today=date(2026, 11, 12), **kw)
    assert again.note == "No plans to draft or refresh today." and len(fake.calls) == 3
    asked = plans.run_plan_desk(cfg, triggers=FakeTriggers(), today=WED, symbols=("wtch",), **kw)
    assert asked.note == "WTCH isn't a holding in today's plan facts."
