import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.engine.lab.data import NotReady
from desk.engine.lab.runner import process_queue, sims
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


def tick(cfg: Config, holding: bool, now: datetime | None = None) -> tuple[dict | None, bool]:
    if not (holding or in_window(cfg, now)):
        return None, False
    result = once(cfg)
    return result, bool(result.get("waiting_for_worker"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.engine.lab", description="Vektor Desk strategy lab: runs queued experiments with no network.")
    parser.add_argument("--once", action="store_true", help="process the queue now and exit, ignoring the overnight window")
    parser.add_argument("--sims", metavar="REQUEST", help="simulate one queued experiment file against --data and print the rows; touches no ledger")
    parser.add_argument("--data", metavar="LAB_DB", help="the lab data file for --sims")
    args = parser.parse_args(argv)
    if args.sims:
        if not args.data:
            parser.error("--sims needs --data")
        try:
            print(json.dumps(sims(Path(args.data), json.loads(Path(args.sims).read_text())), separators=(",", ":")))
        except (NotReady, OSError, ValueError) as e:
            print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
            return 1
        return 0
    cfg = Config.from_env()
    if args.once:
        result = once(cfg)
        print(json.dumps(result))
        return 0 if result.get("ok") else 1
    holding = False
    while True:
        result, holding = tick(cfg, holding)
        if result is not None:
            print(json.dumps(result), flush=True)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
