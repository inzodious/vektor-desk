import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

from desk import jobrun, memory, runlock, scheduler, startrun
from desk.notify.ops import ops_check
from desk.scheduler import drain, launch, make_job, reap, serve_requests, tick
from tests.fakes import Res

NOW = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)
TIGHT = {"total_mb": 15360, "available_mb": 512, "swap_mb": 0, "cache_mb": 6144}
ROOMY = {"total_mb": 32768, "available_mb": 20000, "swap_mb": 0, "cache_mb": None}


class Ntfy:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append(json)
        return Res(200, {})


def low_on(cfg, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "on")
    monkeypatch.setitem(scheduler._LOW, "checked", None)
    return cfg


def finish(job):
    job.proc.wait()
    for _ in range(50):
        if job.pump is None or not job.pump.is_alive():
            return
        time.sleep(0.05)


# ---- Reading the box ----


def test_reads_free_memory_swap_and_the_zfs_cache(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal:       15728640 kB\nMemFree:          204800 kB\nMemAvailable:     524288 kB\nSwapTotal:             0 kB\n")
    (tmp_path / "arc").write_text(
        "13 1 0x01 147 39984 1 2\nname                            type data\nhits            4    123\nsize            4    6442450944\n"
    )
    assert memory.meminfo(tmp_path / "meminfo", tmp_path / "arc") == {"total_mb": 15360, "available_mb": 512, "swap_mb": 0, "cache_mb": 6144, "apps_mb": None}
    (tmp_path / "meminfo").write_text((tmp_path / "meminfo").read_text() + "AnonPages:       9216000 kB\n")
    assert memory.meminfo(tmp_path / "meminfo", tmp_path / "arc")["apps_mb"] == 9000
    assert memory.meminfo(tmp_path / "missing") is None
    assert memory.meminfo(tmp_path / "meminfo", tmp_path / "missing")["cache_mb"] is None


def test_live_model_sessions_are_counted_by_their_command(tmp_path):
    lines = {
        "1": b"python\0-m\0desk.scheduler\0",
        "40": b"node\0/usr/local/bin/claude\0-p\0--model\0x\0",
        "41": b"/usr/local/bin/claude\0-p\0",
        "42": b"python\0-m\0desk.agents\0queue\0--claude\0claude\0",
        "43": b"",
    }
    for pid, line in lines.items():
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "cmdline").write_bytes(line)
    (tmp_path / "44").mkdir()
    (tmp_path / "self").mkdir()
    assert memory.claude_processes(tmp_path) == 2 and memory.claude_processes(tmp_path, "/opt/bin/other") == 0
    assert memory.claude_processes(tmp_path / "missing") is None and isinstance(memory.claude_processes(), int)


def test_a_kill_is_the_services_cap_or_the_whole_box(tmp_path):
    (tmp_path / "memory.max").write_text("671088640\n")
    (tmp_path / "memory.current").write_text("335544320\n")
    (tmp_path / "memory.events").write_text("low 0\nhigh 0\nmax 12\noom 1\noom_kill 1\n")
    before = memory.cgroup(tmp_path)
    assert before == {"limit_mb": 640, "used_mb": 320, "oom_kills": 1, "cap_hits": 1}
    assert memory.kill_scope(before, before) is None
    assert memory.kill_scope(before, before | {"oom_kills": 2, "cap_hits": 2}) == "cap"
    assert memory.kill_scope(before, before | {"oom_kills": 2}) == "box"
    assert memory.kill_scope(None, before) is None and memory.cgroup(tmp_path / "none")["oom_kills"] is None
    assert memory.job_words("cap", 640) == "It needed more memory than the scheduler is allowed (640 MB) and was stopped."
    assert memory.job_words("box") == "The box ran out of memory and stopped it."


# ---- The last two days ----

SAMPLE = {"at", "free_mb", "cache_mb", "apps_mb", "scheduler_mb", "claude_processes", "low", "running"}


