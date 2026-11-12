import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from desk import jobrun, memory, notify, overnight, scheduler
from desk.api.app import create_app
from desk.scheduler import launch, make_job, reap, start, tick

ET = ZoneInfo("America/New_York")
EVENING = ("mirror", "engine-daily", "engine-review", "engine-discounts", "agents-run-plan_keeper", "agents-run-debrief")
NIGHT = datetime(2026, 11, 11, 23, 30, tzinfo=ET)
DEPLOYED = datetime(2026, 11, 11, 21, 0, tzinfo=ET)


def jobs_for(tmp_path, scripts: dict[str, str] | None = None, extra: dict[str, int] | None = None):
    scripts = scripts or {}
    order = tmp_path / "order"
    extra = {"agents-portfolio": 200, "opportunities-night": 210} if extra is None else extra

    def job(name, place=None):
        said = scripts.get(name, "true")
        return make_job(name, "0 0 1 1 *", ["sh", "-c", f"echo {name} >> {order}; {said}"], name=name, package=name.split("-")[0], overnight=place)

    return [job(n) for n in EVENING] + [job(n, place) for n, place in extra.items()]


def went_live(cfg, at, build="b1", monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv("DESK_BUILD", build)
    overnight.folder(cfg).mkdir(parents=True, exist_ok=True)
    jobrun._write(overnight.folder(cfg) / "build.json", {"build": build, "since": jobrun.stamp(at)})


def drive(cfg, jobs, now, limit=40):
    def busy(name):
        return any(j.name == name and (j.proc is not None or j.waiting is not None) for j in jobs)

    real = jobrun.now_utc
    jobrun.now_utc = lambda: now.astimezone(ZoneInfo("UTC"))
    try:
        for _ in range(limit * 20):
            reap(jobs, cfg)
            scheduler.drain(jobs, cfg)
            chain = overnight.advance(cfg, jobs, lambda job, rid: launch(jobs, job, cfg, "overnight", rid), busy, now)
            if chain and chain["state"] == "done":
                return chain
            time.sleep(0.05)
    finally:
        jobrun.now_utc = real
    raise AssertionError("the night never finished")


def ran(tmp_path) -> list[str]:
    path = tmp_path / "order"
    return path.read_text().split() if path.exists() else []


# ---- The window ----


def test_the_night_is_named_by_its_evening_and_runs_from_2330_to_0630():
    assert overnight.night_of(datetime(2026, 11, 11, 23, 29, tzinfo=ET)) is None
    assert overnight.night_of(datetime(2026, 11, 11, 23, 30, tzinfo=ET)) == "2026-11-11"
    assert overnight.night_of(datetime(2026, 11, 12, 6, 29, tzinfo=ET)) == "2026-11-11"
    assert overnight.night_of(datetime(2026, 11, 12, 6, 30, tzinfo=ET)) is None
    assert overnight.fresh(datetime(2026, 11, 12, 2, 59, tzinfo=ET)) and not overnight.fresh(datetime(2026, 11, 12, 3, 0, tzinfo=ET))


def test_nothing_starts_before_2330(cfg, tmp_path, monkeypatch):
    went_live(cfg, DEPLOYED, monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path)
    assert overnight.advance(cfg, jobs, lambda j, r: start(j, cfg, "overnight", r), lambda n: False, NIGHT - timedelta(minutes=1)) is None
    assert ran(tmp_path) == [] and not overnight.active(cfg)


# ---- The order ----


def test_after_an_evening_deploy_the_evening_run_repeats_then_the_night_jobs_run_in_order(cfg, tmp_path, monkeypatch):
    went_live(cfg, DEPLOYED, monkeypatch=monkeypatch)
    scripts = {"agents-portfolio": """echo '{"ready": "14 holdings analysed"}'""", "opportunities-night": """echo '{"skipped": "No discounts today."}'"""}
    jobs = jobs_for(tmp_path, scripts)
    chain = drive(cfg, jobs, NIGHT)
    assert ran(tmp_path) == [*EVENING, "agents-portfolio", "opportunities-night"]
    got = {s["id"]: s for s in chain["steps"]}
    assert got["agents-portfolio"]["state"] == "ok" and got["agents-portfolio"]["ready"] == "14 holdings analysed"
    assert got["opportunities-night"]["state"] == "skipped" and got["opportunities-night"]["detail"] == "No discounts today."
    assert chain["night"] == "2026-11-11" and chain["build"] == "b1" and chain["restarts"] == 0
    again = drive(cfg, jobs, NIGHT + timedelta(hours=1))
    assert again["finished_at"] == chain["finished_at"] and len(ran(tmp_path)) == 8


def test_on_a_quiet_night_the_evening_run_is_not_repeated(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path)
    chain = drive(cfg, jobs, NIGHT)
    assert ran(tmp_path) == ["agents-portfolio", "opportunities-night"]
    assert {s["detail"] for s in chain["steps"] if s["id"] in EVENING} == {"No new version went live since this evening's run."}


def test_an_evening_job_that_already_ran_on_the_live_version_is_skipped(cfg, tmp_path, monkeypatch):
    went_live(cfg, DEPLOYED, monkeypatch=monkeypatch)
    after = jobrun.stamp(DEPLOYED + timedelta(minutes=5))
    jobrun.record(cfg, "mirror", {"started": after, "finished": after, "result": "ok"})
    jobrun.record(cfg, "engine-daily", {"started": jobrun.stamp(DEPLOYED - timedelta(hours=3)), "finished": after, "result": "ok"})
    chain = drive(cfg, jobs_for(tmp_path, extra={}), NIGHT)
    assert ran(tmp_path) == list(EVENING[1:])
    assert chain["steps"][0]["state"] == "skipped" and chain["steps"][0]["detail"] == "It already ran on the version that is live."


def test_a_failed_step_does_not_stop_the_night(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"agents-portfolio": """echo '{"error": "The Claude token was refused."}' >&2; exit 1"""})
    chain = drive(cfg, jobs, NIGHT)
    first, second = chain["steps"][-2:]
    assert first["state"] == "failed" and first["detail"] == "It stopped: The Claude token was refused." and second["state"] == "ok"
    assert overnight.summary(chain) == "7 of 8 steps done. Not done: Agents portfolio."


