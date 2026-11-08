import csv
import io
import json
import re
import sqlite3
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from statistics import median
from xml.etree import ElementTree
from xml.parsers import expat

from desk.engine import alpaca
from desk.engine.filings import _text
from desk.engine.market import ProviderError, trading_day
from desk.engine.research import SEC_GAP, sec_agent
from desk.engine.universe import BENCHMARK, CAP_MAX, CAP_MIN, DOLLAR_VOLUME_MIN, SEC_FRAME, SHARES_MAX_AGE_DAYS, VOLUME_DAYS
from desk.paper_check import NotPaper

BULK_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{q}_form345.zip"
FIRST_QUARTER = (2016, 1)
QUARTERS_PER_RUN = 8
FORM4_PER_RUN = 200
HISTORY_START = "2016-01-01"
HISTORY_PER_RUN = 300
SHARES_LAG_DAYS = 45
CLUSTER_DAYS = 30
CLUSTER_BUYERS = 2
ROLES = ("director", "officer")
FORMS = {"4", "4/A"}
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
RULE = "Open-market purchases (code P) on Form 4 by directors and officers; known the session after the filing date"


# ---- Parsing ----


def _date(text: str | None) -> str | None:
    s = str(text or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", s)
    if m:
        return date(int(m[3]), MONTHS[m[2].upper()], int(m[1])).isoformat()
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


def _num(text) -> float:
    try:
        return float(str(text or "").replace(",", ""))
    except ValueError:
        return 0.0


def role(text: str) -> str | None:
    low = str(text or "").lower()
    hits = [r for r in ROLES if r in low]
    return ",".join(hits) or None


def _tsv(z: zipfile.ZipFile, name: str) -> list[dict]:
    match = next((n for n in z.namelist() if n.upper().endswith(name.upper())), None)
    if match is None:
        return []
    with z.open(match) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE))


