import calendar
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.decisions.detect import schedule as detect_schedule
from desk.decisions.profile import active_profile
from desk.decisions.records import DecisionError, _account_ok
from desk.decisions.store import loads, now_iso, session
from desk.engine.broker import decision_rows

CADENCES = ("weekly", "biweekly", "semimonthly", "monthly")
LAND_WINDOW_DAYS = 3
LAND_TOLERANCE = 0.25
LOOKBACK_DAYS = 14
AUTO = "auto"
AUTO_WINDOW_DAYS = 180
MIN_LATE_OBS = 3
CASH_IN_WORDS = re.compile(r"TRANSFER|\bEFT\b|\bACH\b|ELECTRONIC|DEPOSIT|CONTRIB|RECEIVED|WIRE", re.I)
CASH_OUT_WORDS = re.compile(r"JOURNAL|TRANSFERRED TO|\bPAID\b|WITHDRAW|DEBIT|DISTRIBUTION", re.I)


# ---- Deposit schedule ----


def validate_deposits(deposits) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if deposits == AUTO:
        return [], []
    if not isinstance(deposits, list):
        return ["deposits must be auto or a list"], []
    seen: set[str] = set()
    for i, d in enumerate(deposits):
        where = f"deposits[{i}]"
        if not isinstance(d, dict):
            errors.append(f"{where} must be a mapping")
            continue
        did = d.get("id")
        if not isinstance(did, str) or not did.strip():
            errors.append(f"{where} needs an id")
        elif did in seen:
            errors.append(f"{where}: id {did!r} is used twice")
        else:
            seen.add(did)
        cadence = d.get("cadence")
        if cadence not in CADENCES:
            errors.append(f"{where}.cadence must be one of {', '.join(CADENCES)}")
            continue
        for key in ("anchor", "until"):
            if key in d:
                try:
                    date.fromisoformat(str(d[key]))
                except ValueError:
                    errors.append(f"{where}.{key} must be a date like 2026-11-14")
        if cadence in ("weekly", "biweekly") and "anchor" not in d:
            errors.append(f"{where}: a {cadence} deposit needs an anchor date it landed on")
        if cadence in ("semimonthly", "monthly"):
            days = d.get("days")
            want = 2 if cadence == "semimonthly" else 1
            if not isinstance(days, list) or len(days) != want or not all(isinstance(x, int) and 1 <= x <= 31 for x in days):
                errors.append(f"{where}.days must list {want} day{'s' if want > 1 else ''} of the month from 1 to 31")
        amount = d.get("amount_usd")
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int | float) or amount < 0):
            errors.append(f"{where}.amount_usd must be a positive number")
        if d.get("weekend", "before") not in ("before", "after"):
            errors.append(f"{where}.weekend must be before or after")
    return errors, []


def _shift(day: date, weekend: str) -> date:
    step = -1 if weekend == "before" else 1
    while day.weekday() >= 5:
        day += timedelta(days=step)
    return day


def schedule_dates(d: dict, start: date, end: date) -> list[date]:
    cadence = d["cadence"]
    weekend = d.get("weekend", "before")
    until = date.fromisoformat(str(d["until"])) if d.get("until") else None
    out: list[date] = []
    if cadence in ("weekly", "biweekly"):
        step = timedelta(days=7 if cadence == "weekly" else 14)
        anchor = date.fromisoformat(str(d["anchor"]))
        k = (start - anchor).days // step.days
        day = anchor + step * k
        while day <= end + timedelta(days=3):
            out.append(_shift(day, weekend))
            day += step
    else:
        y, m = start.year, start.month
        while date(y, m, 1) <= end + timedelta(days=3):
            last = calendar.monthrange(y, m)[1]
            for n in d["days"]:
                out.append(_shift(date(y, m, min(n, last)), weekend))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if d.get("anchor") and cadence in ("semimonthly", "monthly"):
        first = date.fromisoformat(str(d["anchor"]))
        out = [x for x in out if x >= first]
    return sorted({x for x in out if start <= x <= end and (until is None or x <= until)})


def is_cash_in(a: dict) -> bool:
    amount = a.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int | float) or amount <= 0 or not a.get("accountKey") or not a.get("date"):
        return False
    kind = a.get("kind")
    if kind == "deposit":
        return True
    if kind not in ("transfer", "other") or (a.get("symbol") and not a.get("core")):
        return False
    text = f"{a.get('action') or ''} {a.get('description') or ''}"
    return bool(CASH_IN_WORDS.search(text)) and not CASH_OUT_WORDS.search(text)


