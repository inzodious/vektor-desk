import pytest

from desk.agents import __main__ as cli
from desk.agents import console, pipeline
from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import Report, run_proposal_desk
from desk.agents.sources import RealDecisions, RealEngine
from desk.db import apply_schemas
from desk.decisions import desk_history, records
from tests.agents.agent_fakes import SLICE, FakeEngine, answer, proposal

PROFILE = """
agents:
  enabled: true
  desks:
    plan_keeper: true
    research: true
    skeptic: true
"""


@pytest.fixture
def live_cfg(demo_cfg, tmp_path, monkeypatch):
    path = tmp_path / "desk.yaml"
    path.write_text(PROFILE)
    monkeypatch.setenv("DESK_PROFILE", str(path))
    apply_schemas(demo_cfg)
    return demo_cfg


def test_plan_keeper_writes_real_decision_records(live_cfg):
    bad = proposal(title="Wrong number", numbers_used=[{"field": "cash.ready:all:now", "value": 9}])
    report = run_proposal_desk(
        live_cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=RealDecisions(), adapter=FakeAdapter({"plan_keeper": answer(proposal(), bad)})
    )
    assert report.status == "ok" and report.note is None
    assert report.created[0]["status"] == "proposed" and report.created[0]["run_id"] == str(report.outcome.run_id)
    assert report.created[0]["profile_version"] >= 1
    assert report.rejected[0]["status"] == "rejected"
    history = desk_history(live_cfg, "plan_keeper", limit=20)
    assert {h["title"] for h in history} >= {"Send the ready cash to FUNDA"}


ALERT = {
    "kind": "alert",
    "title": "Single-stock rule is over its band",
    "symbol": None,
    "amount_usd": None,
    "funding": None,
    "thesis": "One holding is past the single-stock cap. Steer the next deposit elsewhere.",
    "rule_served": "Single-stock max",
    "numbers_used": [],
    "order_ticket": None,
}
NO_THESIS = {"title": "Buy more FUNDA", "thesis": "", "numbers_used": []}


def test_a_rule_alert_is_counted_as_a_note_not_a_proposal(live_cfg, monkeypatch, capsys):
    monkeypatch.setenv("DESK_DATA_DIR", str(live_cfg.data_dir))
    monkeypatch.setattr(pipeline, "RealEngine", lambda: FakeEngine(SLICE))
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"plan_keeper": answer(proposal(**ALERT), summary="One rule is out.")}))
    assert cli.main(["run", "plan_keeper"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "Plan keeper: ok, 0 proposals, 1 note, 0 rejected."
    assert records.queue(live_cfg)["count"] == 0
    assert [n["title"] for n in records.notes(live_cfg)["items"]] == ["Single-stock rule is over its band"]


def test_the_tally_follows_what_the_record_did_with_each_proposal(live_cfg):
    asked = answer(proposal(), proposal(**ALERT), proposal(**NO_THESIS))
    report = run_proposal_desk(live_cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=RealDecisions(), adapter=FakeAdapter({"plan_keeper": asked}))
    assert [r["status"] for r in report.created] == ["proposed", "logged", "rejected"]
    assert (len(report.waiting), len(report.notes), len(report.refused)) == (1, 1, 1)
    assert report.tally == "1 proposal, 1 note, 1 rejected"
    assert records.queue(live_cfg)["count"] == len(report.waiting)
    assert console._answer(report).splitlines()[1:] == [
        "1 proposal(s) added to the queue.",
        "1 note(s) filed under Notes.",
        "1 proposal(s) turned down by the desk's checks.",
    ]


def test_a_quiet_run_keeps_the_old_line():
    assert Report(None).tally == "0 proposals, 0 rejected"


def test_real_profile_switches_desks_off_by_default(demo_cfg):
    apply_schemas(demo_cfg)
    report = run_proposal_desk(demo_cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=RealDecisions(), adapter=FakeAdapter())
    assert report.status == "disabled"


def test_engine_slice_still_falls_back(live_cfg):
    report = run_proposal_desk(live_cfg, "plan_keeper", engine=RealEngine(), decisions=RealDecisions(), adapter=FakeAdapter())
    assert report.status == "not_ready"