def parse_bulk(blob: bytes) -> list[tuple]:
    z = zipfile.ZipFile(io.BytesIO(blob))
    subs = {r["ACCESSION_NUMBER"]: r for r in _tsv(z, "SUBMISSION.tsv") if str(r.get("DOCUMENT_TYPE") or "").strip() in FORMS}
    owners: dict[str, list[tuple[int, str]]] = {}
    for r in _tsv(z, "REPORTINGOWNER.tsv"):
        who = role(r.get("RPTOWNER_RELATIONSHIP") or "")
        if r["ACCESSION_NUMBER"] in subs and who and str(r.get("RPTOWNERCIK") or "").strip().isdigit():
            owners.setdefault(r["ACCESSION_NUMBER"], []).append((int(r["RPTOWNERCIK"]), who))
    buys: dict[str, list[float]] = {}
    for r in _tsv(z, "NONDERIV_TRANS.tsv"):
        acc = r["ACCESSION_NUMBER"]
        if acc not in owners or str(r.get("TRANS_CODE") or "").strip().upper() != "P" or str(r.get("TRANS_ACQUIRED_DISP_CD") or "").strip().upper() != "A":
            continue
        shares, px = _num(r.get("TRANS_SHARES")), _num(r.get("TRANS_PRICEPERSHARE"))
        if shares > 0 and px > 0:
            got = buys.setdefault(acc, [0.0, 0.0, ""])
            got[0] += shares
            got[1] += shares * px
            got[2] = max(got[2], _date(r.get("TRANS_DATE")) or "")
    rows = []
    for acc, (shares, usd, traded) in buys.items():
        s = subs[acc]
        symbol = str(s.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
        filed = _date(s.get("FILING_DATE"))
        if not symbol or not filed or not str(s.get("ISSUERCIK") or "").strip().isdigit():
            continue
        for owner, who in owners[acc]:
            rows.append((acc, owner, int(s["ISSUERCIK"]), symbol, traded or filed, filed, round(shares, 4), round(usd, 2), who, "bulk"))
    return rows


def _x(node, path: str) -> str:
    found = node.find(path) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def _no_dtd(*_):
    raise ValueError("DTDs and entities are not allowed")


def tree(data: bytes) -> ElementTree.Element:
    b = ElementTree.TreeBuilder()
    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = _no_dtd
    p.EntityDeclHandler = _no_dtd
    p.StartElementHandler = b.start
    p.EndElementHandler = b.end
    p.CharacterDataHandler = b.data
    p.Parse(data, True)
    return b.close()


def parse_form4(xml: str, accession: str, filed: str) -> list[tuple]:
    try:
        root = tree(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except (expat.ExpatError, ValueError):
        return []
    if _x(root, "documentType") not in FORMS:
        return []
    cik, symbol = _x(root, "issuer/issuerCik"), _x(root, "issuer/issuerTradingSymbol").upper()
    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        flags = [r for r, tag in (("director", "isDirector"), ("officer", "isOfficer")) if _x(rel, tag).lower() in ("1", "true")]
        oc = _x(o, "reportingOwnerId/rptOwnerCik")
        if flags and oc.isdigit():
            owners.append((int(oc), ",".join(flags)))
    shares = usd = 0.0
    traded = ""
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _x(t, "transactionCoding/transactionCode").upper() != "P" or _x(t, "transactionAmounts/transactionAcquiredDisposedCode/value").upper() != "A":
            continue
        n, px = _num(_x(t, "transactionAmounts/transactionShares/value")), _num(_x(t, "transactionAmounts/transactionPricePerShare/value"))
        if n > 0 and px > 0:
            shares, usd = shares + n, usd + n * px
            traded = max(traded, _date(_x(t, "transactionDate/value")) or "")
    if not owners or not shares or not cik.isdigit() or not symbol:
        return []
    return [(accession, o, int(cik), symbol, traded or filed, filed, round(shares, 4), round(usd, 2), who, "form4") for o, who in owners]


def known_day(filed: str) -> str:
    d = date.fromisoformat(filed) + timedelta(days=1)
    while not trading_day(d):
        d += timedelta(days=1)
    return d.isoformat()


# ---- Fetch ----


def quarters(today: date) -> list[tuple[int, int]]:
    out, (y, q) = [], FIRST_QUARTER
    last = (today.year, (today.month - 1) // 3 + 1)
    while (y, q) < last:
        out.append((y, q))
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def _blob(http, url: str, agent: str) -> bytes | None:
    res = http.get(url, headers={"User-Agent": agent}, timeout=180)
    if res.status_code == 429:
        raise ProviderError("SEC rate limit")
    if res.status_code in (403, 404):
        return None
    if res.status_code != 200:
        raise ProviderError(f"SEC {res.status_code}")
    return res.content


def _store(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany("INSERT OR REPLACE INTO insider_buys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def fetch_bulk(conn: sqlite3.Connection, http, agent: str, *, now: datetime, sleep=time.sleep) -> dict:
    done = {r[0] for r in conn.execute("SELECT quarter FROM insider_quarters")}
    todo = [(y, q) for y, q in quarters(now.date()) if f"{y}Q{q}" not in done][:QUARTERS_PER_RUN]
    got, missing = 0, []
    for y, q in todo:
        blob = _blob(http, BULK_URL.format(year=y, q=q), agent)
        sleep(SEC_GAP)
        if blob is None:
            missing.append(f"{y}Q{q}")
            continue
        rows = parse_bulk(blob)
        with conn:
            _store(conn, rows)
            conn.execute("INSERT OR REPLACE INTO insider_quarters VALUES (?, ?, ?)", (f"{y}Q{q}", now.isoformat(timespec="seconds"), len(rows)))
        got += len(rows)
    return {"quarters": len(todo) - len(missing), "rows": got, "not_published": missing}


def xml_url(url: str) -> str:
    return re.sub(r"/xsl[^/]+/", "/", url or "")


def fetch_form4(conn: sqlite3.Connection, http, agent: str, *, sleep=time.sleep) -> dict:
    seen = {r[0] for r in conn.execute("SELECT DISTINCT accession FROM insider_buys")}
    tried = {r[0] for r in conn.execute("SELECT accession FROM insider_form4_seen")}
    queue = conn.execute(
        "SELECT accession, url, filed_date, filed_at FROM filings_feed WHERE form IN ('4', '4/A') AND url IS NOT NULL ORDER BY filed_at DESC"
    ).fetchall()
    queue = [r for r in queue if r["accession"] not in seen and r["accession"] not in tried][:FORM4_PER_RUN]
    rows = []
    for r in queue:
        body = _text(http, xml_url(r["url"]), agent)
        sleep(SEC_GAP)
        filed = r["filed_date"] or str(r["filed_at"])[:10]
        found = parse_form4(body, r["accession"], filed) if body else []
        rows += found
        with conn:
            conn.execute("INSERT OR REPLACE INTO insider_form4_seen VALUES (?, ?)", (r["accession"], len(found)))
    with conn:
        _store(conn, rows)
    return {"form4": len(queue), "rows": len(rows)}


def frames_since(start: date, today: date) -> list[str]:
    out, y, q = [], start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (today.year, (today.month - 1) // 3 + 1):
        out.append(f"{y}Q{q}")
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def fetch_frames(conn: sqlite3.Connection, http, agent: str, *, now: datetime, sleep=time.sleep) -> int:
    done = {r[0] for r in conn.execute("SELECT frame FROM sec_frames")}
    recent = set(frames_since(now.date() - timedelta(days=200), now.date()))
    rows, fetched = [], 0
    for frame in frames_since(date.fromisoformat(HISTORY_START) - timedelta(days=SHARES_MAX_AGE_DAYS), now.date()):
        if frame in done and frame not in recent:
            continue
        y, q = frame.split("Q")
        body = _get_json(http, SEC_FRAME.format(year=y, q=q), agent) or {}
        sleep(SEC_GAP)
        for r in body.get("data") or []:
            if r.get("cik") and r.get("val") and r.get("end"):
                rows.append((int(r["cik"]), str(r["end"]), float(r["val"]), str(r.get("accn") or ""), now.isoformat(timespec="seconds")))
        conn.execute("INSERT OR REPLACE INTO sec_frames VALUES (?, ?)", (frame, now.isoformat(timespec="seconds")))
        fetched += 1
    with conn:
        conn.executemany("INSERT OR REPLACE INTO sec_shares VALUES (?, ?, ?, ?, ?)", rows)
    return fetched


def _get_json(http, url: str, agent: str) -> dict | None:
    body = _text(http, url, agent)
    return json.loads(body) if body else None


# ---- Names worth prices ----


def clusters(conn: sqlite3.Connection, days: int = CLUSTER_DAYS, buyers: int = CLUSTER_BUYERS) -> dict[str, str]:
    by_sym: dict[str, list[tuple[str, int]]] = {}
    for r in conn.execute("SELECT symbol, filed_date, owner_cik FROM insider_buys WHERE filed_date >= ? ORDER BY symbol, filed_date", (HISTORY_START,)):
        by_sym.setdefault(r[0], []).append((r[1], r[2]))
    out = {}
    for sym, rows in by_sym.items():
        j = 0
        for i, (d, _) in enumerate(rows):
            lo = (date.fromisoformat(d) - timedelta(days=days)).isoformat()
            while rows[j][0] <= lo:
                j += 1
            if len({o for _, o in rows[j : i + 1]}) >= buyers:
                out[sym] = rows[j][0]
                break
    return out


def fetch_history(conn: sqlite3.Connection, http, symbols: list[str], *, now: datetime, sleep=time.sleep) -> dict:
    done = {r[0] for r in conn.execute("SELECT symbol FROM alpaca_history")}
    todo = [s for s in symbols if s not in done][:HISTORY_PER_RUN]
    if not todo:
        return {"symbols": 0, "bars": 0}
    end = (now - timedelta(minutes=alpaca.SIP_DELAY_MIN)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    raw = alpaca.fetch_bars(http, todo, HISTORY_START, end, "raw", sleep=sleep)
    adj = alpaca.fetch_bars(http, todo, HISTORY_START, end, "all", sleep=sleep)
    rows: dict[tuple[str, str], list] = {}
    for sym, bars in raw.items():
        for b in bars:
            rows[(sym, alpaca._day(b["t"]))] = [sym, alpaca._day(b["t"]), b.get("o"), b.get("h"), b.get("l"), float(b["c"]), None, b.get("v"), b.get("vw")]
    for sym, bars in adj.items():
        for b in bars:
            key = (sym, alpaca._day(b["t"]))
            if key in rows:
                rows[key][6] = float(b["c"])
    stamp = now.isoformat(timespec="seconds")
    with conn:
        conn.executemany("INSERT OR IGNORE INTO alpaca_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [tuple(r) for r in rows.values()])
        conn.executemany("INSERT OR REPLACE INTO alpaca_history VALUES (?, ?, ?, ?)", [(s, HISTORY_START, len(raw.get(s, [])), stamp) for s in todo])
    return {"symbols": len(todo), "bars": len(rows), "left": max(0, len([s for s in symbols if s not in done]) - len(todo))}


# ---- Point-in-time small-cap membership ----


def months(conn: sqlite3.Connection, symbols: list[str] | None = None) -> int:
    ciks = {}
    for r in conn.execute("SELECT symbol, issuer_cik, max(filed_date) FROM insider_buys GROUP BY symbol, issuer_cik ORDER BY 3"):
        ciks[r[0]] = r[1]
    shares: dict[int, list[tuple[str, float]]] = {}
    for r in conn.execute("SELECT cik, end, val FROM sec_shares ORDER BY cik, end"):
        shares.setdefault(r[0], []).append((r[1], r[2]))
    rows = []
    for sym in symbols if symbols is not None else sorted(ciks):
        cik = ciks.get(sym)
        if cik is None or cik not in shares:
            continue
        bars = conn.execute("SELECT date, close, volume FROM alpaca_bars WHERE symbol=? ORDER BY date", (sym,)).fetchall()
        last_month = None
        for i, b in enumerate(bars):
            month = b["date"][:7]
            if month == last_month or i < VOLUME_DAYS:
                last_month = month
                continue
            last_month = month
            seen = (date.fromisoformat(b["date"]) - timedelta(days=SHARES_LAG_DAYS)).isoformat()
            known = [(e, v) for e, v in shares[cik] if e <= seen]
            if not known or (date.fromisoformat(seen) - date.fromisoformat(known[-1][0])).days > SHARES_MAX_AGE_DAYS:
                continue
            cap = known[-1][1] * b["close"]
            window = bars[i - VOLUME_DAYS : i]
            dollar = median(w["close"] * (w["volume"] or 0) for w in window)
            if CAP_MIN <= cap <= CAP_MAX and dollar >= DOLLAR_VOLUME_MIN:
                rows.append((sym, month, round(cap, 0), round(dollar, 0)))
    with conn:
        if symbols is None:
            conn.execute("DELETE FROM smallcap_months")
        else:
            conn.executemany("DELETE FROM smallcap_months WHERE symbol=?", [(s,) for s in symbols])
        conn.executemany("INSERT OR REPLACE INTO smallcap_months VALUES (?, ?, ?, ?)", rows)
    return len(rows)


# ---- Nightly job ----


def run(conn: sqlite3.Connection, http, *, now: datetime, sleep=time.sleep) -> dict:
    agent = sec_agent()
    if not agent:
        return {"ok": True, "skipped": "DESK_SEC_USER_AGENT is not set"}
    out: dict = {"ok": True}
    try:
        out["bulk"] = fetch_bulk(conn, http, agent, now=now, sleep=sleep)
        out["live"] = fetch_form4(conn, http, agent, sleep=sleep)
        out["frames"] = fetch_frames(conn, http, agent, now=now, sleep=sleep)
        if alpaca.headers() is not None:
            names = sorted(set(clusters(conn)) | {BENCHMARK})
            out["history"] = fetch_history(conn, http, names, now=now, sleep=sleep)
        else:
            out["history"] = {"skipped": "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set"}
    except (ProviderError, NotPaper) as e:
        out = {"ok": False, "error": str(e), **{k: v for k, v in out.items() if k != "ok"}}
    out["months"] = months(conn)
    out["buys"] = conn.execute("SELECT count(*) FROM insider_buys").fetchone()[0]
    return out