def cash_in(rows) -> list[dict]:
    found = []
    for rid, a in rows:
        if not is_cash_in(a):
            continue
        try:
            date.fromisoformat(str(a["date"])[:10])
        except ValueError:
            continue
        found.append({"activity_id": rid, "date": str(a["date"])[:10], "accountKey": a["accountKey"], "amount": float(a["amount"]), "source": a.get("source")})
    found.sort(key=lambda x: (x["accountKey"], x["date"], x["activity_id"] or ""))
    kept: list[dict] = []
    for x in found:
        day = date.fromisoformat(x["date"])
        twin = any(
            k["accountKey"] == x["accountKey"]
            and k["source"] != x["source"]
            and round(k["amount"] * 100) == round(x["amount"] * 100)
            and abs((date.fromisoformat(k["date"]) - day).days) <= LAND_WINDOW_DAYS
            for k in kept[-20:]
        )
        if not twin:
            kept.append(x)
    days: dict[tuple[str, str], dict] = {}
    for x in kept:
        same = days.get((x["accountKey"], x["date"]))
        if same is None:
            days[(x["accountKey"], x["date"])] = x | {"activity_ids": [x["activity_id"]]}
        else:
            same["amount"] = round(same["amount"] + x["amount"], 2)
            same["activity_ids"].append(x["activity_id"])
    return sorted(days.values(), key=lambda x: (x["date"], x["accountKey"]))


def mirror_deposits(conn, since: str) -> list[dict]:
    try:
        rows = decision_rows(conn, since)
    except Exception:  # noqa: BLE001
        return []
    return [{k: v for k, v in x.items() if k != "source"} for x in cash_in(rows)]


def _today(cfg: Config, now: datetime | None) -> date:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(cfg.timezone)).date()


def deposit_series(cfg: Config, *, now: datetime | None = None) -> tuple[str, list[dict]]:
    listed = active_profile(cfg).get("deposits", default=AUTO)
    if listed != AUTO:
        return "listed", list(listed or [])
    today = _today(cfg, now)
    with session(cfg) as conn:
        seen = mirror_deposits(conn, (today - timedelta(days=AUTO_WINDOW_DAYS)).isoformat())
    return AUTO, detect_schedule(seen, today)


def upcoming_deposits(cfg: Config, days: int = 60, *, now: datetime | None = None) -> list[dict]:
    today = _today(cfg, now)
    start, end = today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=days)
    mode, plan = deposit_series(cfg, now=now)
    with session(cfg) as conn:
        seen = mirror_deposits(conn, (start - timedelta(days=LAND_WINDOW_DAYS)).isoformat())
    taken: set[str] = set()
    out = []
    expected = sorted(((day, d) for d in plan for day in schedule_dates(d, start, end)), key=lambda x: (x[0], x[1]["id"]))
    for day, d in expected:
        amount = d.get("amount_usd")
        hit = None
        for a in seen:
            if a["activity_id"] in taken or not _account_ok(d.get("account"), a.get("accountKey")):
                continue
            gap = abs((date.fromisoformat(a["date"]) - day).days)
            if gap > LAND_WINDOW_DAYS:
                continue
            if amount and abs(a["amount"] - amount) > amount * LAND_TOLERANCE:
                continue
            if hit is None or gap < abs((date.fromisoformat(hit["date"]) - day).days):
                hit = a
        if hit:
            taken.add(hit["activity_id"])
        overdue = day < today - timedelta(days=LAND_WINDOW_DAYS)
        if not hit and overdue and mode == AUTO and (d.get("observed") or 0) < MIN_LATE_OBS:
            continue
        status = "landed" if hit else "late" if overdue else "expected"
        item = {"id": d["id"], "date": day.isoformat(), "account": d.get("account"), "amount_usd": amount, "status": status}
        out.append(item | {"landed": hit, "scheduled": True, "mode": mode})
    for a in seen:
        if a["activity_id"] in taken or not start.isoformat() <= a["date"] <= today.isoformat():
            continue
        item = {"id": f"money-in-{a['activity_id']}", "date": a["date"], "account": a["accountKey"], "amount_usd": a["amount"], "status": "landed"}
        out.append(item | {"landed": a, "scheduled": False, "mode": mode})
    return sorted(out, key=lambda x: (x["date"], x["id"]))


