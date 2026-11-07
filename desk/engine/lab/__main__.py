import argparse
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.engine.lab.data import NotReady
from desk.engine.lab.runner import process_queue
from desk.runlock import Busy, job_lock


def hours() -> tuple[int, int]:
    try:
        lo, hi = (int(x) for x in os.environ.get("DESK_LAB_HOURS", "1-6").split("-"))
        return lo, hi
    except ValueError:
        return 1, 6


def in_window(cfg: Config, now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo(cfg.timezone))
    lo, hi = hours()
    return lo <= now.hour < hi


def once(cfg: Config) -> dict:
    try:
        with job_lock("lab", wait=0, cfg=cfg):
            return process_queue(cfg)
    except Busy as e:
        return {"ok": False, "error": str(e)}
    except NotReady as e:
        return {"ok": False, "error": str(e)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.engine.lab", description="Vektor Desk strategy lab: runs queued experiments with no network.")
    parser.add_argument("--once", action="store_true", help="process the queue now and exit, ignoring the overnight window")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.once:
        result = once(cfg)
        print(json.dumps(result))
        return 0 if result.get("ok") else 1
    while True:
        if in_window(cfg):
            print(json.dumps(once(cfg)), flush=True)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
