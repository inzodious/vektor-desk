import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from desk.agents import store
from desk.agents.desks import DESKS
from desk.config import Config

UNIT = "usd_estimate"
MAX_AHEAD = timedelta(days=8)
RETRY_AFTER = timedelta(minutes=5)
RETRIED = ("schedule",)
IN_FLIGHT = timedelta(hours=2)
ORDER = ("plan_keeper", "risk", "debrief", "discounts", "research", "plans", "tax", "filings", "strategy", "scout")
FAILED = ("deferred", "failed", "timeout")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CLOCK = re.compile(
    r"resets?\s+(?:at\s+|on\s+)?"
    r"(?:(?P<dow>mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    r"(?:(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:,|\s+at)?\s+)?"
    r"(?:at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+/[A-Za-z_/]+)\))?",
    re.IGNORECASE,
)
IN = re.compile(r"resets?\s+in\s+(?P<n>\d+)\s*(?P<unit>minute|min|hour|hr|day)", re.IGNORECASE)
STEP = {"minute": timedelta(minutes=1), "min": timedelta(minutes=1), "hour": timedelta(hours=1), "hr": timedelta(hours=1), "day": timedelta(days=1)}

# ---- What the limit message says ----


def clock_now() -> datetime:
    return datetime.now(UTC)


def _zone(name: str | None, fallback: ZoneInfo) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else fallback
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def reset_time(text: str, now: datetime, zone: ZoneInfo) -> datetime | None:
    found = IN.search(text)
    if found:
        return now + int(found["n"]) * STEP[found["unit"].lower()]
    found = CLOCK.search(text)
    if not found:
        return None
    hour, minute, half = int(found["h"]), int(found["m"] or 0), (found["ap"] or "").lower()
    if hour > 23 or minute > 59 or (half and not 1 <= hour <= 12):
        return None
    if half:
        hour = hour % 12 + (12 if half == "pm" else 0)
    local = now.astimezone(_zone(found["tz"], zone))
    at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if found["mon"]:
        try:
            at = at.replace(month=MONTHS.index(found["mon"].lower()) + 1, day=int(found["day"]))
        except ValueError:
            return None
        if at < local - timedelta(days=1):
            at = at.replace(year=at.year + 1)
    elif found["dow"]:
        at += timedelta(days=(DAYS.index(found["dow"].lower()) - at.weekday()) % 7)
        if at <= local:
            at += timedelta(days=7)
    elif at <= local:
        at += timedelta(days=1)
    return at if now <= at <= now + MAX_AHEAD else None


def scope_of(text: str) -> str:
    return "week" if re.search(r"week", text, re.IGNORECASE) else "session"


def _at(text: object) -> datetime:
    t = datetime.fromisoformat(str(text))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def clock(t: datetime, now: datetime, zone: ZoneInfo) -> str:
    local, today = t.astimezone(zone), now.astimezone(zone).date()
    hour = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == today:
        return f"at {hour}"
    if local.date() == today + timedelta(days=1):
        return f"tomorrow at {hour}"
    return f"on {local.strftime('%A')} at {hour}"


def saw_limit(cfg: Config, text: str, run_id: int | None = None, now: datetime | None = None) -> datetime | None:
    now = now or clock_now()
    resets = reset_time(text, now, ZoneInfo(cfg.timezone))
    if resets is not None:
        store.note_limit(cfg, scope_of(text), now, resets, run_id)
    return resets


def paused_until(cfg: Config, now: datetime | None = None) -> datetime | None:
    now = now or clock_now()
    ahead = [_at(r["resets_at"]) for r in store.limits(cfg) if now < _at(r["resets_at"]) <= _at(r["seen_at"]) + MAX_AHEAD]
    return max(ahead, default=None)


# ---- One retry after the reset ----


def _rank(desk: str) -> tuple[int, str]:
    return (ORDER.index(desk) if desk in ORDER else len(ORDER), desk)


def plan(cfg: Config, desk: str, trigger: str, resets: datetime | None, run_id: int | None = None, now: datetime | None = None) -> str:
    now = now or clock_now()
    if resets is None or trigger not in RETRIED or desk not in DESKS:
        return ""
    last = store.last_retry(cfg, desk)
    if last and last["status"] == "running" and now - _at(last["ran_at"]) < IN_FLIGHT:
        return ""
    row = store.plan_retry(cfg, desk, resets + RETRY_AFTER, "Claude's limit was used up.", run_id)
    return f"The desk tries again {clock(_at(row['due_at']), now, ZoneInfo(cfg.timezone))}."