def deposits_landed(cfg: Config, since: str | None = None, *, now: datetime | None = None) -> list[dict]:
    since = since or (_today(cfg, now) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    return [d for d in upcoming_deposits(cfg, days=0, now=now) if d["status"] == "landed" and d["landed"]["date"] >= since]


# ---- Tax calendar ----


def _last_weekday(year: int, month: int, day: int) -> date:
    return _shift(date(year, month, day), "before")


def _next_weekday(year: int, month: int, day: int) -> date:
    return _shift(date(year, month, day), "after")


def fixed_events(profile, year: int) -> list[dict]:
    start = str(profile.get("tax", "year_end_start", default="12-01"))
    month, day = (int(x) for x in start.split("-"))
    return [
        {"date": date(year, month, day).isoformat(), "kind": "tax", "title": "Year-end tax window opens", "source": "desk"},
        {"date": _last_weekday(year, 12, 31).isoformat(), "kind": "tax", "title": "Last trading day to realize gains or losses this year", "source": "desk"},
        {"date": _next_weekday(year, 4, 15).isoformat(), "kind": "tax", "title": "Last day for last year's HSA and IRA contributions", "source": "desk"},
    ]


def _wash_events(conn, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, symbol, tax_impact FROM decisions WHERE status IN ('approved', 'placed', 'filled') AND tax_impact IS NOT NULL",
    ).fetchall()
    out = []
    for r in rows:
        clear = (loads(r["tax_impact"]) or {}).get("wash_clear_date")
        if clear and start <= str(clear)[:10] <= end:
            out.append({"date": str(clear)[:10], "kind": "wash", "title": f"{r['symbol']} wash-sale window clears", "source": "desk", "decision_id": r["id"]})
    return out


def calendar_events(cfg: Config, since: str | None = None, until: str | None = None, *, now: datetime | None = None) -> list[dict]:
    today = _today(cfg, now)
    start = date.fromisoformat(since) if since else today - timedelta(days=30)
    end = date.fromisoformat(until) if until else today + timedelta(days=365)
    if end < start:
        raise DecisionError("The end date is before the start date.")
    profile = active_profile(cfg)
    events = [e for y in range(start.year, end.year + 1) for e in fixed_events(profile, y) if start.isoformat() <= e["date"] <= end.isoformat()]
    events += [
        {"date": d["date"], "kind": "deposit", "title": f"Deposit: {d['id']}" if d["scheduled"] else "Money in", "source": "desk", "status": d["status"]}
        for d in _deposit_window(cfg, start, end, now)
    ]
    with session(cfg) as conn:
        rows = conn.execute("SELECT * FROM plan_events WHERE date BETWEEN ? AND ? ORDER BY date", (start.isoformat(), end.isoformat())).fetchall()
        events += [{**dict(r), "source": "you"} for r in rows]
        events += _wash_events(conn, start.isoformat(), end.isoformat())
    return sorted(events, key=lambda e: (e["date"], e["kind"], e["title"]))


def _deposit_window(cfg: Config, start: date, end: date, now: datetime | None) -> list[dict]:
    today = _today(cfg, now)
    if end < today - timedelta(days=LOOKBACK_DAYS):
        return []
    items = upcoming_deposits(cfg, days=max((end - today).days, 0), now=now)
    return [d for d in items if start.isoformat() <= d["date"] <= end.isoformat()]


def add_event(cfg: Config, day: str, title: str, note: str | None = None, kind: str = "note") -> dict:
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError) as e:
        raise DecisionError("The date should look like 2026-12-15.", 422) from e
    title = (title or "").strip()
    if not title:
        raise DecisionError("An event needs a title.", 422)
    if kind not in ("note", "tax", "deposit"):
        raise DecisionError("kind must be note, tax or deposit", 422)
    eid = f"e_{secrets.token_hex(5)}"
    with session(cfg) as conn, conn:
        conn.execute(
            "INSERT INTO plan_events (id, date, title, note, kind, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (eid, day, title[:200], (note or "").strip()[:2000] or None, kind, now_iso()),
        )
        row = conn.execute("SELECT * FROM plan_events WHERE id=?", (eid,)).fetchone()
    return {**dict(row), "source": "you"}


def delete_event(cfg: Config, event_id: str) -> dict:
    with session(cfg) as conn, conn:
        cur = conn.execute("DELETE FROM plan_events WHERE id=?", (event_id,))
    if cur.rowcount == 0:
        raise DecisionError("No such event", 404)
    return {"deleted": event_id}
