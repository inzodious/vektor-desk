import pytest

from desk.agents import store, switches
from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import run_proposal_desk
from desk.agents.runner import FIRST_RUN
from desk.agents.status import crew
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer

YAML_OFF = {"agents": {"enabled": True, "desks": {"plan_keeper": False}}}


@pytest.mark.parametrize(
    ("app", "profile", "want"),
    [
        (None, {}, (True, "default")),
        (None, YAML_OFF, (False, "desk.yaml")),
        (True, YAML_OFF, (True, "app")),
        (False, {"agents": {"desks": {"plan_keeper": True}}}, (False, "app")),
    ],
)
def test_app_switch_overrides_desk_yaml(cfg, app, profile, want):
    if app is not None:
        store.set_enabled(cfg, "plan_keeper", app)
    got = switches.resolve(cfg, "plan_keeper", profile)
    assert (got["enabled"], got["source"]) == want
    assert got["app"] is app


def test_filings_defaults_off_and_clearing_returns_to_yaml(cfg):
    assert switches.resolve(cfg, "filings", {}) == {"enabled": False, "source": "default", "app": None, "yaml": None}
    store.set_enabled(cfg, "filings", True)
    assert switches.blocked(cfg, "filings", {"agents": {"desks": {"filings": False}}}) is None
    store.clear_enabled(cfg, "filings")
    assert switches.blocked(cfg, "filings", {"agents": {"desks": {"filings": False}}}) == "Switched off in desk.yaml."


def test_master_switch_blocks_every_desk(cfg):
    assert switches.blocked(cfg, "tax", {"agents": {"enabled": False}}) == "All desks are switched off in desk.yaml."
    store.set_enabled(cfg, store.ALL, True)
    assert switches.blocked(cfg, "tax", {"agents": {"enabled": False}}) is None


def test_app_switch_lets_a_yaml_off_desk_run(cfg):
    store.set_enabled(cfg, "plan_keeper", True)
    fake = FakeAdapter({"plan_keeper": answer()})
    report = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(profile_data=YAML_OFF), adapter=fake)
    assert report.status == "ok" and fake.calls


def test_guard_ready_after_first_run_desks_finish(cfg):
    assert switches.guard_ready(cfg, FIRST_RUN) == (False, "The Plan keeper and the Tax desk haven't finished a run yet.")
    store.finish_run(cfg, store.start_run(cfg, "plan_keeper", trigger="schedule", model="opus", effort="high"), "ok")
    assert switches.guard_ready(cfg, FIRST_RUN) == (False, "The Tax desk hasn't finished a run yet.")
    store.finish_run(cfg, store.start_run(cfg, "tax", trigger="schedule", model="opus", effort="high"), "ok")
    assert switches.guard_ready(cfg, FIRST_RUN) == (True, None)


def test_status_shows_where_each_switch_comes_from(cfg):
    store.set_enabled(cfg, "risk", False)
    body = crew(cfg, decisions=FakeDecisions(profile_data=YAML_OFF))
    tiles = {d["desk"]: d for d in body["desks"]}
    assert (body["enabled"], body["enabled_source"]) == (True, "desk.yaml")
    assert (tiles["plan_keeper"]["enabled"], tiles["plan_keeper"]["source"], tiles["plan_keeper"]["yaml"]) == (False, "desk.yaml", False)
    assert (tiles["risk"]["enabled"], tiles["risk"]["source"], tiles["risk"]["app"]) == (False, "app", False)
    assert (tiles["filings"]["enabled"], tiles["filings"]["source"]) == (False, "default")
    assert tiles["plan_keeper"]["next_run"] is None
    assert set(body["guard"]) == {"on", "allowed", "ready", "why"}


def test_delete_switch_api(cfg, app_client):
    client = app_client(packages=["agents"])
    client.put("/api/agents/filings/enabled", json={"enabled": True})
    assert store.app_switch(cfg, "filings") is True
    body = client.delete("/api/agents/filings/enabled").json()
    assert body["desk"] == "filings" and body["app"] is None and body["source"] != "app"
    assert store.app_switch(cfg, "filings") is None
    assert client.delete("/api/agents/nope/enabled").status_code == 404
    assert client.delete("/api/agents/*/enabled").status_code == 200
