import json
import os
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.engine import KEYS_AT
from desk.engine.holdings import CASH_SYMBOLS
from desk.engine.market import BENCHMARKS, ET, LIBRARY_FUNDS, QUALITY, ProviderError, last_trading_day, tiingo_daily, tiingo_key

PUBLIC = "public"
ROLE_PRIORITY = {"held": 0, "benchmark": 1, "plan": 1, "watch": 2, "past": 3, "universe": 3, PUBLIC: 4}
TICKER = re.compile(r"^[A-Z]{1,5}$")
ROTATE_DAYS = 90
NO_PRICES = "Tiingo has no daily prices"
NO_ANSWER = "Tiingo did not answer"
ASK_MINUTE = 13
DAILY = (*QUALITY, *(s for s in LIBRARY_FUNDS if s not in QUALITY))
LAST = frozenset(DAILY) - frozenset(QUALITY)
PARK_DAYS = 7
HELD_PARK_HOURS = 20
ASK_WORDS = "every hour, day and night"
TOP_UP_DAYS = 7
QUIET_FROM, QUIET_TO = 16, 20


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


def traded_symbols(conn: sqlite3.Connection) -> list[str]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='broker_txns'").fetchone() is None:
        return []
    rows = conn.execute("SELECT DISTINCT symbol FROM broker_txns WHERE symbol IS NOT NULL AND kind IN ('buy', 'sell', 'reinvest')")
    return sorted(r[0] for r in rows if TICKER.match(r[0]) and r[0] not in CASH_SYMBOLS)


def public_names(conn: sqlite3.Connection) -> dict[str, bool]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='public_stocks'").fetchone() is None:
        return {}
    rows = conn.execute("SELECT symbol, trading FROM public_stocks WHERE state='priced' AND symbol IS NOT NULL ORDER BY rank")
    return {r[0]: bool(r[1]) for r in rows}


def quiet(now: datetime) -> bool:
    hour = now.astimezone(ET).hour
    return QUIET_FROM <= hour < QUIET_TO


def sync_roles(conn: sqlite3.Connection, now: datetime | None = None) -> None:
    add_symbols(conn, BENCHMARKS, "benchmark")
    add_symbols(conn, DAILY, "universe")
    add_symbols(conn, traded_symbols(conn), "past")
    add_symbols(conn, public_names(conn), PUBLIC)
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        return
    target = last_trading_day((now or datetime.now(UTC)).date() - timedelta(days=1)).isoformat()
    covered = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM prices_daily WHERE date >= ?", (target,))}
    held = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0", (day,))]
    add_symbols(conn, [s for s in held if s not in covered], "held")
    add_symbols(conn, past_gaps(conn), "past")


def past_gaps(conn: sqlite3.Connection) -> list[str]:
    first_bar = {r[0]: r[1] for r in conn.execute("SELECT symbol, min(date) FROM price_bars GROUP BY symbol")}
    rows = conn.execute("SELECT symbol, min(date) FROM holdings_daily WHERE source='history' AND is_cash=0 GROUP BY symbol")
    return sorted(sym for sym, first in rows if sym not in first_bar or first_bar[sym] > first)


def never_fetched(conn: sqlite3.Connection, symbols) -> list[str]:
    tried = {r[0] for r in conn.execute("SELECT symbol FROM market_symbols WHERE fetched_at IS NOT NULL")}
    return sorted(s for s in symbols if s not in tried)


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


def parked_until(row) -> datetime | None:
    if not row["fetched_at"] or row["last_bar"] is not None or not (row["error"] or "").startswith(NO_PRICES):
        return None
    wait = timedelta(hours=HELD_PARK_HOURS) if row["priority"] == 0 else timedelta(days=PARK_DAYS)
    return datetime.fromisoformat(row["fetched_at"]) + wait


