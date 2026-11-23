import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

from desk.engine import KEYS_AT, rapid
from desk.engine.backfill import TICKER, public_names
from desk.engine.market import ProviderError

CALLS = 100
DAY_CEILING = 490
REFRESH_DAYS = 80
RETRY_DAYS = 1
NO_DATA_DAYS = 14
ROLES = ("held", "plan", "watch", "past")
INCOME = {"revenue": "totalRevenue", "gross_profit": "grossProfit", "operating_income": "operatingIncome", "net_income": "netIncome"}
SHOWN_ERRORS = 50


def _budget(conn: sqlite3.Connection, now: datetime) -> int:
    try:
        calls = int(os.environ.get("DESK_AV_HISTORY_CALLS", CALLS))
    except ValueError:
        calls = CALLS
    spent = rapid.used(conn, rapid.BY_NAME[rapid.AV], now)["day"]
    return max(0, min(calls, DAY_CEILING - spent))


def _no_data(error: str) -> bool:
    return "has no" in error


def wanted(conn: sqlite3.Connection, now: datetime) -> list[str]:
    names = list(public_names(conn))
    marks = ",".join("?" * len(ROLES))
    names += [r[0] for r in conn.execute(f"SELECT symbol FROM market_symbols WHERE role IN ({marks}) ORDER BY priority, symbol", ROLES)]
    fresh = (now - timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds")
    retry = (now - timedelta(days=RETRY_DAYS)).isoformat(timespec="seconds")
    later = (now - timedelta(days=NO_DATA_DAYS)).isoformat(timespec="seconds")
    done = set()
    for symbol, at, error in conn.execute("SELECT symbol, fetched_at, error FROM av_fetches"):
        if error is None and at >= fresh or error is not None and at >= (later if _no_data(error) else retry):
            done.add(symbol)
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
    body = rapid.ask(http, src, "/query", {"function": function, "symbol": symbol}, api_key, symbol) or {}
    if not isinstance(body, dict):
        raise ProviderError(f"{src.title} sent something other than figures for {symbol}")
    if body.get("Error Message"):
        raise ProviderError(f"{src.title} has no {function.lower().replace('_', ' ')} for {symbol}: {' '.join(str(body['Error Message']).split())[:120]}")
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
    src = rapid.BY_NAME[rapid.AV]
    budget = _budget(conn, now)
    queue = wanted(conn, now)
    loaded, failed, calls, stopped = [], [], 0, None
    for symbol in queue:
        if calls + 2 > budget:
            break
        bodies, error = [], None
        for function in ("EARNINGS", "INCOME_STATEMENT"):
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            try:
                bodies.append(_ask(http, api_key, symbol, function))
            except ProviderError as e:
                error = str(e)
                if rapid.stops(e):
                    stopped = error
            except (OSError, ValueError):
                error = stopped = f"{src.title} did not answer for {symbol}"
            calls += 1
            with conn:
                conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES (?, ?, ?, ?)", (rapid.AV, stamp, symbol, int(error is None)))
            if error:
                rapid.note_error(conn, src, stamp, symbol, error)
                break
        rows = quarters(*bodies) if error is None else []
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with conn:
            conn.executemany(
                """INSERT OR REPLACE INTO av_quarters (symbol, period_end, reported, eps, eps_estimate, revenue, gross_profit, operating_income, net_income)
                   VALUES (:symbol, :period_end, :reported, :eps, :eps_estimate, :revenue, :gross_profit, :operating_income, :net_income)""",
                [r | {"symbol": symbol} for r in rows],
            )
            conn.execute("INSERT OR REPLACE INTO av_fetches (symbol, fetched_at, quarters, error) VALUES (?, ?, ?, ?)", (symbol, stamp, len(rows), error))
        if error:
            failed.append(f"{symbol}: {error}")
            if stopped:
                break
        else:
            loaded.append(symbol)
    held = conn.execute("SELECT count(DISTINCT symbol) FROM av_quarters").fetchone()[0]
    left = max(0, len(queue) - len(loaded) - len(failed))
    detail = f"Loaded earnings history for {len(loaded)} {'company' if len(loaded) == 1 else 'companies'}; {held} held in all."
    if failed and not stopped:
        detail += f" {len(failed)} had no figures this time and are asked again later."
    if stopped:
        detail += f" Stopped early: {stopped}."
    if left:
        detail += f" {left} more wait for the next nights, to stay inside Alpha Vantage's free plan."
    refused = isinstance(stopped, str) and "refused the key" in stopped
    ok = not refused and (bool(loaded) or not failed)
    return {
        "ok": ok,
        "loaded": loaded,
        "errors": failed,
        "stopped": stopped,
        "left": left,
        "calls": calls,
        "budget": budget,
        "companies": held,
        "detail": detail,
    }


def state(conn: sqlite3.Connection | None) -> dict:
    out = {"asked": 0, "with_quarters": 0, "errors": [], "last_run": None}
    if conn is None or conn.execute("SELECT 1 FROM sqlite_master WHERE name='av_fetches'").fetchone() is None:
        return out
    out["asked"], out["with_quarters"] = conn.execute("SELECT count(*), coalesce(sum(quarters > 0), 0) FROM av_fetches").fetchone()
    out["errors"] = [
        {"symbol": r[0], "at": r[1], "error": r[2]}
        for r in conn.execute("SELECT symbol, fetched_at, error FROM av_fetches WHERE error IS NOT NULL ORDER BY fetched_at DESC LIMIT ?", (SHOWN_ERRORS,))
    ]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='engine_runs'").fetchone():
        last = conn.execute("SELECT finished_at, ok, detail FROM engine_runs WHERE job='av-history' ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            detail = json.loads(last[2] or "{}")
            keys = ("detail", "loaded", "errors", "stopped", "left", "calls", "budget", "companies", "skipped")
            out["last_run"] = {"finished_at": last[0], "ok": bool(last[1])} | {k: detail.get(k) for k in keys}
    return out
