import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.engine import preflight as pf
from desk.engine.core import PROFILE_ERRORS, convictions

MODERATE = {"label": "Moderate", "single_stock_max_pct": 5, "speculative_max_pct": 5}
STOCK_SLICE_PCT = 1.0
FUND_SLICE_PCT = 2.5
MIN_TICKET = 25.0
CASH_NOTE = "Each size stands alone: together they can't be more than your free cash. Never from margin."
CAP_LAMPS = ("concentration", "plan_rules")
SHORT = "It needs more settled cash than the buying account holds today."
FAILS = (pf.PreflightError, sqlite3.Error, ValueError, KeyError, TypeError, OSError, *PROFILE_ERRORS)


# ---- Words ----


def usd(v: float) -> str:
    return f"${v:,.0f}"


def day_words(iso: str | None) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return f"{d:%b} {d.day}"


# ---- His band ----


def profile(cfg: Config) -> dict:
    try:
        from desk.decisions import risk

        now = risk.current(cfg)
    except Exception:  # noqa: BLE001
        now = None
    real = isinstance(now, dict) and now.get("version") is not None and now.get("source") != "default" and not now.get("default")
    if real:
        return {
            "source": "risk_check",
            "label": now.get("label"),
            "single_stock_max_pct": now.get("single_stock_max_pct"),
            "speculative_max_pct": now.get("speculative_max_pct"),
            "note": None,
        }
    single, sleeve = MODERATE["single_stock_max_pct"], MODERATE["speculative_max_pct"]
    note = f"No risk check on file yet, so sizes use the Moderate band: {single}% a single stock, {sleeve}% for all single stocks together."
    return {"source": "default_moderate", **MODERATE, "note": note}


# ---- The book ----


@dataclass
class Book:
    ctx: pf.Context
    before: dict
    total: float
    account: str
    free: float
    spendable: float
    debit: float
    deposit_usd: float | None
    deposit_on: str | None
    usable_deposit: float
    profile: dict
    conv: dict[str, tuple[float, float]] = field(default_factory=dict)
    stock_cap: float | None = None
    sleeve_cap: float | None = None
    no_buy: dict = field(default_factory=dict)
    today: str = ""


