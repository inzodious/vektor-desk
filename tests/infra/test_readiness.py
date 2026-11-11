from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from desk import jobrun, readiness, startrun
from desk.api.app import create_app
from desk.scheduler import all_jobs, make_job

KEYS = [
    "bridge.value",
    "bridge.brief",
    "results.day",
    "results.week",
    "results.month",
    "results.year",
    "results.debrief",
    "portfolio.holdings",
    "portfolio.stock_plans",
    "portfolio.risk",
    "portfolio.tax",
    "strategies.race",
    "strategies.mixes",
    "strategies.habits",
    "decisions.queue",
    "decisions.journal",
    "research.feed",
    "research.boards",
    "settings.risk_check",
]
NY = ZoneInfo("America/New_York")
WED = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)


def sections(client):
    body = client.get("/api/readiness").json()
    return body, {row["key"]: row for row in body["sections"]}


def well_formed(rows):
    for row in rows.values():
        assert set(row) == {"key", "state", "why", "action", "next_auto", "next_auto_text"}
        assert row["state"] in ("ready", "empty", "stale", "blocked")
        if row["state"] == "ready":
            assert row["why"] is None and row["action"] is None
        else:
            assert row["why"] and row["action"]["kind"] in ("start", "job", "link") and row["action"]["label"]
            assert set(row["action"]) == {"start": {"kind", "label"}, "job": {"kind", "job", "label"}, "link": {"kind", "to", "label"}}[row["action"]["kind"]]


def test_a_desk_that_never_ran_points_every_empty_section_at_start(cfg):
    with TestClient(create_app(cfg)) as client:
        body, rows = sections(client)
    assert [row["key"] for row in body["sections"]] == KEYS and body["start"] == {"state": "idle", "needs_start": True}
    well_formed(rows)
    assert rows["bridge.value"] == {
        "key": "bridge.value",
        "state": "empty",
        "why": "Your accounts haven't been pulled yet.",
        "action": {"kind": "start", "label": "Start the desk"},
        "next_auto": None,
        "next_auto_text": None,
    }
    assert rows["results.day"]["why"] == "It needs today's numbers first." and rows["results.day"]["action"]["kind"] == "start"
    assert rows["results.debrief"]["why"] == "It needs the results review first."
    assert rows["settings.risk_check"]["state"] == "blocked" and rows["settings.risk_check"]["action"] == {
        "kind": "link",
        "to": "/settings/risk",
        "label": "Answer it",
    }
    assert rows["research.boards"]["state"] == "ready"
    assert {k for k, row in rows.items() if row["state"] == "ready"} <= {"decisions.journal", "research.boards"}
    journal = rows["decisions.journal"]
    assert journal["state"] == "ready" or journal["action"] == {"kind": "link", "to": "/decisions", "label": "Open the queue"}


def test_after_the_numbers_and_the_review_each_section_names_its_one_action(demo_cfg):
    from desk.engine.__main__ import JOBS

    with TestClient(create_app(demo_cfg)) as client:
        assert JOBS["daily"](demo_cfg)["ok"] and JOBS["review"](demo_cfg)["ok"]
        body, rows = sections(client)
        well_formed(rows)
        assert body["start"]["needs_start"] is False
        ready = [k for k, row in rows.items() if row["state"] == "ready"]
        assert {
            "bridge.value",
            "results.day",
            "results.week",
            "results.month",
            "results.year",
            "portfolio.holdings",
            "portfolio.risk",
            "portfolio.tax",
            "strategies.habits",
        } <= set(ready)
        brief = rows["bridge.brief"]
        assert (
            brief["state"] == "blocked"
            and brief["why"] == "All desks are switched off."
            and brief["action"] == {"kind": "link", "to": "/settings/crew", "label": "Switch the desks on"}
        )
        assert rows["results.debrief"]["state"] == "blocked" and rows["decisions.queue"]["state"] == "blocked" and brief["next_auto"] is None
        mixes = rows["strategies.mixes"]
        assert mixes["state"] == "empty" and mixes["action"] == {"kind": "job", "job": "engine-french", "label": "Fetch market history now"}
        assert mixes["why"] == "No mixes yet: they need the monthly market history." and mixes["next_auto"] and mixes["next_auto_text"]
        race = rows["strategies.race"]
        assert (
            race["action"] == {"kind": "job", "job": "engine-paper", "label": "Run the paper race now"}
            and race["why"] == "No strategies are paper trading yet."
        )
        jobrun.record(demo_cfg, "engine-paper", {"result": "failed", "finished": "2026-11-11T13:00:00Z", "error": "Alpaca said no", "note": None})
        again = sections(client)[1]["strategies.race"]
        assert again["why"] == "The last try stopped: Alpaca said no" and again["action"]["label"] == "Try again"
        jobrun.record(
            demo_cfg,
            "engine-paper",
            {"result": "ok", "finished": "2026-11-11T13:00:00Z", "error": None, "note": "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set"},
        )
        keys = sections(client)[1]["strategies.race"]
        assert keys["state"] == "blocked" and keys["action"] == {"kind": "link", "to": "/settings/data", "label": "Add the Alpaca paper keys"}


def test_a_package_can_sharpen_its_own_section(cfg, monkeypatch):
    class Hook:
        @staticmethod
        def sections(cfg):
            return {
                "research.boards": {
                    "state": "empty",
                    "why": "No boards pinned yet.",
                    "action": {"kind": "link", "to": "/strategies", "label": "Pin one"},
                    "junk": 1,
                }
            }

    monkeypatch.setattr(readiness, "seam", lambda pkg, module: Hook if pkg == "engine" else None)
    with TestClient(create_app(cfg)) as client:
        row = sections(client)[1]["research.boards"]
    assert row["state"] == "empty" and row["action"]["to"] == "/strategies" and "junk" not in row


def test_next_run_times_read_like_a_person_says_them():
    jobs = [
        make_job("a", "35 8 * * 1-5", ["true"], name="engine-review"),
        make_job("b", "35,45 17 * * 1-5", ["true"], name="engine-review"),
        make_job("c", "30 3 2 * *", ["true"], name="engine-french"),
    ]
    due = readiness.next_due(jobs, "engine-review", WED, NY)
    assert due == datetime(2026, 11, 11, 17, 35, tzinfo=NY) and readiness.when_text(due, WED, NY) == "today at 5:35 PM"
    friday_night = datetime(2026, 11, 14, 3, 0, tzinfo=UTC)
    monday = readiness.next_due(jobs, "engine-review", friday_night, NY)
    assert monday == datetime(2026, 11, 16, 8, 35, tzinfo=NY) and readiness.when_text(monday, friday_night, NY) == "Mon at 8:35 AM"
    french = readiness.next_due(jobs, "engine-french", WED, NY)
    assert readiness.when_text(french, WED, NY) == "Dec 2 at 3:30 AM" and readiness.next_due(jobs, "nope", WED, NY) is None
    tuesday_evening = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
    assert readiness.when_text(readiness.next_due(jobs, "engine-review", tuesday_evening, NY), tuesday_evening, NY) == "tomorrow at 8:35 AM"


def test_every_section_job_and_chain_job_is_really_scheduled():
    names = {j.name for j in all_jobs()}
    assert {s.job for s in readiness.SECTIONS if s.job} <= names
    assert {s.job for s in startrun.STEPS} <= names
