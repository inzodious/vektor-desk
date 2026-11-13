from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from desk.agents import __main__ as cli
from desk.agents import debrief, limits, pipeline, store
from desk.agents.adapter import FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.runner import run_desk
from desk.agents.status import crew
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer
from tests.agents.test_debrief import ON, FakeReviews, pack_row

ET = ZoneInfo("America/New_York")
HIT = datetime(2026, 11, 13, 5, 5, tzinfo=UTC)
RESET = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)
WEEKLY = "You've hit your weekly limit · resets 9am"


@pytest.fixture
def at(monkeypatch):
    moment = {"now": HIT}
    monkeypatch.setenv("TZ", "America/New_York")
    monkeypatch.setattr(limits, "clock_now", lambda: moment["now"])
    return lambda t: moment.update(now=t)


def limited(cfg, name, trigger="schedule", text=WEEKLY):
    return run_desk(get(name), "s", "p", cfg=cfg, adapter=FakeAdapter({name: UsageLimitError(text)}), trigger=trigger)


def log(cfg, desk, when, status="ok", cost=0.0, out=0, note=None):
    run_id = store.start_run(cfg, desk, trigger="schedule", model="opus", effort="high", status=status, note=note)
    with store.db(cfg) as conn:
        conn.execute(
            "UPDATE agent_runs SET started_at=?, cost_estimate=?, output_tokens=?, turns=1, duration_ms=120000 WHERE id=?",
            (when.isoformat(timespec="seconds"), cost, out, run_id),
        )
    return run_id


# ---- Reading the reset time ----


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (WEEKLY, datetime(2026, 11, 13, 9, 0, tzinfo=ET)),
        ("Claude usage limit reached. Your limit will reset at 3pm (America/Los_Angeles).", datetime(2026, 11, 13, 18, 0, tzinfo=ET)),
        ("5-hour limit reached ∙ resets 12:30am", datetime(2026, 11, 13, 0, 30, tzinfo=ET)),
        ("Weekly limit reached · resets Nov 20, 9am", datetime(2026, 11, 20, 9, 0, tzinfo=ET)),
        ("limit reached, resets Mon 7:15pm", datetime(2026, 11, 16, 19, 15, tzinfo=ET)),
        ("usage limit, resets in 3 hours", datetime(2026, 11, 13, 3, 5, tzinfo=ET)),
        ("usage limit reached", None),
        ("resets 27pm", None),
        ("resets Feb 31, 9am", None),
        ("429 rate limit", None),
    ],
)
def test_the_reset_time_is_read_from_the_limit_message(text, want):
    assert limits.reset_time(text, HIT, ET) == want
    assert limits.scope_of(WEEKLY) == "week" and limits.scope_of("5-hour limit reached ∙ resets 3am") == "session"


# ---- One retry soon after the reset ----


def test_a_deferred_scheduled_run_is_retried_once_just_after_the_reset(cfg, at):
    out = limited(cfg, "debrief")
    assert out.status == "deferred" and out.note == f"{WEEKLY} The desk tries again at 9:05 AM."
    assert [(r["desk"], r["due_at"], r["status"]) for r in store.retries(cfg)] == [("debrief", "2026-11-13T14:05:00+00:00", "waiting")]
    assert store.limits(cfg)[0] | {"id": 0} == {"id": 0, "scope": "week", "seen_at": HIT.isoformat(), "resets_at": RESET.isoformat(), "run_id": out.run_id}


