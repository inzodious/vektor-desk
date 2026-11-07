import argparse
import json
import sys

from desk.agents.desks import DESKS, Desk, get
from desk.agents.runner import run_desk
from desk.agents.status import crew
from desk.config import Config

SMOKE = Desk("smoke", "Smoke test", "low", 0, 1, 1000)
SMOKE_SYSTEM = "You are a connectivity check. Reply with the single word OK."
EXIT = {"ok": 0, "disabled": 0, "over_budget": 0, "busy": 75, "deferred": 75}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.agents", description="Vektor Desk agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one desk now")
    run.add_argument("desk", choices=sorted(DESKS))
    run.add_argument("--trigger", default="schedule")
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
    desk = get(args.desk)
    if not desk.live:
        print(f"{desk.title} isn't built yet.")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
