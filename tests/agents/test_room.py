from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from desk.agents import limits, store
from desk.agents.adapter import FakeAdapter
from desk.agents.desks import get
from desk.agents.runner import room, run_desk
from desk.agents.status import _free, next_run, week_of

ET = ZoneInfo("America/New_York")
FRIDAY = datetime(2026, 11, 13, 18, 10, tzinfo=ET)
SATURDAY = datetime(2026, 11, 14, 2, 0, tzinfo=ET)


@pytest.fixture
def at(monkeypatch):
    moment = {"now": FRIDAY.astimezone(UTC)}
    monkeypatch.setenv("TZ", "America/New_York")
    monkeypatch.setattr(limits, "clock_now", lambda: moment["now"])
    return lambda t: moment.update(now=t.astimezone(UTC))


def stamp(cfg, run_id, when):
    with store.db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET started_at=? WHERE id=?", (when.astimezone(UTC).isoformat(timespec="seconds"), run_id))
    return run_id


def ran(cfg, desk, when, trigger="trigger", status="ok"):
    return stamp(cfg, store.start_run(cfg, desk, trigger=trigger, model="opus", effort="high", status=status), when)


def go(cfg, name, trigger, when=None):
    out = run_desk(get(name), "s", "p", cfg=cfg, adapter=FakeAdapter(), trigger=trigger)
    if when is not None:
        stamp(cfg, out.run_id, when)
    return out


# ---- Risk keeps one run for its Saturday check ----


def test_triggers_stop_at_two_so_the_saturday_check_still_runs(cfg, at):
    ran(cfg, "risk", datetime(2026, 11, 10, 9, 41, tzinfo=ET))
    ran(cfg, "risk", datetime(2026, 11, 12, 17, 46, tzinfo=ET))
    refused = go(cfg, "risk", "trigger")
    assert refused.status == "over_budget"
    assert refused.note == "This week's 2 extra runs are used. One run is kept for the scheduled check. The next one is free on Tuesday at 9:41 AM."
    assert go(cfg, "risk", "lab").status == "over_budget"
    at(SATURDAY)
    assert go(cfg, "risk", "schedule", SATURDAY).status == "ok"
    assert store.week_usage(cfg, "risk", SATURDAY.astimezone(UTC))["runs"] == 3
    again = go(cfg, "risk", "retry")
    assert again.status == "over_budget" and again.note == "This week's scheduled check has already run. The next one is free on Friday at 8:00 PM."


def test_a_trigger_slot_comes_back_seven_days_after_the_run_that_used_it(cfg, at):
    ran(cfg, "risk", datetime(2026, 11, 10, 9, 41, tzinfo=ET))
    ran(cfg, "risk", datetime(2026, 11, 12, 17, 46, tzinfo=ET))
    at(datetime(2026, 11, 17, 9, 40, tzinfo=ET))
    assert go(cfg, "risk", "trigger").status == "over_budget"
    at(datetime(2026, 11, 17, 9, 42, tzinfo=ET))
    assert go(cfg, "risk", "trigger").status == "ok"


def test_next_saturdays_check_is_not_refused_for_starting_a_few_seconds_early(cfg, at):
    ran(cfg, "risk", SATURDAY + timedelta(seconds=40), trigger="schedule")
    ran(cfg, "risk", datetime(2026, 11, 17, 9, 41, tzinfo=ET))
    ran(cfg, "risk", datetime(2026, 11, 19, 17, 46, tzinfo=ET))
    at(SATURDAY + timedelta(days=7, seconds=5))
    assert go(cfg, "risk", "schedule").status == "ok"


def test_runs_that_did_not_reach_claude_use_no_slot(cfg, at):
    for status in ("deferred", "busy", "over_budget", "unchanged"):
        ran(cfg, "risk", datetime(2026, 11, 12, 17, 46, tzinfo=ET), status=status)
    assert room(cfg, get("risk"), "trigger")["runs"] == 0 and go(cfg, "risk", "trigger").status == "ok"


# ---- What the page is told ----


def test_the_risk_tile_says_when_an_extra_run_is_free_and_that_saturday_is_safe(cfg, at):
    ran(cfg, "risk", datetime(2026, 11, 10, 9, 41, tzinfo=ET))
    ran(cfg, "risk", datetime(2026, 11, 12, 17, 46, tzinfo=ET))
    now, risk = FRIDAY.astimezone(UTC), get("risk")
    week = week_of(cfg, risk, now)
    assert (week["runs"], week["cap"], week["frees_at"]) == (2, 3, "2026-11-17T14:41:00+00:00")
    assert week["line"] == "This week's 2 extra runs are used. The next one is free on Tuesday at 9:41 AM. The scheduled check keeps its own run."
    assert next_run(risk, now, ET, _free(cfg, risk, now)) == "2026-11-14T02:00:00-05:00"
    ran(cfg, "risk", SATURDAY, trigger="schedule")
    later = (SATURDAY + timedelta(hours=1)).astimezone(UTC)
    assert next_run(risk, later, ET, _free(cfg, risk, later)) == "2026-11-21T02:00:00-05:00"


def test_a_desk_at_its_cap_says_the_day_and_next_skips_the_runs_the_cap_would_refuse(cfg, at):
    tax, now = get("tax"), FRIDAY.astimezone(UTC)
    assert week_of(cfg, tax, now)["line"] is None and next_run(tax, now, ET, _free(cfg, tax, now)) == "2026-11-15T02:00:00-05:00"
    for hour in range(8):
        ran(cfg, "tax", datetime(2026, 11, 12, 10 + hour, 0, tzinfo=ET))
    week = week_of(cfg, tax, now)
    assert week["line"] == "This week's 8 runs are used. The next one is free on Thursday at 10:00 AM."
    assert week["frees_at"] == "2026-11-19T15:00:00+00:00"
    assert next_run(tax, now, ET, _free(cfg, tax, now)) == "2026-11-22T02:00:00-05:00"
    refused = go(cfg, "tax", "schedule")
    assert refused.status == "over_budget" and refused.note == "Weekly cap of 8 runs reached. The next one is free on Thursday at 10:00 AM."


def test_over_the_cap_the_free_time_waits_for_enough_runs_to_age_out(cfg, at):
    for n in range(12):
        ran(cfg, "plan_keeper", datetime(2026, 11, 11, 17, 30 + n, tzinfo=ET))
    now, keeper = FRIDAY.astimezone(UTC), get("plan_keeper")
    week = week_of(cfg, keeper, now)
    assert week["line"] == "Over this week's allowance until Wednesday at 5:32 PM, so extra runs wait. The daily check still runs once a day."
    assert week["frees_at"] == "2026-11-18T22:32:00+00:00"
    assert next_run(keeper, now, ET, _free(cfg, keeper, now)) == "2026-11-14T17:30:00-05:00"


def test_a_desk_with_one_run_a_week_says_run_not_runs(cfg, at):
    ran(cfg, "scout", datetime(2026, 11, 13, 9, 0, tzinfo=ET))
    assert week_of(cfg, get("scout"), FRIDAY.astimezone(UTC))["line"] == "This week's run is used. The next one is free on Friday, Nov 20 at 9:00 AM."
