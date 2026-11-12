import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from desk.agents import store
from desk.opportunities import __main__ as cli
from desk.opportunities import build as ob
from desk.opportunities import night
from tests.opportunities.test_build import AS_OF, seed, signal

NOW = datetime(2026, 11, 7, 7, 0, tzinfo=UTC)


def cases_report(status="ok", written=("a", "b"), pending=2, note=None):
    return SimpleNamespace(status=status, written=list(written), failed=[], pending=pending, note=note)


def scout_report(status="ok", created=1, note=None):
    return SimpleNamespace(status=status, created=[{}] * created, note=note)


def fakes(calls, cases=None, scout=None):
    def run_cases(cfg, *, trigger, wait):
        calls.append(("cases", trigger))
        return cases or cases_report()

    def run_scout(cfg, name, *, trigger, wait):
        calls.append((name, trigger))
        return scout or scout_report()

    def run_scan(cfg):
        calls.append(("scan", None))
        return {"scanned": 20, "hits": 2}

    return {"cases": run_cases, "scout": run_scout, "scan": run_scan}


def scout_run(cfg, status, days_ago, now=NOW):
    rid = store.start_run(cfg, "scout", trigger="schedule", model="opus", effort="xhigh", status=status)
    stamp = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    with store.db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET started_at=?, finished_at=? WHERE id=?", (stamp, stamp, rid))


def test_the_night_scans_when_stale_writes_cases_and_runs_an_overdue_scout(cfg):
    seed(cfg)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert calls == [("scan", None), ("cases", "schedule"), ("scout", "schedule")]
    assert out["status"] == "ok" and [s["step"] for s in out["steps"]] == ["scan", "cases", "scout"]
    assert out["summary"] == "Scanned 20 names, 2 hits. Wrote 2 of 2 discount cases. Scout wrote 1 idea."
    assert night.last_night(cfg)["status"] == "ok"
    fresh = ob.build(cfg, now=NOW)["freshness"]
    assert fresh["night_status"] == "ok" and fresh["night_run_at"] == "2026-11-07T07:00:00Z"


def test_a_current_scan_and_a_recent_scout_are_left_alone(cfg):
    conn = seed(cfg)
    signal(conn, "QUAL", day=AS_OF)
    scout_run(cfg, "ok", 10)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert calls == [("cases", "schedule")]
    assert out["steps"][0]["status"] == "current" and out["steps"][2]["status"] == "fresh"
    assert "Scout last ran on Oct 28" in out["steps"][2]["note"] and out["status"] == "ok"


def test_scout_is_not_tried_twice_in_a_week_so_a_second_start_tonight_is_safe(cfg):
    seed(cfg)
    scout_run(cfg, "failed", 0.1)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert ("scout", "schedule") not in calls
    assert out["steps"][2] == {"step": "scout", "status": "over_budget", "note": "Scout already used this week's run."}


def test_a_busy_or_deferred_desk_leaves_the_night_waiting_and_the_reason_in_plain_words(cfg):
    seed(cfg)
    calls = []
    deferred = cases_report("deferred", (), 3, "Usage limit reached; resets at 9 AM.")
    out = night.run_night(cfg, now=NOW, **fakes(calls, cases=deferred, scout=scout_report("disabled", 0, "Switched off in Settings.")))
    assert out["status"] == "waiting"
    assert out["steps"][1]["note"] == "Usage limit reached; resets at 9 AM." and out["steps"][2]["note"] == "Switched off in Settings."


def test_a_desk_that_throws_does_not_stop_the_night(cfg):
    seed(cfg)

    def boom(cfg, **kw):
        raise RuntimeError("no token")

    out = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=boom, scout=lambda cfg, name, **kw: scout_report("ok", 0))
    assert out["status"] == "partial" and out["steps"][1]["status"] == "failed" and "no token" in out["steps"][1]["note"]
    assert out["steps"][2]["note"] == "Scout looked and proposed nothing."


def test_no_engine_yet_is_a_quiet_night(cfg):
    out = night.run_night(
        cfg,
        now=NOW,
        cases=lambda cfg, **kw: cases_report("not_ready", (), 0, "Discount scanner not ready."),
        scout=lambda *a, **kw: scout_report("not_ready", 0, "Engine brief not ready."),
    )
    assert out["steps"][0] == {"step": "scan", "status": "not_ready", "note": "The engine has not run yet."} and out["status"] == "ok"


def test_the_job_ends_with_the_line_the_morning_alert_reads(cfg, monkeypatch, capsys):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    monkeypatch.setattr("desk.config.Config.from_env", classmethod(lambda cls, env=None: cfg))
    monkeypatch.setattr(cli, "run_night", lambda cfg: night.run_night(cfg, now=NOW, **fakes([])))
    assert cli.main(["night"]) == 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(last) == {"ready"} and last["ready"].endswith("1 rated a buy") and len(last["ready"]) < 120 and "$" not in last["ready"]


def test_the_job_says_why_when_there_is_nothing_to_show(cfg, monkeypatch, capsys):
    monkeypatch.setattr("desk.config.Config.from_env", classmethod(lambda cls, env=None: cfg))
    quiet = {
        "cases": lambda cfg, **kw: cases_report("not_ready", (), 0, "Discount scanner not ready."),
        "scout": lambda *a, **kw: scout_report("not_ready", 0, "Engine brief not ready."),
    }
    monkeypatch.setattr(cli, "run_night", lambda cfg: night.run_night(cfg, now=NOW, **quiet))
    assert cli.main(["night"]) == 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last == {"skipped": "The engine has not run yet. Discount scanner not ready. Engine brief not ready."}


def test_the_job_joins_the_night_s_order_after_the_portfolio_pass():
    from desk.opportunities.jobs import JOBS
    from desk.scheduler import package_jobs

    assert JOBS[0]["overnight"] == 210 and JOBS[0]["command"] == "python -m desk.opportunities night"
    job = next(j for j in package_jobs(["opportunities"]))
    assert job.name == "opportunities-night" and job.title == "Work up tonight's buying opportunities"