# ---- Deploys in the middle of the night ----


def test_a_restart_runs_the_interrupted_step_again_and_keeps_what_was_done(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path)
    started = []
    lost = lambda job, rid: started.append(job.name)  # noqa: E731
    idle = lambda name: False  # noqa: E731
    overnight.advance(cfg, jobs, lost, idle, NIGHT)
    assert started == ["agents-portfolio"] and overnight.active(cfg)
    chain = drive(cfg, jobs_for(tmp_path), NIGHT + timedelta(minutes=20))
    assert ran(tmp_path) == ["agents-portfolio", "opportunities-night"] and chain["restarts"] == 0
    assert [s["tries"] for s in chain["steps"][-2:]] == [2, 1]


def test_a_new_version_before_0300_starts_the_night_again_and_after_0300_only_carries_on(cfg, tmp_path, monkeypatch):
    went_live(cfg, DEPLOYED, monkeypatch=monkeypatch)
    drive(cfg, jobs_for(tmp_path), NIGHT)
    assert len(ran(tmp_path)) == 8
    monkeypatch.setenv("DESK_BUILD", "b2")
    one = datetime(2026, 11, 12, 1, 0, tzinfo=ET)
    chain = drive(cfg, jobs_for(tmp_path), one)
    assert len(ran(tmp_path)) == 16 and chain["restarts"] == 1 and chain["build"] == "b2" and chain["night"] == "2026-11-11"
    monkeypatch.setenv("DESK_BUILD", "b3")
    late = datetime(2026, 11, 12, 3, 30, tzinfo=ET)
    more = jobs_for(tmp_path, extra={"agents-portfolio": 200, "opportunities-night": 210, "engine-extra": 150})
    chain = drive(cfg, more, late)
    assert ran(tmp_path)[16:] == ["engine-extra"] and chain["restarts"] == 1 and chain["build"] == "b3"
    assert [s["id"] for s in chain["steps"]][-3:] == ["engine-extra", "agents-portfolio", "opportunities-night"]


