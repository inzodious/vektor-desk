import json
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from desk import jobrun, startrun
from desk.api.app import create_app
from desk.scheduler import make_job, reap, start
from desk.startrun import Facts

NOW = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)
NO_ALPACA = "The Alpaca paper keys are not set. Add them in Settings, Data, Keys."
ALL = (
    "mirror",
    "engine-backfill",
    "engine-daily",
    "engine-french",
    "engine-review",
    "engine-discounts",
    "agents-run-plan_keeper",
    "agents-run-debrief",
    "engine-paper",
)
CREW_ON = {
    "enabled": True,
    "desks": [
        {"desk": "plan_keeper", "title": "Plan keeper", "enabled": True, "guarded": False, "last_run": None},
        {"desk": "debrief", "title": "Debrief desk", "enabled": False, "guarded": False, "last_run": None},
    ],
}
READY = Facts(accounts=True, numbers=True, closes_ok=True, market=False, reviews=True, claude="ok", crew=CREW_ON)


def jobs_for(tmp_path, scripts: dict[str, str] | None = None):
    scripts = scripts or {}
    order = tmp_path / "order"
    return [make_job(n, "0 0 1 1 *", ["sh", "-c", f"echo {n} >> {order}; {scripts.get(n, 'true')}"], name=n, package=n.split("-")[0]) for n in ALL]


def drive(cfg, jobs, known=READY, limit=60):
    def busy(name):
        return any(j.name == name and j.proc is not None for j in jobs)

    for _ in range(limit * 20):
        reap(jobs, cfg)
        chain = startrun.advance(cfg, jobs, lambda job, rid: start(job, cfg, "start", rid), busy, get_facts=lambda c, n: known)
        if chain and chain["state"] == "done":
            return chain
        time.sleep(0.05)
    raise AssertionError("the chain never finished")


def ask(cfg, jobs):
    jobrun.heartbeat(cfg)
    return startrun.request_start(cfg, jobs, "test")


def test_one_tap_runs_every_step_in_order_and_says_why_some_stopped(cfg, tmp_path):
    jobs = jobs_for(
        tmp_path,
        {
            "engine-discounts": """echo '{"ok": false, "error": "no universe yet"}' >&2; exit 1""",
            "engine-paper": f"""echo '{{"ok": true, "skipped": "{NO_ALPACA}", "skipped_code": "no_alpaca_keys"}}'""",
        },
    )
    code, body = ask(cfg, jobs)
    assert code == 202 and body["ok"] and body["state"] == "running" and [s["state"] for s in body["steps"]] == ["waiting"] * 9
    assert ask(cfg, jobs)[0] == 409
    chain = drive(cfg, jobs)
    assert (tmp_path / "order").read_text().split() == [
        "mirror",
        "engine-daily",
        "engine-french",
        "engine-review",
        "engine-discounts",
        "agents-run-plan_keeper",
        "engine-paper",
    ]
    view = startrun.describe(cfg, jobs, known=READY)
    got = {s["id"]: s for s in view["steps"]}
    assert [s["state"] for s in view["steps"]] == ["ok", "skipped", "ok", "ok", "ok", "failed", "ok", "skipped", "skipped"]
    assert got["prices"]["detail"] == "Price history is already complete." and got["prices"]["fix"] is None
    assert got["discounts"]["detail"] == "It stopped: no universe yet" and got["discounts"]["fix"] == {"label": "Open Box", "to": "/settings/box"}
    assert got["debrief"]["detail"] == "The Debrief desk is switched off." and got["debrief"]["fix"] == {"label": "Switch it on", "to": "/settings/crew"}
    assert got["paper"]["detail"] == NO_ALPACA and got["paper"]["fix"] == {"label": "Add the Alpaca paper keys", "to": "/settings/data"}
    assert jobrun.last_run(cfg, "engine-paper")["skipped_code"] == "no_alpaca_keys" and jobrun.last_run(cfg, "mirror")["skipped_code"] is None
    assert view["state"] == "done" and view["result"] == "partial" and view["summary"] == "6 of 9 steps done. 3 need you."
    assert chain["last_ok_at"] is None and jobrun.last_run(cfg, "mirror")["trigger"] == "start"
    assert set(view["steps"][0]) == {"id", "title", "state", "detail", "fix", "job", "started_at", "finished_at", "waiting"}


