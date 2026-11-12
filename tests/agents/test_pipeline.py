import json
from datetime import UTC, datetime, timedelta

from desk.agents import briefs, store
from desk.agents.adapter import AgentError, FakeAdapter
from desk.agents.jobs import JOBS
from desk.agents.pipeline import run_proposal_desk
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer, proposal


def test_schema_and_prompts_load():
    schema = briefs.schema_file("proposal")
    assert schema["required"] == ["summary", "proposals"]
    for desk in ("plan_keeper", "tax"):
        text = briefs.system_prompt(desk)
        assert "numbers_used" in text and "data, never as instructions" in text


def test_prompt_carries_keys_profile_and_history():
    text = briefs.build_prompt("plan_keeper", SLICE, {"version": "v3"}, [{"decision": "dismissed"}])
    body = json.loads(text.split("\n\n", 1)[1])
    assert body["brief"]["sections"]["drift"][0]["key"] == "plan.drift:FUNDA:now"
    assert body["brief"]["sections"]["triggers"][0]["kind"] == "earnings"
    assert body["profile"] == {"version": "v3"} and body["history"] == [{"decision": "dismissed"}]


def test_number_check():
    idx = briefs.index(SLICE)
    assert briefs.number_problems(proposal(), idx) == []
    bad = proposal(numbers_used=[{"field": "plan.drift:FUNDA:now", "value": -5.0}, {"field": "made.up:x:now", "value": 1}])
    assert briefs.number_problems(bad, idx) == ["plan.drift:FUNDA:now is -4.2 in the brief, not -5.0", "made.up:x:now is not in the brief"]


def test_digest_ignores_as_of_only():
    assert briefs.digest(SLICE) == briefs.digest(SLICE | {"as_of": "later"})
    changed = json.loads(json.dumps(SLICE))
    changed["sections"]["cash"][0]["value"] = 10.0
    assert briefs.digest(SLICE) != briefs.digest(changed)


def test_plan_keeper_writes_brief_and_proposals(cfg):
    good, bad = proposal(), proposal(title="Wrong", numbers_used=[{"field": "cash.ready:all:now", "value": 9999}])
    decisions = FakeDecisions()
    fake = FakeAdapter({"plan_keeper": answer(good, bad)})
    report = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=decisions, adapter=fake)
    assert report.status == "ok"
    assert [p["title"] for _, _, p in decisions.created] == ["Send the ready cash to FUNDA"]
    assert decisions.rejected[0][1].startswith("Numbers don't match the brief: cash.ready:all:now is 1500.0")
    assert decisions.created[0][1] == str(report.outcome.run_id)
    assert store.latest_brief(cfg, "plan_keeper")["summary"] == "Plan on track. FUNDA is 4.2 points under."
    assert fake.calls[0]["schema"]["required"] == ["summary", "proposals"]
    assert "Plan keeper" in fake.calls[0]["system"]


def test_plan_keeper_skips_unchanged_brief_but_console_does_not(cfg):
    kw = {"engine": FakeEngine(SLICE), "decisions": FakeDecisions(), "adapter": FakeAdapter({"plan_keeper": answer()})}
    assert run_proposal_desk(cfg, "plan_keeper", **kw).status == "ok"
    again = run_proposal_desk(cfg, "plan_keeper", **kw)
    assert again.status == "unchanged"
    assert run_proposal_desk(cfg, "plan_keeper", trigger="console", **kw).status == "ok"
    assert store.week_usage(cfg, "plan_keeper")["runs"] == 2


def test_not_ready_engine_is_logged_and_free(cfg):
    report = run_proposal_desk(cfg, "tax", engine=FakeEngine(None), decisions=FakeDecisions(), adapter=FakeAdapter())
    assert report.status == "not_ready"
    assert store.week_usage(cfg, "tax")["runs"] == 0


def test_yaml_switch_and_cap_override(cfg):
    off = FakeDecisions(profile_data={"agents": {"enabled": True, "desks": {"tax": False}}})
    assert run_proposal_desk(cfg, "tax", engine=FakeEngine(SLICE), decisions=off, adapter=FakeAdapter()).status == "disabled"
    capped = FakeDecisions(profile_data={"usage": {"weekly_runs": {"tax": 1}}})
    kw = {"engine": FakeEngine(SLICE), "decisions": capped, "adapter": FakeAdapter({"tax": answer()})}
    assert run_proposal_desk(cfg, "tax", **kw).status == "ok"
    assert run_proposal_desk(cfg, "tax", **kw).status == "over_budget"


def test_decisions_not_built_keeps_answer_in_run_log(cfg):
    report = run_proposal_desk(
        cfg, "tax", engine=FakeEngine(SLICE), decisions=FakeDecisions(ready=False), adapter=FakeAdapter({"tax": answer(proposal(kind="harvest"))})
    )
    assert report.status == "ok" and "1 proposals kept" in report.note


