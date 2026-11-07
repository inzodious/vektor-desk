import argparse
import json
import sys

from desk.config import Config
from desk.decisions.alerts import send_alerts
from desk.decisions.profile import active_profile
from desk.decisions.records import confirm_fills, expire_due, rerun_preflight
from desk.decisions.store import now_iso, session


def sync(cfg: Config) -> dict:
    profile = active_profile(cfg)
    with session(cfg) as conn:
        expired = expire_due(conn, now_iso())
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
        "expired": expired,
        "preflight_rerun": checked,
        "filled": len(filled),
        "alerts": len(alerts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.decisions", description="Decision records: reload desk.yaml and tidy the queue.")
    parser.add_argument("command", choices=["sync", "profile"])
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.command == "profile":
        print(json.dumps(active_profile(cfg).as_dict(), indent=2))
        return 0
    result = sync(cfg)
    print(json.dumps(result))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
