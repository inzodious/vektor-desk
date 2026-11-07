import dataclasses

from desk.agents import alerts, console
from desk.agents.adapter import AgentError, AgentTimeout, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.pipeline import run_proposal_desk
from desk.agents.runner import run_desk
from desk.notify import recent, set_enabled
from tests.agents.agent_fakes import FakeDecisions, FakeEngine
from tests.agents.test_console import HELD, research_answer
from tests.agents.test_strategy import FakeLab, experiment_answer


def sent(cfg, topic=None):
    return [(r["topic"], r["title"], r["body"], r["click"]) for r in reversed(recent(cfg, topic=topic))]


def test_failed_and_timed_out_runs_alert_ops_once_a_day(cfg):
    cfg = dataclasses.replace(cfg, demo=True)
    run_desk(get("tax"), "s", "p", cfg=cfg, schema={"type": "object"}, adapter=FakeAdapter({"tax": AgentError("exit 1: boom")}))
    run_desk(get("tax"), "s", "p", cfg=cfg, schema={"type": "object"}, adapter=FakeAdapter({"tax": AgentError("exit 1: again")}))
    run_desk(get("risk"), "s", "p", cfg=cfg, adapter=FakeAdapter({"risk": AgentTimeout("stuck for 20 minutes")}))
    run_desk(get("tax"), "s", "p", cfg=cfg, schema={"type": "object"}, adapter=FakeAdapter({"tax": "no json"}))
    rows = sent(cfg, "ops")
    assert [t for _, t, _, _ in rows] == ["Tax desk failed", "Risk desk timed out"]
    assert "boom" in rows[0][2] and rows[0][3] == cfg.public_url + "/settings"


def test_usage_limit_and_ok_runs_stay_quiet(cfg):
    run_desk(get("tax"), "s", "p", cfg=cfg, adapter=FakeAdapter({"tax": UsageLimitError("limit")}))
    run_desk(get("tax"), "s", "p", cfg=cfg, adapter=FakeAdapter())
    assert recent(cfg) == []


def test_console_answer_goes_to_research_with_a_link(cfg):
    rid = console.ask(cfg, "research", "What changed at TICKA?", symbol="TICKA", run_now=True)
    fake = FakeAdapter({"research": lambda p: research_answer(p, summary="TICKA guided up; holding pays $1,200 a year.")})
    console.process_queue(cfg, now_only=True, engine=FakeEngine(HELD), decisions=FakeDecisions(), adapter=fake)
    rows = sent(cfg)
    assert len(rows) == 1
    topic, title, body, click = rows[0]
    assert (topic, title, click) == ("research", "Research desk answered", cfg.public_url + "/research")
    assert "$1,200" not in body and "TICKA guided up" in body
    assert recent(cfg)[0]["status"] == "off" and rid


def test_lab_answers_link_to_the_lab(cfg):
    console.ask(cfg, "strategy", "Test a low-volatility tilt.", run_now=True)
    console.process_queue(cfg, now_only=True, lab=FakeLab(), decisions=FakeDecisions(), adapter=FakeAdapter({"strategy": experiment_answer()}))
    assert sent(cfg)[-1][3] == cfg.public_url + "/lab"


def test_not_ready_answers_send_nothing(cfg):
    console.ask(cfg, "tax", "Any harvest room?", run_now=True)
    console.process_queue(cfg, now_only=True, engine=FakeEngine(None), decisions=FakeDecisions(), adapter=FakeAdapter())
    assert recent(cfg) == []


def test_requests_that_never_ran_alert_ops(cfg):
    console.ask(cfg, "risk", "Check margin.", run_now=True)
    fake = FakeAdapter({"risk": UsageLimitError("limit")})
    console.process_queue(cfg, now_only=True, engine=FakeEngine(HELD), decisions=FakeDecisions(), adapter=fake)
    console.process_queue(cfg, now_only=False, engine=FakeEngine(HELD), decisions=FakeDecisions(), adapter=fake)
    assert [t for _, t, _, _ in sent(cfg, "ops")] == ["Risk desk hit the usage limit twice"]


def test_scheduled_dossier_alerts_low_and_console_dossier_does_not_double(cfg):
    kw = {"engine": FakeEngine(HELD), "decisions": FakeDecisions(), "adapter": FakeAdapter({"research": research_answer})}
    run_proposal_desk(cfg, "research", **kw)
    run_proposal_desk(cfg, "research", trigger="console", **kw)
    rows = recent(cfg)
    assert [r["title"] for r in rows] == ["Dossier ready: TICKA"] and rows[0]["priority"] == 2


def test_muted_topic_and_publish_errors_never_break_a_run(cfg, monkeypatch):
    set_enabled(cfg, "ops", False)
    out = run_desk(get("tax"), "s", "p", cfg=cfg, adapter=FakeAdapter({"tax": AgentError("x")}))
    assert out.status == "failed" and recent(cfg)[0]["status"] == "muted"

    def boom(*a, **k):
        raise RuntimeError("notify down")

    monkeypatch.setattr(alerts, "publish", boom)
    assert run_desk(get("risk"), "s", "p", cfg=cfg, adapter=FakeAdapter({"risk": AgentError("y")})).status == "failed"
