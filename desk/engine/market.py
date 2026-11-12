import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

NYSE_HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 2, 15),
    date(2027, 3, 26),
    date(2027, 5, 31),
    date(2027, 6, 18),
    date(2027, 7, 5),
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 12, 24),
}
EARLY_CLOSE = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}
CALENDAR_YEARS = {d.year for d in NYSE_HOLIDAYS}

BENCHMARKS = ("SPY", "VTI", "VXUS", "AGG", "QQQ", "IWM", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC")
QUALITY = ("VOO", "VTI", "QQQ", "VXUS", "QUAL", "SCHD", "VGT", "FTEC", "SMH", "MSFT", "AAPL", "GOOGL", "AMZN", "NVDA", "ASML", "COST", "V", "JPM")

FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
TIINGO_DAILY = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"


# ---- Market clock ----


@dataclass(frozen=True)
class Session:
    state: str
    day: str
    known_calendar: bool
    opens_at: str | None
    closes_at: str | None


def trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def last_trading_day(d: date) -> date:
    while not trading_day(d):
        d -= timedelta(days=1)
    return d


def et_day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(ET).date().isoformat()


def session_day(now: datetime | None = None) -> str:
    return last_trading_day((now or datetime.now(UTC)).astimezone(ET).date()).isoformat()


def session(now: datetime | None = None) -> Session:
    t = (now or datetime.now(UTC)).astimezone(ET)
    d = t.date()
    known = d.year in CALENDAR_YEARS
    if not trading_day(d):
        return Session("closed", d.isoformat(), known, None, None)
    open_at = datetime.combine(d, time(9, 30), ET)
    close_at = datetime.combine(d, time(13, 0) if d in EARLY_CLOSE else time(16, 0), ET)
    if t < datetime.combine(d, time(4, 0), ET):
        state = "closed"
    elif t < open_at:
        state = "pre"
    elif t < close_at:
        state = "open"
    elif t < datetime.combine(d, time(20, 0), ET):
        state = "after"
    else:
        state = "closed"
    return Session(state, d.isoformat(), known, open_at.isoformat(), close_at.isoformat())


# ---- Providers ----


class ProviderError(RuntimeError):
    pass


def finnhub_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "").strip()


def tiingo_key() -> str:
    return os.environ.get("TIINGO_API_KEY", "").strip()


def finnhub_quote(http, symbol: str, key: str) -> dict | None:
    res = http.get(FINNHUB_QUOTE, params={"symbol": symbol, "token": key}, timeout=20)
    if res.status_code == 429:
        raise ProviderError("Finnhub rate limit")
    if res.status_code != 200:
        raise ProviderError(f"Finnhub {res.status_code} for {symbol}")
    body = res.json() or {}
    if not body.get("c") or not body.get("t"):
        return None
    return {
        "price": float(body["c"]),
        "prev_close": float(body["pc"]) if body.get("pc") else None,
        "at": datetime.fromtimestamp(int(body["t"]), UTC).isoformat(timespec="seconds"),
    }


def tiingo_daily(http, symbol: str, key: str, start: str) -> list[dict]:
    res = http.get(TIINGO_DAILY.format(symbol=symbol.lower()), params={"startDate": start}, headers={"Authorization": f"Token {key}"}, timeout=60)
    if res.status_code == 404:
        raise ProviderError(f"Tiingo has no daily prices for {symbol}")
    if res.status_code == 429:
        raise ProviderError("Tiingo rate limit")
    if res.status_code != 200:
        raise ProviderError(f"Tiingo {res.status_code} for {symbol}")
    out = []
    for r in res.json() or []:
        if r.get("close") is None or not r.get("date"):
            continue
        out.append(
            {
                "date": str(r["date"])[:10],
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": float(r["close"]),
                "adj_close": r.get("adjClose"),
                "volume": r.get("volume"),
                "div_cash": r.get("divCash") or 0.0,
                "split_factor": r.get("splitFactor") or 1.0,
            }
        )
    return out


# ---- Symbols the desk prices ----


def held_symbols(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        return []
    rows = conn.execute("SELECT symbol, sum(shares) AS shares, max(is_cash) AS cash FROM holdings_daily WHERE date=? GROUP BY symbol", (day,))
    return [(r["symbol"], r["shares"]) for r in rows if not r["cash"]]


def latest_close(conn: sqlite3.Connection, symbol: str, before: str | None = None) -> tuple[str, float] | None:
    q = "SELECT date, close FROM ({u}) WHERE symbol=? {cond} ORDER BY date DESC LIMIT 1"
    union = "SELECT symbol, date, close FROM prices_daily UNION ALL SELECT symbol, date, close FROM price_bars"
    cond, args = ("AND date < ?", (symbol, before)) if before else ("", (symbol,))
    r = conn.execute(q.format(u=union, cond=cond), args).fetchone()
    return (r["date"], r["close"]) if r else None
