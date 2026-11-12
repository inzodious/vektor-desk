import json
import os
import re
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from xml.parsers import expat

from desk.engine import JOBS_AT, key_fix, research
from desk.engine.market import ProviderError, finnhub_key
from desk.engine.research import SEC_ARCHIVE, SEC_SUBMISSIONS, _fresh, _get, _log, _stamp, sec_agent, sec_ciks

SEC_FUNDS = "https://www.sec.gov/files/company_tickers_mf.json"
FINNHUB_PROFILE = "https://finnhub.io/api/v1/stock/profile2"

NPORT_FORMS = ("NPORT-P", "NPORT-P/A")
NPORT_SCAN = 40
NPORT_REFRESH_DAYS = 30
PROFILE_DAYS = 90
FINNHUB_GAP = 1.05
TOP_UNDERLYING = 25
EQUITY = ("EC", "EP")
SUFFIXES = {
    "INC",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "PLC",
    "LLC",
    "LP",
    "SA",
    "NV",
    "AG",
    "HOLDINGS",
    "GROUP",
    "THE",
    "CLASS",
    "CL",
    "A",
    "B",
    "C",
}
SECTOR_FUNDS = {
    "XLK": "Technology",
    "FTEC": "Technology",
    "VGT": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}
SECTORS = {
    "Technology": ("technology", "semiconductor", "software", "it services", "electronic", "communications equipment", "computers"),
    "Communication Services": ("media", "telecommunication", "entertainment", "interactive"),
    "Financials": ("bank", "financial", "insurance", "capital markets", "diversified financial"),
    "Health Care": ("health", "pharma", "biotech", "life sciences", "medical"),
    "Energy": ("energy", "oil", "gas", "coal"),
    "Utilities": ("utilit",),
    "Real Estate": ("real estate", "reit"),
    "Materials": ("chemical", "metals", "mining", "packaging", "paper", "construction materials"),
    "Consumer Staples": ("food", "beverage", "tobacco", "household products", "personal products", "consumer staples"),
    "Consumer Discretionary": ("retail", "auto", "hotel", "restaurant", "leisure", "textile", "apparel", "luxury", "household durables", "consumer products"),
    "Industrials": (
        "aerospace",
        "defense",
        "machinery",
        "industrial",
        "airline",
        "logistics",
        "transportation",
        "road",
        "rail",
        "marine",
        "electrical",
        "commercial services",
        "professional services",
        "building",
        "construction",
        "trading companies",
    ),
}


# ---- Names and sectors ----


def norm_name(name: str) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def sector_of(industry: str | None) -> str | None:
    if not industry:
        return None
    low = industry.lower()
    for sector, keys in SECTORS.items():
        if any(k in low for k in keys):
            return sector
    return industry.strip()


def title_map(conn: sqlite3.Connection) -> dict[str, str]:
    out = {}
    for r in conn.execute("SELECT symbol, title FROM sec_tickers ORDER BY length(symbol) DESC"):
        key = norm_name(r["title"])
        if key:
            out[key] = r["symbol"]
    return out


# ---- N-PORT parsing ----


class _Nport:
    def __init__(self):
        self.path: list[str] = []
        self.text: list[str] = []
        self.series = None
        self.period = None
        self.holdings: list[dict] = []
        self.cur: dict | None = None

    def start(self, tag, attrs):
        name = tag.rsplit(" ", 1)[-1].rsplit("}", 1)[-1].rsplit(":", 1)[-1]
        self.path.append(name)
        self.text = []
        if name == "invstOrSec":
            self.cur = {"name": "", "title": "", "ticker": None, "cusip": None, "pct": None, "asset_cat": None, "country": None}
        elif name == "ticker" and self.cur is not None and self.path[-2:-1] == ["identifiers"]:
            self.cur["ticker"] = (attrs.get("value") or "").strip().upper() or None

    def end(self, tag):
        name = self.path.pop()
        value = "".join(self.text).strip()
        self.text = []
        cur = self.cur
        if name == "seriesId" and self.series is None and value:
            self.series = value
        elif name == "repPdDate" and value:
            self.period = value
        elif cur is not None and self.path and self.path[-1] == "invstOrSec":
            keys = {"name": "name", "title": "title", "cusip": "cusip", "pctVal": "pct", "assetCat": "asset_cat", "invCountry": "country"}
            if name in keys:
                cur[keys[name]] = value
        elif name == "invstOrSec" and cur is not None:
            try:
                cur["pct"] = float(cur["pct"] or "")
            except ValueError:
                cur["pct"] = None
            if cur["pct"] is not None:
                cur["name"] = cur["name"] or cur.pop("title")
                cur.pop("title", None)
                self.holdings.append(cur)
            self.cur = None

    def chars(self, data):
        self.text.append(data)


