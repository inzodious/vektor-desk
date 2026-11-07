import os
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.engine.market import BENCHMARKS, ProviderError, last_trading_day, tiingo_daily, tiingo_key

ROLE_PRIORITY = {"held": 0, "benchmark": 1, "plan": 1, "watch": 2, "universe": 3}
ROTATE_DAYS = 90


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def limits() -> dict[str, int]:
    return {
        "hour": _int_env("DESK_TIINGO_HOURLY", 40),
        "day": _int_env("DESK_TIINGO_DAILY", 800),
        "month_symbols": _int_env("DESK_TIINGO_MONTHLY_SYMBOLS", 400),
    }


def start_date() -> str:
    return os.environ.get("DESK_BACKFILL_START", "2005-01-01")


def add_symbols(conn: sqlite3.Connection, symbols, role: str, *, now: datetime | None = None) -> int:
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    prio = ROLE_PRIORITY.get(role, 3)
    with conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT INTO market_symbols (symbol, role, priority, added_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET role = CASE WHEN excluded.priority < market_symbols.priority THEN excluded.role ELSE market_symbols.role END,
               priority = min(market_symbols.priority, excluded.priority)""",
            [(s.strip().upper(), role, prio, stamp) for s in symbols if s and s.strip()],
        )
        return conn.total_changes - before


def sync_roles(conn: sqlite3.Connection) -> None:
    add_symbols(conn, BENCHMARKS, "benchmark")
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        return
    covered = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM prices_daily WHERE date >= date(?, '-7 days')", (day,))}
    held = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0", (day,))]
    add_symbols(conn, [s for s in held if s not in covered], "held")


def usage(conn: sqlite3.Connection, now: datetime) -> dict[str, int]:
    hour = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    day = (now - timedelta(days=1)).isoformat(timespec="seconds")
    month = now.strftime("%Y-%m")
    q = "SELECT count(*) FROM api_calls WHERE provider='tiingo' AND at >= ?"
    return {
        "hour": conn.execute(q, (hour,)).fetchone()[0],
        "day": conn.execute(q, (day,)).fetchone()[0],
        "month_symbols": conn.execute("SELECT count(DISTINCT symbol) FROM api_calls WHERE provider='tiingo' AND substr(at, 1, 7) = ?", (month,)).fetchone()[0],
    }


def month_symbols(conn: sqlite3.Connection, now: datetime) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM api_calls WHERE provider='tiingo' AND substr(at, 1, 7) = ?", (now.strftime("%Y-%m"),))}


def due(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    target = last_trading_day(now.date() - timedelta(days=1)).isoformat()
    rotate = (now.date() - timedelta(days=ROTATE_DAYS)).isoformat()
    return conn.execute(
        """SELECT * FROM market_symbols
           WHERE (error IS NULL OR fetched_at < ?)
             AND (last_bar IS NULL
                  OR (priority <= 2 AND last_bar < ?)
                  OR (priority > 2 AND substr(fetched_at, 1, 10) < ?))
           ORDER BY (last_bar IS NULL) DESC, priority, symbol""",
        ((now - timedelta(days=7)).isoformat(timespec="seconds"), target, rotate),
    ).fetchall()


def store_bars(conn: sqlite3.Connection, symbol: str, bars: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close, volume, div_cash, split_factor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(symbol, b["date"], b["open"], b["high"], b["low"], b["close"], b["adj_close"], b["volume"], b["div_cash"], b["split_factor"]) for b in bars],
    )


def run_backfill(conn: sqlite3.Connection, http, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    key = tiingo_key()
    if not key:
        return {"ok": False, "error": "TIINGO_API_KEY is not set."}
    sync_roles(conn)
    cap = limits()
    used = usage(conn, now)
    this_month = month_symbols(conn, now)
    fetched, skipped, errors = [], 0, []
    for row in due(conn, now):
        if used["hour"] >= cap["hour"] or used["day"] >= cap["day"]:
            break
        symbol = row["symbol"]
        new_symbol = symbol not in this_month
        if new_symbol and used["month_symbols"] >= cap["month_symbols"]:
            skipped += 1
            continue
        start = start_date() if row["last_bar"] is None else (date.fromisoformat(row["last_bar"]) - timedelta(days=7)).isoformat()
        stamp = now.isoformat(timespec="seconds")
        try:
            bars = tiingo_daily(http, symbol, key, start)
            error = None
        except ProviderError as e:
            bars, error = [], str(e)
        with conn:
            conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('tiingo', ?, ?, ?)", (stamp, symbol, int(error is None)))
            if bars:
                store_bars(conn, symbol, bars)
            first, last = conn.execute("SELECT min(date), max(date) FROM price_bars WHERE symbol=?", (symbol,)).fetchone()
            conn.execute("UPDATE market_symbols SET first_bar=?, last_bar=?, fetched_at=?, error=? WHERE symbol=?", (first, last, stamp, error, symbol))
        used["hour"] += 1
        used["day"] += 1
        if new_symbol:
            used["month_symbols"] += 1
            this_month.add(symbol)
        if error:
            errors.append(f"{symbol}: {error}")
            if "rate limit" in error:
                break
        else:
            fetched.append(symbol)
    return {"ok": not errors, "fetched": fetched, "skipped_for_month_cap": skipped, "errors": errors, "used": used, "limits": cap}
