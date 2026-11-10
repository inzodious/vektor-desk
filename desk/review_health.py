import sqlite3
import sys
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from desk import jobrun
from desk.config import Config
from desk.db import connect
from desk.scheduler import all_jobs

KINDS = ("day", "week", "month", "year")
JOB = "engine-review"
RUN_AT = time(17, 35)
GRACE = timedelta(minutes=30)
END_COLUMNS = ("end", "end_date", "period_end")
FIXES = {
    "stale": "Fix: Settings → Jobs → Review → Run now.",
    "failing": "Fix: Settings → Box → Export logs shows why (cron.log), then Settings → Jobs → Review → Run now.",
}


# ---- When ----


def parse(value: str | None) -> datetime | None:
    seen = jobrun.parse_stamp(value)
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return seen


def due(cfg: Config, now: datetime) -> datetime:
    zone = ZoneInfo(cfg.timezone)
    local = now.astimezone(zone)
    day = local.date()
    while True:
        run = datetime.combine(day, RUN_AT, tzinfo=zone)
        if day.weekday() < 5 and run + GRACE <= local:
            return run.astimezone(UTC)
        day -= timedelta(days=1)


# ---- What's there ----


def packs(cfg: Config) -> dict[str, dict] | None:
    if not cfg.desk_db.exists():
        return None
    try:
        conn = connect(cfg.desk_db, readonly=True)
    except sqlite3.Error:
        return None
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(period_reviews)")}
        if not {"kind", "computed_at"} <= cols:
            return None
        end = next((c for c in END_COLUMNS if c in cols), None)
        through = f'max("{end}")' if end else "NULL"
        rows = conn.execute(f"SELECT kind, {through} AS through, max(computed_at) AS computed_at, count(*) AS periods FROM period_reviews GROUP BY kind")  # noqa: S608
        return {r["kind"]: {"through": r["through"], "computed_at": r["computed_at"], "periods": r["periods"]} for r in rows}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def reviews_status(cfg: Config, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    expected = due(cfg, now)
    found = packs(cfg) or {}
    run = jobrun.last_run(cfg, JOB)
    job = {"result": run.get("result"), "finished": run.get("finished"), "detail": run.get("detail")} if run else None
    base = {"due": jobrun.stamp(expected), "job": job, "kinds": {k: found[k] for k in KINDS if k in found}, "missing": [k for k in KINDS if k not in found]}
    finished = parse(run.get("finished")) if run else None
    ran_ok = finished if run and run.get("result") == "ok" else None
    computed = parse((found.get("day") or {}).get("computed_at"))
    seen = max([t for t in (ran_ok, computed) if t is not None], default=None)
    if run and run.get("result") == "failed" and finished is not None and (seen is None or finished >= seen):
        return base | {"state": "failing", "last_ok": jobrun.stamp(seen) if seen else None}
    if seen is None:
        return base | {"state": "empty", "last_ok": None, "note": "No reviews yet. The first run is 17:35 Eastern on a weekday, or Run now on Review."}
    return base | {"state": "ok" if seen >= expected else "stale", "last_ok": jobrun.stamp(seen)}


# ---- Words ----


def clock(value: str | None, cfg: Config, now: datetime) -> str:
    seen = parse(value)
    if seen is None:
        return "?"
    zone = ZoneInfo(cfg.timezone)
    local = seen.astimezone(zone)
    return local.strftime("%H:%M") if local.date() == now.astimezone(zone).date() else local.strftime("%a %b %-d %H:%M")


def stage_lines(cfg: Config, jobs: list, now: datetime) -> list[str]:
    by_stage: dict[str, list[str]] = {s: [] for s in jobrun.STAGE_ORDER}
    for entry in jobrun.catalogue(jobs).values():
        if entry.stage not in by_stage:
            continue
        run = jobrun.last_run(cfg, entry.name)
        if not run:
            word = "not yet"
        elif not run.get("finished"):
            word = f"running since {clock(run.get('started'), cfg, now)}"
        else:
            word = f"{run.get('result')} {clock(run.get('finished'), cfg, now)}"
        by_stage[entry.stage].append(f"{entry.title} {word}")
    return [f"{stage}: {', '.join(rows) if rows else 'no job yet'}" for stage, rows in by_stage.items()]


def lines(cfg: Config, now: datetime | None = None, jobs: list | None = None) -> tuple[bool, list[str]]:
    now = now or jobrun.now_utc()
    report = reviews_status(cfg, now)
    state = report["state"]
    expected = clock(report["due"], cfg, now)
    if state == "empty":
        out = [report["note"]]
    elif state == "ok":
        out = [f"fresh: last run {clock(report['last_ok'], cfg, now)}, due since {expected}"]
    elif state == "failing":
        out = [
            f"failing: the last run failed at {clock(report['job']['finished'], cfg, now)} ({report['job'].get('detail') or 'no detail'}). {FIXES['failing']}"
        ]
    else:
        out = [f"stale: last good run {clock(report['last_ok'], cfg, now)}, but one was due at {expected}. {FIXES['stale']}"]
    if report["kinds"]:
        out.append(", ".join(f"{k} through {v['through'] or '?'} ({v['periods']})" for k, v in report["kinds"].items()))
    if report["missing"] and state != "empty":
        out.append(f"no {', '.join(report['missing'])} review yet")
    if jobs:
        out.append("Today's run:")
        out.extend(f"  {row}" for row in stage_lines(cfg, jobs, now))
    return state in ("ok", "empty"), out


def main() -> int:
    cfg = Config.from_env()
    try:
        jobs = all_jobs()
    except (OSError, ValueError, ImportError):
        jobs = []
    ok, out = lines(cfg, jobs=jobs)
    print("\n".join(out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
