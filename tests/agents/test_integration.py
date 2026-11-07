import pytest

from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import run_proposal_desk
from desk.agents.sources import RealDecisions, RealEngine
from desk.db import apply_schemas
from desk.decisions import desk_history
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


def test_real_profile_switches_desks_off_by_default(demo_cfg):
    apply_schemas(demo_cfg)
    report = run_proposal_desk(demo_cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=RealDecisions(), adapter=FakeAdapter())
    assert report.status == "disabled"


def test_engine_slice_still_falls_back(live_cfg):
    report = run_proposal_desk(live_cfg, "plan_keeper", engine=RealEngine(), decisions=RealDecisions(), adapter=FakeAdapter())
    assert report.status == "not_ready"
