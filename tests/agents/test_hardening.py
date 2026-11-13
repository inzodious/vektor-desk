from datetime import UTC, datetime, timedelta

import pytest

from desk.agents import __main__ as cli
from desk.agents import console, pipeline, store
from desk.agents.adapter import FakeAdapter
from desk.agents.desks import Desk, get
from desk.agents.jobs import JOBS
from desk.agents.pipeline import run_proposal_desk
from desk.agents.runner import run_desk
from desk.agents.status import crew
from desk.runlock import job_lock
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer

SICK = SLICE | {"data_health": [{"check": "freshness", "status": "fail", "detail": "Mirror pulled 30.0 hours ago (limit 14)."}]}


def old() -> dict:
    return SLICE | {"as_of": (datetime.now(UTC) - timedelta(hours=40)).isoformat(timespec="seconds")}


class NoCli:
    def run(self, *a, **k):
        raise AssertionError("dry-run must not call claude")


@pytest.fixture
def cli_env(cfg, monkeypatch):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(pipeline, "RealEngine", lambda: FakeEngine(SLICE))
    monkeypatch.setattr(pipeline, "RealDecisions", FakeDecisions)
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", NoCli)
    return cfg


# ---- Engine health ----


@pytest.mark.parametrize(("slice_", "words"), [(lambda: SICK, "freshness: Mirror pulled"), (old, "finished 40 hours ago")])
def test_desks_refuse_to_run_on_failing_or_stale_engine(cfg, slice_, words):
    fake = FakeAdapter({"plan_keeper": answer()})
    report = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(slice_()), decisions=FakeDecisions(), adapter=fake)
    assert report.status == "unhealthy" and words in report.note and fake.calls == []
    assert store.last_run(cfg, "plan_keeper")["status"] == "unhealthy"
    assert store.week_usage(cfg, "plan_keeper")["runs"] == 0


def test_warnings_do_not_block_and_console_gets_the_reason(cfg):
    warn = SLICE | {"data_health": [{"check": "shares", "status": "warn", "detail": "No lot export yet."}]}
    assert run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(warn), decisions=FakeDecisions(), adapter=FakeAdapter()).status == "ok"
    rid = console.ask(cfg, "tax", "Any harvest room?", run_now=True)
    console.process_queue(cfg, now_only=True, engine=FakeEngine(SICK), decisions=FakeDecisions(), adapter=FakeAdapter())
    row = store.get_request(cfg, rid)
    assert row["status"] == "done" and "Engine health is fail" in row["answer"]


# ---- First-run guard ----


