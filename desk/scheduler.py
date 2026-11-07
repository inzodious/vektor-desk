import argparse
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from desk.config import Config

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
    line: int
    spec: tuple[frozenset[int], ...]
    command: list[str]
    any_day: tuple[bool, bool]
    proc: subprocess.Popen | None = field(default=None, repr=False)

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


def parse(text: str) -> list[Job]:
    jobs = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            raise ValueError(f"line {n}: need five time fields and a command")
        spec = tuple(_field(p, lo, hi) for p, (lo, hi) in zip(parts[:5], RANGES, strict=True))
        jobs.append(Job(line=n, spec=spec, command=shlex.split(parts[5]), any_day=(parts[2] == "*", parts[4] == "*")))
    return jobs


def log(msg: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} scheduler {msg}", flush=True)


def tick(jobs: list[Job], t: datetime) -> list[Job]:
    started = []
    for job in jobs:
        if job.proc is not None and job.proc.poll() is not None:
            log(f"line {job.line} exited {job.proc.returncode}")
            job.proc = None
        if not job.due(t):
            continue
        if job.proc is not None:
            log(f"line {job.line} skipped: still running from last time")
            continue
        log(f"line {job.line} start: {shlex.join(job.command)}")
        job.proc = subprocess.Popen(job.command)  # noqa: S603
        started.append(job)
    return started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.scheduler", description="Runs deploy/crontab lines in the desk's time zone.")
    parser.add_argument("crontab", nargs="?", default="/app/deploy/crontab")
    parser.add_argument("--check", action="store_true", help="parse the file and exit")
    args = parser.parse_args(argv)
    jobs = parse(Path(args.crontab).read_text())
    if args.check:
        print(f"{len(jobs)} jobs ok")
        return 0
    zone = ZoneInfo(Config.from_env().timezone)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(f"{len(jobs)} jobs, time zone {zone.key}")
    t = datetime.now(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    while not stopping:
        wait = (t - datetime.now(zone)).total_seconds()
        if wait > 0:
            time.sleep(min(wait, 5))
            continue
        tick(jobs, t)
        t += timedelta(minutes=1)
    for job in jobs:
        if job.proc is not None and job.proc.poll() is None:
            job.proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
