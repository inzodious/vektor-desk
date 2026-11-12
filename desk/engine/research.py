import os
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from desk.engine import NO_FINNHUB, NO_FRED, NO_SEC, skip
from desk.engine.market import ProviderError, finnhub_key

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
FINNHUB_EARNINGS = "https://finnhub.io/api/v1/calendar/earnings"
FINNHUB_INSIDERS = "https://finnhub.io/api/v1/stock/insider-transactions"

SEC_GAP = 0.12
FILING_YEARS = 2
REFRESH_HOURS = 20
TICKERS_DAYS = 7
FRED_START = "2000-01-01"
FRED_SERIES = {
    "DGS3MO": "rf_3m",
    "DGS2": "y2",
    "DGS10": "y10",
    "CPIAUCSL": "cpi",
    "BAMLH0A0HYM2": "hy_spread",
    "VIXCLS": "vix",
}
CONCEPTS = {
    ("us-gaap", "Revenues"): "revenue",
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"): "revenue",
    ("us-gaap", "NetIncomeLoss"): "net_income",
    ("us-gaap", "GrossProfit"): "gross_profit",
    ("us-gaap", "OperatingIncomeLoss"): "operating_income",
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"): "cash",
    ("us-gaap", "LongTermDebt"): "long_term_debt",
    ("us-gaap", "StockholdersEquity"): "equity",
    ("us-gaap", "EarningsPerShareDiluted"): "eps_diluted",
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"): "operating_cash_flow",
    ("dei", "EntityCommonStockSharesOutstanding"): "shares_outstanding",
}
OPEN_MARKET = ("P", "S")


def sec_agent() -> str:
    return os.environ.get("DESK_SEC_USER_AGENT", "").strip()


def fred_key() -> str:
    return os.environ.get("FRED_API_KEY", "").strip()


def _stamp(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _get(http, url: str, provider: str, *, params=None, headers=None):
    res = http.get(url, params=params, headers=headers, timeout=60)
    if res.status_code == 429:
        raise ProviderError(f"{provider} rate limit")
    if res.status_code == 404:
        return None
    if res.status_code != 200:
        raise ProviderError(f"{provider} {res.status_code}")
    return res.json()


def _log(conn: sqlite3.Connection, provider: str, symbol: str | None, ok: bool, now: datetime) -> None:
    conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES (?, ?, ?, ?)", (provider, _stamp(now), symbol, int(ok)))


def _fresh(conn: sqlite3.Connection, provider: str, symbol: str, now: datetime, hours: float = REFRESH_HOURS) -> bool:
    cut = _stamp(now - timedelta(hours=hours))
    return conn.execute("SELECT 1 FROM api_calls WHERE provider=? AND symbol=? AND ok=1 AND at >= ? LIMIT 1", (provider, symbol, cut)).fetchone() is not None


# ---- Which symbols ----


def research_symbols(conn: sqlite3.Connection, kinds: dict[str, str]) -> list[str]:
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    held = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0", (day,))} if day else set()
    watch = {r[0] for r in conn.execute("SELECT symbol FROM market_symbols WHERE role='watch'")}
    watch |= {s.strip().upper() for s in os.environ.get("DESK_WATCHLIST", "").split(",") if s.strip()}
    return sorted(s for s in held | watch if kinds.get(s, "unknown") != "fund")


# ---- SEC EDGAR ----


def sec_ciks(conn: sqlite3.Connection, http, agent: str, now: datetime, sleep=time.sleep) -> dict[str, int]:
    newest = conn.execute("SELECT max(fetched_at) FROM sec_tickers").fetchone()[0]
    if not newest or newest < _stamp(now - timedelta(days=TICKERS_DAYS)):
        body = _get(http, SEC_TICKERS, "SEC", headers={"User-Agent": agent}) or {}
        sleep(SEC_GAP)
        rows = [(str(v["ticker"]).upper(), int(v["cik_str"]), str(v.get("title") or ""), _stamp(now)) for v in body.values() if v.get("ticker")]
        if rows:
            with conn:
                conn.execute("DELETE FROM sec_tickers")
                conn.executemany("INSERT OR REPLACE INTO sec_tickers VALUES (?, ?, ?, ?)", rows)
                _log(conn, "sec", None, True, now)
    return {r["symbol"]: r["cik"] for r in conn.execute("SELECT symbol, cik FROM sec_tickers")}


def parse_filings(symbol: str, cik: int, body: dict, today: str) -> list[tuple]:
    recent = ((body or {}).get("filings") or {}).get("recent") or {}
    cut = (date.fromisoformat(today) - timedelta(days=365 * FILING_YEARS)).isoformat()
    cols = {k: recent.get(k) or [] for k in ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "primaryDocDescription")}

    def at(key: str, i: int) -> str:
        values = cols[key]
        return str(values[i] or "") if i < len(values) else ""

    out = []
    for i, acc in enumerate(cols["accessionNumber"]):
        filed = at("filingDate", i)
        if not filed or filed < cut:
            continue
        doc = at("primaryDocument", i)
        url = SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=doc) if doc else None
        out.append((acc, symbol, cik, at("form", i), filed, at("reportDate", i) or None, at("primaryDocDescription", i)[:200], url))
    return out


