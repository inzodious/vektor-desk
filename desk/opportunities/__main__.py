import argparse
import json
import sys

from desk.config import Config
from desk.opportunities import ready
from desk.opportunities.build import build
from desk.opportunities.night import run_night


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.opportunities", description="Vektor Desk buying opportunities. Advice only; nothing trades.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("night", help="write tonight's discount cases, run Scout if it is overdue, and say what is ready")
    sub.add_parser("list", help="print the ranked list as JSON")
    sub.add_parser("ready", help="print the one line the morning alert uses")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.cmd == "list":
        json.dump(build(cfg), sys.stdout, indent=2)
        print()
        return 0
    if args.cmd == "ready":
        print(ready(cfg) or "Nothing on the list.")
        return 0
    night = run_night(cfg)
    for step in night["steps"]:
        print(f"{step['step']}: {step['status']}. {step.get('note') or ''}".rstrip())
    line = ready(cfg)
    print(json.dumps({"ready": line} if line else {"skipped": night["summary"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
