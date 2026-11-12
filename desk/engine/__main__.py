import argparse
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from desk import jobrun
from desk.config import Config
from desk.db import connect
from desk.engine import (
    ENGINE_VERSION,
    JOBS_AT,
    asof,
    broker,
    core,
    discounts,
    earnings,
    filings,
    french,
    insider,
    lane,
    paper_exec,
    review,
    schema,
    triggers,
    universe,
)
from desk.engine.backfill import never_fetched, run_backfill
from desk.engine.holdings import rebuild
from desk.engine.kinds import offer_queue
from desk.engine.lab import data as lab_data
from desk.engine.lab import paper, shelf
from desk.engine.live import refresh_quotes
from desk.engine.lookthrough import run_all as run_lookthrough_all
from desk.engine.lots import import_inbox
from desk.engine.research import run_all as run_research_all
from desk.engine.source import open_mirror
from desk.notify import publish
from desk.runlock import BUSY, Busy, job_lock

DRY_RUN = "DESK_ENGINE_DRY_RUN"
DRY_JOBS = ("holdings", "core", "daily", "history")
RESTATE_RETRY = timedelta(hours=1)
RESTATE_WAIT = 900
DEBRIEF_JOB = "agents-run-debrief"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_holdings(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    if mirror is None:
        return {"ok": False, "error": f"The desk has not pulled your accounts yet. In {JOBS_AT}, run Accounts first."}
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
        return {"ok": False, "error": f"The desk has not pulled your accounts yet. In {JOBS_AT}, run Accounts first."}
    try:
        result = _with_desk(cfg, "core", lambda desk: _core(cfg, mirror, desk))
    finally:
        mirror.close()
    return result


def _core(cfg: Config, mirror, desk) -> dict:
    stored = core.store(desk, core.compute(cfg, mirror, desk))
    if os.environ.get(DRY_RUN) == "1":
        return {"ok": True, **stored, "triggers": "skipped in a dry run"}
    fired = triggers.run(cfg, desk, stored["as_of"]) if stored["metrics"] else {"new": 0, "kinds": []}
    return {"ok": True, **stored, "triggers": fired}


def run_daily(cfg: Config) -> dict:
    history = run_history(cfg)
    closes = run_closes(cfg)
    held = run_holdings(cfg)
    if not held.get("ok"):
        return held
    filled = _fill_backcast(cfg, held)
    if filled and filled.get("fetched"):
        held = run_holdings(cfg)
    out = {"ok": True, "history": history, "closes": closes, "holdings": held, "core": run_core(cfg)}
    return out | {"backfill": filled} if filled else out


def run_closes(cfg: Config) -> dict:
    desk = connect(cfg.desk_db)
    try:
        schema.apply(desk)
        settled = asof.settle(desk)
        return settled | asof.stamp(desk)
    finally:
        desk.close()


def _restate_check(cfg: Config) -> tuple[dict, dict | None]:
    desk = connect(cfg.desk_db)
    try:
        schema.apply(desk)
        check = asof.pending(desk)
        last = desk.execute("SELECT ok, finished_at, detail FROM engine_runs WHERE job='restate' ORDER BY id DESC LIMIT 1").fetchone()
        return check, dict(last) if last else None
    finally:
        desk.close()


def _restate_skip(check: dict, last: dict | None) -> str | None:
    if not check["due"]:
        return check["why"]
    if not last or json.loads(last["detail"] or "{}").get("signature") != check["signature"]:
        return None
    if last["ok"]:
        return "Already restated on these closes and quotes."
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(last["finished_at"])
    except (TypeError, ValueError):
        return None
    return "The last try on these closes failed; trying again an hour after it." if age < RESTATE_RETRY else None


def _ask_for(cfg: Config, job: str) -> str:
    folder = jobrun.requests_dir(cfg)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(folder / f"{job}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return "already asked"
    except OSError as e:
        return f"not asked: {e!r}"
    with os.fdopen(fd, "w") as f:
        json.dump({"id": secrets.token_hex(6), "requested_at": jobrun.stamp(jobrun.now_utc()), "client": "restate"}, f)
    return "asked"


def run_restate(cfg: Config) -> dict:
    check, last = _restate_check(cfg)
    skip = _restate_skip(check, last)
    if skip:
        return {"ok": True, "skipped": skip}
    try:
        with job_lock("engine-daily", wait=RESTATE_WAIT, cfg=cfg):
            check, last = _restate_check(cfg)
            skip = _restate_skip(check, last)
            if skip:
                return {"ok": True, "skipped": skip}
            started = now_iso()
            daily = run_daily(cfg)
    except Busy:
        return {"ok": True, "skipped": "The daily pass is still running; the next check looks again."}
    reviewed = run_review(cfg) if daily.get("ok") else {"ok": False, "skipped": "the daily pass failed"}
    ok = bool(daily.get("ok") and reviewed.get("ok"))
    after = _restate_check(cfg)[0]
    result = {"ok": ok, "why": check["why"], "signature": check["signature"], "from": check["day"], "to": after.get("day")}
    result |= {"daily": daily, "review": reviewed, "debrief": _ask_for(cfg, DEBRIEF_JOB) if ok and os.environ.get(DRY_RUN) != "1" else "not asked"}
    desk = connect(cfg.desk_db)
    try:
        with desk:
            desk.execute(
                "INSERT INTO engine_runs (job, started_at, finished_at, ok, detail, engine_version) VALUES ('restate', ?, ?, ?, ?, ?)",
                (started, now_iso(), int(result["ok"]), json.dumps(result), ENGINE_VERSION),
            )
    finally:
        desk.close()
    return result


def _fill_backcast(cfg: Config, held: dict) -> dict | None:
    unpriced = (held.get("backcast") or {}).get("unpriced") or []
    if not unpriced or os.environ.get(DRY_RUN) == "1":
        return None
    desk = connect(cfg.desk_db)
    try:
        new = never_fetched(desk, unpriced)
    finally:
        desk.close()
    return run_market_backfill(cfg) if new else None


def run_history(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    try:
        return _with_desk(cfg, "history", lambda desk: broker.import_inbox(cfg, desk, mirror))
    finally:
        if mirror is not None:
            mirror.close()


def run_lots(cfg: Config) -> dict:
    return _with_desk(cfg, "lots", lambda desk: _lots(cfg, desk))


def _lots(cfg: Config, desk) -> dict:
    result = import_inbox(cfg, desk)
    mirror = open_mirror(cfg)
    try:
        result["history"] = broker.import_inbox(cfg, desk, mirror)
    finally:
        if mirror is not None:
            mirror.close()
    result["ok"] = result["ok"] and result["history"]["ok"]
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
        why = "The Finnhub key is not set" if not result.get("key") else "Finnhub is not answering"
        publish(
            "ops",
            "Live quotes are stale",
            f"{why}, so Live shows the last close. Check Settings.",
            "default",
            tags=["hourglass"],
            click="/settings/data",
            key=f"quotes-{datetime.now(UTC).date().isoformat()}",
            cfg=cfg,
        )
    return result


def _kinds(cfg: Config) -> dict[str, str]:
    mirror = open_mirror(cfg)
    if mirror is None:
        return {}
    desk = connect(cfg.desk_db, readonly=True) if cfg.desk_db.exists() else None
    try:
        return core.symbol_kinds(mirror, core.plan_targets(core.latest_plan(mirror)), desk)
    finally:
        mirror.close()
        if desk is not None:
            desk.close()


def run_research(cfg: Config, http=None) -> dict:
    kinds = _kinds(cfg)
    return _with_desk(cfg, "research", lambda desk: run_research_all(desk, http or http_session(), kinds))


def run_lookthrough(cfg: Config, http=None) -> dict:
    kinds = _kinds(cfg)
    return _with_desk(cfg, "lookthrough", lambda desk: run_lookthrough_all(desk, http or http_session(), kinds))


def run_lab_export(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    try:
        targets = core.plan_targets(core.latest_plan(mirror)) if mirror else {}
    finally:
        if mirror:
            mirror.close()
    kinds = _kinds(cfg)

    def work(desk):
        exported = lab_data.export(cfg, desk, kinds, targets)
        return {**exported, **paper.run(cfg, desk), "library": shelf.queue_missing(cfg), "worker": offer_queue(cfg)}

    return _with_desk(cfg, "lab-export", work)


def run_lab_offer(cfg: Config) -> dict:
    late = shelf.queue_missing(cfg)
    return {"ok": True, **({"library": late} if late.get("queued") or late.get("error") else {}), **offer_queue(cfg)}


def run_french(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "french", lambda desk: french.run(desk, http or http_session()))


def run_universe(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "universe", lambda desk: _universe(desk, http or http_session()))


def _universe(desk, http) -> dict:
    result = universe.run(desk, http, now=datetime.now(UTC))
    result["lane"] = lane.rebuild(desk)
    return result


def run_insider(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "insider", lambda desk: insider.run(desk, http or http_session(), now=datetime.now(UTC)))


def run_earnings(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "earnings", lambda desk: earnings.run(desk, http or http_session(), now=datetime.now(UTC)))


def run_paper(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "paper", lambda desk: paper_exec.run(desk, http or http_session(), now=datetime.now(UTC)))


def run_filings(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "filings", lambda desk: filings.run(desk, http or http_session(), now=datetime.now(UTC)))


def run_discounts(cfg: Config) -> dict:
    return _with_desk(cfg, "discounts", lambda desk: discounts.scan(desk, now=datetime.now(UTC)))


def run_review(cfg: Config) -> dict:
    mirror = open_mirror(cfg)
    try:
        return _with_desk(cfg, "review", lambda desk: review.run(cfg, mirror, desk, now=datetime.now(UTC)))
    finally:
        if mirror is not None:
            mirror.close()


def run_market_backfill(cfg: Config, http=None) -> dict:
    return _with_desk(cfg, "backfill", lambda desk: _backfill_then_scan(desk, http or http_session()))


def _backfill_then_scan(desk, http) -> dict:
    out = run_backfill(desk, http)
    if out.get("advanced"):
        try:
            out["discounts"] = discounts.scan(desk, now=datetime.now(UTC))
        except sqlite3.Error as e:
            out["discounts"] = {"ok": False, "error": str(e)}
    return out


JOBS = {
    "holdings": run_holdings,
    "core": run_core,
    "daily": run_daily,
    "lots": run_lots,
    "history": run_history,
    "universe": run_universe,
    "filings": run_filings,
    "paper": run_paper,
    "insider": run_insider,
    "earnings": run_earnings,
    "discounts": run_discounts,
    "review": run_review,
    "restate": run_restate,
    "quotes": run_quotes,
    "backfill": run_market_backfill,
    "lookthrough": run_lookthrough,
    "lab-export": run_lab_export,
    "lab-offer": run_lab_offer,
    "french": run_french,
    "research": run_research,
}


# ---- Dry run ----


def dry_run(cfg: Config, job: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="desk-dry-") as tmp:
        root = Path(tmp)
        for db in sorted(cfg.data_dir.glob("*.db")):
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            dst = sqlite3.connect(root / db.name)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
        if (cfg.data_dir / "desk.yaml").exists():
            shutil.copy2(cfg.data_dir / "desk.yaml", root / "desk.yaml")
        if (cfg.data_dir / "lab").is_dir():
            (root / "lab").symlink_to(cfg.data_dir / "lab")
        copy = replace(cfg, data_dir=root)
        before = os.environ.get(DRY_RUN)
        os.environ[DRY_RUN] = "1"
        try:
            result = JOBS[job](copy)
        finally:
            if before is None:
                os.environ.pop(DRY_RUN, None)
            else:
                os.environ[DRY_RUN] = before
        health = []
        if copy.desk_db.exists():
            conn = connect(copy.desk_db, readonly=True)
            try:
                health = [
                    {"check": r["check_name"], "status": r["status"], "detail": r["detail"]}
                    for r in conn.execute(
                        "SELECT check_name, status, detail FROM data_health WHERE as_of=(SELECT max(as_of) FROM data_health) ORDER BY check_name"
                    )
                ]
            except sqlite3.Error:
                health = []
            finally:
                conn.close()
    return {**result, "dry_run": True, "health_detail": health}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.engine", description="Vektor Desk statistics engine.")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--dry-run", action="store_true", help="run on a throwaway copy of the data, write nothing and send no alerts")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.dry_run and args.job not in DRY_JOBS:
        print(json.dumps({"ok": False, "error": f"--dry-run covers {', '.join(DRY_JOBS)}; the other jobs call outside services."}), file=sys.stderr)
        return 2
    try:
        with job_lock(f"engine-{args.job}", wait=600, cfg=cfg):
            result = dry_run(cfg, args.job) if args.dry_run else JOBS[args.job](cfg)
    except Busy as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return BUSY
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