def test_between_steps_the_night_waits_for_the_hosts_next_check_in_so_a_deploy_takes_the_gap(cfg):
    box = cfg.data_dir / "run" / "box"
    box.mkdir(parents=True)
    done = NIGHT + timedelta(minutes=10)
    assert not overnight.hold_for_host(cfg, done, done)
    (box / "host.alive").write_text(jobrun.stamp(done - timedelta(minutes=2)) + "\n")
    assert overnight.hold_for_host(cfg, done, done + timedelta(seconds=30))
    (box / "host.alive").write_text(jobrun.stamp(done + timedelta(seconds=20)) + "\n")
    assert overnight.hold_for_host(cfg, done, done + timedelta(seconds=40))
    (box / "host.alive").write_text(jobrun.stamp(done + timedelta(minutes=3)) + "\n")
    assert not overnight.hold_for_host(cfg, done, done + timedelta(minutes=3, seconds=5))
    (box / "host.alive").write_text(jobrun.stamp(done - timedelta(minutes=2)) + "\n")
    assert not overnight.hold_for_host(cfg, done, done + timedelta(minutes=11))
    (box / "host.alive").write_text(jobrun.stamp(done - timedelta(minutes=25)) + "\n")
    assert not overnight.hold_for_host(cfg, done, done + timedelta(seconds=30))
    assert not overnight.hold_for_host(cfg, None, done)


def test_the_gap_holds_the_next_step_until_the_host_checks_in(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    box = cfg.data_dir / "run" / "box"
    box.mkdir(parents=True)
    (box / "host.alive").write_text(jobrun.stamp(NIGHT - timedelta(minutes=1)) + "\n")
    jobs = jobs_for(tmp_path)
    busy = lambda name: any(j.name == name and j.proc is not None for j in jobs)  # noqa: E731
    go = lambda job, rid: start(job, cfg, "overnight", rid)  # noqa: E731
    overnight.advance(cfg, jobs, go, busy, NIGHT)
    jobs[-2].proc.wait()
    reap(jobs, cfg)
    held = overnight.advance(cfg, jobs, go, busy, NIGHT + timedelta(seconds=30))
    assert [s["state"] for s in held["steps"][-2:]] == ["ok", "waiting"] and ran(tmp_path) == ["agents-portfolio"]
    (box / "host.alive").write_text(jobrun.stamp(NIGHT + timedelta(minutes=4)) + "\n")
    moved = overnight.advance(cfg, jobs, go, busy, NIGHT + timedelta(minutes=4, seconds=5))
    assert moved["steps"][-1]["state"] == "running"
    jobs[-1].proc.wait()
    reap(jobs, cfg)


# ---- The end of the night ----


def test_at_0630_what_has_not_started_is_closed_and_a_running_step_finishes(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"agents-portfolio": """sleep 0.4; echo '{"ready": "9 holdings analysed"}'"""})
    busy = lambda name: any(j.name == name and j.proc is not None for j in jobs)  # noqa: E731
    go = lambda job, rid: start(job, cfg, "overnight", rid)  # noqa: E731
    overnight.advance(cfg, jobs, go, busy, NIGHT)
    morning = datetime(2026, 11, 12, 6, 30, tzinfo=ET)
    chain = overnight.advance(cfg, jobs, go, busy, morning)
    assert chain["state"] == "running" and chain["steps"][-1]["detail"] == "The night ran out before its turn."
    jobs[-2].proc.wait()
    reap(jobs, cfg)
    chain = overnight.advance(cfg, jobs, go, busy, morning + timedelta(minutes=1))
    assert chain["state"] == "done" and chain["steps"][-2]["ready"] == "9 holdings analysed" and ran(tmp_path) == ["agents-portfolio"]
    assert overnight.summary(chain) == "7 of 8 steps done. Not done: Opportunities night."
    assert overnight.advance(cfg, jobs, go, busy, morning + timedelta(hours=3))["state"] == "done"


# ---- The scheduler ----