def test_a_memory_sample_is_kept_every_five_minutes_for_two_days_and_no_longer(cfg):
    start = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    seen = {"available_mb": 553, "cache_mb": 3100, "apps_mb": 9000, "scheduler_mb": 212, "claude_processes": 2}
    first = memory.sample(cfg, start, low=True, running=["engine-lookthrough"], reading=seen)
    assert first == {
        "at": "2026-11-10T12:00:00Z",
        "free_mb": 553,
        "cache_mb": 3100,
        "apps_mb": 9000,
        "scheduler_mb": 212,
        "claude_processes": 2,
        "low": True,
        "running": ["engine-lookthrough"],
    }
    assert memory.sample(cfg, start + timedelta(minutes=4), reading=seen) is None
    assert memory.sample(cfg, start + timedelta(minutes=4, seconds=45), reading=seen)["running"] == []
    for n in range(2, 700):
        assert memory.sample(cfg, start + timedelta(minutes=5 * n), reading={"available_mb": n}, running=[f"job-{i}" for i in range(20)])
    end = start + timedelta(minutes=5 * 699)
    rows = memory.history(cfg, end)
    assert len(rows) == 576 and rows[-1]["free_mb"] == 699 and rows[-1]["scheduler_mb"] is None and len(rows[-1]["running"]) == 12
    assert jobrun.parse_stamp(rows[0]["at"]) > end - timedelta(hours=48) and memory.history_file(cfg).stat().st_size < 200_000
    assert memory.history(cfg, end + timedelta(hours=47, minutes=59)) == rows[-1:] and memory.history(cfg, end + timedelta(hours=49)) == []
    assert memory.history(cfg, start) == [] and memory.sample(cfg, end + timedelta(days=3), reading=seen)["free_mb"] == 553
    assert [r["free_mb"] for r in memory.history(cfg, end + timedelta(days=3))] == [553]
    memory.history_file(cfg).write_text("not json")
    assert memory.history(cfg, end) == [] and memory.sample(cfg, end, reading=seen)["at"] == jobrun.stamp(end)
    memory.history_file(cfg).write_text(json.dumps({"samples": ["x", {"at": "never"}, {"free_mb": 1}]}))
    assert memory.history(cfg, end) == []


def test_the_scheduler_notes_memory_and_what_is_running_without_doing_it_twice(cfg, monkeypatch):
    a = make_job("a", "0 0 1 1 *", ["sleep", "5"], name="engine-daily")
    b = make_job("b", "0 0 1 1 *", ["true"], name="engine-review")
    assert launch([a, b], a, cfg, "schedule") == "started"
    try:
        monkeypatch.setitem(scheduler._LOW, "on", True)
        scheduler.remember([a, b], cfg)
        (row,) = memory.history(cfg)
        assert row["running"] == ["engine-daily"] and row["low"] is True and set(row) == SAMPLE
        due = scheduler._LOW["sample_due"]
        scheduler.remember([a, b], cfg)
        assert len(memory.history(cfg)) == 1 and scheduler._LOW["sample_due"] == due
        monkeypatch.setitem(scheduler._LOW, "sample_due", None)
        scheduler.remember([a, b], cfg)
        assert len(memory.history(cfg)) == 1 and scheduler._LOW["sample_due"] - time.monotonic() <= scheduler.MODE_EVERY
        monkeypatch.setitem(scheduler._LOW, "sample_due", None)
        monkeypatch.setattr(memory, "sample", lambda *a, **k: 1 / 0)
        scheduler.remember([a, b], cfg)
        assert scheduler._LOW["sample_due"] is not None
    finally:
        a.proc.kill()
        a.proc.wait()


def test_the_memory_route_shows_the_record_only_when_asked(app_client, cfg):
    client = app_client(packages=[])
    now = jobrun.now_utc()
    memory.sample(cfg, now - timedelta(minutes=10), running=["mirror"], reading={"available_mb": 900, "scheduler_mb": 100})
    memory.sample(cfg, now - timedelta(minutes=5), reading={"available_mb": 2400, "cache_mb": 5000, "scheduler_mb": 80})
    assert "history" not in client.get("/api/memory").json() and "history" not in client.get("/api/status").json()["memory"]
    body = client.get("/api/memory?history=1").json()
    assert body["history"]["every_minutes"] == 5 and body["history"]["keeps_hours"] == 48 and body["state"] in ("ok", "tight", "unknown")
    assert [(r["free_mb"], r["running"]) for r in body["history"]["samples"]] == [(900, ["mirror"]), (2400, [])]


# ---- The mode ----