def test_a_clean_chain_clears_the_banner_and_a_new_one_can_start(cfg, tmp_path):
    jobs = jobs_for(tmp_path)
    fresh = startrun.describe(cfg, jobs, known=Facts())
    assert fresh["state"] == "idle" and fresh["needs_start"] and not fresh["can_start"] and fresh["blocked"]["error"] == "scheduler_down"
    assert startrun.request_start(cfg, jobs)[0] == 503
    assert ask(cfg, jobs)[0] == 202
    drive(cfg, jobs)
    jobrun.heartbeat(cfg)
    view = startrun.describe(cfg, jobs, known=Facts())
    assert view["result"] == "ok" and view["last_ok_at"] == view["finished_at"] and not view["needs_start"] and view["can_start"]
    assert view["summary"] == "8 of 9 steps done. 1 needs you."
    assert ask(cfg, jobs)[0] == 202
    assert startrun.describe(cfg, jobs, known=Facts())["last_ok_at"] == view["last_ok_at"]


def test_the_banner_stays_away_when_the_schedule_already_filled_the_desk(cfg, tmp_path):
    jobs = jobs_for(tmp_path)
    assert not startrun.describe(cfg, jobs, known=READY)["needs_start"]
    assert startrun.describe(cfg, jobs, known=Facts(accounts=True, numbers=True))["needs_start"]


def test_steps_that_cannot_run_are_skipped_with_the_screen_that_fixes_them(cfg, tmp_path):
    jobs = jobs_for(tmp_path, {"mirror": "exit 2"})
    ask(cfg, jobs)
    drive(cfg, jobs, Facts(claude="expired"))
    got = {s["id"]: s for s in startrun.describe(cfg, jobs, known=Facts())["steps"]}
    assert got["accounts"]["state"] == "failed" and got["accounts"]["fix"]["to"] == "/settings/box"
    assert got["prices"]["state"] == "skipped" and got["prices"]["detail"].startswith("It needs your accounts first")
    assert got["numbers"]["state"] == "skipped" and got["market"]["state"] == "ok"
    assert got["review"]["detail"] == "It needs today's numbers first." and got["review"]["fix"] is None
    assert (tmp_path / "order").read_text().split() == ["mirror", "engine-french"]
    off = Facts(accounts=True, numbers=True, market=True, crew={"enabled": False, "desks": []})
    assert startrun.skip_reason(startrun.BY_ID["plan_keeper"], off) == ("All desks are switched off.", {"label": "Switch the desks on", "to": "/settings/crew"})
    expired = Facts(accounts=True, numbers=True, claude="expired", crew=CREW_ON)
    assert startrun.skip_reason(startrun.BY_ID["plan_keeper"], expired)[1] == {"label": "Renew the token", "to": "/settings/data"}
    guarded = Facts(accounts=True, numbers=True, crew={"enabled": True, "desks": [{"desk": "plans", "title": "Plan desk", "enabled": True, "guarded": True}]})
    assert startrun.skip_reason(startrun.BY_ID["plans"], guarded)[1]["label"] == "Lift the guard"
    assert startrun.skip_reason(startrun.BY_ID["debrief"], Facts(accounts=True, numbers=True, crew=None)) == ("It needs the results review first.", None)
    assert startrun.skip_reason(startrun.BY_ID["market"], off) == ("Market history is already here.", None)