def _no_dtd(*_):
    raise ValueError("N-PORT documents never carry a DTD")


def parse_nport(text: str | bytes) -> dict:
    doc = _Nport()
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartDoctypeDeclHandler = _no_dtd
    parser.EntityDeclHandler = _no_dtd
    parser.StartElementHandler = doc.start
    parser.EndElementHandler = doc.end
    parser.CharacterDataHandler = doc.chars
    parser.Parse(text.encode() if isinstance(text, str) else text, True)
    return {"series": doc.series, "period": doc.period, "holdings": doc.holdings}


def holding_key(h: dict, titles: dict[str, str]) -> str:
    if h.get("ticker") and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", h["ticker"]):
        return h["ticker"]
    name = norm_name(h.get("name") or "")
    return titles.get(name) or name or (h.get("cusip") or "UNKNOWN")


# ---- Fetchers ----


def fund_series(conn: sqlite3.Connection, http, agent: str, now: datetime, sleep) -> dict[str, tuple[int, str]]:
    newest = conn.execute("SELECT max(fetched_at) FROM sec_funds").fetchone()[0]
    if not newest or newest < _stamp(now - timedelta(days=7)):
        body = _get(http, SEC_FUNDS, "SEC", headers={"User-Agent": agent}) or {}
        sleep(research.SEC_GAP)
        fields = body.get("fields") or []
        rows = []
        for rec in body.get("data") or []:
            r = dict(zip(fields, rec, strict=False))
            if r.get("symbol") and r.get("cik") and r.get("seriesId"):
                rows.append((str(r["symbol"]).upper(), int(r["cik"]), str(r["seriesId"]), str(r.get("classId") or ""), _stamp(now)))
        if rows:
            with conn:
                conn.execute("DELETE FROM sec_funds")
                conn.executemany("INSERT OR REPLACE INTO sec_funds VALUES (?, ?, ?, ?, ?)", rows)
    return {r["symbol"]: (r["cik"], r["series_id"]) for r in conn.execute("SELECT symbol, cik, series_id FROM sec_funds")}


def _text_get(http, url: str, agent: str) -> str | None:
    res = http.get(url, headers={"User-Agent": agent}, timeout=120)
    if res.status_code == 429:
        raise ProviderError("SEC rate limit")
    if res.status_code == 404:
        return None
    if res.status_code != 200:
        raise ProviderError(f"SEC {res.status_code}")
    return res.text


def held_funds(conn: sqlite3.Connection, kinds: dict[str, str]) -> list[str]:
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        return []
    held = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0 AND value > 0", (day,))]
    return sorted(s for s in held if kinds.get(s) == "fund")


def run_nport(conn: sqlite3.Connection, http, funds: list[str], *, now: datetime, sleep=time.sleep) -> dict:
    agent = sec_agent()
    if not agent:
        return {"ok": True, "skipped": "DESK_SEC_USER_AGENT is not set"}
    series = fund_series(conn, http, agent, now, sleep)
    titles = title_map(conn)
    done, missing, errors = [], [], []
    for fund in funds:
        if _fresh(conn, "nport", fund, now, hours=24 * NPORT_REFRESH_DAYS):
            continue
        if fund not in series:
            missing.append(fund)
            continue
        cik, want = series[fund]
        try:
            found = _scan(conn, http, agent, cik, want, now, sleep)
        except ProviderError as e:
            errors.append(f"{fund}: {e}")
            with conn:
                _log(conn, "nport", fund, False, now)
            if "rate limit" in str(e):
                break
            continue
        if not found:
            missing.append(fund)
            continue
        acc, parsed = found
        rows = [
            (fund, parsed["period"] or now.date().isoformat(), holding_key(h, titles), h["name"][:200], h["cusip"], h["pct"], h["asset_cat"], h["country"], acc)
            for h in parsed["holdings"]
        ]
        merged: dict[str, tuple] = {}
        for r in rows:
            merged[r[2]] = r if r[2] not in merged else (*merged[r[2]][:5], merged[r[2]][5] + r[5], *merged[r[2]][6:])
        with conn:
            conn.execute("DELETE FROM fund_holdings WHERE fund=?", (fund,))
            conn.executemany("INSERT INTO fund_holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", list(merged.values()))
            _log(conn, "nport", fund, True, now)
        done.append(fund)
    return {"ok": not errors, "funds": done, "missing": missing, "errors": errors}


