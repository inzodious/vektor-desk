import argparse
import json
import sys

from desk.config import DEFAULT_TABLES, Config
from desk.mirror.firestore import FirestoreReader, MirrorError, service_account_session
from desk.mirror.store import MirrorStore, run_mirror
from desk.runlock import BUSY, Busy, job_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.mirror", description="Copy Escape Vektor's Firestore rows into mirror.db (read-only, one way).")
    parser.add_argument("--tables", default="", help="comma-separated tables; default is every table under lockIn/{uid}")
    parser.add_argument("--list", action="store_true", help="list the tables Firestore has and exit")
    parser.add_argument("--full", action="store_true", help="read every row, not just rows changed since the last pull (automatic once a week)")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    try:
        reader = FirestoreReader(cfg.project, cfg.uid, service_account_session(str(cfg.credentials)))
        if args.list:
            print("\n".join(reader.tables()))
            return 0
        tables = [t.strip() for t in args.tables.split(",") if t.strip()] or list(cfg.tables)
        with job_lock("mirror", wait=600, cfg=cfg):
            store = MirrorStore(cfg.mirror_db)
            try:
                result = run_mirror(reader, store, tables=tables, fallback=DEFAULT_TABLES, full=args.full)
            finally:
                store.close()
    except Busy as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return BUSY
    except (MirrorError, OSError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