def test_while_the_night_runs_heavy_jobs_take_turns_and_a_fallback_schedule_line_is_skipped(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "off")
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"agents-portfolio": "sleep 0.5"})
    hourly = make_job("hourly", "* * * * *", ["true"], name="engine-backfill")
    other = make_job("other", "0 0 1 1 *", ["true"], name="engine-french")
    light = make_job("light", "0 0 1 1 *", ["true"], name="engine-lab-offer", heavy=False)
    fallback = make_job("fallback", "* * * * *", ["true"], name="agents-portfolio")
    everything = [*jobs, hourly, other, light, fallback]
    monkeypatch.setattr(jobrun, "now_utc", lambda: NIGHT.astimezone(ZoneInfo("UTC")))
    overnight.advance(cfg, everything, lambda job, rid: launch(everything, job, cfg, "overnight", rid), lambda n: scheduler._busy(everything, n), NIGHT)
    assert launch(everything, other, cfg, "request") == "waiting" and launch(everything, light, cfg, "schedule") == "started"
    started = tick(everything, NIGHT, cfg)
    assert [j.line for j in started] == [] and fallback.proc is None and hourly.proc is None
    for job in everything:
        if job.proc is not None:
            job.proc.wait()
    reap(everything, cfg)
    assert [j.name for j in scheduler.drain(everything, cfg)] == ["engine-french"]
    other.proc.wait()
    reap(everything, cfg)


def test_a_job_held_behind_the_nights_step_is_held_once_and_is_not_a_memory_wait(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "off")
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"agents-portfolio": "sleep 0.5"})
    restate = make_job("restate", "2-57/5 * * * *", ["true"], name="engine-restate")
    everything = [*jobs, restate]
    monkeypatch.setattr(jobrun, "now_utc", lambda: NIGHT.astimezone(ZoneInfo("UTC")))
    overnight.advance(cfg, everything, lambda job, rid: launch(everything, job, cfg, "overnight", rid), lambda n: scheduler._busy(everything, n), NIGHT)
    assert tick(everything, NIGHT + timedelta(minutes=2), cfg) == [] and restate.proc is None
    held = dict(restate.waiting)
    assert held["trigger"] == "schedule"
    assert tick(everything, NIGHT + timedelta(minutes=7), cfg) == [] and restate.waiting == held
    seen = memory.status(cfg)
    assert seen["waiting"] == [] and [w["job"] for w in seen["queued_for_night"]] == ["engine-restate"]
    assert seen["low_memory"]["on"] is False and "Waiting for a turn" not in seen["note"]
    rows = {r["name"]: r for r in jobrun.describe(cfg, everything)["jobs"]}
    assert (rows["engine-restate"]["waiting"], rows["engine-restate"]["waiting_for"]) == (True, "night")
    for job in everything:
        if job.proc is not None:
            job.proc.wait()
    reap(everything, cfg)
    assert [j.name for j in scheduler.drain(everything, cfg)] == ["engine-restate"]
    restate.proc.wait()
    reap(everything, cfg)
    seen = memory.status(cfg)
    assert seen["waiting"] == [] and seen["queued_for_night"] == []


def test_a_fallback_line_runs_when_the_night_has_stalled_or_the_step_did_not_work(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"opportunities-night": "exit 1"})
    overnight.advance(cfg, jobs, lambda job, rid: None, lambda n: True, NIGHT)
    assert overnight.covers(cfg, "opportunities-night", NIGHT + timedelta(minutes=2))
    assert not overnight.covers(cfg, "opportunities-night", NIGHT + timedelta(minutes=4))
    assert not overnight.covers(cfg, "mirror", NIGHT) and not overnight.covers(cfg, "engine-backfill", NIGHT)
    overnight.chain_file(cfg).unlink()
    drive(cfg, jobs, NIGHT)
    later = NIGHT + timedelta(hours=2)
    assert overnight.covers(cfg, "agents-portfolio", later) and not overnight.covers(cfg, "opportunities-night", later)
    assert not overnight.covers(cfg, "agents-portfolio", datetime(2026, 11, 12, 7, 0, tzinfo=ET))


