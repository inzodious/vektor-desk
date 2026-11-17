import os
import sqlite3
from datetime import UTC, datetime, timedelta

from desk.engine import KEYS_AT, rapid
from desk.engine.backfill import TICKER, public_names
from desk.engine.market import ProviderError

CALLS = 100
DAY_CEILING = 490
REFRESH_DAYS = 80
ROLES = ("held", "plan", "watch", "past")
INCOME = {"revenue": "totalRevenue", "gross_profit": "grossProfit", "operating_income": "operatingIncome", "net_income": "netIncome"}


def _budget(conn: sqlite3.Connection, now: datetime) -> int:
    try:
        calls = int(os.environ.get("DESK_AV_HISTORY_CALLS", CALLS))
    except ValueError:
        calls = CALLS
    spent = rapid.used(conn, rapid.BY_NAME[rapid.AV], now)["day"]
    return max(0, min(calls, DAY_CEILING - spent))


def wanted(conn: sqlite3.Connection, now: datetime) -> list[str]:
    names = list(public_names(conn))
    marks = ",".join("?" * len(ROLES))
    names += [r[0] for r in conn.execute(f"SELECT symbol FROM market_symbols WHERE role IN ({marks}) ORDER BY priority, symbol", ROLES)]
    fresh = (now - timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds")
    done = {r[0] for r in conn.execute("SELECT symbol FROM av_fetches WHERE fetched_at >= ?", (fresh,))}
    seen: set[str] = set()
    out = []
    for s in names:
        if s in seen or s in done or not TICKER.match(s):
            continue
        seen.add(s)
        out.append(s)
    return out


def _ask(http, api_key: str, symbol: str, function: str) -> dict:
    src = rapid.BY_NAME[rapid.AV]
    body = rapid._get(http, src, "/query", {"function": function, "symbol": symbol}, api_key, symbol) or {}
    if "Note" in body or "Information" in body:
        raise ProviderError(f"{src.title} rate limit")
    return body


def quarters(earnings: dict, income: dict) -> list[dict]:
    rows: dict[str, dict] = {}
    for r in earnings.get("quarterlyEarnings") or []:
        end = str(r.get("fiscalDateEnding") or "")[:10]
        if end:
            rows[end] = {
                "period_end": end,
                "reported": (str(r.get("reportedDate") or "")[:10] or None),
                "eps": rapid._num(r.get("reportedEPS")),
                "eps_estimate": rapid._num(r.get("estimatedEPS")),
            }
    for r in income.get("quarterlyReports") or []:
        end = str(r.get("fiscalDateEnding") or "")[:10]
        if end:
            row = rows.setdefault(end, {"period_end": end, "reported": None, "eps": None, "eps_estimate": None})
            row |= {col: rapid._num(r.get(field)) for col, field in INCOME.items()}
    return [r | {c: r.get(c) for c in INCOME} for _, r in sorted(rows.items())]


def run(conn: sqlite3.Connection, http, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    api_key = rapid.key()
    if not api_key:
        return {"ok": True, "skipped": f"The RapidAPI key is not set, so no earnings history was loaded. Add it in {KEYS_AT}."}
    budget = _budget(conn, now)
    queue = wanted(conn, now)
    loaded, failed, calls = [], [], 0
    for symbol in queue:
        if calls + 2 > budget:
            break
        stamp = now.isoformat(timespec="seconds")
        bodies, error = [], None
        for function in ("EARNINGS", "INCOME_STATEMENT"):
            try:
                bodies.append(_ask(http, api_key, symbol, function))
            except ProviderError as e:
                error = str(e)
            except (OSError, ValueError):
                error = f"Alpha Vantage did not answer for {symbol}"
            calls += 1
            with conn:
                conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES (?, ?, ?, ?)", (rapid.AV, stamp, symbol, int(error is None)))
            if error:
                break
        rows = quarters(*bodies) if error is None else []
        with conn:
            conn.executemany(
                """INSERT OR REPLACE INTO av_quarters (symbol, period_end, reported, eps, eps_estimate, revenue, gross_profit, operating_income, net_income)
                   VALUES (:symbol, :period_end, :reported, :eps, :eps_estimate, :revenue, :gross_profit, :operating_income, :net_income)""",
                [r | {"symbol": symbol} for r in rows],
            )
            conn.execute("INSERT OR REPLACE INTO av_fetches (symbol, fetched_at, quarters, error) VALUES (?, ?, ?, ?)", (symbol, stamp, len(rows), error))
        if error:
            failed.append(f"{symbol}: {error}")
            if "rate limit" in error or "refused" in error or "did not answer" in error:
                break
        else:
            loaded.append(symbol)
    held = conn.execute("SELECT count(DISTINCT symbol) FROM av_quarters").fetchone()[0]
    left = max(0, len(queue) - len(loaded) - len(failed))
    detail = f"Loaded earnings history for {len(loaded)} {'company' if len(loaded) == 1 else 'companies'}; {held} held in all."
    if left:
        detail += f" {left} more wait for the next nights, to stay inside Alpha Vantage's free plan."
    return {"ok": not failed, "loaded": loaded, "errors": failed, "left": left, "calls": calls, "budget": budget, "companies": held, "detail": detail}
