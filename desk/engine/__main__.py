import argparse
import json
import sys
from datetime import UTC, datetime

import requests

from desk.config import Config
from desk.db import connect
from desk.engine import ENGINE_VERSION, core, schema, triggers
from desk.engine.backfill import run_backfill
from desk.engine.holdings import rebuild
from desk.engine.lab import data as lab_data
from desk.engine.lab import paper
from desk.engine.live import refresh_quotes
from desk.engine.lookthrough import run_all as run_lookthrough_all
from desk.engine.lots import import_inbox
from desk.engine.research import run_all as run_research_all
from desk.engine.source import open_mirror
from desk.notify import publish
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
        result = _with_desk(cfg, "core", lambda desk: _core(cfg, mirror, desk))
    finally:
        mirror.close()
    return result


def _core(cfg: Config, mirror, desk) -> dict:
    stored = core.store(desk, core.compute(cfg, mirror, desk))
    fired = triggers.run(cfg, desk, stored["as_of"]) if stored["metrics"] else {"new": 0, "kinds": []}
    return {"ok": True, **stored, "triggers": fired}


def run_daily(cfg: Config) -> dict:
    held = run_holdings(cfg)
    if not held.get("ok"):
        return held
    return {"ok": True, "holdings": held, "core": run_core(cfg)}


def run_lots(cfg: Config) -> dict:
    return _with_desk(cfg, "lots", lambda desk: _lots(cfg, desk))


def _lots(cfg: Config, desk) -> dict:
    result = import_inbox(cfg, desk)
    if result["imported"]:
        triggers.record(cfg, desk, triggers.lot_export(cfg, desk, result["imported"]))
    return result


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
    result = _with_desk(cfg, "quotes", lambda desk: refresh_quotes(desk, http or http_session(), force=force))
    if result.get("state") == "open" and not cfg.demo and (not result.get("key") or (result.get("errors") and not result.get("quotes"))):
        why = "FINNHUB_API_KEY is not set" if not result.get("key") else "Finnhub is not answering"
        publish(
            "ops",
            "Live quotes are stale",
            f"{why}, so Live shows the last close. Check Settings.",
            "default",
            tags=["hourglass"],
            click="/settings",
            key=f"quotes-{datetime.now(UTC).date().isoformat()}",
            cfg=cfg,
        )
    return result


def _kinds(cfg: Config) -> dict[str, str]:
    mirror = open_mirror(cfg)
    if mirror is None:
        return {}
    try:
        return core.symbol_kinds(mirror, core.plan_targets(core.latest_plan(mirror)))
    finally:
        mirror.close()


def run_research(cfg: Config, http=None) -> dict:
    kinds = _kinds(cfg)
    return _with_desk(cfg, "research", lambda desk: run_research_all(desk, http or http_session(), kinds))


def run_lookthrough(cfg: Config, http=None) -> dict:
    kinds = _kinds(cfg)
    return _with_desk(cfg, "lookthrough", lambda desk: run_lookthrough_all(desk, http or http_session(), kinds))


def run_lab_export(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    try:
        kinds = core.symbol_kinds(mirror, core.plan_targets(core.latest_plan(mirror))) if mirror else {}
        targets = core.plan_targets(core.latest_plan(mirror)) if mirror else {}
    finally:
        if mirror:
            mirror.close()

    def work(desk):
        exported = lab_data.export(cfg, desk, kinds, targets)
        return {**exported, **paper.run(cfg, desk)}

    return _with_desk(cfg, "lab-export", work)


def run_market_backfill(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "backfill", lambda desk: run_backfill(desk, http or http_session()))


JOBS = {
    "holdings": run_holdings,
    "core": run_core,
    "daily": run_daily,
    "lots": run_lots,
    "quotes": run_quotes,
    "backfill": run_market_backfill,
    "lookthrough": run_lookthrough,
    "lab-export": run_lab_export,
    "research": run_research,
}


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