def test_auto_turns_on_under_the_floor_and_only_off_again_with_room(cfg, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "auto")
    assert memory.decide("auto", 999, False)[0] is True and memory.decide("auto", 1000, False) == (False, None)
    assert memory.decide("auto", 1499, True)[0] is True and memory.decide("auto", 1500, True) == (False, None)
    assert memory.decide("auto", 2400, True) == (False, None) and memory.decide("auto", 2400, False) == (False, None)
    assert memory.decide("auto", None, True)[0] is True and memory.decide("auto", None, False) == (False, None)
    state = memory.refresh(cfg, NOW, info=TIGHT, group={"limit_mb": 640, "used_mb": 300})
    assert state["on"] is True and state["paused"] == [] and "512 MB free, under the 1,000 MB floor" in state["why"]
    assert state["scheduler"] == {"limit_mb": 640, "used_mb": 300}
    later = NOW + timedelta(minutes=30)
    kept = memory.refresh(cfg, later, info=TIGHT | {"available_mb": 1200}, group={})
    assert kept["on"] is True and kept["since"] == state["since"] and "switches itself off at 1.5 GB" in kept["why"]
    assert memory.refresh(cfg, later, info=ROOMY, group={})["on"] is False


def test_auto_stays_on_for_half_an_hour_after_something_was_stopped_for_memory(cfg, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "auto")
    roomy = TIGHT | {"available_mb": 2400}
    assert memory.refresh(cfg, NOW, info=roomy, group={})["on"] is False
    memory.record_kill(cfg, "engine-daily", "Engine daily", "cap", NOW)
    held = memory.refresh(cfg, NOW + timedelta(minutes=29), info=roomy, group={})
    assert held["on"] is True and held["why"] == "Something was stopped for memory in the last 30 minutes."
    assert memory.refresh(cfg, NOW + timedelta(minutes=31), info=roomy, group={})["on"] is False


def test_a_fresh_scheduler_verdict_is_trusted_and_a_stale_one_is_not(cfg, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "auto")
    memory.refresh(cfg, NOW, info=TIGHT, group={})
    assert memory.low_memory(cfg, NOW + timedelta(minutes=5), info=ROOMY)["on"] is True
    assert memory.low_memory(cfg, NOW + timedelta(minutes=11), info=ROOMY)["on"] is False


def test_the_switch_wins_over_auto_and_is_logged(app_client, cfg, monkeypatch):
    monkeypatch.setenv("DESK_LOW_MEMORY", "auto")
    client = app_client(packages=[])
    assert client.get("/api/memory").json()["low_memory"]["mode"] == "auto"
    body = client.put("/api/memory/low", json={"mode": "on"}).json()
    assert body["ok"] is True and body["low_memory"]["on"] is True and body["low_memory"]["why"] == "You switched it on."
    assert "Low-memory mode is on: heavy jobs run one at a time." in body["note"]
    assert client.put("/api/memory/low", json={"mode": "off"}).json()["low_memory"] | {"since": None} == {
        "on": False,
        "mode": "off",
        "why": None,
        "since": None,
        "paused": [],
        "low_mb": 1000,
        "roomy_mb": 1500,
    }
    assert client.put("/api/memory/low", json={"mode": "sometimes"}).status_code == 422
    log = [json.loads(line) for line in (cfg.data_dir / "run" / "job-requests.log").read_text().splitlines()]
    assert [(e["job"], e["outcome"]) for e in log] == [("low-memory", "on"), ("low-memory", "off")]
    for path in ("/api/status", "/api/box", "/api/start", "/api/readiness"):
        assert "memory" in client.get(path).json(), path
    assert client.get("/api/jobs").json()["low_memory"] == {"on": False, "why": None}


# ---- Heavy jobs one at a time ----