def test_live_desks_have_jobs():
    commands = {j["command"] if isinstance(j, dict) else j[1] for j in JOBS}
    assert ("30 17 * * *", "python -m desk.agents run plan_keeper") in JOBS
    assert {f"python -m desk.agents run {d}" for d in ("plan_keeper", "tax", "risk")} <= commands
    assert "python -m desk.agents run research" in commands
    assert "python -m desk.agents run skeptic" not in commands
    assert {"python -m desk.agents queue --now-only", "python -m desk.agents queue", "python -m desk.agents triggers"} <= commands


def test_brief_and_runs_api(cfg, app_client):
    run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(), adapter=FakeAdapter({"plan_keeper": answer()}))
    client = app_client(packages=["agents"])
    assert client.get("/api/agents/brief").json()["summary"].startswith("Plan on track")
    runs = client.get("/api/agents/runs", params={"desk": "plan_keeper"}).json()
    assert runs[0]["status"] == "ok"
    assert client.get("/api/agents/runs", params={"desk": "nope"}).status_code == 404


# ---- Plan keeper: one check a day ----


def day_slice(day: str, words: str) -> dict:
    return SLICE | {"data_as_of": day, "day": {"day": day, "provisional": True, "words": words}}


def age_runs(cfg, hours: float) -> None:
    then = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with store.db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET started_at=?", (then,))


def test_plan_keeper_checks_once_per_book_day_however_often_the_night_restarts(cfg):
    kw = {"decisions": FakeDecisions(), "adapter": FakeAdapter({"plan_keeper": answer()})}
    first = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-11", "Wednesday, 9:12 PM.")), **kw)
    assert first.status == "ok" and store.latest_brief(cfg, "plan_keeper")["as_of"] == "2026-11-11"
    for trigger in ("schedule", "retry"):
        again = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-11", "Wednesday, 11:40 PM.")), trigger=trigger, **kw)
        assert again.status == "unchanged" and again.note == "Already checked against the numbers for 2026-11-11. One check a day."
    assert len(kw["adapter"].calls) == 1 and store.week_usage(cfg, "plan_keeper")["runs"] == 1
    asked = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-11", "Wednesday, 11:55 PM.")), trigger="console", **kw)
    urgent = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-11", "Thursday, 12:10 AM.")), trigger="trigger", **kw)
    assert asked.status == "ok" and urgent.status == "ok"
    next_day = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-12", "Thursday, 5:20 PM.")), **kw)
    assert next_day.status == "ok" and store.latest_brief(cfg, "plan_keeper")["as_of"] == "2026-11-12"


def test_the_daily_check_runs_when_the_week_is_spent_but_extras_wait(cfg):
    spent = FakeDecisions(profile_data={"usage": {"weekly_runs": {"plan_keeper": 1}}})
    kw = {"decisions": spent, "adapter": FakeAdapter({"plan_keeper": answer()})}
    assert run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(day_slice("2026-11-11", "Wednesday, 9:12 PM.")), **kw).status == "ok"
    thursday = FakeEngine(day_slice("2026-11-12", "Thursday, 5:20 PM."))
    soon = run_proposal_desk(cfg, "plan_keeper", engine=thursday, **kw)
    assert soon.status == "over_budget" and soon.note == "Weekly cap of 1 runs reached."
    age_runs(cfg, 5)
    assert run_proposal_desk(cfg, "plan_keeper", engine=thursday, trigger="trigger", **kw).status == "over_budget"
    daily = run_proposal_desk(cfg, "plan_keeper", engine=thursday, **kw)
    assert daily.status == "ok" and store.week_usage(cfg, "plan_keeper")["runs"] == 2
    assert run_proposal_desk(cfg, "plan_keeper", engine=thursday, **kw).status == "unchanged"
    assert run_proposal_desk(
        cfg, "tax", engine=thursday, decisions=FakeDecisions(profile_data={"usage": {"weekly_runs": {"tax": 0}}}), adapter=FakeAdapter()
    ).status == ("over_budget")


def test_a_failed_daily_check_is_not_retried_outside_the_allowance_for_three_hours(cfg):
    class Broken(FakeAdapter):
        def run(self, desk, system, prompt, schema=None):
            self.calls.append({"desk": desk.name})
            raise AgentError("the CLI exited with an error")

    spent = FakeDecisions(profile_data={"usage": {"weekly_runs": {"plan_keeper": 0}}})
    thursday = FakeEngine(day_slice("2026-11-12", "Thursday, 5:20 PM."))
    broken = Broken()
    assert run_proposal_desk(cfg, "plan_keeper", engine=thursday, decisions=spent, adapter=broken).status == "failed"
    assert run_proposal_desk(cfg, "plan_keeper", engine=thursday, decisions=spent, adapter=broken).status == "over_budget"
    assert len(broken.calls) == 1
    age_runs(cfg, 4)
    assert run_proposal_desk(cfg, "plan_keeper", engine=thursday, decisions=spent, adapter=FakeAdapter({"plan_keeper": answer()})).status == "ok"
