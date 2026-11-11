import argparse
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from desk import jobrun
from desk.config import Config
from desk.packages import seams
from desk.runlock import BUSY

RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field(text: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, raw = part.split("/", 1)
            step = int(raw)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if step < 1 or start < low or end > high or start > end:
            raise ValueError(f"{text!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return frozenset(0 if high == 7 and v == 7 else v for v in values)


@dataclass
class Job:
    line: str
    spec: tuple[frozenset[int], ...]
    command: list[str]
    any_day: tuple[bool, bool]
    name: str = ""
    title: str = ""
    package: str = ""
    timing: str = ""
    lock: str = ""
    refreshes: tuple[str, ...] = ()
    stage: str = ""
    proc: subprocess.Popen | None = field(default=None, repr=False)
    said: str = field(default="", repr=False)
    pump: threading.Thread | None = field(default=None, repr=False)
    run: dict | None = field(default=None, repr=False)

    def due(self, t: datetime) -> bool:
        minute, hour, dom, month, dow = self.spec
        if t.minute not in minute or t.hour not in hour or t.month not in month:
            return False
        weekday = (t.weekday() + 1) % 7
        day_ok, dow_ok = t.day in dom, weekday in dow
        dom_star, dow_star = self.any_day
        if dom_star or dow_star:
            return day_ok and dow_ok
        return day_ok or dow_ok


def make_job(
    label: str, timing: str, command: list[str], *, name: str = "", package: str = "", lock: str = "", refreshes: tuple[str, ...] = (), stage: str = ""
) -> Job:
    parts = timing.split()
    if len(parts) != 5:
        raise ValueError(f"{label}: need five time fields, got {timing!r}")
    spec = tuple(_field(p, lo, hi) for p, (lo, hi) in zip(parts, RANGES, strict=True))
    if not command:
        raise ValueError(f"{label}: no command")
    name = name or re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-")
    return Job(
        line=label,
        spec=spec,
        command=command,
        any_day=(parts[2] == "*", parts[4] == "*"),
        name=name,
        title=jobrun.job_title(name),
        package=package,
        timing=" ".join(parts),
        lock=lock,
        refreshes=refreshes,
        stage=stage,
    )


def parse(text: str) -> list[Job]:
    jobs = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            raise ValueError(f"line {n}: need five time fields and a command")
        jobs.append(make_job(f"line {n}", " ".join(parts[:5]), shlex.split(parts[5]), name=f"crontab-{n}", package="crontab"))
    return jobs


def lock_name(pkg: str, command: list[str]) -> str:
    words = [w for w in command if not w.startswith("-") and w not in ("python", "python3", "-m")]
    slug = "-".join(w.rsplit(".", 1)[-1] for w in words[:3])
    return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{pkg}-{slug}").strip("-")[:60]


def package_jobs(only: list[str] | None = None) -> list[Job]:
    jobs = []
    for pkg, mod in seams("jobs", only).items():
        for i, entry in enumerate(getattr(mod, "JOBS", [])):
            if isinstance(entry, dict):
                timing, command, name = entry["schedule"], entry["command"], entry.get("name")
                refreshes, stage = tuple(str(c) for c in entry.get("refreshes") or ()), str(entry.get("stage") or "")
            else:
                timing, command, name, refreshes, stage = entry[0], entry[1], None, (), ""
            cmd = shlex.split(command) if isinstance(command, str) else list(command)
            lock = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{pkg}-{name}")[:60] if name else lock_name(pkg, cmd)
            held = ["python", "-m", "desk.runlock", "--hold", lock, "--", *cmd]
            job_id = jobrun.job_name(pkg, cmd, name)
            jobs.append(make_job(f"{pkg}.jobs[{i}]", timing, held, name=job_id, package=pkg, lock=lock, refreshes=refreshes, stage=stage))
    return jobs


def all_jobs(only: list[str] | None = None, crontab: str | None = None) -> list[Job]:
    path = Path(crontab or os.environ.get("DESK_CRONTAB", "/app/deploy/crontab"))
    extra = parse(path.read_text()) if path.exists() else []
    return extra + package_jobs(only)


def log(msg: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} scheduler {msg}", flush=True)


def _record(cfg: Config | None, job: Job) -> None:
    if cfg is not None and job.run is not None:
        jobrun.record(cfg, job.name, job.run)


def _pump(job: Job, out) -> None:
    for line in out:
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.strip():
            job.said = line.strip()[-2000:]


def start(job: Job, cfg: Config | None, trigger: str, request_id: str | None = None) -> None:
    log(f"{job.line} start ({trigger}): {shlex.join(job.command)}")
    job.said = ""
    job.proc = subprocess.Popen(job.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)  # noqa: S603
    job.pump = threading.Thread(target=_pump, args=(job, job.proc.stdout), daemon=True)
    job.pump.start()
    job.run = {
        "trigger": trigger,
        "request_id": request_id,
        "started": jobrun.stamp(jobrun.now_utc()),
        "finished": None,
        "result": None,
        "exit_code": None,
        "detail": None,
        "note": None,
        "error": None,
    }
    _record(cfg, job)


def reap(jobs: list[Job], cfg: Config | None = None) -> None:
    for job in jobs:
        if job.proc is None or job.proc.poll() is None:
            continue
        rc = job.proc.returncode
        if job.pump is not None:
            job.pump.join(timeout=2)
        log(f"{job.line} exited {rc}")
        if job.run is not None:
            result = "ok" if rc == 0 else "skipped" if rc == BUSY else "failed"
            said = jobrun.last_words(job.said)
            detail = None if rc == 0 else "another run held the lock" if rc == BUSY else f"exit {rc}; see docker logs vektor-desk-cron"
            job.run.update(finished=jobrun.stamp(jobrun.now_utc()), result=result, exit_code=rc, detail=detail)
            job.run.update(note=said.get("skipped") if rc == 0 else None, error=said.get("error") if result == "failed" else None)
            _record(cfg, job)
        job.proc = None
        job.pump = None
        job.run = None


def _busy(jobs: list[Job], name: str) -> bool:
    return any(j.name == name and j.proc is not None for j in jobs)


def tick(jobs: list[Job], t: datetime, cfg: Config | None = None) -> list[Job]:
    reap(jobs, cfg)
    started = []
    for job in jobs:
        if not job.due(t):
            continue
        if _busy(jobs, job.name):
            log(f"{job.line} skipped: still running from last time")
            continue
        start(job, cfg, "schedule")
        started.append(job)
    return started


def serve_requests(jobs: list[Job], cfg: Config) -> list[Job]:
    started = []
    by_name: dict[str, Job] = {}
    for job in jobs:
        by_name.setdefault(job.name, job)
    for name, req in jobrun.take_requests(cfg):
        job = by_name.get(name)
        if job is None:
            log(f"run request for unknown job {name!r} dropped")
            continue
        if _busy(jobs, name):
            log(f"run request for {name} dropped: it's running")
            continue
        start(job, cfg, "request", str(req.get("id") or "")[:32] or None)
        started.append(job)
    return started


def run_chain(jobs: list[Job], cfg: Config) -> None:
    try:
        from desk import startrun

        startrun.advance(cfg, jobs, lambda job, rid: start(job, cfg, "start", rid), lambda name: _busy(jobs, name))
    except Exception as e:  # noqa: BLE001
        log(f"start chain stopped on an error and will try again: {e!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.scheduler", description="Runs every package's jobs.py and deploy/crontab in the desk's time zone.")
    parser.add_argument("crontab", nargs="?", default="/app/deploy/crontab")
    parser.add_argument("--check", action="store_true", help="parse the file and exit")
    args = parser.parse_args(argv)
    jobs = parse(Path(args.crontab).read_text()) + package_jobs()
    if args.check:
        for job in jobs:
            print(f"{job.line} [{job.name}]: {shlex.join(job.command)}")
        print(f"{len(jobs)} jobs ok")
        return 0
    from desk.db import apply_schemas

    log(f"schemas applied: {', '.join(apply_schemas()) or 'none'}")
    zone = ZoneInfo(Config.from_env().timezone)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(f"{len(jobs)} jobs, time zone {zone.key}")
    t = datetime.now(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    cfg = Config.from_env()
    while not stopping:
        jobrun.heartbeat(cfg)
        reap(jobs, cfg)
        serve_requests(jobs, cfg)
        run_chain(jobs, cfg)
        wait = (t - datetime.now(zone)).total_seconds()
        if wait > 0:
            time.sleep(min(wait, jobrun.PICKUP_SECONDS))
            continue
        tick(jobs, t, cfg)
        t += timedelta(minutes=1)
    for job in jobs:
        if job.proc is not None and job.proc.poll() is None:
            job.proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
