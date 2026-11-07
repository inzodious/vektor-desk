import argparse
import json
import sys
from datetime import UTC, datetime

import requests

from desk.config import Config
from desk.db import connect
from desk.engine import ENGINE_VERSION, core, schema
from desk.engine.backfill import run_backfill
from desk.engine.holdings import rebuild
from desk.engine.live import refresh_quotes
from desk.engine.lots import import_inbox
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


def run_core(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    if mirror is None:
        return {"ok": False, "error": "mirror.db does not exist yet; run python -m desk.mirror first."}
    try:
        result = _with_desk(cfg, "core", lambda desk: {"ok": True, **core.store(desk, core.compute(cfg, mirror, desk))})
    finally:
        mirror.close()
    return result


def run_daily(cfg: Config) -> dict:
    held = run_holdings(cfg)
    if not held.get("ok"):
        return held
    return {"ok": True, "holdings": held, "core": run_core(cfg)}


def run_lots(cfg: Config) -> dict:
    return _with_desk(cfg, "lots", lambda desk: import_inbox(cfg, desk))


def http_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "vektor-desk/" + ENGINE_VERSION
    return s


def _with_desk(cfg: Config, job: str, fn) -> dict:
    desk = connect(cfg.desk_db)
    try:
        schema.apply(desk)
        started = now_iso()
        result = fn(desk)
        with desk:
            desk.execute(
                "INSERT INTO engine_runs (job, started_at, finished_at, ok, detail, engine_version) VALUES (?, ?, ?, ?, ?, ?)",
                (job, started, now_iso(), int(bool(result.get("ok"))), json.dumps(result), ENGINE_VERSION),
            )
        return result
    finally:
        desk.close()


def run_quotes(cfg: Config, http=None, force: bool = False) -> dict:
    return _with_desk(cfg, "quotes", lambda desk: refresh_quotes(desk, http or http_session(), force=force))


def run_market_backfill(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "backfill", lambda desk: run_backfill(desk, http or http_session()))


JOBS = {"holdings": run_holdings, "core": run_core, "daily": run_daily, "lots": run_lots, "quotes": run_quotes, "backfill": run_market_backfill}


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
