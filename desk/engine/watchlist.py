import os
import re
import sqlite3
from datetime import UTC, datetime

from desk.engine.backfill import add_symbols

SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,5}([.-][A-Z0-9]{1,3})?")
MAX_ROWS = 200
RESEARCH = {
    "filings": "SELECT 1 FROM filings WHERE symbol=? LIMIT 1",
    "fundamentals": "SELECT 1 FROM fundamentals WHERE symbol=? LIMIT 1",
    "earnings": "SELECT 1 FROM earnings WHERE symbol=? LIMIT 1",
    "insider_trades": "SELECT 1 FROM insider_trades WHERE symbol=? LIMIT 1",
}


class WatchError(ValueError):
    pass


def env_symbols() -> list[str]:
    return sorted({s.strip().upper() for s in os.environ.get("DESK_WATCHLIST", "").split(",") if s.strip()})


def clean(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if not SYMBOL.fullmatch(sym):
        raise WatchError(f"'{symbol}' is not a ticker symbol")
    return sym


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def rows(conn: sqlite3.Connection) -> list[dict]:
    have = _tables(conn)
    desk = {}
    if "market_symbols" in have:
        desk = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT symbol, added_at, last_bar FROM market_symbols WHERE role='watch'")}
    env = [s for s in env_symbols() if s not in desk]
    out = []
    for sym, source in [(s, "desk") for s in sorted(desk)] + [(s, "env") for s in env]:
        added, last_bar = desk.get(sym, (None, None))
        closes = []
        if "prices_daily" in have:
            closes = conn.execute("SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 2", (sym,)).fetchall()
        name = None
        if "sym_profiles" in have:
            r = conn.execute("SELECT name FROM sym_profiles WHERE symbol=?", (sym,)).fetchone()
            name = r[0] if r else None
        if not name and "sec_tickers" in have:
            r = conn.execute("SELECT title FROM sec_tickers WHERE symbol=?", (sym,)).fetchone()
            name = r[0] if r else None
        research = any(t in have and conn.execute(q, (sym,)).fetchone() for t, q in RESEARCH.items())
        out.append(
            {
                "symbol": sym,
                "name": name,
                "source": source,
                "added_at": added,
                "last_close": closes[0][1] if closes else None,
                "prev_close": closes[1][1] if len(closes) > 1 else None,
                "last_bar": last_bar or (closes[0][0] if closes else None),
                "has_research": research,
            }
        )
    return out


def add(conn: sqlite3.Connection, symbol: str, *, now: datetime | None = None) -> str:
    sym = clean(symbol)
    if conn.execute("SELECT count(*) FROM market_symbols WHERE role='watch'").fetchone()[0] >= MAX_ROWS:
        raise WatchError(f"The watchlist holds at most {MAX_ROWS} symbols")
    add_symbols(conn, [sym], "watch", now=now or datetime.now(UTC))
    return sym


def remove(conn: sqlite3.Connection, symbol: str) -> str:
    sym = clean(symbol)
    row = conn.execute("SELECT role FROM market_symbols WHERE symbol=?", (sym,)).fetchone()
    if row is None or row[0] != "watch":
        if sym in env_symbols():
            raise WatchError(f"{sym} is on the watchlist from the box's own setup, not from this page, so it cannot be removed here")
        raise WatchError(f"{sym} is not on the watchlist")
    with conn:
        conn.execute("DELETE FROM market_symbols WHERE symbol=? AND role='watch'", (sym,))
    return sym
