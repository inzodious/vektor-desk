import re
import sqlite3
import time
from datetime import date, datetime
from statistics import median

from desk.engine import alpaca
from desk.engine.market import ProviderError
from desk.engine.research import SEC_GAP, _get, sec_agent, sec_ciks
from desk.paper_check import NotPaper

SEC_FRAME = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{year}Q{q}I.json"
EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}
CAP_MIN, CAP_MAX = 50e6, 2e9
DOLLAR_VOLUME_MIN = 500e3
VOLUME_DAYS = 20
MIN_SESSIONS = 15
FRAMES_BACK = 3
SHARES_MAX_AGE_DAYS = 400
TICKER = re.compile(r"^[A-Z]{1,5}$")
EXCLUDE = re.compile(
    r"\b(ETF|ETN|ETFS|FUND|FUNDS|ISHARES|SPDR|PROSHARES|INDEX|PORTFOLIO|NOTES?|WARRANTS?|UNITS?|RIGHTS?|PREFERRED|PFD|DEPOSITARY|ADR|ADS|"
    r"ACQUISITION CORP|ACQUISITION CO|ACQUISITION INC|BDC)\b",
    re.I,
)
RULE = "US common stock on NYSE, Nasdaq or NYSE American; market cap $50M to $2B (SEC shares x close); 20-day median dollar volume at least $500K"


# ---- SEC shares outstanding ----


def _frames(day: date) -> list[tuple[int, int]]:
    year, q = day.year, (day.month - 1) // 3 + 1
    out = []
    for _ in range(FRAMES_BACK):
        out.append((year, q))
        year, q = (year, q - 1) if q > 1 else (year - 1, 4)
    return out


def fetch_shares(conn: sqlite3.Connection, http, *, now: datetime, sleep=time.sleep) -> int:
    agent = sec_agent()
    if not agent:
        raise ProviderError("DESK_SEC_USER_AGENT is not set")
    rows = []
    for year, q in _frames(now.date()):
        body = _get(http, SEC_FRAME.format(year=year, q=q), "SEC", headers={"User-Agent": agent}) or {}
        sleep(SEC_GAP)
        for r in body.get("data") or []:
            if r.get("cik") and r.get("val") and r.get("end"):
                rows.append((int(r["cik"]), str(r["end"]), float(r["val"]), str(r.get("accn") or ""), now.isoformat(timespec="seconds")))
    with conn:
        conn.executemany("INSERT OR REPLACE INTO sec_shares VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


def latest_shares(conn: sqlite3.Connection, day: str) -> dict[int, tuple[float, str]]:
    out: dict[int, tuple[float, str]] = {}
    for r in conn.execute("SELECT cik, end, val FROM sec_shares WHERE end <= ? ORDER BY cik, end", (day,)):
        out[r["cik"]] = (r["val"], r["end"])
    return out


# ---- The rule ----


def candidates(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    ciks = {r["symbol"]: r["cik"] for r in conn.execute("SELECT symbol, cik FROM sec_tickers")}
    funds = {r[0] for r in conn.execute("SELECT symbol FROM sec_funds")}
    out = []
    for r in conn.execute("SELECT symbol, name, exchange FROM alpaca_assets WHERE tradable=1 ORDER BY symbol"):
        sym, name, ex = r["symbol"], r["name"] or "", (r["exchange"] or "").upper()
        if ex not in EXCHANGES or not TICKER.match(sym) or sym in funds or EXCLUDE.search(name) or sym not in ciks:
            continue
        out.append((sym, name, ex, ciks[sym]))
    return out


def build(conn: sqlite3.Connection, day: str | None = None) -> dict:
    day = day or conn.execute("SELECT max(date) FROM alpaca_bars").fetchone()[0]
    if not day:
        return {"date": None, "members": 0, "candidates": 0}
    shares = latest_shares(conn, day)
    pool = candidates(conn)
    members = []
    for sym, name, ex, cik in pool:
        if cik not in shares:
            continue
        count, end = shares[cik]
        if (date.fromisoformat(day) - date.fromisoformat(end)).days > SHARES_MAX_AGE_DAYS:
            continue
        bars = conn.execute(
            "SELECT date, close, volume FROM alpaca_bars WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT ?", (sym, day, VOLUME_DAYS)
        ).fetchall()
        if len(bars) < MIN_SESSIONS or bars[0]["date"] != day:
            continue
        close = bars[0]["close"]
        cap = count * close
        dollar = median(b["close"] * (b["volume"] or 0) for b in bars)
        if CAP_MIN <= cap <= CAP_MAX and dollar >= DOLLAR_VOLUME_MIN:
            members.append((day, sym, cik, name, ex, close, count, end, round(cap, 0), round(dollar, 0)))
    with conn:
        conn.execute("DELETE FROM universe_daily WHERE date=?", (day,))
        conn.executemany("INSERT INTO universe_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", members)
    return {"date": day, "members": len(members), "candidates": len(pool)}


def members(conn: sqlite3.Connection, day: str | None = None) -> list[dict]:
    day = day or conn.execute("SELECT max(date) FROM universe_daily").fetchone()[0]
    if not day:
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM universe_daily WHERE date=? ORDER BY symbol", (day,))]


# ---- Nightly job ----


def run(conn: sqlite3.Connection, http, *, now: datetime, sleep=time.sleep) -> dict:
    if alpaca.headers() is None:
        return {"ok": True, "skipped": "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set"}
    if not sec_agent():
        return {"ok": True, "skipped": "DESK_SEC_USER_AGENT is not set"}
    try:
        sec_ciks(conn, http, sec_agent(), now, sleep)
        assets = alpaca.fetch_assets(conn, http, now=now)
        shares = fetch_shares(conn, http, now=now, sleep=sleep)
        pool = candidates(conn)
        have = latest_shares(conn, now.date().isoformat())
        symbols = [sym for sym, _, _, cik in pool if cik in have]
        bars = alpaca.run_bars(conn, http, symbols, now=now, sleep=sleep)
    except (ProviderError, NotPaper) as e:
        return {"ok": False, "error": str(e)}
    built = build(conn)
    return {"ok": True, "assets": assets, "shares": shares, "bars": bars, **built}