def test_work_waits_while_the_limit_is_used_up_without_calling_claude(cfg, at):
    limited(cfg, "debrief")
    at(HIT + timedelta(hours=1))
    fake = FakeAdapter()
    again = run_desk(get("debrief"), "s", "p", cfg=cfg, adapter=fake)
    keeper = run_desk(get("plan_keeper"), "s", "p", cfg=cfg, adapter=fake, capped=False)
    assert (again.status, keeper.status, fake.calls) == ("deferred", "deferred", [])
    assert keeper.note == "Claude's limit is used up until 9:00 AM, so this run waits. The desk tries again at 9:05 AM."
    assert [r["desk"] for r in store.retries(cfg, "waiting")] == ["debrief", "plan_keeper"]
    asked = run_desk(get("tax"), "s", "p", cfg=cfg, adapter=fake, trigger="console")
    assert asked.status == "ok" and len(fake.calls) == 1
    assert run_desk(get("risk"), "s", "p", cfg=cfg, adapter=fake, trigger="retry").status == "deferred"
    assert store.waiting_retry(cfg, "risk") is None
    at(RESET + timedelta(minutes=1))
    assert run_desk(get("risk"), "s", "p", cfg=cfg, adapter=fake).status == "ok"


def test_a_limit_with_no_reset_time_plans_nothing(cfg, at):
    out = limited(cfg, "tax", text="usage limit reached")
    assert out.note == "usage limit reached" and store.retries(cfg) == [] and limits.paused_until(cfg) is None


def test_retries_wait_for_the_reset_then_run_one_at_a_time_most_important_first(cfg, at):
    for name in ("research", "discounts", "debrief", "risk", "plan_keeper", "filings"):
        limited(cfg, name)
    ran = []

    def run(name):
        ran.append(name)
        log(cfg, name, limits.clock_now(), {"discounts": "failed", "research": "deferred"}.get(name, "ok"))

    at(RESET + timedelta(minutes=4))
    assert limits.fire(cfg, run) is None and ran == []
    at(RESET + timedelta(minutes=5))
    done = [limits.fire(cfg, run) for _ in range(7)]
    assert done == [("plan_keeper", "ok"), ("risk", "ok"), ("debrief", "ok"), ("discounts", "failed"), ("research", "deferred"), ("filings", "ok"), None]
    assert ran == ["plan_keeper", "risk", "debrief", "discounts", "research", "filings"]
    assert {r["desk"]: r["status"] for r in store.retries(cfg)} == {
        "plan_keeper": "done",
        "risk": "done",
        "debrief": "done",
        "discounts": "failed",
        "research": "failed",
        "filings": "done",
    }


def test_a_busy_retry_stays_waiting_and_one_with_nothing_to_do_is_done(cfg, at):
    limited(cfg, "debrief")
    limited(cfg, "plans")
    at(RESET + timedelta(minutes=6))
    assert limits.fire(cfg, lambda name: log(cfg, name, limits.clock_now(), "busy")) == ("debrief", "busy")
    assert [r["status"] for r in store.retries(cfg)] == ["waiting", "waiting"]
    assert [limits.fire(cfg, lambda name: None) for _ in range(2)] == [("debrief", "nothing to do"), ("plans", "nothing to do")]

    def boom(name):
        raise RuntimeError("no engine")

    at(HIT)
    limited(cfg, "tax")
    at(RESET + timedelta(minutes=6))
    assert limits.fire(cfg, boom) == ("tax", "failed") and store.last_retry(cfg, "tax")["note"] == "RuntimeError: no engine"