def fire(cfg: Config, run: Callable[[str], object], now: datetime | None = None) -> tuple[str, str] | None:
    now = now or clock_now()
    if paused_until(cfg, now):
        return None
    due = sorted((r for r in store.retries(cfg, "waiting") if _at(r["due_at"]) <= now), key=lambda r: _rank(r["desk"]))
    if not due:
        return None
    retry, desk = due[0], due[0]["desk"]
    before = (store.last_run(cfg, desk) or {}).get("id", 0)
    store.mark_retry(cfg, retry["id"], "running", at=now)
    try:
        run(desk)
    except Exception as e:  # noqa: BLE001
        store.mark_retry(cfg, retry["id"], "failed", f"{type(e).__name__}: {e}"[:300])
        return desk, "failed"
    last = store.last_run(cfg, desk) or {}
    status = str(last.get("status")) if last.get("id", 0) > before else "nothing to do"
    if status == "busy":
        store.mark_retry(cfg, retry["id"], "waiting")
    else:
        store.mark_retry(cfg, retry["id"], "failed" if status in FAILED else "done", f"{status}: {last.get('note') or ''}".strip(": ")[:300])
    return desk, status


# ---- What the app reads ----


def state(cfg: Config, now: datetime | None = None) -> dict:
    now = now or clock_now()
    zone = ZoneInfo(cfg.timezone)
    held = paused_until(cfg, now)
    waiting = sorted(store.retries(cfg, "waiting"), key=lambda r: _rank(r["desk"]))
    names = ", ".join(DESKS[r["desk"]].title for r in waiting if r["desk"] in DESKS)
    if held:
        line = f"Claude's limit is used up until {clock(held, now, zone).removeprefix('at ').removeprefix('on ')}. Scheduled desk work waits."
        line += f" Then, in this order: {names}." if names else ""
    elif waiting:
        line = f"Catching up after Claude's limit, in this order: {names}."
    else:
        line = None
    last = store.limits(cfg, limit=1)
    return {
        "paused": held is not None,
        "paused_until": held.isoformat(timespec="seconds") if held else None,
        "scope": last[0]["scope"] if held and last else None,
        "retries": [{"desk": r["desk"], "title": DESKS[r["desk"]].title if r["desk"] in DESKS else r["desk"], "due_at": r["due_at"]} for r in waiting],
        "order": list(ORDER),
        "line": line,
    }


# ---- What was spent ----

SUMS = ("turns", "input_tokens", "output_tokens", "cache_tokens", "cost_estimate")
KINDS = {"ok": "ok", "deferred": "deferred", "failed": "failed", "timeout": "failed"}


def _blank() -> dict:
    return {"runs": 0, "ok": 0, "deferred": 0, "failed": 0, "skipped": 0, "minutes": 0.0} | dict.fromkeys(SUMS, 0)


def _add(row: dict, run: dict) -> None:
    row["runs"] += 1
    row[KINDS.get(run["status"], "skipped")] += 1
    row["minutes"] = round(row["minutes"] + (run["duration_ms"] or 0) / 60000, 1)
    for key in SUMS:
        row[key] = round(row[key] + (run[key] or 0), 4)


def usage(cfg: Config, days: int = 8, now: datetime | None = None) -> dict:
    now = now or clock_now()
    zone = ZoneInfo(cfg.timezone)
    since = (now.astimezone(zone) - timedelta(days=max(1, min(int(days), 60)) - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cells: dict[tuple[str, str], dict] = {}
    desks: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    total = _blank()
    for run in store.runs_between(cfg, since.astimezone(UTC), now):
        day = _at(run["started_at"]).astimezone(zone).date().isoformat()
        for row in (cells.setdefault((day, run["desk"]), _blank()), desks.setdefault(run["desk"], _blank()), by_day.setdefault(day, _blank()), total):
            _add(row, run)
    return {
        "unit": UNIT,
        "since": since.isoformat(timespec="seconds"),
        "until": now.isoformat(timespec="seconds"),
        "rows": [{"day": day, "desk": desk} | cell for (day, desk), cell in sorted(cells.items())],
        "desks": [{"desk": desk} | row for desk, row in sorted(desks.items(), key=lambda kv: (-kv[1]["cost_estimate"], kv[0]))],
        "days": [{"day": day} | row for day, row in sorted(by_day.items())],
        "total": total,
        "limits": store.limits(cfg),
    }
