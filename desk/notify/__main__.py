import argparse
import json
import logging
import sys

from desk.config import Config
from desk.notify import PRIORITIES, TOPICS, publish, recent, subscribe_url
from desk.notify.ops import ops_check


def _outcome(cfg: Config, ok: bool, label: str) -> None:
    last = recent(cfg, 1)
    state = last[0]["status"] if last else "sent"
    if ok:
        print(f"{label}: {state}")
        return
    why = {
        "failed": last[0]["error"] if last else "",
        "off": "DESK_NTFY_URL is empty",
        "muted": "switched off in Settings",
    }
    if state in why:
        print(f"{label}: {state}, {why[state]}")
    else:
        print(f"{label}: skipped, already sent recently")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="python -m desk.notify", description="Phone alerts through the desk's ntfy server")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="publish one alert")
    send.add_argument("topic", choices=sorted(TOPICS))
    send.add_argument("title")
    send.add_argument("body", nargs="?", default="")
    send.add_argument("--priority", choices=list(PRIORITIES), default="default")
    send.add_argument("--click")
    send.add_argument("--key")
    send.add_argument("--tags", default="")
    test = sub.add_parser("test", help="send a test alert to each topic, or the ones named")
    test.add_argument("topics", nargs="*", default=[])
    sub.add_parser("ops", help="alert on a stale mirror or an expiring Claude token")
    sub.add_parser("topics", help="list topics and their subscribe URLs")
    rec = sub.add_parser("recent", help="the last alerts, newest first")
    rec.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    cfg = Config.from_env()

    if args.command == "send":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        ok = publish(args.topic, args.title, args.body, args.priority, tags=tags, click=args.click, key=args.key, cfg=cfg)
        _outcome(cfg, ok, args.topic)
        return 0 if ok else 1
    if args.command == "test":
        unknown = [t for t in args.topics if t not in TOPICS]
        if unknown:
            parser.error(f"unknown topic {unknown[0]}; use one of {', '.join(TOPICS)}")
        failed = 0
        for topic in args.topics or sorted(TOPICS):
            ok = publish(topic, "Vektor Desk test", f"Alerts for {topic} reach this phone.", "low", tags=["rocket"], cfg=cfg)
            _outcome(cfg, ok, topic)
            failed += not ok
        return 1 if failed else 0
    if args.command == "ops":
        sent = ops_check(cfg)
        print("sent: " + ", ".join(sent) if sent else "nothing to report")
        return 0
    if args.command == "topics":
        for topic, about in TOPICS.items():
            print(f"{subscribe_url(cfg, topic):<55} {about}")
        return 0
    json.dump(recent(cfg, args.limit), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
