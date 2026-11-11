import fcntl
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from desk.config import Config

BUSY = 75


class Busy(RuntimeError):
    pass


def run_dir(cfg: Config | None = None) -> Path:
    return (cfg or Config.from_env()).data_dir / "run"


@contextmanager
def job_lock(name: str, *, wait: float = 0.0, cfg: Config | None = None) -> Iterator[Path]:
    folder = run_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + wait
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Busy(f"{name} is already running") from None
                time.sleep(1)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"pid": os.getpid(), "since": datetime.now(UTC).isoformat(timespec="seconds")}).encode())
        yield path
    finally:
        os.close(fd)


def running(cfg: Config | None = None) -> list[dict]:
    folder = run_dir(cfg)
    out = []
    for path in sorted(folder.glob("*.lock")) if folder.exists() else []:
        fd = os.open(path, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            try:
                info = json.loads(path.read_text() or "{}")
            except ValueError:
                info = {}
            out.append({"job": path.stem, **info})
        finally:
            os.close(fd)
    return out


def hold(name: str, command: list[str]) -> int:
    import subprocess

    try:
        with job_lock(name):
            rc = subprocess.call(command)  # noqa: S603
            return rc if rc >= 0 else 128 - rc
    except Busy as e:
        print(f"skipped: {e}", file=sys.stderr)
        return BUSY


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--hold"]:
        if len(argv) < 4 or argv[2] != "--":
            print("usage: python -m desk.runlock --hold NAME -- COMMAND...", file=sys.stderr)
            return 2
        return hold(argv[1], argv[3:])
    jobs = running()
    if jobs:
        print(", ".join(f"{j['job']} (since {j.get('since', '?')})" for j in jobs))
        return BUSY
    return 0


if __name__ == "__main__":
    sys.exit(main())