def test_heavy_jobs_take_turns_and_light_ones_do_not_wait(cfg, monkeypatch):
    low_on(cfg, monkeypatch)
    a = make_job("a", "0 0 1 1 *", ["sleep", "0.4"], name="engine-daily", package="engine")
    b = make_job("b", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="engine-review", package="engine")
    c = make_job("c", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="mirror", package="mirror")
    light = make_job("l", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="engine-quotes", package="engine")
    minutely = make_job("m", "* * * * *", ["sh", "-c", "exit 0"], name="agents-queue-now-only", package="agents")
    jobs = [a, b, c, light, minutely]
    assert (a.heavy, light.heavy) == (True, False)
    assert launch(jobs, a, cfg, "schedule") == "started"
    assert launch(jobs, b, cfg, "request", "abc123") == "waiting" and launch(jobs, c, cfg, "start", "def456") == "waiting"
    assert launch(jobs, light, cfg, "schedule") == "started" and launch(jobs, minutely, cfg, "schedule") == "skipped"
    assert scheduler._busy(jobs, "engine-review") and b.proc is None
    assert [w["job"] for w in memory.waiting(cfg)] == ["engine-review", "mirror"]
    rows = {r["name"]: r for r in jobrun.describe(cfg, jobs)["jobs"]}
    assert rows["engine-review"]["waiting"] is True and rows["engine-review"]["can_run"] is False and rows["engine-daily"]["waiting"] is False
    assert (rows["engine-review"]["waiting_for"], rows["engine-daily"]["waiting_for"]) == ("memory", None)
    seen = memory.status(cfg)
    assert [w["job"] for w in seen["waiting"]] == ["engine-review", "mirror"] and seen["queued_for_night"] == []
    assert "Waiting for a turn: " in seen["note"]
    assert jobrun.request_run(cfg, jobs, "engine-review")[0] == 409
    assert drain(jobs, cfg) == []
    finish(a)
    reap(jobs, cfg)
    assert drain(jobs, cfg) == [b] and c.waiting is not None
    assert b.run["trigger"] == "request" and b.run["request_id"] == "abc123"
    finish(b)
    reap(jobs, cfg)
    assert drain(jobs, cfg) == [c] and memory.waiting(cfg) == []
    finish(c)
    reap(jobs, cfg)
    assert jobrun.last_run(cfg, "mirror")["request_id"] == "def456" and jobrun.last_run(cfg, "mirror")["result"] == "ok"


def test_everything_waiting_starts_when_the_mode_goes_off(cfg, monkeypatch):
    low_on(cfg, monkeypatch)
    a = make_job("a", "0 0 1 1 *", ["sleep", "0.3"], name="engine-daily")
    b = make_job("b", "0 0 1 1 *", ["sleep", "0.3"], name="engine-review")
    c = make_job("c", "0 8 * * *", ["sleep", "0.3"], name="mirror")
    jobs = [a, b, c]
    assert launch(jobs, a, cfg, "schedule") == "started" and launch(jobs, b, cfg, "schedule") == "waiting"
    assert tick(jobs, datetime(2026, 11, 11, 8, 0), cfg) == [] and c.waiting["trigger"] == "schedule"
    assert tick(jobs, datetime(2026, 11, 12, 8, 0), cfg) == []
    monkeypatch.setenv("DESK_LOW_MEMORY", "off")
    monkeypatch.setitem(scheduler._LOW, "checked", None)
    assert drain(jobs, cfg) == [b, c] and memory.waiting(cfg) == []
    for job in jobs:
        finish(job)
    reap(jobs, cfg)


def test_jobs_all_start_at_once_when_the_box_has_room(cfg):
    a = make_job("a", "0 0 1 1 *", ["sleep", "0.2"], name="engine-daily")
    b = make_job("b", "0 0 1 1 *", ["sleep", "0.2"], name="engine-review")
    assert launch([a, b], a, cfg, "schedule") == "started" and launch([a, b], b, cfg, "schedule") == "started"
    finish(a)
    finish(b)
    reap([a, b], cfg)


def test_the_start_chain_waits_its_turn_and_says_so(cfg, monkeypatch):
    low_on(cfg, monkeypatch)
    jobrun.heartbeat(cfg)
    busy = make_job("x", "0 0 1 1 *", ["sleep", "0.5"], name="engine-research", package="engine")
    mirror = make_job("m", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="mirror", package="mirror")
    jobs = [busy, mirror]
    scheduler.start(busy, cfg, "schedule")
    assert startrun.request_start(cfg, jobs)[0] == 202
    scheduler.run_chain(jobs, cfg)
    assert mirror.proc is None and mirror.waiting["trigger"] == "start"
    seen = startrun.describe(cfg, jobs)
    step = next(s for s in seen["steps"] if s["job"] == "mirror")
    assert step["state"] == "running" and step["detail"] == "Waiting for its turn: low-memory mode runs heavy jobs one at a time."
    assert step["waiting"] is True and not any(s["waiting"] for s in seen["steps"] if s["job"] != "mirror")
    assert seen["memory"]["low_memory"] is True and "Waiting for a turn: Mirror." in seen["memory"]["note"]
    scheduler.run_chain(jobs, cfg)
    assert mirror.proc is None
    finish(busy)
    reap(jobs, cfg)
    assert drain(jobs, cfg) == [mirror] and mirror.run["trigger"] == "start"
    finish(mirror)
    reap(jobs, cfg)
    assert jobrun.last_run(cfg, "mirror")["trigger"] == "start"