def _scan(conn, http, agent, cik: int, want: str, now: datetime, sleep):
    subs = _get(http, SEC_SUBMISSIONS.format(cik=cik), "SEC", headers={"User-Agent": agent}) or {}
    sleep(research.SEC_GAP)
    recent = (subs.get("filings") or {}).get("recent") or {}
    accs, forms, docs, filed = (recent.get(k) or [] for k in ("accessionNumber", "form", "primaryDocument", "filingDate"))
    cut = (now.date() - timedelta(days=200)).isoformat()
    picks = [
        (accs[i], docs[i] if i < len(docs) else "primary_doc.xml", filed[i] if i < len(filed) else "")
        for i in range(len(accs))
        if i < len(forms) and forms[i] in NPORT_FORMS
    ]
    picks.sort(key=lambda p: p[2], reverse=True)
    for acc, doc, day in picks[:NPORT_SCAN]:
        if day and day < cut:
            break
        known = conn.execute("SELECT series_id FROM nport_filings WHERE accession=?", (acc,)).fetchone()
        if known and known[0] != want:
            continue
        xml_doc = doc if doc.endswith(".xml") and "/" not in doc else "primary_doc.xml"
        text = _text_get(http, SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=xml_doc), agent)
        sleep(research.SEC_GAP)
        if not text:
            continue
        try:
            parsed = parse_nport(text)
        except (expat.ExpatError, ValueError):
            continue
        with conn:
            conn.execute("INSERT OR REPLACE INTO nport_filings VALUES (?, ?, ?, ?, ?)", (acc, cik, parsed["series"] or "", parsed["period"], day))
        if parsed["series"] == want:
            return acc, parsed
    return None


def run_profiles(conn: sqlite3.Connection, http, symbols: list[str], *, now: datetime, sleep=time.sleep) -> dict:
    key = finnhub_key()
    if not key:
        return {"ok": True, "skipped": "FINNHUB_API_KEY is not set"}
    cap = int(os.environ.get("DESK_SECTOR_PROFILES", "150") or 150)
    cut = _stamp(now - timedelta(days=PROFILE_DAYS))
    fresh = {r[0] for r in conn.execute("SELECT symbol FROM sym_profiles WHERE fetched_at >= ?", (cut,))}
    todo = [s for s in symbols if s not in fresh][:cap]
    done, errors = [], []
    for sym in todo:
        try:
            body = _get(http, FINNHUB_PROFILE, "Finnhub", params={"symbol": sym, "token": key}) or {}
        except ProviderError as e:
            errors.append(f"{sym}: {e}")
            if "rate limit" in str(e):
                break
            continue
        industry = str(body.get("finnhubIndustry") or "") or None
        with conn:
            conn.execute("INSERT OR REPLACE INTO sym_profiles VALUES (?, ?, ?, ?, ?)", (sym, body.get("name"), industry, sector_of(industry), _stamp(now)))
            _log(conn, "finnhub_profile", sym, True, now)
        done.append(sym)
        sleep(FINNHUB_GAP)
    return {"ok": not errors, "symbols": done, "errors": errors}


def run_all(conn: sqlite3.Connection, http, kinds: dict[str, str], *, now: datetime | None = None, sleep=time.sleep) -> dict:
    now = now or datetime.now(UTC)
    agent = sec_agent()
    if agent:
        try:
            sec_ciks(conn, http, agent, now, sleep)
        except ProviderError as e:
            return {"ok": False, "error": str(e)}
    funds = held_funds(conn, kinds)
    nport = run_nport(conn, http, funds, now=now, sleep=sleep)
    tickers = {r[0] for r in conn.execute("SELECT symbol FROM sec_tickers")}
    view = exposures(conn, kinds)
    wanted = [e["holding"] for e in view["rows"] if e["holding"] in tickers or e["direct"]]
    return {"ok": nport.get("ok", True), "funds": funds, "nport": nport, "profiles": run_profiles(conn, http, wanted, now=now, sleep=sleep)}


# ---- Exposure ----


