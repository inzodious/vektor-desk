import calendar
import re
import secrets
from datetime import date, datetime, timedelta

from desk.config import Config
from desk.decisions.plan import _today
from desk.decisions.records import DecisionError, _now, day_words, local_day, mirror_trades, now_iso, to_dict
from desk.decisions.store import log_event, session

LOOKBACK_DAYS = 60
WINDOW_DAYS = 30
PAST_DAYS = 180
SELL_KINDS = ("trim", "harvest", "sell")
BUY_KINDS = ("add",)
ACTIVE = ("open", "standing")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
MONTH = "(" + "|".join(f"{m[:3]}(?:{m[3:]})?" for m in MONTHS).replace("sep(?:tember)?", "sep(?:t(?:ember)?)?") + r")\.?"
DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
FORMS = (
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("month_day", re.compile(rf"\b{MONTH}\s+{DAY}(?!\d)(?:,?\s+(\d{{4}}))?", re.I)),
    ("day_month", re.compile(rf"\b{DAY}\s+(?:of\s+)?{MONTH}(?![a-z])(?:,?\s+(\d{{4}}))?", re.I)),
    ("slash", re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")),
)
MONTH_ONLY = re.compile(rf"\b(in|during|after|by|before|until|till)\s+(?:early\s+|mid[- ]|late\s+|the\s+end\s+of\s+)?{MONTH}(?![a-z])", re.I)
AFTER = re.compile(r"\b(after|past|following)\s+(?:the\s+)?$", re.I)
BY = re.compile(r"\b(by|until|till|no\s+later\s+than)\s+(?:the\s+)?$", re.I)
BEFORE = re.compile(r"\bbefore\s+(?:the\s+)?$", re.I)
LEAD = re.compile(r"\b(on|after|past|by|before|until|till)\s+(?:the\s+)?$", re.I)
RELATIVE = (
    ("tomorrow", re.compile(r"\btomorrow\b", re.I)),
    ("next_week", re.compile(r"\bnext\s+week\b", re.I)),
    ("next_month", re.compile(r"\bnext\s+month\b", re.I)),
    ("year_end", re.compile(r"\b(?:by|before)\s+(?:the\s+)?(?:end\s+of\s+(?:the\s+)?year|year[- ]end)\b", re.I)),
    ("new_year", re.compile(r"\b(?:after\s+the\s+new\s+year|next\s+year|in\s+the\s+new\s+year)\b", re.I)),
    ("in_days", re.compile(r"\bin\s+(\d{1,3})\s+(day|week)s?\b", re.I)),
)
INTENT = re.compile(
    r"\b(i\s+will|i'll|i\s+plan|i\s+intend|i\s+want\s+to|going\s+to|will\s+(?:sell|buy|trim|add|wait|hold|revisit)|wait(?:ing)?\s+(?:for|until|till)|once|until)\b",
    re.I,
)
HARVEST = re.compile(r"harvest|tax[- ]loss|\blosses\b", re.I)


class StepError(DecisionError):
    pass


# ---- Reading a date from his words ----


def _month(name: str) -> int:
    return next(i for i, m in enumerate(MONTHS, 1) if m.startswith(name.lower().rstrip(".")[:3]))


def _roll(year: int | None, month: int, day: int, ref: date) -> date | None:
    try:
        if year is not None:
            return date(year + 2000 if year < 100 else year, month, day)
        found = date(ref.year, month, day)
        if found >= ref:
            return found
        return date(ref.year + 1, month, day) if (ref - found).days > PAST_DAYS else None
    except ValueError:
        return None


def _day_level(text: str, ref: date) -> tuple[date, re.Match] | None:
    best = None
    for form, pattern in FORMS:
        for m in pattern.finditer(text):
            if form == "iso":
                found = _roll(int(m[1]), int(m[2]), int(m[3]), ref)
            elif form == "month_day":
                found = _roll(int(m[3]) if m[3] else None, _month(m[1]), int(m[2]), ref)
            elif form == "day_month":
                found = None if m[2].lower() == "may" else _roll(int(m[3]) if m[3] else None, _month(m[2]), int(m[1]), ref)
            else:
                named = m[3] or LEAD.search(text[: m.start()])
                found = _roll(int(m[3]) if m[3] else None, int(m[1]), int(m[2]), ref) if named and int(m[1]) <= 12 else None
            if found and found >= ref and (best is None or m.start() < best[1].start()):
                best = (found, m)
    return best


def read_date(text: str | None, ref: date) -> dict | None:
    text = " ".join(str(text or "").split())
    if not text:
        return None
    hit = _day_level(text, ref)
    if hit:
        found, m = hit
        lead = text[: m.start()]
        word = AFTER.search(lead) or BY.search(lead) or BEFORE.search(lead)
        phrase = text[word.start() if word else m.start() : m.end()]
        if word and AFTER.search(lead):
            return {"date": (found + timedelta(days=1)).isoformat(), "until": None, "phrase": phrase}
        if word and BEFORE.search(lead):
            return {"date": ref.isoformat(), "until": (found - timedelta(days=1)).isoformat(), "phrase": phrase}
        if word:
            return {"date": ref.isoformat(), "until": found.isoformat(), "phrase": phrase}
        return {"date": found.isoformat(), "until": None, "phrase": phrase}
    m = MONTH_ONLY.search(text)
    if m:
        month = _month(m[2])
        year = ref.year if month >= ref.month else ref.year + 1
        first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        how = m[1].lower()
        if how == "after":
            return {"date": (last + timedelta(days=1)).isoformat(), "until": None, "phrase": m[0]}
        if how == "before":
            return {"date": ref.isoformat(), "until": (first - timedelta(days=1)).isoformat(), "phrase": m[0]}
        if how in ("by", "until", "till"):
            return {"date": ref.isoformat(), "until": last.isoformat(), "phrase": m[0]}
        return {"date": max(first, ref).isoformat(), "until": last.isoformat(), "phrase": m[0]}
    for form, pattern in RELATIVE:
        m = pattern.search(text)
        if not m:
            continue
        if form == "tomorrow":
            return {"date": (ref + timedelta(days=1)).isoformat(), "until": None, "phrase": m[0]}
        if form == "next_week":
            monday = ref + timedelta(days=7 - ref.weekday())
            return {"date": monday.isoformat(), "until": (monday + timedelta(days=4)).isoformat(), "phrase": m[0]}
        if form == "next_month":
            year, month = (ref.year + 1, 1) if ref.month == 12 else (ref.year, ref.month + 1)
            return {"date": date(year, month, 1).isoformat(), "until": date(year, month, calendar.monthrange(year, month)[1]).isoformat(), "phrase": m[0]}
        if form == "year_end":
            return {"date": ref.isoformat(), "until": date(ref.year, 12, 31).isoformat(), "phrase": m[0]}
        if form == "new_year":
            return {"date": date(ref.year + 1, 1, 1).isoformat(), "until": None, "phrase": m[0]}
        span = int(m[1]) * (7 if m[2].lower() == "week" else 1)
        return {"date": (ref + timedelta(days=span)).isoformat(), "until": None, "phrase": m[0]}
    return None


def step_kind(d: dict, said: str) -> str:
    if d["kind"] in ("sell", "trim", "harvest"):
        return "harvest" if d["kind"] == "harvest" or HARVEST.search(said) else d["kind"]
    return "add" if d["kind"] in ("buy", "deposit_route") else "other"


# ---- Writing a step from a pass ----


def from_pass(conn, d: dict, at: str, tz: str) -> dict | None:
    said = " ".join(str(d["status_reason"] or "").split())
    if d["status"] != "passed" or not said or conn.execute("SELECT 1 FROM loose_steps WHERE decision_id=?", (d["id"],)).fetchone():
        return None
    ref = date.fromisoformat(local_day(d["decided_at"], tz))
    read = read_date(said, ref)
    kind = step_kind(d, said)
    status = "open" if read else "standing" if INTENT.search(said) else "skipped"
    due = read["date"] if read else None
    until = read["until"] if read else None
    if read and not until:
        year_end = date(int(due[:4]), 12, 31).isoformat()
        until = year_end if kind == "harvest" else (date.fromisoformat(due) + timedelta(days=WINDOW_DAYS)).isoformat()
    sid = f"s_{d['id'][2:]}_{secrets.token_hex(2)}"
    row = {"id": sid, "decision_id": d["id"], "symbol": d["symbol"], "kind": kind, "said": said, "phrase": read["phrase"] if read else None}
    row |= {"due": due, "until": until, "status": status, "said_on": ref.isoformat(), "created_at": at, "updated_at": at}
    conn.execute(f"INSERT INTO loose_steps ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    if status == "skipped":
        return None
    log_event(conn, d["id"], "step_added", reason=said, detail={"step_id": sid, "date": due, "until": until}, at=at)
    return dict(conn.execute("SELECT * FROM loose_steps WHERE id=?", (sid,)).fetchone())


def _sweep(conn, moment: datetime, tz: str) -> None:
    since = now_iso(moment - timedelta(days=LOOKBACK_DAYS))
    rows = conn.execute(
        "SELECT * FROM decisions d WHERE status='passed' AND status_reason IS NOT NULL AND decided_at >= ? "
        "AND NOT EXISTS (SELECT 1 FROM loose_steps s WHERE s.decision_id = d.id) ORDER BY decided_at",
        (since,),
    ).fetchall()
    for r in rows:
        from_pass(conn, to_dict(r), now_iso(moment), tz)


def _close(conn, s: dict, status: str, reason: str, event: str, at: str) -> None:
    conn.execute("UPDATE loose_steps SET status=?, status_reason=?, updated_at=? WHERE id=? AND status IN ('open', 'standing')", (status, reason, at, s["id"]))
    if s["decision_id"]:
        log_event(conn, s["decision_id"], event, reason=reason, detail={"step_id": s["id"]}, at=at)


def _settle(conn, moment: datetime, today: str, tz: str) -> None:
    rows = [dict(r) for r in conn.execute("SELECT * FROM loose_steps WHERE status='open' AND due IS NOT NULL ORDER BY due")]
    if not rows:
        return
    from desk.decisions.plans import _fills

    at = now_iso(moment)
    trades = mirror_trades(conn, (date.fromisoformat(min(r["due"] for r in rows)) - timedelta(days=7)).isoformat())
    for s in rows:
        traded = s["symbol"] and s["kind"] in SELL_KINDS + BUY_KINDS
        if traded:
            hits, filled = _fills(s["symbol"], s, trades)
            if hits:
                verb = "Sold" if s["kind"] in SELL_KINDS else "Bought"
                _close(conn, s, "done", f"{verb} {filled:g} {s['symbol']} by {day_words(str(hits[-1]['date'])[:10], tz)}.", "step_done", at)
                continue
        if today > s["until"]:
            what = f" with no {'sale' if s['kind'] in SELL_KINDS else 'buy'}" if traded else ""
            _close(conn, s, "retired", f"Its window ended on {day_words(s['until'], tz)}{what}.", "step_retired", at)


def _view(s: dict, title: str | None, today: str) -> dict:
    status = "standing" if not s["due"] else "upcoming" if today < s["due"] else "open"
    blank = {"when": None, "shares": None, "amount_usd": None, "account": None, "lots": None, "no_buy_days": 0, "note": None, "done_on": None}
    blank |= {"done_by": None, "filled_shares": None, "activity_ids": [], "no_buy_from": None, "rebuy_on": None, "no_buy_now": False}
    keep = {k: s[k] for k in ("id", "symbol", "kind", "due", "until", "decision_id", "said", "phrase", "said_on")}
    return blank | keep | {"text": s["said"].rstrip("."), "by": "you", "status": status, "passed_title": title}


def loose(cfg: Config, *, now: datetime | None = None) -> list[dict]:
    moment = _now(now)
    today = _today(cfg, moment).isoformat()
    with session(cfg) as conn:
        with conn:
            _sweep(conn, moment, cfg.timezone)
            _settle(conn, moment, today, cfg.timezone)
        rows = conn.execute(
            "SELECT s.*, d.title AS passed_title FROM loose_steps s LEFT JOIN decisions d ON d.id = s.decision_id "
            "WHERE s.status IN ('open', 'standing') ORDER BY s.due IS NULL, s.due, s.created_at"
        ).fetchall()
    return [_view(dict(r), r["passed_title"], today) for r in rows]


def remove(cfg: Config, step_id: str, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    with session(cfg) as conn:
        row = conn.execute("SELECT * FROM loose_steps WHERE id=?", (step_id,)).fetchone()
        if row is None:
            raise StepError("That step is not on your list.", 404)
        if row["status"] not in ACTIVE:
            raise StepError("That step has already left your list.", 409)
        with conn:
            _close(conn, dict(row), "removed", "You took it off the list.", "step_removed", at)
    return {"removed": step_id}