def _least(*values) -> float | None:
    found = [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    return min(found) if found else None


def _no_buy(cfg: Config, now: datetime | None) -> dict:
    try:
        from desk.decisions import plans

        return {str(k).upper(): dict(v) for k, v in plans.no_buy(cfg, now=now).items()}
    except Exception:  # noqa: BLE001
        return {}


def _figure(numbers: dict | None, key: str) -> float | None:
    v = (numbers or {}).get(key)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def load(
    cfg: Config, mirror: sqlite3.Connection | None, conn: sqlite3.Connection, kinds: dict[str, str], *, now: datetime, numbers: dict | None = None
) -> Book | None:
    try:
        ctx = pf.load_context(cfg, mirror, conn, now=now)
    except FAILS:
        return None
    for sym, kind in kinds.items():
        if ctx.kinds.get(sym, "unknown") == "unknown":
            ctx.kinds[sym] = kind if kind in ("stock", "fund") else "stock"
    before = pf.picture(ctx.rows, ctx)
    account = pf.pick_account(None, ctx.rows, "", "buy")
    cash = sum(r["value"] for r in ctx.rows if r["is_cash"] and r["account"] == account)
    ready, owed = _figure(numbers, "cash_ready"), _figure(numbers, "margin_debit")
    debit = max(0.0, owed) if owed is not None else max(before["debit"], -cash, 0.0)
    free = max(0.0, ready) if ready is not None else max(0.0, cash)
    amount, when = ctx.next_deposit
    mine = profile(cfg)
    rule_caps = [
        (r.get("params") or {}).get("max_pct") for r in ctx.rules if r.get("kind") == "single_stock_band" and r.get("enabled", True) and not r.get("symbols")
    ]
    return Book(
        ctx=ctx,
        before=before,
        total=before["total"],
        account=account,
        free=free,
        spendable=0.0 if debit > 0 else free,
        debit=debit,
        deposit_usd=float(amount) if amount else None,
        deposit_on=when,
        usable_deposit=max(0.0, float(amount) - debit) if amount else 0.0,
        profile=mine,
        conv=convictions(ctx.rules),
        stock_cap=_least(_least(*rule_caps) if _least(*rule_caps) is not None else ctx.satellite_cap, mine.get("single_stock_max_pct")),
        sleeve_cap=_least(ctx.satellite_cap, mine.get("speculative_max_pct")),
        no_buy=_no_buy(cfg, now),
        today=now.astimezone(ZoneInfo(cfg.timezone)).date().isoformat() if now.tzinfo else now.date().isoformat(),
    )


def cash_view(book: Book | None) -> dict:
    if book is None:
        return {"free_usd": None, "account": None, "margin_debit_usd": None, "next_deposit_usd": None, "next_deposit_on": None, "note": CASH_NOTE}
    return {
        "free_usd": round(book.free, 2),
        "account": book.account,
        "margin_debit_usd": round(book.debit, 2),
        "next_deposit_usd": book.deposit_usd,
        "next_deposit_on": book.deposit_on,
        "note": CASH_NOTE,
    }


# ---- Room under the caps ----


def room(book: Book, symbol: str, kind: str) -> tuple[float | None, float, str]:
    weights, singles = book.before["weights"], book.before["singles"]
    w = weights.get(symbol, 0.0)
    if symbol in book.conv:
        hi = book.conv[symbol][1]
        return hi - w, STOCK_SLICE_PCT, f"its {hi:g}% conviction band"
    if kind == "fund" or symbol in book.ctx.targets:
        return None, FUND_SLICE_PCT, ""
    others = sum(v for s, v in singles.items() if s not in book.conv)
    one = None if book.stock_cap is None else book.stock_cap - w
    sleeve = None if book.sleeve_cap is None else book.sleeve_cap - others
    if one is None and sleeve is None:
        return None, STOCK_SLICE_PCT, ""
    if sleeve is None or (one is not None and one <= sleeve):
        return one, STOCK_SLICE_PCT, f"the {book.stock_cap:g}% single-stock band"
    return sleeve, STOCK_SLICE_PCT, f"the {book.sleeve_cap:g}% cap on all single stocks together"


def _window(book: Book, symbol: str) -> str | None:
    w = book.no_buy.get(symbol)
    if not isinstance(w, dict):
        return None
    start, until = str(w.get("from") or "")[:10], str(w.get("until") or "")[:10]
    if (start and start > book.today) or (until and until < book.today):
        return None
    return until or "the window ends"


def _blank(note: str, blocked: str | None = None, room_usd: float | None = None, limited_by: str | None = None) -> dict:
    return {"usd": 0.0, "shares": 0.0, "pct_points": 0.0, "room_usd": room_usd, "funding": "wait", "limited_by": limited_by, "note": note, "blocked": blocked}


def _check(book: Book, symbol: str, amount: float, price: float | None, funding: str) -> tuple[str | None, str | None]:
    trade = {"symbol": symbol, "side": "buy", "amount_usd": amount, "funding": funding, "account": book.account}
    if price:
        trade["limit"] = price
    try:
        result = pf.preflight(book.ctx, trade)
    except FAILS as e:
        return None, f"The checker could not confirm this size: {e}."
    lights = {x["id"]: x for x in result["lights"]}
    if funding == "cash" and lights["funding"]["status"] == "act":
        return SHORT, None
    for lamp in CAP_LAMPS:
        if lights[lamp]["status"] == "act":
            return lights[lamp]["detail"], None
    wash = lights["wash_sales"]
    if wash["status"] == "act":
        return wash["detail"], None
    return None, wash["detail"] if wash["status"] == "watch" else None


def size(book: Book | None, symbol: str, kind: str, price: float | None) -> dict:
    if book is None or book.total <= 0:
        return _blank("Sizes appear once the engine has your holdings.")
    until = _window(book, symbol)
    if until:
        text = f"{symbol} is inside a planned loss-sale window: no buys until {day_words(until)}."
        return _blank(text, blocked=text, limited_by="no-buy window")
    room_pct, slice_pct, cap_name = room(book, symbol, kind)
    slice_usd = slice_pct * book.total / 100
    room_usd = None if room_pct is None else round(max(0.0, room_pct) * book.total / 100, 2)
    if room_usd is not None and room_usd < MIN_TICKET:
        text = f"Nothing to add: {symbol} has no room left under {cap_name}."
        return _blank(text, blocked=text, room_usd=room_usd, limited_by=cap_name)
    want = slice_usd if room_usd is None else min(slice_usd, room_usd)
    limited = "starter slice" if room_usd is None or slice_usd <= room_usd else cap_name
    base = f"A starter slice of {slice_pct:g}% of the portfolio" if limited == "starter slice" else f"Cut to the room left under {cap_name}"
    if book.spendable >= MIN_TICKET:
        amount, funding = min(want, book.spendable), "cash"
        note = f"{base}, paid from free cash."
        if book.spendable < want:
            limited, note = "free cash", f"Cut to your free cash of {usd(book.spendable)}."
    elif book.usable_deposit >= MIN_TICKET:
        amount, funding = min(want, book.usable_deposit), "deposit"
        after = " after it clears the margin debit" if book.debit > 0 else ""
        note = f"{base}. Waits for the {day_words(book.deposit_on)} deposit{after}. Never on margin."
        if book.usable_deposit < want:
            limited = "next deposit"
    else:
        why = "the margin debit comes first" if book.debit > 0 else "nothing is free to spend"
        ceiling = f"The caps leave room for {usd(room_usd)}" if room_usd is not None else f"A starter slice would be {usd(want)}"
        return _blank(f"No free cash today: {why}. {ceiling} once cash is free. Never on margin.", room_usd=room_usd, limited_by="free cash")
    blocked, warning = _check(book, symbol, amount, price, funding)
    if blocked == SHORT:
        return _blank(f"{SHORT} Never on margin.", room_usd=room_usd, limited_by="free cash")
    if blocked:
        return _blank(blocked, blocked=blocked, room_usd=room_usd, limited_by="plan rules")
    if warning:
        note = f"{note} {warning}"
    return {
        "usd": round(amount, 2),
        "shares": round(amount / price, 4) if price else None,
        "pct_points": round(amount / book.total * 100, 2),
        "room_usd": room_usd,
        "funding": funding,
        "limited_by": limited,
        "note": note,
        "blocked": None,
    }