def test_a_desk_that_ended_without_writing_is_not_called_ok(cfg):
    step = startrun.BY_ID["plan_keeper"]
    run = {"result": "ok", "finished": "2026-11-11T14:05:00Z"}

    def crew(status, note):
        last = {"status": status, "note": note, "started_at": "2026-11-11T14:01:00+00:00"}
        return Facts(crew={"enabled": True, "desks": [{"desk": "plan_keeper", "title": "Plan keeper", "enabled": True, "last_run": last}]})

    assert startrun.outcome(step, run, crew("ok", None), NOW) == ("ok", None, None)
    assert startrun.outcome(step, run, crew("over_budget", "Weekly cap of 10 runs reached."), NOW) == ("skipped", "Weekly cap of 10 runs reached.", None)
    state, detail, fix = startrun.outcome(step, run, crew("failed", "The Claude token was refused."), NOW)
    assert state == "failed" and detail == "The Claude token was refused." and fix == {"label": "Check the Claude token", "to": "/settings/data"}
    earlier = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    assert startrun.outcome(step, run, crew("failed", "old"), earlier) == ("ok", None, None)
    assert startrun.outcome(step, {"result": "skipped"}, Facts(), NOW)[0] == "skipped"


def test_a_job_already_running_on_its_schedule_counts_as_the_step(cfg, tmp_path):
    jobs = jobs_for(tmp_path, {"mirror": "sleep 0.3"})
    start(jobs[0], cfg, "schedule")
    ask(cfg, jobs)
    chain = startrun.advance(
        cfg, jobs, lambda job, rid: start(job, cfg, "start", rid), lambda n: any(j.name == n and j.proc is not None for j in jobs), get_facts=lambda c, n: READY
    )
    assert chain["steps"][0]["state"] == "running" and chain["steps"][0]["adopted"] and chain["steps"][0]["request_id"] is None
    done = drive(cfg, jobs)
    assert done["steps"][0]["state"] == "ok" and (tmp_path / "order").read_text().split().count("mirror") == 1


def test_a_restart_in_the_middle_of_a_step_runs_it_once_more_then_gives_up(cfg, tmp_path):
    jobs = jobs_for(tmp_path)
    ask(cfg, jobs)
    started = []
    idle = lambda name: False  # noqa: E731
    lost = lambda job, rid: started.append(job.name)  # noqa: E731
    startrun.advance(cfg, jobs, lost, idle, get_facts=lambda c, n: READY)
    startrun.advance(cfg, jobs, lost, idle, get_facts=lambda c, n: READY)
    assert started == ["mirror", "mirror"]
    chain = startrun.advance(cfg, jobs, lost, idle, get_facts=lambda c, n: READY)
    first = chain["steps"][0]
    assert first["state"] == "failed" and first["detail"] == "The desk restarted while this was running." and started[2] == "engine-daily"


def test_the_api_serves_the_chain(cfg):
    with TestClient(create_app(cfg)) as client:
        idle = client.get("/api/start").json()
        assert idle["state"] == "idle" and idle["needs_start"] and [s["id"] for s in idle["steps"]] == [s.id for s in startrun.STEPS]
        assert idle["steps"][0] == {
            "id": "accounts",
            "title": "Pull your accounts",
            "state": "waiting",
            "detail": None,
            "fix": None,
            "job": "mirror",
            "started_at": None,
            "finished_at": None,
            "waiting": False,
        }
        assert client.post("/api/start").status_code == 503
        jobrun.heartbeat(cfg)
        res = client.post("/api/start")
        assert res.status_code == 202 and res.json()["state"] == "running" and res.json()["summary"] == "Step 1 of 10: Pull your accounts"
        again = client.post("/api/start")
        assert again.status_code == 409 and again.json()["error"] == "running" and again.json()["state"] == "running"
        assert json.loads(startrun.request_file(cfg).read_text())["client"] == "testclient"
        log = (cfg.data_dir / "run" / "job-requests.log").read_text().splitlines()
        assert [json.loads(line)["outcome"] for line in log] == ["scheduler_down", "queued", "running"]


