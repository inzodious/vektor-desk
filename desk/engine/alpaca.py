import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta

from desk.engine.market import ET, ProviderError
from desk.paper_check import KEYS, paper_base

DATA_URL = "https://data.alpaca.markets"
BARS_PATH = "/v2/stocks/bars"
ASSETS_PATH = "/v2/assets"
FEED_ENV = "DESK_ALPACA_FEED"
CHUNK = 100
GAP = 0.35
FIRST_DAYS = 45
OVERLAP_DAYS = 7
SIP_DELAY_MIN = 20


class BadRequest(ProviderError):
    pass


def headers() -> dict[str, str] | None:
    key, secret = (os.environ.get(k, "").strip() for k in KEYS)
    if not key or not secret:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def feed() -> str:
    return os.environ.get(FEED_ENV, "").strip().lower() or "sip"


def _get(http, url: str, params: dict, hdrs: dict):
    res = http.get(url, params=params, headers=hdrs, timeout=60)
    if res.status_code in (401, 403):
        raise ProviderError(f"Alpaca refused the keys ({res.status_code})")
    if res.status_code == 429:
        raise ProviderError("Alpaca rate limit")
    if res.status_code != 200:
        path = url.split("//", 1)[-1].partition("/")[2]
        text = f"Alpaca {res.status_code} on /{path}: {_message(res)}"
        raise BadRequest(text) if res.status_code in (400, 404, 422) else ProviderError(text)
    return res.json()


def _message(res) -> str:
    try:
        body = res.json()
    except ValueError:
        body = None
    said = body.get("message") if isinstance(body, dict) else None
    return str(said or getattr(res, "text", "") or "no message")[:200]


def _day(stamp: str) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ET).date().isoformat()


# ---- Assets (trading API, paper host, read only) ----


def fetch_assets(conn: sqlite3.Connection, http, *, now: datetime) -> int:
    hdrs = headers()
    if hdrs is None:
        raise ProviderError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set")
    body = _get(http, paper_base() + ASSETS_PATH, {"status": "active", "asset_class": "us_equity"}, hdrs) or []
    rows = [
        (str(a["symbol"]).upper(), str(a.get("name") or ""), str(a.get("exchange") or ""), int(bool(a.get("tradable"))), now.isoformat(timespec="seconds"))
        for a in body
        if isinstance(a, dict) and a.get("symbol")
    ]
    if rows:
        with conn:
            conn.execute("DELETE FROM alpaca_assets")
            conn.executemany("INSERT OR REPLACE INTO alpaca_assets VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


# ---- Daily bars (market data host, read only) ----


def fetch_bars(http, symbols: list[str], start: str, end: str, adjustment: str, *, sleep=time.sleep, skipped: list | None = None) -> dict[str, list[dict]]:
    hdrs = headers()
    if hdrs is None:
        raise ProviderError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set")
    out: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), CHUNK):
        _batch(http, symbols[i : i + CHUNK], start, end, adjustment, hdrs, sleep, out, skipped)
    return out


def _batch(http, symbols: list[str], start: str, end: str, adjustment: str, hdrs: dict, sleep, out: dict, skipped: list | None) -> None:
    try:
        got = _pages(http, symbols, start, end, adjustment, hdrs, sleep)
    except BadRequest as e:
        if skipped is None:
            raise
        if len(symbols) == 1:
            skipped.append((symbols[0], str(e)))
            return
        mid = len(symbols) // 2
        _batch(http, symbols[:mid], start, end, adjustment, hdrs, sleep, out, skipped)
        _batch(http, symbols[mid:], start, end, adjustment, hdrs, sleep, out, skipped)
        return
    for sym, bars in got.items():
        out.setdefault(sym, []).extend(bars)


def _pages(http, symbols: list[str], start: str, end: str, adjustment: str, hdrs: dict, sleep) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    token = None
    while True:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": start, "end": end, "adjustment": adjustment, "feed": feed(), "limit": 10000}
        if token:
            params["page_token"] = token
        body = _get(http, DATA_URL + BARS_PATH, params, hdrs) or {}
        sleep(GAP)
        for sym, bars in (body.get("bars") or {}).items():
            out.setdefault(sym.upper(), []).extend(bars or [])
        token = body.get("next_page_token")
        if not token:
            return out


def run_bars(conn: sqlite3.Connection, http, symbols: list[str], *, now: datetime, sleep=time.sleep) -> dict:
    have = {r[0]: r[1] for r in conn.execute("SELECT symbol, max(date) FROM alpaca_bars GROUP BY symbol")}
    end = (now - timedelta(minutes=SIP_DELAY_MIN)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    groups = {
        (now - timedelta(days=OVERLAP_DAYS)).date().isoformat(): [s for s in symbols if s in have],
        (now - timedelta(days=FIRST_DAYS)).date().isoformat(): [s for s in symbols if s not in have],
    }
    rows: dict[tuple[str, str], list] = {}
    for start, syms in groups.items():
        if not syms:
            continue
        raw = fetch_bars(http, syms, start, end, "raw", sleep=sleep)
        adj = fetch_bars(http, syms, start, end, "all", sleep=sleep)
        for sym, bars in raw.items():
            for b in bars:
                rows[(sym, _day(b["t"]))] = [sym, _day(b["t"]), b.get("o"), b.get("h"), b.get("l"), float(b["c"]), None, b.get("v"), b.get("vw")]
        for sym, bars in adj.items():
            for b in bars:
                key = (sym, _day(b["t"]))
                if key in rows:
                    rows[key][6] = float(b["c"])
    with conn:
        conn.executemany("INSERT OR REPLACE INTO alpaca_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [tuple(r) for r in rows.values()])
    return {"symbols": len(symbols), "bars": len(rows), "new": sum(1 for s in symbols if s not in have)}
