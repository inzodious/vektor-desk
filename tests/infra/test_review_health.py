import dataclasses
import sqlite3
from datetime import UTC, datetime

from desk import jobrun, review_health
from desk.notify.ops import ops_check
from desk.scheduler import make_job
from desk.status import status
from tests.fakes import Res

WED_EVENING = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)
WED_RUN = "2026-11-11T22:36:00Z"
TUE_RUN = "2026-11-10T22:36:00Z"


class Ntfy:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append(json)
        return Res(200, {})


def table(cfg, rows, end="end"):
    cfg.desk_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(f'CREATE TABLE period_reviews (kind TEXT, start TEXT, "{end}" TEXT, closed INTEGER, pack TEXT, computed_at TEXT)')
    conn.executemany("INSERT INTO period_reviews VALUES (?, ?, ?, ?, '{}', ?)", rows)
    conn.commit()
    conn.close()


def ran(cfg, result, finished, name=review_health.JOB):
    jobrun.record(
        cfg, name, {"trigger": "schedule", "started": finished, "finished": finished, "result": result, "exit_code": 0 if result == "ok" else 1, "detail": None}
    )


def test_the_run_is_due_after_1735_eastern_on_weekdays_with_half_an_hour_of_grace(cfg):
    wed = datetime(2026, 11, 11, 22, 35, tzinfo=UTC)
    assert review_health.due(cfg, datetime(2026, 11, 11, 23, 5, tzinfo=UTC)) == wed
    assert review_health.due(cfg, datetime(2026, 11, 11, 23, 4, tzinfo=UTC)) == datetime(2026, 11, 10, 22, 35, tzinfo=UTC)
    assert review_health.due(cfg, datetime(2026, 11, 15, 15, 0, tzinfo=UTC)) == datetime(2026, 11, 13, 22, 35, tzinfo=UTC)
    assert review_health.due(cfg, datetime(2026, 7, 1, 22, 10, tzinfo=UTC)) == datetime(2026, 7, 1, 21, 35, tzinfo=UTC)


def test_reviews_are_empty_then_fresh_then_stale_then_failing(cfg):
    assert status(cfg, WED_EVENING)["reviews"]["state"] == "empty"
    table(
        cfg,
        [("day", "2026-11-11", "2026-11-11", 0, WED_RUN), ("day", "2026-11-10", "2026-11-10", 1, TUE_RUN), ("week", "2026-11-09", "2026-11-13", 0, WED_RUN)],
    )
    fresh = review_health.reviews_status(cfg, WED_EVENING)
    assert fresh["state"] == "ok" and fresh["due"] == "2026-11-11T22:35:00Z" and fresh["missing"] == ["month", "year"]
    assert fresh["kinds"]["day"] == {"through": "2026-11-11", "computed_at": WED_RUN, "periods": 2}
    thursday = datetime(2026, 11, 12, 23, 30, tzinfo=UTC)
    assert review_health.reviews_status(cfg, thursday)["state"] == "stale"
    ran(cfg, "ok", "2026-11-12T22:36:10Z")
    assert review_health.reviews_status(cfg, thursday)["state"] == "ok"
    ran(cfg, "skipped", "2026-11-13T22:35:02Z")
    friday = datetime(2026, 11, 13, 23, 30, tzinfo=UTC)
    assert review_health.reviews_status(cfg, friday)["state"] == "stale"
    ran(cfg, "failed", "2026-11-13T22:35:40Z")
    failing = review_health.reviews_status(cfg, friday)
    assert failing["state"] == "failing" and failing["last_ok"] == WED_RUN and failing["job"]["result"] == "failed"


def test_a_failed_first_run_is_failing_and_other_column_names_still_read(cfg):
    ran(cfg, "failed", WED_RUN)
    assert review_health.reviews_status(cfg, WED_EVENING)["state"] == "failing"
    table(cfg, [("day", "2026-11-11", "2026-11-11", 0, "2026-11-11 22:40:00")], end="end_date")
    report = review_health.reviews_status(cfg, WED_EVENING)
    assert report["state"] == "ok" and report["kinds"]["day"]["through"] == "2026-11-11"


def test_check_lines_name_the_fix_and_walk_the_stages(cfg):
    jobs = [
        make_job("a", "0 8 * * *", ["true"], name="mirror", package="mirror"),
        make_job("b", "20 17 * * *", ["true"], name="engine-daily", package="engine"),
        make_job("c", "35 17 * * 1-5", ["true"], name="engine-review", package="engine"),
        make_job("d", "50 17 * * 1-5", ["true"], name="agents-run-recap", package="agents", stage="desks", refreshes=("debrief",)),
        make_job("e", "*/5 * * * *", ["true"], name="engine-quotes", package="engine"),
    ]
    ok, out = review_health.lines(cfg, WED_EVENING, jobs)
    assert ok and out[0].startswith("No reviews yet")
    table(cfg, [("day", "2026-11-10", "2026-11-10", 1, TUE_RUN)])
    ran(cfg, "ok", "2026-11-11T22:00:10Z", "mirror")
    ran(cfg, "failed", "2026-11-11T22:52:00Z", "agents-run-recap")
    ok, out = review_health.lines(cfg, WED_EVENING, jobs)
    assert not ok and out[0].startswith("stale: last good run Tue Nov 10 17:36, but one was due at 17:35.") and "Run now" in out[0]
    assert out[1] == "day through 2026-11-10 (1)" and out[2] == "no week, month, year review yet"
    assert out[3:] == [
        "Today's run:",
        "  mirror: Mirror ok 17:00",
        "  engine: Engine daily not yet",
        "  review: Engine review not yet",
        "  desks: Agents run recap failed 17:52",
        "  paper: no job yet",
    ]
    entries = jobrun.catalogue(jobs)
    assert entries["agents-run-recap"].refreshes == ["debrief"] and entries["engine-review"].refreshes == ["reviews"]
    assert entries["engine-quotes"].stage is None and jobrun.describe(cfg, jobs)["stages"] == ["mirror", "engine", "review", "desks", "paper"]


def test_ops_alert_goes_out_once_a_day_while_reviews_are_behind(cfg):
    on = dataclasses.replace(cfg, ntfy_url="http://ntfy")
    ntfy = Ntfy()
    assert ops_check(on, WED_EVENING, session=ntfy) == []
    table(on, [("day", "2026-11-10", "2026-11-10", 1, TUE_RUN)])
    assert ops_check(on, WED_EVENING, session=ntfy) == ["reviews-stale"]
    assert ops_check(on, WED_EVENING, session=ntfy) == []
    assert ntfy.sent[-1]["title"] == "Today's review hasn't run" and "Run now on Review" in ntfy.sent[-1]["message"]