def test_the_scheduler_keeps_what_a_job_said_last_without_secrets(cfg):
    token = "sk" + "A1b2" * 10
    fail = make_job(
        "a", "0 0 1 1 *", ["sh", "-c", f"""echo noise; echo '{{"ok": false, "error": "Alpaca 401 for key {token}"}}' >&2; exit 1"""], name="engine-paper"
    )
    crash = make_job("b", "0 0 1 1 *", ["sh", "-c", "echo 'sqlite3.OperationalError: database is locked' >&2; exit 1"], name="engine-daily")
    skip = make_job(
        "c",
        "0 0 1 1 *",
        ["sh", "-c", """echo '{"ok": true, "skipped": "The value series has under two days; run the daily engine first."}'"""],
        name="engine-review",
    )
    quiet = make_job("d", "0 0 1 1 *", ["true"], name="mirror")
    jobs = [fail, crash, skip, quiet]
    for j in jobs:
        start(j, cfg, "request")
    for j in jobs:
        j.proc.wait()
    reap(jobs, cfg)
    failed = jobrun.last_run(cfg, "engine-paper")
    assert failed["result"] == "failed" and failed["error"] == "Alpaca 401 for key …" and token not in json.dumps(failed) and "exit 1" in failed["detail"]
    assert jobrun.last_run(cfg, "engine-daily")["error"] == "sqlite3.OperationalError: database is locked"
    skipped = jobrun.last_run(cfg, "engine-review")
    assert skipped["result"] == "ok" and skipped["note"].startswith("The value series has under two days") and skipped["error"] is None
    assert jobrun.last_run(cfg, "mirror") | {"started": None, "finished": None} == {
        "trigger": "request",
        "request_id": None,
        "started": None,
        "finished": None,
        "result": "ok",
        "exit_code": 0,
        "detail": None,
        "note": None,
        "skipped_code": None,
        "error": None,
        "oom": None,
        "ready": None,
        "did": None,
        "said": None,
    }


def test_a_skip_code_picks_the_fix_and_the_words_are_only_the_fallback():
    keys = {"to": "/settings/data"}
    assert startrun.fix_for("Anything at all.", "no_fred_key") == keys | {"label": "Add the FRED key"}
    assert startrun.fix_for("Anything at all.", "no_sec_contact") == keys | {"label": "Add the SEC contact"}
    assert startrun.fix_for("Reworded since.", "no_alpaca_keys") == keys | {"label": "Add the Alpaca paper keys"}
    assert startrun.fix_for("Reworded since.", "no_finnhub_key") == keys | {"label": "Add the Finnhub key"}
    assert startrun.fix_for("The list of small companies is not built yet. Alpaca supplies it.", "no_small_companies") is None
    assert startrun.fix_for("The Alpaca paper keys are not set.", "a_code_from_a_newer_build") == keys | {"label": "Add the Alpaca paper keys"}
    assert startrun.fix_for(NO_ALPACA) == keys | {"label": "Add the Alpaca paper keys"} and startrun.fix_for("Nothing to do.") is None
    line = {"ok": True, "skipped": "The FRED key is not set. Add it in Settings, Data, Keys.", "skipped_code": "no_fred_key", "asked": 3}
    said = jobrun.last_words(json.dumps(line))
    assert said["skipped"] == line["skipped"] and said["skipped_code"] == "no_fred_key" and said["said"] == "ok: true; asked: 3"
    for odd in ("No Fred Key", "x" * 41, 7, None, ""):
        assert jobrun.last_words(json.dumps(line | {"skipped_code": odd}))["skipped_code"] is None
    assert jobrun.last_words(json.dumps({"ok": True, "skipped_code": "no_fred_key"}))["skipped_code"] is None


def test_every_entry_point_imports_on_its_own():
    import subprocess
    import sys

    for module in ("desk.agents.__main__", "desk.engine.__main__", "desk.scheduler", "desk.startrun", "desk.readiness", "desk.review_health", "desk.api.app"):
        res = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, f"{module}: {res.stderr[-400:]}"


def test_a_bug_in_the_chain_never_stops_the_scheduler(cfg, monkeypatch, capsys):
    from desk import scheduler

    def boom(*args, **kwargs):
        raise RuntimeError("chain bug")

    monkeypatch.setattr(startrun, "advance", boom)
    scheduler.run_chain([], cfg)
    assert "start chain stopped on an error" in capsys.readouterr().out