def due(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    target = last_trading_day(now.date() - timedelta(days=1)).isoformat()
    rotate = (now.date() - timedelta(days=ROTATE_DAYS)).isoformat()
    week = (now - timedelta(days=TOP_UP_DAYS)).isoformat(timespec="seconds")
    weekly, hush = public_names(conn), quiet(now)
    rows = [r for r in conn.execute("SELECT * FROM market_symbols ORDER BY priority, (last_bar IS NULL) DESC, symbol") if (parked_until(r) or now) <= now]

    def stale(r: sqlite3.Row) -> bool:
        if r["priority"] <= 2 or r["symbol"] in DAILY:
            return r["last_bar"] is None or r["last_bar"] < target
        if r["symbol"] in weekly:
            if hush:
                return False
            if r["last_bar"] is None:
                return True
            return weekly[r["symbol"]] and r["fetched_at"] is not None and r["fetched_at"] < week
        if r["last_bar"] is None:
            return True
        return r["fetched_at"] is not None and r["fetched_at"][:10] < rotate

    rows.sort(key=lambda r: (r["priority"], r["last_bar"] is not None, (r["symbol"] in LAST) == (r["last_bar"] is not None)))
    return [r for r in rows if stale(r)]


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
        return {"ok": False, "error": f"The Tiingo key is not set. Add it in {KEYS_AT}."}
    sync_roles(conn, now)
    cap = limits()
    used = usage(conn, now)
    this_month = month_symbols(conn, now)
    fetched, skipped, errors, unpriced, advanced, behind = [], 0, [], [], [], []
    target = last_trading_day(now.date() - timedelta(days=1)).isoformat()
    queue = due(conn, now)
    left = len(queue)
    for row in queue:
        if used["hour"] >= cap["hour"] or used["day"] >= cap["day"]:
            break
        left -= 1
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
        except (OSError, ValueError):
            bars, error = [], f"{NO_ANSWER} for {symbol}"
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
        if error and error.startswith(NO_PRICES):
            unpriced.append(symbol)
        elif error:
            errors.append(f"{symbol}: {error}")
            if "rate limit" in error or error.startswith(NO_ANSWER):
                break
        else:
            fetched.append(symbol)
            if last and last > (row["last_bar"] or ""):
                advanced.append(symbol)
            if not last or last < target:
                behind.append(symbol)
    out = {
        "ok": not errors,
        "target": target,
        "fetched": fetched,
        "advanced": advanced,
        "behind": behind,
        "skipped_for_month_cap": skipped,
        "unpriced": unpriced,
        "errors": errors,
        "left": left,
        "used": used,
        "limits": cap,
    }
    return out | {"detail": words(out)}


def _names(xs: list[str], most: int = 6) -> str:
    shown = list(xs[:most]) + ([f"{len(xs) - most} more"] if len(xs) > most else [])
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def words(out: dict) -> str:
    asked = len(out["fetched"]) + len(out["unpriced"]) + len(out["errors"])
    if not asked and not out["left"] and not out["skipped_for_month_cap"]:
        return "Nothing was behind, so Tiingo was not asked."
    parts = [f"Asked Tiingo for {asked} {'name' if asked == 1 else 'names'}."] if asked else ["Tiingo was not asked."]
    if out["errors"]:
        parts.append(f"Failed: {'; '.join(out['errors'][:3])}.")
    if out["behind"]:
        parts.append(f"{_names(out['behind'])} answered with nothing new for {out['target']}.")
    if out["unpriced"]:
        parts.append(f"Tiingo has no prices for {_names(out['unpriced'])}.")
    if out["advanced"]:
        parts.append(f"New bars for {_names(out['advanced'])}.")
    waiting = out["left"] + out["skipped_for_month_cap"]
    if waiting:
        parts.append(f"{waiting} more wait for a later run, to stay inside Tiingo's limits.")
    return " ".join(parts)


# ---- Seam for the API ----


def view(conn: sqlite3.Connection | None, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    target = last_trading_day(now.date() - timedelta(days=1)).isoformat()
    out = {"target": target, "asks": ASK_WORDS, "limits": limits(), "used": None, "last_run": None, "symbols": []}
    if conn is None or conn.execute("SELECT 1 FROM sqlite_master WHERE name='market_symbols'").fetchone() is None:
        return out
    asked = {r["symbol"] for r in due(conn, now)}
    for r in conn.execute("SELECT * FROM market_symbols ORDER BY priority, symbol"):
        until = parked_until(r)
        daily = r["priority"] <= 2 or r["symbol"] in DAILY
        out["symbols"].append(
            {
                "symbol": r["symbol"],
                "role": r["role"],
                "priority": r["priority"],
                "daily": daily,
                "first_bar": r["first_bar"],
                "last_bar": r["last_bar"],
                "fetched_at": r["fetched_at"],
                "error": r["error"],
                "parked_until": until.isoformat(timespec="seconds") if until and until > now else None,
                "behind": bool(daily and (r["last_bar"] is None or r["last_bar"] < target)),
                "due": r["symbol"] in asked,
            }
        )
    out["used"] = usage(conn, now)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='engine_runs'").fetchone():
        last = conn.execute("SELECT finished_at, ok, detail FROM engine_runs WHERE job='backfill' ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            detail = json.loads(last["detail"] or "{}")
            keys = ("detail", "fetched", "advanced", "behind", "unpriced", "errors", "error", "left", "skipped_for_month_cap")
            out["last_run"] = {"finished_at": last["finished_at"], "ok": bool(last["ok"])} | {k: detail.get(k) for k in keys}
    return out
