import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine.market import ET
from desk.opportunities.sizing import day_words
from desk.runlock import run_dir

SCOUT = "scout"
SCOUT_EVERY_DAYS = 35
SCOUT_RETRY_DAYS = 7
LOCK_WAIT = 600.0
CASES_WAIT = 900.0
LATE = (time(5, 30), time(9, 0))
COUNTED = ("ok", "failed", "timeout", "running")
WAITING = ("busy", "deferred")
STOPPED = ("disabled", "guarded", "over_budget", "busy", "deferred", "failed")
QUIET = ("ok", "fresh", "current", "late", "disabled", "guarded", "over_budget", "not_ready", "unhealthy")


# ---- Last night's record ----


def _path(cfg: Config):
    return run_dir(cfg) / "opportunities" / "night.json"


def last_night(cfg: Config) -> dict | None:
    try:
        found = json.loads(_path(cfg).read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _save(cfg: Config, night: dict) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(night, indent=1))
    tmp.replace(path)


def _stamp(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---- Steps ----


def scan_step(cfg: Config, scan: Callable | None = None) -> dict:
    if not cfg.desk_db.exists():
        return {"step": "scan", "status": "not_ready", "note": "The engine has not run yet."}
    conn = connect(cfg.desk_db, readonly=True)
    try:
        latest = conn.execute("SELECT max(date) FROM price_bars").fetchone()[0]
        scanned = conn.execute("SELECT max(as_of) FROM discount_scans").fetchone()[0]
    except sqlite3.Error:
        return {"step": "scan", "status": "not_ready", "note": "The engine has not run yet."}
    finally:
        conn.close()
    if latest is None:
        return {"step": "scan", "status": "not_ready", "note": "No prices yet."}
    if scanned is not None and scanned >= latest:
        return {"step": "scan", "status": "current", "note": f"The discount scan is current to {day_words(scanned)}."}
    if scan is None:
        from desk.engine.__main__ import run_discounts as scan
    try:
        result = scan(cfg) or {}
    except Exception as e:  # noqa: BLE001
        return {"step": "scan", "status": "failed", "note": f"The discount scan did not finish: {e}"}
    return {"step": "scan", "status": "ok", "note": f"Scanned {result.get('scanned', 0)} names, {result.get('hits', 0)} hits."}


def cases_step(cfg: Config, cases: Callable | None = None, wait: float = LOCK_WAIT) -> dict:
    if cases is None:
        from desk.agents.discounts import run_discount_desk as cases
    try:
        report = cases(cfg, trigger="schedule", wait=wait)
    except Exception as e:  # noqa: BLE001
        return {"step": "cases", "status": "failed", "note": f"Discount cases did not finish: {e}"}
    written, failed = len(report.written), len(report.failed)
    note = report.note or f"Wrote {written} of {report.pending} discount cases" + (f", {failed} failed." if failed else ".")
    return {"step": "cases", "status": report.status, "note": note, "written": written, "pending": report.pending}


def list_cases_step(cfg: Config, cases: Callable | None = None, wait: float = LOCK_WAIT, now: datetime | None = None) -> dict:
    from desk.opportunities import cases as own
    from desk.opportunities.build import build

    step = "list_cases"
    now = now or datetime.now(UTC)
    try:
        listing = build(cfg, now=now)
        if listing["as_of"] is None:
            return {"step": step, "status": "not_ready"}
        hits = own.wanted(listing)
        room = max(0, own.CAP - own.written_tonight(cfg, now))
    except Exception as e:  # noqa: BLE001
        return {"step": step, "status": "failed", "note": f"Could not read the list for cases: {e}"}
    if not hits:
        return {"step": step, "status": "current", "note": "Every row on sale has a written case or note."}
    if not room:
        return {"step": step, "status": "over_budget", "note": f"Tonight's {own.CAP} cases are written; {len(hits)} rows wait for tomorrow night."}
    if LATE[0] <= now.astimezone(ET).time() < LATE[1]:
        return {"step": step, "status": "late", "note": f"Too close to morning to start cases; {len(hits)} rows wait for tomorrow night."}
    hits = hits[:room]
    if cases is None:
        from desk.agents.discounts import run_discount_desk as cases
    try:
        report = cases(cfg, discounts=own.ListSource(hits), trigger="schedule", limit=len(hits), wait=max(wait, CASES_WAIT))
    except Exception as e:  # noqa: BLE001
        return {"step": step, "status": "failed", "note": f"Cases for the list did not finish: {e}"}
    written, failed = len(report.written), len(report.failed)
    note = f"Wrote {written} of {len(hits)} cases for rows on sale" + (f", {failed} failed." if failed else ".")
    if report.note and not written:
        note = report.note
    return {"step": step, "status": report.status, "note": note, "written": written, "pending": len(hits)}


def _scout_runs(cfg: Config) -> list[dict]:
    from desk.agents import store

    return store.runs(cfg, SCOUT, 30)


def scout_step(cfg: Config, scout: Callable | None = None, wait: float = LOCK_WAIT, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        runs = _scout_runs(cfg)
    except Exception as e:  # noqa: BLE001
        return {"step": "scout", "status": "not_ready", "note": f"Could not read Scout's runs: {e}"}
    fresh = (now - timedelta(days=SCOUT_EVERY_DAYS)).isoformat(timespec="seconds")
    recent = (now - timedelta(days=SCOUT_RETRY_DAYS)).isoformat(timespec="seconds")
    good = next((r for r in runs if r["status"] == "ok" and r["started_at"] >= fresh), None)
    if good:
        return {"step": "scout", "status": "fresh", "note": f"Scout last ran on {day_words(good['started_at'])}; it runs about once a month."}
    if any(r["status"] in COUNTED and r["started_at"] >= recent for r in runs):
        return {"step": "scout", "status": "over_budget", "note": "Scout already used this week's run."}
    if scout is None:
        from desk.agents.pipeline import run_proposal_desk as scout
    try:
        report = scout(cfg, SCOUT, trigger="schedule", wait=wait)
    except Exception as e:  # noqa: BLE001
        return {"step": "scout", "status": "failed", "note": f"Scout did not finish: {e}"}
    made = len(report.created)
    note = report.note or (f"Scout wrote {made} idea{'s' if made != 1 else ''}." if made else "Scout looked and proposed nothing.")
    return {"step": "scout", "status": report.status, "note": note, "ideas": made}


# ---- The night ----


def run_night(
    cfg: Config,
    *,
    scan: Callable | None = None,
    cases: Callable | None = None,
    scout: Callable | None = None,
    wait: float = LOCK_WAIT,
    now: datetime | None = None,
) -> dict:
    started = now or datetime.now(UTC)
    steps = [scan_step(cfg, scan), cases_step(cfg, cases, wait)]
    stopped = steps[1]["status"] in STOPPED
    steps.append({"step": "list_cases", "status": steps[1]["status"]} if stopped else list_cases_step(cfg, cases, wait, now))
    steps.append(scout_step(cfg, scout, wait, now))
    states = [s["status"] for s in steps]
    status = "waiting" if any(s in WAITING for s in states) else "ok" if all(s in QUIET for s in states) else "partial"
    night = {
        "started_at": _stamp(started),
        "finished_at": _stamp(now or datetime.now(UTC)),
        "status": status,
        "summary": " ".join(s["note"] for s in steps if s.get("note")),
        "steps": steps,
    }
    _save(cfg, night)
    return night
