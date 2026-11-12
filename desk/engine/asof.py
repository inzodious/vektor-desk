import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from desk.engine.market import EARLY_CLOSE, ET, session, trading_day

CLOSE_GRACE = timedelta(seconds=60)
KEEP_DAYS = 7
WAIT_DAYS = 7
NAMED = 3
NUMBERS = (
    ("value", "value.market", "now"),
    ("day_change", "value.day_change", "now"),
    ("day_change_pct", "ret.twr", "1D"),
    ("cash_ready", "cash.ready", "now"),
    ("cash_pending", "cash.pending", "now"),
    ("cash_pending_days", "cash.pending_days", "now"),
    ("margin_debit", "margin.debit", "now"),
    ("margin_cost_month", "margin.cost_month", "now"),
)
EMPTY_WORDS = "The engine has not run yet."


def now_utc() -> datetime:
    return datetime.now(UTC)


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None


def _stamp(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def close_at(day: date) -> datetime:
    return datetime.combine(day, time(13, 0) if day in EARLY_CLOSE else time(16, 0), ET)


def last_session(now: datetime | None = None) -> str:
    t = (now or now_utc()).astimezone(ET)
    d = t.date()
    if not trading_day(d) or t < close_at(d):
        d -= timedelta(days=1)
        while not trading_day(d):
            d -= timedelta(days=1)
    return d.isoformat()


def day_words(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%a %b} {d.day}"


def time_words(at: datetime) -> str:
    t = at.astimezone(ET)
    return f"{t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} ET"


# ---- Closing quotes and the provisional close ----


def closing_quotes(conn: sqlite3.Connection, day: str) -> dict[str, dict]:
    if not _has(conn, "quotes_live"):
        return {}
    d = date.fromisoformat(day)
    lo = datetime.combine(d, time(0, 0), ET).astimezone(UTC).isoformat(timespec="seconds")
    cut = close_at(d) + CLOSE_GRACE
    best: dict[str, tuple] = {}
    rows = conn.execute(
        "SELECT symbol, at, price, prev_close, fetched_at FROM quotes_live WHERE source='finnhub' AND fetched_at >= ? ORDER BY fetched_at", (lo,)
    )
    for r in rows:
        at = _stamp(r["at"])
        if at.astimezone(ET).date() != d or at > cut or not r["price"]:
            continue
        key = (at, r["fetched_at"])
        if r["symbol"] not in best or key >= best[r["symbol"]][0]:
            best[r["symbol"]] = (key, {"price": float(r["price"]), "prev_close": r["prev_close"], "at": r["at"], "fetched_at": r["fetched_at"]})
    return {s: q for s, (_, q) in best.items()}


def _official(conn: sqlite3.Connection, day: str) -> set[str]:
    out: set[str] = set()
    for tbl in ("price_bars", "prices_daily"):
        if _has(conn, tbl):
            out |= {r[0] for r in conn.execute(f"SELECT symbol FROM {tbl} WHERE date=?", (day,))}
    return out


def stamp(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = now or now_utc()
    day = last_session(now)
    if not _has(conn, "closes_provisional"):
        return {"day": day, "stamped": 0}
    have = _official(conn, day)
    at = now.isoformat(timespec="seconds")
    rows = [(s, day, q["price"], q["prev_close"], q["at"], at) for s, q in sorted(closing_quotes(conn, day).items()) if s not in have]
    with conn:
        conn.executemany("INSERT OR REPLACE INTO closes_provisional VALUES (?, ?, ?, ?, ?, ?)", rows)
    return {"day": day, "stamped": len(rows)}


def settle(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    if not _has(conn, "closes_provisional"):
        return {"restated": 0, "left": 0}
    old = ((now or now_utc()).astimezone(ET).date() - timedelta(days=KEEP_DAYS)).isoformat()
    gone = 0
    with conn:
        for tbl in ("price_bars", "prices_daily"):
            if _has(conn, tbl):
                landed = f"SELECT 1 FROM {tbl} t WHERE t.symbol=closes_provisional.symbol AND t.date=closes_provisional.date"
                gone += conn.execute(f"DELETE FROM closes_provisional WHERE EXISTS ({landed})").rowcount
        conn.execute("DELETE FROM closes_provisional WHERE date < ?", (old,))
    left = conn.execute("SELECT count(*) FROM closes_provisional").fetchone()[0]
    return {"restated": gone, "left": left}


def quote_series(conn: sqlite3.Connection) -> dict[str, dict[str, tuple[float, float | None]]]:
    out: dict[str, dict[str, tuple[float, float | None]]] = {}
    if _has(conn, "closes_provisional"):
        for r in conn.execute("SELECT symbol, date, close FROM closes_provisional"):
            out.setdefault(r["symbol"], {})[r["date"]] = (r["close"], None)
    return out


def provisional_symbols(conn: sqlite3.Connection, day: str) -> set[str]:
    if not _has(conn, "closes_provisional"):
        return set()
    return {r[0] for r in conn.execute("SELECT symbol FROM closes_provisional WHERE date=?", (day,))} - _official(conn, day)


def _official_close(conn: sqlite3.Connection, symbol: str, day: str) -> float | None:
    for tbl in ("price_bars", "prices_daily"):
        if _has(conn, tbl):
            r = conn.execute(f"SELECT close FROM {tbl} WHERE symbol=? AND date=?", (symbol, day)).fetchone()
            if r is not None:
                return float(r[0])
    return None


def _rolled(conn: sqlite3.Connection, day: str) -> dict[str, float]:
    if not _has(conn, "holdings_daily"):
        return {}
    rows = conn.execute("SELECT symbol, close FROM holdings_daily WHERE date=? AND is_cash=0 AND source != 'snapshot' AND close IS NOT NULL", (day,))
    return {r["symbol"]: float(r["close"]) for r in rows}


def waiting(conn: sqlite3.Connection, day: str) -> list[str]:
    official, quoted, rolled = _official(conn, day), provisional_symbols(conn, day), _rolled(conn, day)
    carried = [s for s in _held(conn, day) if s in rolled and s not in official and s not in quoted]
    if not carried:
        return []
    floor = (date.fromisoformat(day) - timedelta(days=WAIT_DAYS)).isoformat()
    recent: set[str] = set()
    for tbl in ("price_bars", "prices_daily"):
        if _has(conn, tbl):
            recent |= {r[0] for r in conn.execute(f"SELECT DISTINCT symbol FROM {tbl} WHERE date >= ? AND date < ?", (floor, day))}
    return [s for s in carried if s in recent]


def late_closes(conn: sqlite3.Connection, day: str) -> list[str]:
    out = []
    for symbol, booked in sorted(_rolled(conn, day).items()):
        close = _official_close(conn, symbol, day)
        if close is not None and abs(close - booked) > 1e-6 * max(1.0, abs(close)):
            out.append(symbol)
    return out


def names(symbols: list[str]) -> str:
    shown = list(symbols[:NAMED])
    if len(symbols) > NAMED:
        shown.append(f"{len(symbols) - NAMED} more")
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


# ---- Does the book need another pass ----


def book_day(conn: sqlite3.Connection) -> str | None:
    if _has(conn, "metric_values"):
        day = conn.execute("SELECT max(as_of) FROM metric_values").fetchone()[0]
        if day:
            return day
    return conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0] if _has(conn, "holdings_daily") else None


def _held(conn: sqlite3.Connection, day: str | None) -> list[str]:
    if not day or not _has(conn, "holdings_daily"):
        return []
    on = conn.execute("SELECT max(date) FROM holdings_daily WHERE date <= ?", (day,)).fetchone()[0]
    return [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0 ORDER BY symbol", (on,))] if on else []


def pending(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = now or now_utc()
    day = book_day(conn)
    want = last_session(now)
    if day is None:
        return {"due": False, "why": "no book yet", "signature": None}
    held = _held(conn, day)
    landed = sorted(s for s in provisional_symbols_raw(conn, day) if s in _official(conn, day))
    newest = None
    if held and _has(conn, "price_bars"):
        marks = ",".join("?" * len(held))
        newest = conn.execute(f"SELECT max(date) FROM price_bars WHERE symbol IN ({marks}) AND date <= ?", (*held, want)).fetchone()[0]
    quoted = sorted(closing_quotes(conn, want)) if day < want else []
    late = [s for s in late_closes(conn, day) if s not in landed]
    why = []
    if landed:
        why.append(f"official closes landed for {len(landed)} symbols on {day}")
    if late:
        why.append(f"late official closes landed for {names(late)} on {day}")
    if newest and newest > day:
        why.append(f"official closes reach {newest}, the book stops at {day}")
    if quoted and not (newest and newest >= want):
        why.append(f"closing quotes for {want} are in, the book stops at {day}")
    signature = json.dumps([day, want, landed, newest, len(quoted), *([late] if late else [])])
    return {"due": bool(why), "why": "; ".join(why) or "the book is on the latest day it can reach", "signature": signature, "day": day, "want": want}


def provisional_symbols_raw(conn: sqlite3.Connection, day: str) -> set[str]:
    if not _has(conn, "closes_provisional"):
        return set()
    return {r[0] for r in conn.execute("SELECT symbol FROM closes_provisional WHERE date=?", (day,))}


# ---- The one "as of" ----


def _numbers(conn: sqlite3.Connection, day: str) -> dict:
    out = {}
    for key, metric_id, window in NUMBERS:
        r = conn.execute(
            "SELECT value FROM metric_values WHERE as_of=? AND metric_id=? AND scope='portfolio' AND scope_id='all' AND \"window\"=?", (day, metric_id, window)
        ).fetchone()
        if r is not None and r["value"] is not None:
            out[key] = r["value"]
    return out


def prices(conn: sqlite3.Connection, day: str) -> dict:
    held = _held(conn, day)
    official = _official(conn, day)
    quoted = provisional_symbols(conn, day)
    return {
        "official": sum(1 for s in held if s in official),
        "quoted": sum(1 for s in held if s in quoted),
        "carried": [s for s in held if s not in official and s not in quoted],
        "waiting": waiting(conn, day),
    }


def _sessions_between(day: str, want: str) -> int:
    d, stop, n = date.fromisoformat(day), date.fromisoformat(want), 0
    while d < stop:
        d += timedelta(days=1)
        n += trading_day(d)
    return n


def _live(conn: sqlite3.Connection, day: str, now: datetime) -> dict | None:
    from desk.engine.live import live_view

    if not _has(conn, "quotes_live"):
        return None
    view = live_view(conn, now=now)
    quote_day = view["quote_day"]
    if not quote_day or quote_day <= day or not view["rows"]:
        return None
    seen = _stamp(view["as_of"]) if view["as_of"] else now
    running = view["state"] in ("pre", "open", "after")
    words = f"Live, {day_words(quote_day)}, {time_words(seen)}" if running else f"{day_words(quote_day)}, last quotes {time_words(seen)}"
    return {
        "day": quote_day,
        "state": view["state"],
        "at": seen.isoformat(timespec="seconds"),
        "value": view["value"],
        "day_change": view["day_change"],
        "day_change_pct": view["day_change_pct"],
        "words": words,
    }


def _review(conn: sqlite3.Connection) -> tuple[dict | None, dict | None]:
    if not _has(conn, "period_reviews"):
        return None, None
    r = conn.execute('SELECT "end", computed_at, digest FROM period_reviews WHERE kind=\'day\' ORDER BY "end" DESC LIMIT 1').fetchone()
    review = {"day": r["end"], "computed_at": r["computed_at"]} if r else None
    debrief = None
    if _has(conn, "period_debriefs"):
        d = conn.execute('SELECT "end", written_at, pack_digest FROM period_debriefs WHERE kind=\'day\' ORDER BY "end" DESC LIMIT 1').fetchone()
        if d:
            pack = conn.execute("SELECT digest FROM period_reviews WHERE kind='day' AND \"end\"=?", (d["end"],)).fetchone()
            debrief = {"day": d["end"], "written_at": d["written_at"], "stale": pack is None or pack["digest"] != d["pack_digest"]}
    return review, debrief


def view(conn: sqlite3.Connection | None, *, now: datetime | None = None) -> dict:
    now = now or now_utc()
    sess = session(now)
    market = {"state": sess.state, "day": sess.day}
    empty = {
        "day": None,
        "at": None,
        "provisional": False,
        "status": "empty",
        "words": EMPTY_WORDS,
        "previous_day": None,
        "expected_day": None,
        "behind": None,
        "prices": {"official": 0, "quoted": 0, "carried": [], "waiting": []},
        "numbers": {},
        "live": None,
        "market": market,
        "review": None,
        "debrief": None,
    }
    day = book_day(conn) if conn is not None else None
    if day is None:
        return empty
    run = (
        conn.execute("SELECT finished_at FROM engine_runs WHERE job='core' AND ok=1 ORDER BY id DESC LIMIT 1").fetchone() if _has(conn, "engine_runs") else None
    )
    at = run["finished_at"] if run and run["finished_at"] else None
    priced = prices(conn, day)
    quoted = bool(provisional_symbols(conn, day))
    provisional = quoted or bool(priced["waiting"])
    want = max(last_session(now), day)
    behind = None
    if day < want:
        n = _sessions_between(day, want)
        if n:
            got = "Closing quotes are in" if closing_quotes(conn, want) else "No closing quotes or official closes"
            behind = {
                "sessions": n,
                "reason": f"{got} for {day_words(want)}, and the book stops at {day_words(day)}. The next engine run moves it; nothing to tap.",
            }
    if quoted:
        when = f", {time_words(_stamp(at))}" if at else ""
        words = f"{day_words(day)}{when}. Provisional until official closes land overnight."
    elif provisional:
        words = f"{day_words(day)}, at the close. Waiting on the official close for {names(priced['waiting'])}; the day is restated when it lands."
    else:
        words = f"{day_words(day)}, at the close."
    review, debrief = _review(conn)
    return {
        "day": day,
        "at": at,
        "provisional": provisional,
        "status": "provisional" if provisional else "final",
        "words": words,
        "previous_day": conn.execute("SELECT max(date) FROM holdings_daily WHERE date < ?", (day,)).fetchone()[0],
        "expected_day": want,
        "behind": behind,
        "prices": priced,
        "numbers": _numbers(conn, day) if _has(conn, "metric_values") else {},
        "live": _live(conn, day, now),
        "market": market,
        "review": review,
        "debrief": debrief,
    }
