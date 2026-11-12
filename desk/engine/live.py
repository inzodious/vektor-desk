import json
import os
import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from desk.engine.market import BENCHMARKS, ET, ProviderError, finnhub_key, finnhub_quote, held_symbols, latest_close, session

KEEP_DAYS = 7
FRESH_MINUTES = 10
EXTENDED_EVERY = 30
CLOSE_SETTLE = timedelta(minutes=2)
LIVE_STATES = ("pre", "open", "after")


def now_utc() -> datetime:
    return datetime.now(UTC)


def quote_symbols(conn: sqlite3.Connection) -> list[str]:
    extra = [s.strip().upper() for s in os.environ.get("DESK_QUOTE_EXTRA", "").split(",") if s.strip()]
    return sorted({s for s, _ in held_symbols(conn)} | {"SPY"} | yardstick_symbols(conn) | set(extra))


def yardstick_symbols(conn: sqlite3.Connection) -> set[str]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_strategies'").fetchone() is None:
        return set()
    out: set[str] = set()
    for r in conn.execute("SELECT mix FROM catalog_strategies WHERE retired_at IS NULL"):
        out |= {str(s).upper() for s in (json.loads(r["mix"]).get("weights") or {})}
    return out


def refresh_quotes(conn: sqlite3.Connection, http, *, now: datetime | None = None, force: bool = False) -> dict:
    now = now or now_utc()
    sess = session(now)
    if sess.state not in LIVE_STATES and not force:
        return {"ok": True, "skipped": f"market {sess.state}"}
    last = conn.execute("SELECT max(fetched_at) FROM quotes_live").fetchone()[0]
    settled = sess.state != "after" or (last is not None and datetime.fromisoformat(last) >= datetime.fromisoformat(sess.closes_at) + CLOSE_SETTLE)
    if sess.state != "open" and settled and not force and last and now - datetime.fromisoformat(last) < timedelta(minutes=EXTENDED_EVERY):
        return {"ok": True, "skipped": f"market {sess.state}, refreshed {last}"}
    key = finnhub_key()
    stamp = now.isoformat(timespec="seconds")
    rows, missing, errors = [], [], []
    for symbol in quote_symbols(conn):
        q = None
        if key:
            try:
                q = finnhub_quote(http, symbol, key)
            except ProviderError as e:
                errors.append(f"{symbol}: {e}")
                if "rate limit" in str(e):
                    break
        if q:
            rows.append((symbol, q["at"], q["price"], q["prev_close"], "finnhub", stamp))
            continue
        last = latest_close(conn, symbol)
        if last:
            prev = latest_close(conn, symbol, before=last[0])
            closed_at = datetime.combine(date.fromisoformat(last[0]), time(16, 0), ET).isoformat()
            rows.append((symbol, closed_at, last[1], prev[1] if prev else None, "close", stamp))
        else:
            missing.append(symbol)
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    with conn:
        conn.executemany("INSERT OR REPLACE INTO quotes_live VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute("DELETE FROM quotes_live WHERE fetched_at < ?", (cut,))
        conn.executemany("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('finnhub', ?, ?, 1)", [(stamp, r[0]) for r in rows if r[4] == "finnhub"])
    return {"ok": not errors, "state": sess.state, "quotes": len(rows), "missing": missing, "errors": errors, "key": bool(key)}


def _et_day(at: str) -> str:
    t = datetime.fromisoformat(at.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(ET).date().isoformat()


def live_view(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = now or now_utc()
    sess = session(now)
    latest = {}
    for r in conn.execute(
        "SELECT q.* FROM quotes_live q JOIN (SELECT symbol, max(fetched_at) AS f FROM quotes_live GROUP BY symbol) m ON m.symbol=q.symbol AND m.f=q.fetched_at"
    ):
        latest[r["symbol"]] = dict(r)
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    holdings = [dict(r) for r in conn.execute("SELECT * FROM holdings_daily WHERE date=?", (day,))] if day else []
    quote_day = max((_et_day(q["at"]) for q in latest.values() if q["source"] == "finnhub"), default=None)
    rows, value, change, oldest = [], 0.0, 0.0, None
    for h in holdings:
        q = None if h["is_cash"] else latest.get(h["symbol"])
        price = 1.0 if h["is_cash"] else (q["price"] if q else h["close"])
        carried = bool(q) and q["source"] == "close" and quote_day is not None and _et_day(q["at"]) < quote_day
        prev = 1.0 if h["is_cash"] else (q["prev_close"] if q and q["prev_close"] and not carried else price)
        v = round(h["shares"] * price, 2) if price is not None else h["value"]
        d = round(h["shares"] * (price - prev), 2) if price is not None and prev is not None else 0.0
        value += v
        change += d
        if q:
            oldest = q["fetched_at"] if oldest is None or q["fetched_at"] < oldest else oldest
        rows.append(
            {
                "account": h["account"],
                "symbol": h["symbol"],
                "shares": h["shares"],
                "price": price,
                "prev_close": prev,
                "value": v,
                "day_change": d,
                "source": "cash" if h["is_cash"] else (q["source"] if q else "holdings"),
            }
        )
    base = value - change
    fresh = oldest is not None and now - datetime.fromisoformat(oldest) <= timedelta(minutes=FRESH_MINUTES)
    quality = "ok" if (fresh or sess.state not in LIVE_STATES) and holdings else ("insufficient_history" if not holdings else "stale")
    rows.sort(key=lambda r: -r["value"])
    return {
        "state": sess.state,
        "day": sess.day,
        "opens_at": sess.opens_at,
        "closes_at": sess.closes_at,
        "as_of": oldest,
        "quote_day": quote_day,
        "holdings_date": day,
        "value": round(value, 2),
        "day_change": round(change, 2),
        "day_change_pct": round(change / base * 100, 2) if base else None,
        "quality": quality,
        "rows": rows,
        "benchmarks": {s: latest[s] for s in BENCHMARKS if s in latest},
    }