def parse_facts(symbol: str, body: dict) -> list[tuple]:
    facts = (body or {}).get("facts") or {}
    out = {}
    for (ns, concept), name in CONCEPTS.items():
        units = ((facts.get(ns) or {}).get(concept) or {}).get("units") or {}
        for unit, rows in units.items():
            for r in rows:
                if r.get("val") is None or not r.get("end"):
                    continue
                key = (symbol, name, r["end"], r.get("fp") or "", r.get("form") or "")
                row = (symbol, name, r.get("start"), r["end"], r.get("fy"), r.get("fp"), r.get("form"), r.get("filed"), float(r["val"]), unit)
                if key not in out or (row[7] or "") > (out[key][7] or ""):
                    out[key] = row
    return list(out.values())


def run_edgar(conn: sqlite3.Connection, http, symbols: list[str], *, now: datetime, sleep=time.sleep) -> dict:
    agent = sec_agent()
    if not agent:
        return skip(NO_SEC)
    ciks = sec_ciks(conn, http, agent, now, sleep)
    done, missing, errors = [], [], []
    for sym in symbols:
        if _fresh(conn, "sec", sym, now):
            continue
        cik = ciks.get(sym) or ciks.get(sym.replace(".", "-"))
        if cik is None:
            missing.append(sym)
            continue
        try:
            subs = _get(http, SEC_SUBMISSIONS.format(cik=cik), "SEC", headers={"User-Agent": agent})
            sleep(SEC_GAP)
            facts = _get(http, SEC_FACTS.format(cik=cik), "SEC", headers={"User-Agent": agent})
            sleep(SEC_GAP)
        except ProviderError as e:
            errors.append(f"{sym}: {e}")
            with conn:
                _log(conn, "sec", sym, False, now)
            if "rate limit" in str(e):
                break
            continue
        filings = parse_filings(sym, cik, subs or {}, now.date().isoformat())
        rows = parse_facts(sym, facts or {})
        with conn:
            conn.executemany("INSERT OR REPLACE INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?)", filings)
            if rows:
                conn.execute("DELETE FROM fundamentals WHERE symbol=?", (sym,))
                conn.executemany("INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            _log(conn, "sec", sym, True, now)
        done.append(sym)
    return {"ok": not errors, "symbols": done, "missing": missing, "errors": errors}


# ---- FRED ----


def run_fred(conn: sqlite3.Connection, http, *, now: datetime) -> dict:
    key = fred_key()
    if not key:
        return skip(NO_FRED)
    done, errors = {}, []
    for series in FRED_SERIES:
        if _fresh(conn, "fred", series, now):
            continue
        last = conn.execute("SELECT max(date) FROM macro_daily WHERE series=?", (series,)).fetchone()[0]
        start = (date.fromisoformat(last) - timedelta(days=45)).isoformat() if last else FRED_START
        try:
            body = _get(http, FRED_OBS, "FRED", params={"series_id": series, "api_key": key, "file_type": "json", "observation_start": start}) or {}
        except ProviderError as e:
            errors.append(f"{series}: {e}")
            continue
        rows = []
        for o in body.get("observations") or []:
            try:
                rows.append((series, str(o["date"])[:10], float(o["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        with conn:
            conn.executemany("INSERT OR REPLACE INTO macro_daily VALUES (?, ?, ?)", rows)
            _log(conn, "fred", series, True, now)
        done[series] = len(rows)
    return {"ok": not errors, "series": done, "errors": errors}


# ---- Finnhub earnings and insiders ----


def run_finnhub_research(conn: sqlite3.Connection, http, symbols: list[str], *, now: datetime) -> dict:
    key = finnhub_key()
    if not key:
        return skip(NO_FINNHUB)
    today = now.date()
    done, errors = [], []
    for sym in symbols:
        if _fresh(conn, "finnhub_research", sym, now):
            continue
        try:
            cal = _get(
                http,
                FINNHUB_EARNINGS,
                "Finnhub",
                params={"symbol": sym, "from": (today - timedelta(days=120)).isoformat(), "to": (today + timedelta(days=100)).isoformat(), "token": key},
            )
            ins = _get(http, FINNHUB_INSIDERS, "Finnhub", params={"symbol": sym, "from": (today - timedelta(days=365)).isoformat(), "token": key})
        except ProviderError as e:
            errors.append(f"{sym}: {e}")
            if "rate limit" in str(e):
                break
            continue
        earn = [
            (
                sym,
                r["date"],
                r.get("hour"),
                r.get("quarter"),
                r.get("year"),
                r.get("epsEstimate"),
                r.get("epsActual"),
                r.get("revenueEstimate"),
                r.get("revenueActual"),
            )
            for r in (cal or {}).get("earningsCalendar") or []
            if r.get("date")
        ]
        trades = [
            (
                sym,
                str(r.get("name") or ""),
                r.get("filingDate"),
                r.get("transactionDate"),
                r.get("transactionCode"),
                r.get("change"),
                r.get("share"),
                r.get("transactionPrice"),
            )
            for r in (ins or {}).get("data") or []
            if r.get("transactionDate")
        ]
        with conn:
            conn.executemany("INSERT OR REPLACE INTO earnings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", earn)
            conn.executemany("INSERT OR IGNORE INTO insider_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)", trades)
            _log(conn, "finnhub_research", sym, True, now)
        done.append(sym)
    return {"ok": not errors, "symbols": done, "errors": errors}


# ---- Signals ----


def signals(conn: sqlite3.Connection, symbols: list[str], as_of: str, prev_as_of: str | None) -> list[tuple[str, str, float | None, str, str, int | None]]:
    out: list[tuple[str, str, float | None, str, str, int | None]] = []
    day = date.fromisoformat(as_of)
    for sym in symbols:
        nxt = conn.execute("SELECT min(date) FROM earnings WHERE symbol=? AND date > ?", (sym, as_of)).fetchone()[0]
        if nxt:
            out.append(("sig.earnings_days", sym, (date.fromisoformat(nxt) - day).days, "days", "now", None))
        last = conn.execute(
            "SELECT * FROM earnings WHERE symbol=? AND date <= ? AND eps_actual IS NOT NULL ORDER BY date DESC LIMIT 1", (sym, as_of)
        ).fetchone()
        if last:
            if last["eps_estimate"] not in (None, 0):
                out.append(("sig.eps_surprise", sym, (last["eps_actual"] - last["eps_estimate"]) / abs(last["eps_estimate"]) * 100, "pct", "now", None))
            if last["revenue_estimate"] and last["revenue_actual"] is not None:
                out.append(
                    ("sig.revenue_surprise", sym, (last["revenue_actual"] - last["revenue_estimate"]) / abs(last["revenue_estimate"]) * 100, "pct", "now", None)
                )
            out.append(("sig.earnings_since", sym, (day - date.fromisoformat(last["date"])).days, "days", "now", None))
        cut = (day - timedelta(days=90)).isoformat()
        rows = conn.execute(
            "SELECT name, code, change, price FROM insider_trades WHERE symbol=? AND txn_date > ? AND txn_date <= ? AND code IN (?, ?)",
            (sym, cut, as_of, *OPEN_MARKET),
        ).fetchall()
        net = sum((r["change"] or 0) * (r["price"] or 0) for r in rows)
        out.append(("sig.insider_net", sym, net, "usd", "90D", len(rows)))
        out.append(("sig.insider_buyers", sym, len({r["name"] for r in rows if r["code"] == "P"}), "count", "90D", len(rows)))
        shares = conn.execute(
            "SELECT period_end, value FROM fundamentals WHERE symbol=? AND concept='shares_outstanding' AND period_end <= ? ORDER BY period_end DESC",
            (sym, as_of),
        ).fetchall()
        if shares:
            year_ago = (date.fromisoformat(shares[0]["period_end"]) - timedelta(days=330)).isoformat()
            old = next((r for r in shares if r["period_end"] <= year_ago), None)
            if old and old["value"]:
                out.append(("sig.dilution", sym, (shares[0]["value"] / old["value"] - 1) * 100, "pct", "1Y", None))
        annual = defaultdict(list)
        for r in conn.execute(
            "SELECT concept, start, period_end, value FROM fundamentals WHERE symbol=? AND start IS NOT NULL AND period_end <= ?", (sym, as_of)
        ):
            if (date.fromisoformat(r["period_end"]) - date.fromisoformat(r["start"])).days > 300:
                annual[r["concept"]].append(r)
        for rows_ in annual.values():
            rows_.sort(key=lambda r: r["period_end"], reverse=True)
        if annual.get("revenue"):
            rev = annual["revenue"][0]
            cut = (date.fromisoformat(rev["period_end"]) - timedelta(days=300)).isoformat()
            prior = next((r for r in annual["revenue"] if r["period_end"] <= cut), None)
            if prior and prior["value"]:
                out.append(("fund.revenue_growth", sym, (rev["value"] / prior["value"] - 1) * 100, "pct", "FY", None))
            for concept, metric in (("net_income", "fund.net_margin"), ("gross_profit", "fund.gross_margin"), ("operating_income", "fund.operating_margin")):
                same = next((r for r in annual.get(concept, []) if r["period_end"] == rev["period_end"]), None)
                if same and rev["value"]:
                    out.append((metric, sym, same["value"] / rev["value"] * 100, "pct", "FY", None))
        if prev_as_of and last and prev_as_of < last["date"] <= as_of:
            out.append(("sig.earnings_reported", sym, 1, "count", "now", None))
    return out


def macro(conn: sqlite3.Connection, as_of: str) -> list[tuple[str, str, float | None, str]]:
    latest = {}
    for series, name in FRED_SERIES.items():
        r = conn.execute("SELECT date, value FROM macro_daily WHERE series=? AND date <= ? ORDER BY date DESC LIMIT 1", (series, as_of)).fetchone()
        if r:
            latest[name] = (r["date"], r["value"])
    out = []
    for name in ("rf_3m", "y2", "y10", "hy_spread", "vix"):
        if name in latest:
            out.append((f"macro.{name}", name, latest[name][1], "pts" if name == "vix" else "pct"))
    if "y10" in latest and "y2" in latest:
        out.append(("macro.curve_10y2y", "curve", latest["y10"][1] - latest["y2"][1], "pts"))
    if "cpi" in latest:
        d = date.fromisoformat(latest["cpi"][0])
        old = conn.execute(
            "SELECT value FROM macro_daily WHERE series='CPIAUCSL' AND date <= ? ORDER BY date DESC LIMIT 1", ((d - timedelta(days=360)).isoformat(),)
        ).fetchone()
        if old and old["value"]:
            out.append(("macro.cpi_yoy", "cpi", (latest["cpi"][1] / old["value"] - 1) * 100, "pct"))
    return out


def run_all(conn: sqlite3.Connection, http, kinds: dict[str, str], *, now: datetime | None = None, sleep=time.sleep) -> dict:
    now = now or datetime.now(UTC)
    symbols = research_symbols(conn, kinds)
    return {
        "ok": True,
        "symbols": symbols,
        "edgar": run_edgar(conn, http, symbols, now=now, sleep=sleep),
        "fred": run_fred(conn, http, now=now),
        "finnhub": run_finnhub_research(conn, http, symbols, now=now),
    }
