import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from desk.agents.console import process_queue, process_triggers, queue_retry
from desk.agents.desks import DESKS, Desk, get
from desk.agents.pipeline import run_proposal_desk
from desk.agents.runner import run_desk
from desk.agents.status import crew
from desk.agents.strategy import queue_reviews
from desk.config import Config

SMOKE = Desk("smoke", "Smoke test", "low", 0, 1, 1000)
SMOKE_SYSTEM = "You are a connectivity check. Reply with the single word OK."
EXIT = {"ok": 0, "disabled": 0, "over_budget": 0, "not_ready": 0, "unchanged": 0, "busy": 75, "deferred": 75}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.agents", description="Vektor Desk agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one desk now")
    run.add_argument("desk", choices=sorted(DESKS))
    run.add_argument("--trigger", default="schedule")
    queue = sub.add_parser("queue", help="work through Console and trigger requests")
    queue.add_argument("--now-only", action="store_true", help="only requests marked Run now")
    sub.add_parser("triggers", help="turn today's engine triggers into requests")
    sub.add_parser("lab-reviews", help="queue a Strategy desk run for each new lab result")
    sub.add_parser("smoke", help="one-turn check that the CLI and token work")
    sub.add_parser("status", help="print the crew status as JSON")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.cmd == "status":
        json.dump(crew(cfg), sys.stdout, indent=2)
        print()
        return 0
    if args.cmd == "smoke":
        out = run_desk(SMOKE, SMOKE_SYSTEM, "Connectivity check.", cfg=cfg, trigger="smoke", wait=60)
        print(f"{out.status}: {(out.result.text if out.result else out.note) or ''}".strip())
        return EXIT.get(out.status, 1)
    if args.cmd == "queue":
        tally = process_queue(cfg, now_only=args.now_only)
        if tally.ran:
            print(f"queue: {tally.ran} ran, {tally.done} done, {tally.failed} failed, {tally.requeued} moved to tonight")
        return 0
    if args.cmd == "triggers":
        made = process_triggers(cfg)
        print(f"triggers: {len(made)} new requests")
        return 0
    if args.cmd == "lab-reviews":
        made = queue_reviews(cfg)
        print(f"lab-reviews: {len(made)} new requests")
        return 0
    desk = get(args.desk)
    if not desk.live or not desk.schedules:
        print(f"{desk.title} doesn't run on its own.")
        return 2
    if args.trigger == "schedule" and not desk.due_on(datetime.now(ZoneInfo(cfg.timezone)).date()):
        print(f"{desk.title}: not due today.")
        return 0
    report = run_proposal_desk(cfg, desk.name, trigger=args.trigger)
    if report.status == "deferred" and args.trigger == "schedule":
        queue_retry(cfg, desk.name)
    print(f"{desk.title}: {report.status}, {len(report.created)} proposals, {len(report.rejected)} rejected. {report.note or ''}".strip())
    return EXIT.get(report.status, 1)


if __name__ == "__main__":
    sys.exit(main())
