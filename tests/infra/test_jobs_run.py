import json
from datetime import timedelta

from desk import jobrun
from desk.runlock import job_lock
from desk.scheduler import all_jobs, make_job, reap, serve_requests, tick


def test_every_job_has_a_stable_unique_name():
    names = [j.name for j in all_jobs(crontab="deploy/crontab")]
    entries = jobrun.catalogue(all_jobs(crontab="deploy/crontab"))
    assert {"mirror", "engine-daily", "engine-quotes", "engine-backfill", "decisions-sync", "notify-ops"} <= set(entries)
    assert all(jobrun.NAME.match(n) for n in names)
    assert entries["engine-daily"].schedules == ["20 8,17 * * *"]
    assert entries["engine-daily"].title == "Engine daily"
    tax = [j for j in all_jobs(["agents"], crontab="deploy/crontab") if j.name == "agents-run-tax"]
    if len(tax) > 1:
        assert len(jobrun.catalogue(tax)["agents-run-tax"].schedules) == len(tax)


def test_a_job_table_entry_can_name_itself(monkeypatch):
    from types import SimpleNamespace

    from desk import scheduler

    table = [{"name": "run-debrief", "title": "Debrief desk", "schedule": "0 9 * * *", "command": "true"}, ("0 8 * * *", "python -m desk.agents triggers")]
    monkeypatch.setattr(scheduler, "seams", lambda kind, only=None: {"agents": SimpleNamespace(JOBS=table)})
    named, plain = scheduler.package_jobs()
    assert (named.name, named.title) == ("agents-run-debrief", "Debrief desk")
    assert plain.title == jobrun.job_title(plain.name)
    assert jobrun.catalogue([named])["agents-run-debrief"].title == "Debrief desk"


def test_get_jobs_lists_each_job_with_its_state(app_client, cfg):
    client = app_client(packages=["mirror", "engine"])
    body = client.get("/api/jobs").json()
    assert set(body) == {"now", "scheduler_alive", "cooldown_seconds", "pickup_seconds", "stages", "low_memory", "jobs"}
    assert body["cooldown_seconds"] == 300 and body["scheduler_alive"] is False
    mirror = next(j for j in body["jobs"] if j["name"] == "mirror")
    assert mirror == {
        "name": "mirror",
        "title": "Mirror",
        "package": "mirror",
        "schedules": ["0 8,17 * * *"],
        "running": False,
        "running_since": None,
        "queued": False,
        "queued_at": None,
        "waiting": False,
        "waiting_since": None,
        "waiting_for": None,
        "last_run": None,
        "cooldown_until": None,
        "can_run": True,
        "refreshes": ["freshness", "holdings", "value"],
        "stage": "mirror",
    }


def test_run_request_queues_once_then_cools_down(app_client, cfg):
    client = app_client(packages=["mirror", "engine"])
    assert client.post("/api/jobs/mirror/run").status_code == 503
    jobrun.heartbeat(cfg)
    assert client.post("/api/jobs/rm%20-rf/run").json()["error"] == "unknown_job"
    assert client.post("/api/jobs/nope/run").status_code == 404
    ok = client.post("/api/jobs/mirror/run")
    assert ok.status_code == 202
    body = ok.json()
    assert body["ok"] is True and body["job"] == "mirror" and body["request_id"]
    again = client.post("/api/jobs/mirror/run")
    assert again.status_code == 409 and again.json()["error"] == "queued"
    listed = next(j for j in client.get("/api/jobs").json()["jobs"] if j["name"] == "mirror")
    assert listed["queued"] is True and listed["can_run"] is False
    assert [name for name, _ in jobrun.take_requests(cfg)] == ["mirror"]
    cool = client.post("/api/jobs/mirror/run")
    assert cool.status_code == 429 and cool.json()["error"] == "cooldown"
    assert 0 < int(cool.headers["Retry-After"]) <= 300
    log = [json.loads(line) for line in (cfg.data_dir / "run" / "job-requests.log").read_text().splitlines()]
    assert [e["outcome"] for e in log] == ["scheduler_down", "unknown_job", "unknown_job", "queued", "queued", "cooldown"]


def test_run_request_refused_while_the_job_holds_its_lock(app_client, cfg):
    client = app_client(packages=["engine"])
    jobrun.heartbeat(cfg)
    with job_lock("engine-daily", cfg=cfg):
        res = client.post("/api/jobs/engine-daily/run")
        assert res.status_code == 409 and res.json()["error"] == "running" and res.json()["since"]
        listed = next(j for j in client.get("/api/jobs").json()["jobs"] if j["name"] == "engine-daily")
        assert listed["running"] is True and listed["can_run"] is False


def test_cooldown_ends_after_five_minutes(cfg):
    jobs = all_jobs(["mirror"], crontab="deploy/crontab")
    jobrun.heartbeat(cfg)
    now = jobrun.now_utc()
    assert jobrun.request_run(cfg, jobs, "mirror", now=now)[0] == 202
    jobrun.take_requests(cfg)
    assert jobrun.request_run(cfg, jobs, "mirror", now=now + timedelta(minutes=4))[0] == 429
    later = now + timedelta(minutes=5, seconds=1)
    jobrun.alive_file(cfg).write_text(jobrun.stamp(later))
    assert jobrun.request_run(cfg, jobs, "mirror", now=later)[0] == 202


def test_scheduler_runs_only_table_commands_for_requests_and_records_the_result(cfg):
    good = make_job("t1", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="mirror", package="mirror")
    bad = make_job("t2", "0 0 1 1 *", ["sh", "-c", "exit 3"], name="engine-daily", package="engine")
    jobs = [good, bad]
    folder = jobrun.requests_dir(cfg)
    folder.mkdir(parents=True)
    (folder / "mirror.json").write_text(json.dumps({"id": "abc", "command": "rm -rf /"}))
    (folder / "engine-daily.json").write_text("{}")
    (folder / "elsewhere.json").write_text("{}")
    started = serve_requests(jobs, cfg)
    assert [j.name for j in started] == ["engine-daily", "mirror"]
    assert good.command == ["sh", "-c", "exit 0"]
    assert jobrun.last_run(cfg, "mirror")["result"] is None
    for j in jobs:
        j.proc.wait()
    reap(jobs, cfg)
    ok, failed = jobrun.last_run(cfg, "mirror"), jobrun.last_run(cfg, "engine-daily")
    assert ok["result"] == "ok" and ok["trigger"] == "request" and ok["request_id"] == "abc" and ok["finished"]
    assert failed["result"] == "failed" and failed["exit_code"] == 3 and "exit 3" in failed["detail"]
    assert not list(folder.glob("*.json"))


def test_a_second_schedule_line_waits_for_the_first(cfg):
    from datetime import datetime

    a = make_job("a", "* * * * *", ["sleep", "1"], name="agents-run-tax")
    b = make_job("b", "* * * * *", ["sleep", "1"], name="agents-run-tax")
    started = tick([a, b], datetime(2026, 11, 9, 8, 0), cfg)
    assert started == [a]
    a.proc.wait()
    reap([a, b], cfg)
    assert jobrun.last_run(cfg, "agents-run-tax")["result"] == "ok"
    assert jobrun.last_run(cfg, "agents-run-tax")["trigger"] == "schedule"
