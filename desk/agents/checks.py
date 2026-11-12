import re
from collections.abc import Iterable
from datetime import date

from desk.agents import wording

PLAN_SELLS = ("trim", "harvest", "sell")
LIVE_STEPS = ("upcoming", "open", "partial")
PROSE = ("title", "thesis", "rule_served", "invalidation", "horizon")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
PAYS_MARGIN = re.compile(r"\b(clear|pay|repay|cover|reduc|cut|eras|wip|retir|eliminat|settl)\w*\s+(off\s+|down\s+|out\s+)?(the\s+|your\s+|that\s+)?margin")
KEEPER = "plan_keeper"

# ---- Words and dates ----


def words(p: dict) -> str:
    return " ".join(str(p.get(k) or "") for k in PROSE).lower()


def is_sell(p: dict) -> bool:
    ticket = p.get("order_ticket") if isinstance(p.get("order_ticket"), dict) else {}
    return p.get("kind") in wording.SELLS or ticket.get("action") == "sell"


def _date(day: object) -> date | None:
    try:
        return date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None


def plain_day(day: object) -> str:
    d = _date(day)
    return f"{MONTHS[d.month - 1].capitalize()} {d.day}" if d else str(day or "")


def plain_window(due: object, until: object) -> str:
    a, b = _date(due), _date(until)
    if a is None or b is None or a == b:
        return plain_day(due)
    return f"{plain_day(due)} to {b.day}" if (a.year, a.month) == (b.year, b.month) else f"{plain_day(due)} to {plain_day(until)}"


def names_day(text: str, day: object) -> bool:
    d = _date(day)
    if d is None:
        return False
    month = MONTHS[d.month - 1]
    return bool(re.search(rf"{d.isoformat()}|\b{month}[a-z]*\.?\s+0?{d.day}(?!\d)|\b0?{d.month}/0?{d.day}(?!\d)", text.lower()))


# ---- The checks ----


def margin_hold_off(item: dict) -> bool:
    if item.get("kind") != "hold_off" or str(item.get("symbol") or "").strip():
        return False
    text = f"{item.get('title') or ''} {item.get('rule_served') or ''}".lower()
    return item.get("subject") == "margin" or "margin" in text


def plan_problem(p: dict, steps: Iterable[dict], today: str) -> str | None:
    if not is_sell(p):
        return None
    symbol = str(p.get("symbol") or "").upper()
    text = words(p)
    live = [s for s in steps if isinstance(s, dict) and s.get("status") in LIVE_STEPS]
    for s in live:
        ahead = s.get("status") == "upcoming" and str(s.get("due") or "") > today
        if s.get("kind") in PLAN_SELLS and str(s.get("symbol") or "").upper() == symbol and ahead and not names_day(text, s.get("due")):
            return f"Your plan already times this sale for {plain_window(s.get('due'), s.get('until'))}."
    repay = next((s for s in live if s.get("kind") == "repay"), None)
    if repay and PAYS_MARGIN.search(text):
        when = f" on {plain_day(repay.get('due'))}" if repay.get("due") else ""
        return f"Your plan already pays the margin debit down{when}, so no sale is needed for it."
    return None


def repeat_problem(p: dict, desk: str | None, standing: Iterable[dict]) -> str | None:
    if desk == KEEPER or not margin_hold_off(p):
        return None
    mine = p.get("id")
    for other in standing:
        if not isinstance(other, dict) or not margin_hold_off(other) or other.get("origin") in (None, desk):
            continue
        theirs = other.get("id")
        if other.get("origin") == KEEPER or mine is None or theirs is None or theirs < mine:
            return f"Already covered by a standing note: {other.get('title') or 'hold off on new buys until the margin debit is paid'}."
    return None


def queue_problem(p: dict, *, steps: Iterable[dict] = (), today: str, desk: str | None = None, standing: Iterable[dict] = ()) -> str | None:
    desk = desk or p.get("origin")
    return plan_problem(p, steps, today) or repeat_problem(p, desk, standing)
