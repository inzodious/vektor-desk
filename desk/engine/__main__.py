import argparse
import json
import sys
from datetime import UTC, datetime

from desk.config import Config
from desk.db import connect
from desk.engine import ENGINE_VERSION, schema
from desk.engine.holdings import rebuild
from desk.engine.source import open_mirror
from desk.runlock import BUSY, Busy, job_lock


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_holdings(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    if mirror is None:
        return {"ok": False, "error": "mirror.db does not exist yet; run python -m desk.mirror first."}
    desk = connect(cfg.desk_db)
    try:
        schema.apply(desk)
        with desk:
            run_id = desk.execute("INSERT INTO engine_runs (job, started_at, engine_version) VALUES ('holdings', ?, ?)", (now_iso(), ENGINE_VERSION)).lastrowid
        result = rebuild(mirror, desk)
        with desk:
            desk.execute("UPDATE engine_runs SET finished_at=?, ok=1, detail=? WHERE id=?", (now_iso(), json.dumps(result), run_id))
        return {"ok": True, **result}
    finally:
        mirror.close()
        desk.close()


JOBS = {"holdings": run_holdings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.engine", description="Vektor Desk statistics engine.")
    parser.add_argument("job", choices=sorted(JOBS))
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    try:
        with job_lock(f"engine-{args.job}", wait=600, cfg=cfg):
            result = JOBS[args.job](cfg)
    except Busy as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return BUSY
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
