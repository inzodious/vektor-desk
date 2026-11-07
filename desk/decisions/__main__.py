import argparse
import json
import sys

from desk.config import Config
from desk.decisions.profile import active_profile


def sync(cfg: Config) -> dict:
    profile = active_profile(cfg)
    return {"profile_version": profile.version, "rules_version": profile.rules_version, "source": profile.source, "error": profile.error}


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