def test_a_job_joins_the_night_with_one_key_and_shows_under_overnight(monkeypatch):
    class Seam:
        JOBS = [
            ("5 0 * * *", "python -m desk.agents plain"),
            {"name": "portfolio", "title": "Analyse every holding", "schedule": "5 0 * * *", "command": "python -m desk.agents portfolio", "overnight": 200},
            {"name": "portfolio", "schedule": "5 2 * * *", "command": "python -m desk.agents portfolio"},
        ]

    monkeypatch.setattr(scheduler, "seams", lambda kind, only=None: {"agents": Seam})
    jobs = scheduler.package_jobs()
    assert [j.overnight for j in jobs] == [None, 200, None]
    assert overnight.order(jobs) == [(200, "agents-portfolio", "Analyse every holding", "night")]
    entry = jobrun.catalogue(jobs)["agents-portfolio"]
    assert entry.stage == "overnight" and entry.schedules == ["5 0 * * *", "5 2 * * *"] and jobrun.STAGE_ORDER[-1] == "overnight"


def test_a_job_can_say_what_is_ready_on_its_last_line(cfg):
    job = make_job("a", "0 0 1 1 *", ["sh", "-c", """echo working; echo '{"ready": "31 strategies tested, 9 held up out of sample"}'"""], name="engine-x")
    start(job, cfg, "overnight", "abc")
    job.proc.wait()
    reap([job], cfg)
    assert jobrun.last_run(cfg, "engine-x")["ready"] == "31 strategies tested, 9 held up out of sample"


# ---- What the app and the phone see ----


def test_the_api_shows_tonights_order_before_it_starts_and_the_result_after(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    jobs = jobs_for(tmp_path, {"agents-portfolio": """echo '{"ready": "14 holdings analysed"}'"""})
    idle = overnight.describe(cfg, jobs, NIGHT - timedelta(hours=2))
    assert idle["state"] == "idle" and idle["night"] == "2026-11-11" and idle["summary"] == "Tonight's run starts at 23:30."
    assert [s["id"] for s in idle["steps"]] == [*EVENING, "agents-portfolio", "opportunities-night"] and idle["ready"] == []
    drive(cfg, jobs, NIGHT)
    view = overnight.describe(cfg, jobs, datetime(2026, 11, 12, 9, 0, tzinfo=ET))
    assert view["state"] == "done" and view["night"] == "2026-11-11" and view["ready"] == ["14 holdings analysed"] and view["summary"] == "8 of 8 steps done."
    assert set(view["steps"][0]) == {"id", "job", "title", "state", "detail", "ready", "started_at", "finished_at"}
    with TestClient(create_app(cfg)) as client:
        body = client.get("/api/overnight").json()
        assert body["starts"] == "23:30" and body["ends"] == "06:30" and "steps" in body
        assert client.get("/api/jobs").json()["stages"][-1] == "overnight"


def test_the_morning_alert_says_what_is_ready_and_what_did_not_finish(cfg, tmp_path, monkeypatch):
    went_live(cfg, datetime(2026, 11, 11, 14, 0, tzinfo=ET), monkeypatch=monkeypatch)
    morning = datetime(2026, 11, 12, 6, 45, tzinfo=ET)
    assert overnight.alert(cfg, morning) == {"skipped": "No overnight run to report."}
    scripts = {"agents-portfolio": """echo '{"ready": "14 holdings analysed"}'""", "opportunities-night": "exit 1"}
    drive(cfg, jobs_for(tmp_path, scripts), NIGHT)

    class Shelf:
        @staticmethod
        def ready(cfg):
            return "34 strategies tested, 3 held up out of sample"

    monkeypatch.setattr(
        overnight.importlib, "import_module", lambda path: Shelf if path == "desk.engine.lab.shelf" else (_ for _ in ()).throw(ImportError(path))
    )
    sent = []
    monkeypatch.setattr(notify, "publish", lambda *a, **kw: sent.append((a, kw)) or True)
    out = overnight.alert(cfg, morning)
    assert out["title"] == "Your desk is ready for this morning"
    assert out["body"] == "14 holdings analysed. 34 strategies tested, 3 held up out of sample. Not done: Opportunities night."
    (topic, title, body), kw = sent[0]
    assert topic == "research" and kw["click"] == "/" and kw["key"] == "overnight-2026-11-11" and json.dumps(out)