def test_a_run_request_for_a_waiting_job_is_dropped_not_doubled(cfg, monkeypatch):
    low_on(cfg, monkeypatch)
    a = make_job("a", "0 0 1 1 *", ["sleep", "0.3"], name="engine-daily")
    b = make_job("b", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="mirror")
    scheduler.start(a, cfg, "schedule")
    assert launch([a, b], b, cfg, "schedule") == "waiting"
    jobrun._write(jobrun.requests_dir(cfg) / "mirror.json", {"id": "ffff"})
    assert serve_requests([a, b], cfg) == [] and b.waiting["trigger"] == "schedule"
    finish(a)
    reap([a, b], cfg)


# ---- Out of memory ----


def test_a_job_killed_for_memory_says_so_and_asks_for_one_alert(cfg, monkeypatch):
    counts = iter([{"limit_mb": 640, "used_mb": 100, "oom_kills": 3, "cap_hits": 3}, {"limit_mb": 640, "used_mb": 100, "oom_kills": 4, "cap_hits": 4}])
    last = {}
    monkeypatch.setattr(memory, "cgroup", lambda root=None: last.update(next(counts, last)) or dict(last))
    job = make_job("j", "0 0 1 1 *", ["sh", "-c", 'echo \'{"error": "claude exited -9"}\'; exit 1'], name="agents-run-debrief", package="agents")
    teller = make_job("n", "0 0 1 1 *", ["sh", "-c", "exit 0"], name="notify-ops", package="notify")
    scheduler.start(job, cfg, "schedule")
    finish(job)
    reap([job, teller], cfg)
    run = jobrun.last_run(cfg, "agents-run-debrief")
    assert run["result"] == "failed" and run["oom"] == "cap"
    assert run["error"] == "It needed more memory than the scheduler is allowed (640 MB) and was stopped."
    assert teller.run["trigger"] == "memory"
    finish(teller)
    reap([job, teller], cfg)
    (event,) = memory.status(cfg)["killed"]
    assert event["kind"] == "job" and event["words"] == "Agents run debrief was stopped: it needed more memory than the scheduler is allowed."


def test_a_sigkill_counts_as_memory_and_a_plain_failure_does_not(cfg):
    killed = make_job("k", "0 0 1 1 *", ["sh", "-c", "kill -9 $$"], name="engine-daily", package="engine")
    plain = make_job("p", "0 0 1 1 *", ["sh", "-c", "echo boom; exit 3"], name="engine-review", package="engine")
    for job in (killed, plain):
        scheduler.start(job, cfg, "schedule")
        finish(job)
    reap([killed, plain], cfg)
    assert jobrun.last_run(cfg, "engine-daily")["oom"] == "box"
    assert jobrun.last_run(cfg, "engine-daily")["error"] == "The box ran out of memory and stopped it."
    assert jobrun.last_run(cfg, "engine-review")["oom"] is None and jobrun.last_run(cfg, "engine-review")["error"] == "boom"


def test_the_run_lock_passes_a_kill_on_as_137(cfg, monkeypatch):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    assert runlock.hold("t", ["sh", "-c", "kill -9 $$"]) == 137
    assert runlock.hold("t", ["sh", "-c", "exit 3"]) == 3


