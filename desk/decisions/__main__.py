import argparse
import json
import sys

from desk.config import Config
from desk.decisions.alerts import send_alerts
from desk.decisions.profile import active_profile
from desk.decisions.records import confirm_fills, rerun_preflight, tidy_now
from desk.decisions.store import session


def sync(cfg: Config) -> dict:
    profile = active_profile(cfg)
    moved = tidy_now(cfg)
    with session(cfg) as conn:
        pending = [
            r["id"] for r in conn.execute("SELECT id FROM decisions WHERE status IN ('proposed', 'snoozed') AND preflight_status IN ('pending', 'error')")
        ]
    checked = sum(rerun_preflight(cfg, d)["preflight_status"] not in ("pending", "error") for d in pending)
    filled = confirm_fills(cfg)
    alerts = send_alerts(cfg)
    return {
        "profile_version": profile.version,
        "rules_version": profile.rules_version,
        "source": profile.source,
        "error": profile.error,
        "expired": moved["expired"],
        "replaced": moved["replaced"],
        "notes": moved["notes"],
        "preflight_rerun": checked,
        "filled": len(filled),
        "alerts": len(alerts),
    }


def night(cfg: Config) -> dict:
    moved = tidy_now(cfg, checks=True)
    gone = moved["expired"] + moved["replaced"] + moved["notes"] + moved["cleared"]
    waiting = moved["waiting"]
    if not gone and not waiting:
        return {"skipped": "Nothing is waiting on a decision."}
    items = f"{waiting} decision{'' if waiting == 1 else 's'} waiting"
    if not gone:
        return {"ready": f"{items}, all current"}
    return {"ready": f"{items}; {gone} out-of-date item{'' if gone == 1 else 's'} moved to the journal with the reason"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.decisions", description="Decision records: reload desk.yaml and tidy the queue.")
    parser.add_argument("command", choices=["sync", "profile", "tidy"])
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.command == "profile":
        print(json.dumps(active_profile(cfg).as_dict(), indent=2))
        return 0
    if args.command == "tidy":
        print(json.dumps(night(cfg)))
        return 0
    result = sync(cfg)
    print(json.dumps(result))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
