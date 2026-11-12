import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from desk.agents import store
from desk.opportunities import __main__ as cli
from desk.opportunities import build as ob
from desk.opportunities import cases as own_cases
from desk.opportunities import night
from tests.opportunities.test_build import AS_OF, RULES, seed, signal

NOW = datetime(2026, 11, 7, 7, 0, tzinfo=UTC)


def cases_report(status="ok", written=("a", "b"), pending=2, note=None):
    return SimpleNamespace(status=status, written=list(written), failed=[], pending=pending, note=note)


def scout_report(status="ok", created=1, note=None):
    return SimpleNamespace(status=status, created=[{}] * created, note=note)


def fakes(calls, cases=None, scout=None):
    def run_cases(cfg, *, trigger, wait, discounts=None, limit=None):
        if discounts is not None:
            calls.append(("list_cases", limit))
            return cases_report(written=(), pending=limit, note="Switched off for the test.") if cases is None else cases
        calls.append(("cases", trigger))
        return cases or cases_report()

    def run_scout(cfg, name, *, trigger, wait):
        calls.append((name, trigger))
        return scout or scout_report()

    def run_scan(cfg):
        calls.append(("scan", None))
        return {"scanned": 20, "hits": 2}

    return {"cases": run_cases, "scout": run_scout, "scan": run_scan}


def step(out, name):
    return next(s for s in out["steps"] if s["step"] == name)


def scout_run(cfg, status, days_ago, now=NOW):
    rid = store.start_run(cfg, "scout", trigger="schedule", model="opus", effort="xhigh", status=status)
    stamp = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    with store.db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET started_at=?, finished_at=? WHERE id=?", (stamp, stamp, rid))


def test_the_night_scans_when_stale_writes_cases_and_runs_an_overdue_scout(cfg):
    seed(cfg)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert calls == [("scan", None), ("cases", "schedule"), ("list_cases", 1), ("scout", "schedule")]
    assert out["status"] == "ok" and [s["step"] for s in out["steps"]] == ["scan", "cases", "list_cases", "scout"]
    assert out["summary"] == "Scanned 20 names, 2 hits. This run wrote 2 of 2 discount cases. Switched off for the test. Scout wrote 1 idea."
    assert night.last_night(cfg)["status"] == "ok"
    fresh = ob.build(cfg, now=NOW)["freshness"]
    assert fresh["night_status"] == "ok" and fresh["night_run_at"] == "2026-11-07T07:00:00Z"


def test_a_current_scan_and_a_recent_scout_are_left_alone(cfg):
    conn = seed(cfg)
    signal(conn, "QUAL", day=AS_OF)
    scout_run(cfg, "ok", 10)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert calls == [("cases", "schedule"), ("list_cases", 1)]
    assert out["steps"][0]["status"] == "current" and step(out, "scout")["status"] == "fresh"
    assert "Scout last ran on Oct 28" in step(out, "scout")["note"] and out["status"] == "ok"


def test_scout_is_not_tried_twice_in_a_week_so_a_second_start_tonight_is_safe(cfg):
    seed(cfg)
    scout_run(cfg, "failed", 0.1)
    calls = []
    out = night.run_night(cfg, now=NOW, **fakes(calls))
    assert ("scout", "schedule") not in calls
    assert step(out, "scout") == {"step": "scout", "status": "over_budget", "note": "Scout already used this week's run."}


def test_a_busy_or_deferred_desk_leaves_the_night_waiting_and_the_reason_in_plain_words(cfg):
    seed(cfg)
    calls = []
    deferred = cases_report("deferred", (), 3, "Usage limit reached; resets at 9 AM.")
    out = night.run_night(cfg, now=NOW, **fakes(calls, cases=deferred, scout=scout_report("disabled", 0, "Switched off in Settings.")))
    assert out["status"] == "waiting"
    assert out["steps"][1]["note"] == "Usage limit reached; resets at 9 AM." and step(out, "scout")["note"] == "Switched off in Settings."
    assert step(out, "list_cases") == {"step": "list_cases", "status": "deferred"} and all(c[0] != "list_cases" for c in calls)