def test_host_kills_are_put_in_plain_words_and_not_counted_twice(cfg):
    at = jobrun.stamp(NOW - timedelta(hours=1))
    memory.record_kill(cfg, "agents-run-debrief", "Agents run debrief", "cap", NOW - timedelta(hours=1))
    jobrun._write(
        cfg.data_dir / "run" / "box" / "memory.json",
        {
            "checked_at": jobrun.stamp(NOW),
            "kills": [
                {"at": at, "process": "node", "scope": "cap", "service": "cron"},
                {"at": jobrun.stamp(NOW - timedelta(hours=2)), "process": "python", "scope": "cap", "service": "lab"},
                {"at": jobrun.stamp(NOW - timedelta(hours=3)), "process": "uvicorn", "scope": "box", "service": "api"},
                {"at": jobrun.stamp(NOW - timedelta(hours=4)), "process": "smbd", "scope": "box", "service": ""},
                {"at": jobrun.stamp(NOW - timedelta(hours=60)), "process": "old", "scope": "box", "service": ""},
                {"at": "not a time", "process": "x"},
            ],
        },
    )
    seen = memory.status(cfg, NOW, info=TIGHT)
    assert [e["words"] for e in seen["killed"]] == [
        "Agents run debrief was stopped: it needed more memory than the scheduler is allowed.",
        "The desk's lab needed more memory than it is allowed, and python was stopped.",
        "The box ran out of memory and stopped uvicorn in the desk's app.",
        "The box ran out of memory and stopped smbd, a program outside the desk.",
    ]
    assert seen["host_seen"] is True and seen["state"] == "tight"
    assert seen["note"].startswith(
        "The box has 512 MB of 15.0 GB free, and no swap. Its ZFS file cache holds 6.0 GB, which it hands back under pressure, but slowly."
    )
    assert "Stopped for memory in the last two days: 4. Latest: Agents run debrief was stopped" in seen["note"]
    assert memory.status(cfg, NOW + timedelta(minutes=20), info=TIGHT)["host_seen"] is False


def test_one_alert_a_day_for_memory(cfg):
    on = dataclasses.replace(cfg, ntfy_url="http://ntfy")
    ntfy = Ntfy()
    now = datetime.now(UTC)
    assert "memory" not in ops_check(on, now=now, session=ntfy)
    memory.record_kill(on, "engine-daily", "Engine daily", "box", now)
    assert "memory" in ops_check(on, now=now, session=ntfy)
    memory.record_kill(on, "engine-review", "Engine review", "box", now)
    assert "memory" not in ops_check(on, now=now, session=ntfy)
    sent = [m for m in ntfy.sent if m["title"] == "The desk ran out of memory"]
    assert len(sent) == 1 and sent[0]["message"].startswith("Engine daily was stopped: the box ran out of memory.")
    assert sent[0]["click"].endswith("/settings/box") and "Open Settings, Box to switch on low-memory mode." in sent[0]["message"]
    assert "memory" not in ops_check(on, now=now + timedelta(days=1), session=Ntfy())


# ---- Pausing a service ----


def test_hold_pauses_the_service_while_the_mode_is_on_and_starts_it_after(cfg, tmp_path):
    memory.set_mode(cfg, "on")
    mark = tmp_path / "ran"
    child = f"import pathlib, time; pathlib.Path({str(mark)!r}).write_text('up'); time.sleep(30)"
    code = (
        "import sys, pathlib; from desk import memory; from desk.config import Config; "
        f"sys.exit(memory.hold([sys.executable, '-c', {child!r}], 'the lab', Config(data_dir=pathlib.Path({str(cfg.data_dir)!r})), every=0.2, grace=2))"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=os.environ | {"DESK_LOW_MEMORY": "off"})
    try:
        time.sleep(1.2)
        assert not mark.exists() and proc.poll() is None
        memory.set_mode(cfg, "off")
        for _ in range(60):
            if mark.exists():
                break
            time.sleep(0.1)
        assert mark.exists() and proc.poll() is None
        mark.unlink()
        memory.set_mode(cfg, "on")
        time.sleep(1.2)
        assert not mark.exists() and proc.poll() is None
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    out = proc.stdout.read()
    assert "low-memory mode is on: the lab is paused" in out and "low-memory mode is off: starting the lab" in out


def test_hold_ends_with_the_service_so_docker_restarts_it(cfg):
    memory.set_mode(cfg, "off")
    assert memory.hold(["sh", "-c", "exit 4"], "the lab", cfg, every=0.2) == 4
    assert memory.main(["hold", "--name", "the lab"]) == 2
