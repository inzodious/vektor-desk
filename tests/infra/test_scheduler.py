from datetime import datetime
from pathlib import Path

import pytest

from desk.scheduler import all_jobs, make_job, package_jobs, parse, reap, tick


def at(s):
    return datetime.fromisoformat(s)


def test_repo_crontab_parses_and_mirror_runs_twice_a_day():
    assert parse(Path("deploy/crontab").read_text()) == []
    (job,) = package_jobs(["mirror"])
    assert job.due(at("2026-11-09T08:00")) and job.due(at("2026-11-09T17:00"))
    assert not job.due(at("2026-11-09T08:01"))


def test_fields_steps_ranges_and_weekdays():
    (job,) = parse("*/15 1-5 * * 1-5 echo hi")
    assert job.due(at("2026-11-09T03:45"))
    assert not job.due(at("2026-11-08T03:45"))
    assert not job.due(at("2026-11-09T06:00"))
    (sunday,) = parse("0 9 * * 7 echo sun")
    assert sunday.due(at("2026-11-08T09:00"))


def test_day_of_month_or_weekday_like_cron():
    (job,) = parse("0 12 1 * 5 echo x")
    assert job.due(at("2026-12-01T12:00"))
    assert job.due(at("2026-11-13T12:00"))
    assert not job.due(at("2026-11-12T12:00"))


def test_bad_lines_fail_loudly():
    with pytest.raises(ValueError):
        parse("61 * * * * echo")
    with pytest.raises(ValueError):
        parse("0 8 * *")


def test_skips_a_job_that_is_still_running():
    (job,) = parse("* * * * * sleep 2")
    assert tick([job], at("2026-11-09T08:00"))
    assert not tick([job], at("2026-11-09T08:01"))
    job.proc.wait()
    assert tick([job], at("2026-11-09T08:02"))
    job.proc.wait()


def test_a_job_that_runs_every_minute_gives_way_to_a_fuller_one_with_the_same_lock():
    minutely = make_job("m", "* * * * *", ["sleep", "0.2"], name="agents-queue-now-only", lock="agents-agents-queue")
    hourly = make_job("h", "30 1-5 * * *", ["sleep", "0.2"], name="agents-queue", lock="agents-agents-queue")
    other = make_job("o", "* * * * *", ["true"], name="engine-quotes", lock="engine-engine-quotes")
    jobs = [minutely, hourly, other]
    assert [j.name for j in tick(jobs, datetime(2026, 11, 12, 4, 30))] == ["agents-queue", "engine-quotes"]
    for job in jobs:
        if job.proc is not None:
            job.proc.wait()
    reap(jobs)
    assert [j.name for j in tick(jobs, datetime(2026, 11, 12, 4, 31))] == ["agents-queue-now-only", "engine-quotes"]
    for job in jobs:
        if job.proc is not None:
            job.proc.wait()
    reap(jobs)
    real = {j.name: j for j in all_jobs()}
    assert real["agents-queue"].lock == real["agents-queue-now-only"].lock and real["agents-queue-now-only"].timing.startswith("* ")