def test_a_desk_that_throws_does_not_stop_the_night(cfg):
    seed(cfg)

    def boom(cfg, **kw):
        raise RuntimeError("no token")

    out = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=boom, scout=lambda cfg, name, **kw: scout_report("ok", 0))
    assert out["status"] == "partial" and out["steps"][1]["status"] == "failed" and "no token" in out["steps"][1]["note"]
    assert step(out, "scout")["note"] == "Scout looked and proposed nothing." and step(out, "list_cases")["status"] == "failed"


def test_no_engine_yet_is_a_quiet_night(cfg):
    out = night.run_night(
        cfg,
        now=NOW,
        cases=lambda cfg, **kw: cases_report("not_ready", (), 0, "Discount scanner not ready."),
        scout=lambda *a, **kw: scout_report("not_ready", 0, "Engine brief not ready."),
    )
    assert out["steps"][0] == {"step": "scan", "status": "not_ready", "note": "The engine has not run yet."} and out["status"] == "ok"


# ---- Cases for rows the scanner did not flag ----


def writer(calls, verdict="buy"):
    def run_cases(cfg, *, trigger, wait, discounts=None, limit=None):
        if discounts is None:
            return cases_report(written=(), pending=0, note="No discount hits today.")
        hits = discounts.pending(cfg, limit)
        calls.append((trigger, wait, [h["symbol"] for h in hits]))
        for h in hits:
            case = {"verdict": verdict, "case": f"{h['symbol']} fell with its sector.", "risks": "The sector may keep falling.", "confidence": 0.6}
            case |= {"horizon_days": 90, "numbers_cited": ["drop_from_high_pct"], "model": "opus", "written_at": NOW.isoformat(), "run_id": 3}
            discounts.record(cfg, h["signal_id"], case)
        return cases_report(written=[h["signal_id"] for h in hits], pending=len(hits))

    return run_cases


def quiet_scout(cfg, name, **kw):
    return scout_report("ok", 0)


def test_rows_on_sale_with_no_written_case_get_one_and_a_second_run_pays_for_nothing(cfg):
    seed(cfg)
    before = ob.build(cfg, now=NOW)
    assert [r["symbol"] for r in before["rows"] if r["stance"] == "screen"] == ["QUAL"]
    calls = []
    out = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=writer(calls), scout=quiet_scout)
    assert calls == [("schedule", night.CASES_WAIT, ["QUAL"])]
    assert step(out, "list_cases") == {
        "step": "list_cases",
        "status": "ok",
        "note": "This run wrote 1 of 1 cases for rows on sale.",
        "written": 1,
        "pending": 1,
    }
    r = next(r for r in ob.build(cfg, now=NOW)["rows"] if r["symbol"] == "QUAL")
    assert r["stance"] == "buy" and r["case"]["verdict"] == "buy" and "case" in r["sources"] and r["why_now"] == "QUAL fell with its sector."
    assert r["analysis_as_of"] == AS_OF and "The written case is from the same day." in r["as_of_words"]
    again = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=writer(calls), scout=quiet_scout)
    assert len(calls) == 1 and step(again, "list_cases")["status"] == "current"


def test_the_six_a_night_cap_counts_scanner_cases_too(cfg, monkeypatch):
    monkeypatch.setattr("desk.engine.preflight.rules_in_force", lambda cfg, plan: (RULES, "profile"))
    conn = seed(cfg)
    for i in range(5):
        signal(conn, f"S{i}", case="wait")
    with conn:
        conn.execute("UPDATE discount_cases SET written_at=?", ((NOW - timedelta(hours=1)).isoformat(),))
    assert [h["symbol"] for h in own_cases.wanted(ob.build(cfg, now=NOW))] == ["QUAL", "ACME", "WTCH"]
    calls = []
    out = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=writer(calls, "wait"), scout=quiet_scout)
    assert calls == [("schedule", night.CASES_WAIT, ["QUAL"])] and step(out, "list_cases")["written"] == 1
    out = night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=writer(calls, "wait"), scout=quiet_scout)
    assert len(calls) == 1 and step(out, "list_cases")["status"] == "over_budget"
    assert step(out, "list_cases")["note"] == "Tonight's 6 cases are written; 2 rows wait for tomorrow night."
    later = NOW + timedelta(hours=24)
    out = night.run_night(cfg, now=later, scan=lambda cfg: {}, cases=writer(calls, "wait"), scout=quiet_scout)
    assert calls[-1][2] == ["ACME", "WTCH"]