def test_the_queue_command_fires_the_retry_with_the_real_run_command(cfg, at, monkeypatch, capsys):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(pipeline, "RealEngine", lambda: FakeEngine(SLICE))
    monkeypatch.setattr(pipeline, "RealDecisions", FakeDecisions)
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"plan_keeper": UsageLimitError(WEEKLY)}))
    assert cli.main(["run", "plan_keeper"]) == 75
    assert "Plan keeper: deferred" in capsys.readouterr().out
    assert store.requests(cfg) == [] and store.waiting_retry(cfg, "plan_keeper")["due_at"] == "2026-11-13T14:05:00+00:00"
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"plan_keeper": answer()}))
    assert cli.main(["queue", "--now-only"]) == 0 and "retry" not in capsys.readouterr().out
    at(RESET + timedelta(minutes=5))
    assert cli.main(["queue", "--now-only"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "retry after the limit reset: plan_keeper ok" and out[-2] == "Plan keeper: ok, 0 proposals, 0 rejected."
    assert store.last_run(cfg, "plan_keeper")["trigger"] == "retry" and store.last_retry(cfg, "plan_keeper")["status"] == "done"


def test_a_retry_that_hits_the_limit_again_is_not_retried_a_second_time(cfg, at):
    limited(cfg, "strategy")
    at(RESET + timedelta(minutes=5))
    later = "You've hit your session limit · resets 2pm"
    assert limits.fire(cfg, lambda name: limited(cfg, name, text=later)) == ("strategy", "deferred")
    assert [r["status"] for r in store.retries(cfg)] == ["failed"] and limits.paused_until(cfg) == datetime(2026, 11, 13, 19, 0, tzinfo=UTC)
    at(RESET + timedelta(hours=1))
    assert run_desk(get("strategy"), "s", "p", cfg=cfg, adapter=FakeAdapter()).note.endswith("The desk tries again at 2:05 PM.")


def test_written_cases_for_rows_on_sale_come_back_with_the_discount_retry(cfg, at, monkeypatch, capsys):
    import desk.opportunities.night as night

    seen = []
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(night, "list_cases_step", lambda cfg: seen.append("list") or {"status": "ok", "note": "This run wrote 3 of 3 cases for rows on sale."})
    cli._retry(cfg, "discounts")
    cli._retry(cfg, "debrief")
    assert seen == [["run", "discounts", "--trigger", "retry"], "list", ["run", "debrief", "--trigger", "retry"]]
    assert capsys.readouterr().out.strip() == "Cases for rows on sale: ok. This run wrote 3 of 3 cases for rows on sale."


def test_a_busy_scheduled_run_still_queues_its_overnight_retry(cfg, at, monkeypatch, capsys):
    from desk.runlock import job_lock

    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(pipeline, "RealEngine", lambda: FakeEngine(SLICE))
    monkeypatch.setattr(pipeline, "RealDecisions", FakeDecisions)
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"plan_keeper": answer()}))
    monkeypatch.setattr(cli, "RUN_WAIT", 0)
    with job_lock("agents", cfg=cfg):
        assert cli.main(["run", "plan_keeper"]) == 75
    assert [r["source"] for r in store.requests(cfg)] == ["retry"] and store.retries(cfg) == []


# ---- What the app is told ----


def test_status_says_what_waits_and_in_what_order(cfg, at):
    assert crew(cfg, HIT)["limit"] | {"order": []} == {"paused": False, "paused_until": None, "scope": None, "retries": [], "order": [], "line": None}
    for name in ("research", "debrief", "plan_keeper"):
        limited(cfg, name)
    told = crew(cfg, HIT + timedelta(minutes=1))
    assert told["limit"]["paused"] and told["limit"]["paused_until"] == "2026-11-13T14:00:00+00:00" and told["limit"]["scope"] == "week"
    assert [r["desk"] for r in told["limit"]["retries"]] == ["plan_keeper", "debrief", "research"]
    assert (
        told["limit"]["line"]
        == "Claude's limit is used up until 9:00 AM. Scheduled desk work waits. Then, in this order: Plan keeper, Debrief desk, Research desk."
    )
    assert told["limit"]["order"][:5] == ["plan_keeper", "risk", "debrief", "discounts", "research"]
    rows = {d["desk"]: d for d in told["desks"]}
    assert rows["debrief"]["retry_at"] == "2026-11-13T14:05:00+00:00" and rows["tax"]["retry_at"] is None
    after = crew(cfg, RESET + timedelta(minutes=1))["limit"]
    assert not after["paused"] and after["line"] == "Catching up after Claude's limit, in this order: Plan keeper, Debrief desk, Research desk."
    evening = crew(cfg, HIT - timedelta(hours=8))["limit"]["line"]
    assert evening.startswith("Claude's limit is used up until tomorrow at 9:00 AM.")