def exposures(conn: sqlite3.Connection, kinds: dict[str, str], profiles: dict[str, str] | None = None) -> dict:
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    empty = {"as_of": day, "rows": [], "sectors": {}, "coverage": None, "funds": {}}
    if not day:
        return empty
    by_symbol: dict[str, float] = {}
    total = 0.0
    for r in conn.execute("SELECT symbol, value, is_cash FROM holdings_daily WHERE date=?", (day,)):
        total += r["value"]
        if not r["is_cash"] and r["value"] > 0:
            by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0.0) + r["value"]
    if total <= 0:
        return empty
    sectors_known = {r["symbol"]: r["sector"] for r in conn.execute("SELECT symbol, sector FROM sym_profiles WHERE sector IS NOT NULL")}
    sectors_known.update({k: v for k, v in (profiles or {}).items() if v})
    rows: dict[str, dict] = {}
    sectors: dict[str, float] = {}
    funds: dict[str, dict] = {}
    covered = 0.0
    for sym, value in by_symbol.items():
        w = value / total * 100
        held = conn.execute("SELECT holding, name, weight, asset_cat, as_of FROM fund_holdings WHERE fund=?", (sym,)).fetchall()
        if held:
            covered += w
            funds[sym] = {"weight": w, "as_of": held[0]["as_of"], "holdings": len(held)}
            for h in held:
                share = w * h["weight"] / 100
                e = rows.setdefault(h["holding"], {"holding": h["holding"], "name": h["name"], "weight": 0.0, "direct": 0.0, "via": {}})
                e["weight"] += share
                e["via"][sym] = e["via"].get(sym, 0.0) + share
                equity = (h["asset_cat"] or "EC") in EQUITY
                sector = sectors_known.get(h["holding"]) if equity else "Bonds and other"
                sectors[sector or "Unclassified"] = sectors.get(sector or "Unclassified", 0.0) + share
            continue
        if kinds.get(sym) == "fund":
            sector = SECTOR_FUNDS.get(sym, "Funds without look-through")
            sectors[sector] = sectors.get(sector, 0.0) + w
            funds[sym] = {"weight": w, "as_of": None, "holdings": 0}
            continue
        covered += w
        e = rows.setdefault(sym, {"holding": sym, "name": sym, "weight": 0.0, "direct": 0.0, "via": {}})
        e["weight"] += w
        e["direct"] += w
        sector = sectors_known.get(sym) or "Unclassified"
        sectors[sector] = sectors.get(sector, 0.0) + w
    invested = sum(by_symbol.values()) / total * 100
    ordered = sorted(rows.values(), key=lambda e: -e["weight"])
    return {
        "as_of": day,
        "rows": ordered,
        "sectors": dict(sorted(sectors.items(), key=lambda kv: -kv[1])),
        "coverage": covered / invested * 100 if invested else None,
        "funds": funds,
    }


def metrics(out, desk: sqlite3.Connection, kinds: dict[str, str], profiles: dict[str, str]) -> None:
    if not desk.execute("SELECT 1 FROM sqlite_master WHERE name='fund_holdings'").fetchone():
        return
    view = exposures(desk, kinds, profiles)
    if not view["rows"] and not view["sectors"]:
        return
    stale = [f for f, v in view["funds"].items() if v["as_of"] and (date.fromisoformat(out.as_of) - date.fromisoformat(v["as_of"])).days > 150]
    q = "ok" if not stale else "stale"
    out.m("risk.lookthrough", sum(e["weight"] for e in view["rows"][:10]), "pct", window="top10", quality=q)
    out.m("risk.lookthrough_coverage", view["coverage"], "pct", quality=q)
    for e in view["rows"][:TOP_UNDERLYING]:
        out.m("risk.lookthrough", e["weight"], "pct", scope="underlying", scope_id=e["holding"], quality=q)
    for sector, w in view["sectors"].items():
        out.m("risk.sector", w, "pct", scope="sector", scope_id=sector, quality=q)
    out.lookthrough = [
        (out.as_of, e["holding"], e["name"], round(e["weight"], 4), round(e["direct"], 4), json.dumps({k: round(v, 4) for k, v in e["via"].items()}))
        for e in view["rows"]
    ]
    missing = sorted(f for f, v in view["funds"].items() if not v["holdings"] and f not in SECTOR_FUNDS)
    if missing:
        fix = "the weekly look-through job fills them" if os.environ.get("DESK_SEC_USER_AGENT") else key_fix(["DESK_SEC_USER_AGENT"]).rstrip(".")
        out.h("lookthrough", "warn", f"No N-PORT holdings yet for {', '.join(missing)}. Fix: {fix}.")
    elif stale:
        out.h(
            "lookthrough",
            "warn",
            f"N-PORT holdings for {', '.join(stale)} are over 150 days old. Fix: in {JOBS_AT}, run Fund breakdowns.",
        )
    else:
        out.h("lookthrough", "ok", f"Look-through covers {view['coverage']:.0f}% of invested value.")


def overlap(conn: sqlite3.Connection, a: str, b: str) -> float | None:
    def weights(sym: str) -> dict[str, float] | None:
        rows = conn.execute("SELECT holding, weight FROM fund_holdings WHERE fund=?", (sym,)).fetchall()
        if rows:
            return {r["holding"]: r["weight"] for r in rows if r["weight"] > 0}
        return None

    wa, wb = weights(a), weights(b)
    if wa is None and wb is None:
        return None
    wa = wa if wa is not None else {a: 100.0}
    wb = wb if wb is not None else {b: 100.0}
    return sum(min(v, wb[k]) for k, v in wa.items() if k in wb)