def test_the_night_s_lines_and_the_newest_case_time_can_be_read_from_the_list(cfg):
    conn = seed(cfg)
    signal(conn, "IVV", case="wait")
    assert ob.build(cfg, now=NOW)["freshness"]["last_case_at"] == "2026-11-07T02:00:00+00:00"
    night.run_night(cfg, now=NOW, scan=lambda cfg: {}, cases=writer([]), scout=quiet_scout)
    fresh = ob.build(cfg, now=NOW)["freshness"]
    assert fresh["last_case_at"] == NOW.isoformat()
    assert fresh["night_summary"] == "The discount scan is current to Nov 6. 2 cases written overnight. Scout looked and proposed nothing."
    assert {"step": "list_cases", "status": "ok", "note": "This run wrote 1 of 1 cases for rows on sale."} in fresh["night_steps"]
    from desk.opportunities import ready

    said = ready(cfg, now=NOW)
    assert said == "2 buying opportunities, 1 rated a buy; 2 cases written overnight" == night.last_night(cfg)["ready"]
    assert night.last_night(cfg)["cases_written"] == 2
    assert ready(cfg, now=NOW + timedelta(hours=30)) == "2 buying opportunities, 1 rated a buy"


def test_the_morning_line_is_the_one_the_night_recorded_so_it_is_never_listed_twice(cfg):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    out = night.run_night(cfg, now=NOW, **fakes([]))
    from desk.opportunities import line, ready

    assert out["ready"] == "1 buying opportunity, 1 rated a buy; 1 case written overnight"
    with conn:
        conn.execute("DELETE FROM discount_cases")
    assert line(cfg, now=NOW + timedelta(hours=4)) != out["ready"]
    assert ready(cfg, now=NOW + timedelta(hours=4)) == out["ready"]


def test_one_count_and_one_sentence_for_the_cases_written_overnight():
    steps = [
        {"step": "scan", "status": "current", "note": "The discount scan is current to Nov 11."},
        {"step": "cases", "status": "ok", "note": "No discount hits today."},
        {"step": "list_cases", "status": "ok", "note": "This run wrote 2 of 2 cases for rows on sale."},
        {"step": "scout", "status": "fresh", "note": "Scout last ran on Nov 11; it runs about once a month."},
    ]
    assert night.summary(steps, 3) == "The discount scan is current to Nov 11. 3 cases written overnight. Scout last ran on Nov 11; it runs about once a month."
    assert "No discount hits today. This run wrote 2 of 2" in night.summary(steps, 0)
    steps[2] = {"step": "list_cases", "status": "deferred", "note": "Usage limit reached; resets at 9 AM."}
    assert "1 case written overnight. Usage limit reached; resets at 9 AM." in night.summary(steps, 1)


def test_no_case_is_started_close_to_morning(cfg):
    seed(cfg)
    calls = []
    late = datetime(2026, 11, 7, 10, 45, tzinfo=UTC)
    out = night.run_night(cfg, now=late, scan=lambda cfg: {}, cases=writer(calls), scout=quiet_scout)
    assert calls == [] and step(out, "list_cases")["status"] == "late" and out["status"] == "ok"


def test_the_job_ends_with_the_line_the_morning_alert_reads(cfg, monkeypatch, capsys):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    monkeypatch.setattr("desk.config.Config.from_env", classmethod(lambda cls, env=None: cfg))
    monkeypatch.setattr(cli, "run_night", lambda cfg: night.run_night(cfg, now=NOW, **fakes([])))
    assert cli.main(["night"]) == 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        set(last) == {"ready", "detail"}
        and last["ready"].startswith("1 buying opportunity, 1 rated a buy")
        and len(last["ready"]) < 120
        and "$" not in last["ready"]
    )
    assert last["detail"] == night.last_night(cfg)["summary"] and last["detail"].startswith("The discount scan is current to Nov 6.")


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