def test_usage_sums_each_desk_by_eastern_day(cfg, at):
    log(cfg, "research", datetime(2026, 11, 12, 4, 30, tzinfo=UTC), cost=1.25, out=9000)
    log(cfg, "research", datetime(2026, 11, 12, 6, 0, tzinfo=UTC), cost=0.75, out=5000)
    log(cfg, "plan_keeper", datetime(2026, 11, 12, 22, 30, tzinfo=UTC), cost=0.2, out=800)
    log(cfg, "debrief", datetime(2026, 11, 13, 10, 40, tzinfo=UTC), "deferred", note=WEEKLY)
    log(cfg, "tax", datetime(2026, 11, 13, 7, 0, tzinfo=UTC), "over_budget")
    log(cfg, "scout", datetime(2026, 11, 1, 7, 0, tzinfo=UTC), cost=9.0)
    got = limits.usage(cfg, 8, datetime(2026, 11, 13, 16, 0, tzinfo=UTC))
    assert got["since"] == "2026-11-06T00:00:00-05:00" and got["unit"] == "usd_estimate"
    rows = {(r["day"], r["desk"]): r for r in got["rows"]}
    assert set(rows) == {
        ("2026-11-11", "research"),
        ("2026-11-12", "research"),
        ("2026-11-12", "plan_keeper"),
        ("2026-11-13", "debrief"),
        ("2026-11-13", "tax"),
    }
    assert (rows[("2026-11-11", "research")]["cost_estimate"], rows[("2026-11-12", "research")]["output_tokens"]) == (1.25, 5000)
    assert (rows[("2026-11-13", "debrief")]["deferred"], rows[("2026-11-13", "tax")]["skipped"]) == (1, 1)
    assert [d["desk"] for d in got["desks"]][:2] == ["research", "plan_keeper"] and got["desks"][0]["minutes"] == 4.0
    assert (got["total"]["runs"], got["total"]["ok"], got["total"]["cost_estimate"]) == (5, 3, 2.2)
    assert [d["day"] for d in got["days"]] == ["2026-11-11", "2026-11-12", "2026-11-13"]


def test_the_usage_route_and_command(cfg, monkeypatch, capsys):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from desk.agents.api import router
    from desk.api.deps import get_cfg

    log(cfg, "risk", datetime.now(UTC) - timedelta(hours=30), cost=0.5)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_cfg] = lambda: cfg
    client = TestClient(app)
    assert client.get("/api/agents/usage?days=3").json()["total"]["cost_estimate"] == 0.5
    assert client.get("/api/agents/usage?days=0").status_code == 422
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    assert cli.main(["usage", "--days", "3"]) == 0 and json.loads(capsys.readouterr().out)["desks"][0]["desk"] == "risk"


# ---- The debrief note on Results ----


def test_a_debrief_waiting_on_its_retry_is_due_until_the_retry_fails(cfg, at):
    stale = HIT - timedelta(hours=7)
    view = {"kind": "day", "end": "2026-11-12", "closed": True, "computed_at": stale.isoformat(), "debrief": {"written_at": stale.isoformat(), "stale": True}}
    box = FakeReviews([pack_row(end="2026-11-12", digest="d2", debrief_digest="d1")], shown=view)
    kw = {"reviews": box, "decisions": FakeDecisions(profile_data=ON)}
    assert debrief.rewrite(cfg, "day", now=HIT, **kw)["rewrite"]["state"] == "late"
    limited(cfg, "debrief")
    told = debrief.rewrite(cfg, "day", now=HIT + timedelta(hours=3), **kw)["rewrite"]
    assert told == {"state": "due", "due_at": "2026-11-13T09:05:00-05:00", "words": None}
    at(RESET + timedelta(minutes=6))
    limits.fire(cfg, lambda name: log(cfg, name, limits.clock_now(), "deferred"))
    told = debrief.rewrite(cfg, "day", now=RESET + timedelta(minutes=7), **kw)["rewrite"]
    assert told["state"] == "failed" and told["words"].endswith("The rewrite did not finish; the desk tries again at 5:46 PM.")