def test_guard_allows_only_plan_keeper_and_tax(cfg, app_client):
    store.set_guard(cfg, True)
    assert run_desk(get("research"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "guarded"
    assert run_desk(get("risk"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "guarded"
    assert run_desk(get("plan_keeper"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "ok"
    tiles = {d["desk"]: d for d in crew(cfg)["desks"]}
    assert crew(cfg)["guard"]["on"] and tiles["risk"]["guarded"] and tiles["risk"]["next_run"] is None and not tiles["tax"]["guarded"]
    client = app_client(packages=["agents"])
    assert client.put("/api/agents/guard", json={"enabled": False}).json()["guard"] is False
    assert run_desk(get("risk"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "ok"


def test_guard_lifts_itself_once_plan_keeper_and_tax_have_run(cfg):
    store.clear_enabled(cfg, store.GUARD)
    assert store.guard_on(cfg) and run_desk(get("research"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "guarded"
    run_desk(get("plan_keeper"), "s", "p", cfg=cfg, adapter=FakeAdapter())
    assert store.guard_on(cfg) and crew(cfg)["guard"]["ready"] is False
    run_desk(get("tax"), "s", "p", cfg=cfg, adapter=FakeAdapter())
    body = crew(cfg)
    assert not store.guard_on(cfg) and body["guard"]["on"] is False and body["guard"]["ready"] is True
    assert not {d["desk"] for d in body["desks"] if d["guarded"]}
    assert run_desk(get("research"), "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "ok"
    store.set_guard(cfg, True)
    assert not store.guard_on(cfg)


def test_a_fresh_desk_starts_guarded(tmp_path):
    from desk.config import Config

    assert store.guard_on(Config(data_dir=tmp_path / "fresh", project="p", uid="u"))


def test_guard_cli(cli_env, capsys):
    assert cli.main(["guard", "on"]) == 0 and "on: only plan_keeper, tax" in capsys.readouterr().out
    assert cli.main(["guard", "off"]) == 0 and "off" in capsys.readouterr().out
    assert store.guard_on(cli_env) is False


# ---- Dry run ----


def test_dry_run_prints_the_real_prompt_without_writing(cli_env, capsys):
    assert cli.main(["dry-run", "plan_keeper", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "no model call" in out and "health ok    reconcile" in out and '"cash.ready:all:now"' in out and "Output schema" in out
    assert store.runs(cli_env) == []


def test_dry_run_says_what_would_skip(cli_env, capsys, monkeypatch):
    store.set_guard(cli_env, True)
    cli.main(["dry-run", "research", "--symbol", "ticka"])
    out = capsys.readouterr().out
    assert "Would skip (guarded)" in out and "focus TICKA" in out
    monkeypatch.setattr(pipeline, "RealEngine", lambda: FakeEngine(SICK))
    cli.main(["dry-run", "tax"])
    assert "Would skip (unhealthy): Engine health is fail" in capsys.readouterr().out
    assert cli.main(["dry-run", "skeptic"]) == 2
    assert store.runs(cli_env) == []


# ---- Caps and cron timing ----


def test_trigger_runs_count_against_the_weekly_cap_but_console_does_not(cfg):
    tax = get("tax")
    for _ in range(tax.weekly_runs):
        assert run_desk(tax, "s", "p", cfg=cfg, adapter=FakeAdapter(), trigger="trigger").status == "ok"
    assert run_desk(tax, "s", "p", cfg=cfg, adapter=FakeAdapter(), trigger="trigger").status == "over_budget"
    assert run_desk(tax, "s", "p", cfg=cfg, adapter=FakeAdapter(), trigger="retry").status == "over_budget"
    assert run_desk(tax, "s", "p", cfg=cfg, adapter=FakeAdapter(), trigger="console").status == "ok"


def test_two_queue_passes_never_claim_the_same_request(cfg):
    a = console.ask(cfg, "tax", "One?", run_now=True)
    b = console.ask(cfg, "tax", "Two?", run_now=True)
    first, second = store.next_request(cfg, now_only=True), store.next_request(cfg, now_only=True)
    assert (first["id"], second["id"]) == (a, b) and store.next_request(cfg, now_only=True) is None


def test_interrupted_runs_and_requests_recover_only_when_the_lock_is_free(cfg):
    run_id = store.start_run(cfg, "tax", trigger="schedule", model="opus", effort="high")
    rid = console.ask(cfg, "tax", "Stuck?", run_now=True)
    store.next_request(cfg, now_only=True)
    later = datetime.now(UTC) + timedelta(minutes=15)
    assert store.recover(cfg, lock_free=False, now=later) == {"runs": 0, "requests": 0}
    assert store.recover(cfg, lock_free=True, now=later) == {"runs": 1, "requests": 1}
    assert store.runs(cfg)[0]["status"] == "failed" and store.runs(cfg)[0]["id"] == run_id
    assert store.get_request(cfg, rid)["status"] == "queued"
    store.next_request(cfg, now_only=False)
    store.recover(cfg, lock_free=True, now=later + timedelta(minutes=15))
    assert store.get_request(cfg, rid)["status"] == "failed"
    assert store.recover(cfg, lock_free=True) == {"runs": 0, "requests": 0}


def test_busy_requests_wait_without_using_their_retry(cfg):
    rid = console.ask(cfg, "tax", "Waiting?", run_now=True)
    with job_lock("agents", cfg=cfg):
        tally = console.process_queue(cfg, now_only=True, engine=FakeEngine(SLICE), decisions=FakeDecisions(), adapter=FakeAdapter(), wait=0)
    row = store.get_request(cfg, rid)
    assert tally.requeued == 1 and (row["status"], row["run_now"], row["note"]) == ("queued", 1, None)
    console.process_queue(cfg, now_only=True, engine=FakeEngine(SLICE), decisions=FakeDecisions(), adapter=FakeAdapter())
    assert store.get_request(cfg, rid)["status"] == "done"


def test_a_busy_scheduled_run_waits_then_queues_a_retry(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RUN_WAIT", 0)
    monkeypatch.setattr(Desk, "due_on", lambda self, day: True)
    with job_lock("agents", cfg=cli_env):
        assert cli.main(["run", "tax"]) == 75
    assert [r["source"] for r in store.requests(cli_env)] == ["retry"]


def test_overnight_queue_runs_every_hour_of_the_window():
    assert ("30 1-5 * * *", "python -m desk.agents queue") in JOBS
    assert get("plan_keeper").weekly_runs >= 10


# ---- The night reads the last line ----


def test_a_desk_that_declines_ends_with_a_skipped_line(cli_env, monkeypatch, capsys):
    import json

    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"plan_keeper": answer()}))
    assert cli.main(["run", "plan_keeper"]) == 0
    ran = capsys.readouterr().out.strip().splitlines()
    assert ran[-1].startswith("Plan keeper: ok, ") and not ran[-1].startswith("{")
    assert cli.main(["run", "plan_keeper"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-2].startswith("Plan keeper: unchanged, 0 proposals") and json.loads(out[-1]) == {"skipped": "Nothing in the brief changed since the last run."}
    store.set_enabled(cli_env, "tax", False)
    assert cli.main(["run", "tax"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"skipped": "Switched off in Settings."}
    monkeypatch.setattr(Desk, "due_on", lambda self, day: False)
    assert cli.main(["run", "scout"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"skipped": "Scout: not due today."}
