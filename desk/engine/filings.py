import html
import json
import re
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import JOBS_AT, schema
from desk.engine.market import ProviderError
from desk.engine.research import SEC_ARCHIVE, SEC_GAP, SEC_SUBMISSIONS, sec_agent
from desk.engine.universe import members

DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{q}/master.{stamp}.idx"
FORMS = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "S-1", "S-1/A", "S-3", "S-3/A", "4", "4/A"}
DILUTION = ("S-1", "S-3", "424B")
FIRST_DAYS = 3
MAX_DAYS = 10
EXCERPT_CHARS = 12000
EXCERPTS_PER_RUN = 120
ITEM_WEIGHT = {
    "1.01": 6,
    "1.02": 5,
    "1.03": 10,
    "2.01": 8,
    "2.02": 7,
    "2.03": 6,
    "2.04": 6,
    "2.05": 6,
    "2.06": 7,
    "3.01": 9,
    "3.02": 8,
    "3.03": 6,
    "4.01": 6,
    "4.02": 9,
    "5.01": 7,
    "5.02": 5,
    "5.03": 2,
    "5.07": 2,
    "7.01": 3,
    "8.01": 3,
    "9.01": 0,
}
FORM_WEIGHT = {"10-K": 5, "10-Q": 4, "S-1": 6, "S-3": 6, "424B": 6, "4": 3, "8-K": 2}
EVENT_TYPES = (
    "earnings",
    "guidance",
    "dilution",
    "financing",
    "insider_buy",
    "insider_sell",
    "merger_acquisition",
    "contract",
    "legal",
    "management_change",
    "restatement",
    "going_concern",
    "bankruptcy",
    "delisting",
    "buyback",
    "dividend",
    "product",
    "regulatory",
    "other",
)
RATIONALE_CHARS = 280


class NotReady(RuntimeError):
    pass


def wanted(form: str) -> bool:
    f = form.strip().upper()
    return f in FORMS or f.startswith("424B")


def materiality(form: str, items: list[str]) -> int:
    f = form.upper().removesuffix("/A")
    base = next((w for k, w in FORM_WEIGHT.items() if f == k or f.startswith(k)), 1)
    if f == "8-K":
        base = max([base] + [ITEM_WEIGHT.get(i, 3) for i in items])
    return base - (1 if form.upper().endswith("/A") else 0)


# ---- EDGAR daily index ----


def index_url(day: date) -> str:
    return DAILY_INDEX.format(year=day.year, q=(day.month - 1) // 3 + 1, stamp=day.strftime("%Y%m%d"))


def parse_index(text: str) -> list[tuple[int, str, str, str]]:
    out = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        cik, _, form, _, path = (p.strip() for p in parts)
        m = re.search(r"(\d{10}-\d{2}-\d{6})", path)
        if m and wanted(form):
            out.append((int(cik), form.upper(), m[1], path))
    return out


def _text(http, url: str, agent: str) -> str | None:
    res = http.get(url, headers={"User-Agent": agent}, timeout=60)
    if res.status_code == 429:
        raise ProviderError("SEC rate limit")
    if res.status_code in (403, 404):
        return None
    if res.status_code != 200:
        raise ProviderError(f"SEC {res.status_code}")
    return res.text


def _json(http, url: str, agent: str) -> dict | None:
    body = _text(http, url, agent)
    return json.loads(body) if body else None


def to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw or "")
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# ---- Fetch ----


def _days(conn: sqlite3.Connection, today: date) -> list[date]:
    last = conn.execute("SELECT max(day) FROM filing_days WHERE ok=1").fetchone()[0]
    start = date.fromisoformat(last) + timedelta(days=1) if last else today - timedelta(days=FIRST_DAYS)
    start = max(start, today - timedelta(days=MAX_DAYS))
    out, d = [], start
    while d < today:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _details(body: dict, accessions: set[str]) -> dict[str, dict]:
    recent = ((body or {}).get("filings") or {}).get("recent") or {}
    keys = ("accessionNumber", "acceptanceDateTime", "filingDate", "form", "items", "primaryDocument")
    cols = {k: recent.get(k) or [] for k in keys}
    out = {}
    for i, acc in enumerate(cols["accessionNumber"]):
        if acc in accessions:
            out[acc] = {k: (cols[k][i] if i < len(cols[k]) else "") for k in keys}
    return out


def run(conn: sqlite3.Connection, http, *, now: datetime | None = None, sleep=time.sleep, excerpts: int = EXCERPTS_PER_RUN) -> dict:
    now = now or datetime.now(UTC)
    agent = sec_agent()
    if not agent:
        return {"ok": True, "skipped": "DESK_SEC_USER_AGENT is not set"}
    names = {m["cik"]: m for m in members(conn)}
    if not names:
        return {"ok": True, "skipped": "No universe yet; the universe job builds it"}
    stamp = now.isoformat(timespec="seconds")
    found: dict[int, dict[str, str]] = {}
    days_done, errors = [], []
    for day in _days(conn, now.date()):
        try:
            text = _text(http, index_url(day), agent)
            sleep(SEC_GAP)
        except ProviderError as e:
            errors.append(f"{day}: {e}")
            break
        for cik, form, acc, _ in parse_index(text or ""):
            if cik in names:
                found.setdefault(cik, {})[acc] = form
        days_done.append(day.isoformat())
    have = {r[0] for r in conn.execute("SELECT accession FROM filings_feed")}
    rows = []
    for cik, accs in sorted(found.items()):
        new = {a for a in accs if a not in have}
        if not new:
            continue
        try:
            body = _json(http, SEC_SUBMISSIONS.format(cik=cik), agent) or {}
            sleep(SEC_GAP)
        except ProviderError as e:
            errors.append(f"CIK {cik}: {e}")
            if "rate limit" in str(e):
                break
            continue
        m = names[cik]
        sector = str(body.get("sicDescription") or "") or None
        info = _details(body, new)
        for acc in sorted(new):
            d = info.get(acc, {})
            form = str(d.get("form") or accs[acc]).upper()
            items = [i.strip() for i in str(d.get("items") or "").split(",") if i.strip()]
            doc = str(d.get("primaryDocument") or "")
            url = SEC_ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=doc) if doc else None
            filed_at = str(d.get("acceptanceDateTime") or d.get("filingDate") or "")
            rows.append(
                (
                    acc,
                    cik,
                    m["symbol"],
                    form,
                    json.dumps(items),
                    filed_at,
                    str(d.get("filingDate") or ""),
                    url,
                    m["name"],
                    sector,
                    materiality(form, items),
                    stamp,
                )
            )
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO filings_feed (accession, cik, symbol, form, items, filed_at, filed_date, url, company, sector, materiality, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.executemany("INSERT OR REPLACE INTO filing_days (day, ok, fetched_at) VALUES (?, 1, ?)", [(d, stamp) for d in days_done])
    pulled = _excerpts(conn, http, agent, excerpts, sleep, errors)
    return {"ok": not errors, "days": days_done, "filings": len(rows), "excerpts": pulled, "errors": errors}


def _excerpts(conn: sqlite3.Connection, http, agent: str, cap: int, sleep, errors: list[str]) -> int:
    todo = conn.execute(
        "SELECT accession, url FROM filings_feed WHERE excerpt IS NULL AND url IS NOT NULL AND excerpt_tries < 3 "
        "AND accession NOT IN (SELECT accession FROM filing_signals) ORDER BY materiality DESC, filed_at DESC LIMIT ?",
        (cap,),
    ).fetchall()
    pulled = 0
    for r in todo:
        try:
            raw = _text(http, r["url"], agent)
            sleep(SEC_GAP)
        except ProviderError as e:
            errors.append(f"{r['accession']}: {e}")
            if "rate limit" in str(e):
                break
            raw = None
        text = to_text(raw)[:EXCERPT_CHARS] if raw else None
        with conn:
            conn.execute("UPDATE filings_feed SET excerpt=?, excerpt_tries=excerpt_tries+1 WHERE accession=?", (text or None, r["accession"]))
        pulled += int(bool(text))
    return pulled


# ---- The scorer's seam ----


def _open(cfg: Config, readonly: bool) -> sqlite3.Connection:
    if not cfg.desk_db.exists():
        raise NotReady("desk.db does not exist yet")
    conn = connect(cfg.desk_db, readonly=readonly)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='filings_feed'").fetchone() is None:
        conn.close()
        raise NotReady(f"No filings have been read yet. In {JOBS_AT}, run Filings.")
    return conn


def pending(cfg: Config, limit: int) -> list[dict]:
    conn = _open(cfg, readonly=True)
    try:
        caps = {m["symbol"]: m["market_cap"] for m in members(conn)}
        rows = conn.execute(
            "SELECT * FROM filings_feed WHERE excerpt IS NOT NULL AND accession NOT IN (SELECT accession FROM filing_signals) "
            "ORDER BY materiality DESC, filed_at DESC LIMIT ?",
            (max(0, int(limit)),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "accession": r["accession"],
            "symbol": r["symbol"],
            "form": r["form"],
            "items": json.loads(r["items"] or "[]"),
            "filed_at": r["filed_at"],
            "url": r["url"],
            "excerpt": r["excerpt"],
            "company": {"name": r["company"], "market_cap": caps.get(r["symbol"]), "sector": r["sector"]},
        }
        for r in rows
    ]


def _check(result: dict) -> tuple:
    d, c = result.get("direction"), result.get("confidence")
    if isinstance(d, bool) or not isinstance(d, int) or not -2 <= d <= 2:
        raise ValueError("direction must be a whole number from -2 to 2")
    if isinstance(c, bool) or not isinstance(c, int | float) or not 0 <= c <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if result.get("event_type") not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {', '.join(EVENT_TYPES)}")
    h = result.get("horizon_days")
    if isinstance(h, bool) or not isinstance(h, int) or h < 1:
        raise ValueError("horizon_days must be a whole number of days, at least 1")
    model, scored_at = str(result.get("model") or ""), str(result.get("scored_at") or "")
    if not model or not scored_at:
        raise ValueError("model and scored_at are required")
    datetime.fromisoformat(scored_at.replace("Z", "+00:00"))
    cited = [str(x) for x in result.get("numbers_cited") or []]
    rationale = str(result.get("rationale") or "")[:RATIONALE_CHARS]
    return d, float(c), result["event_type"], h, rationale, json.dumps(cited), model, scored_at, str(result.get("run_id") or "")


def record(cfg: Config, accession: str, result: dict) -> None:
    values = _check(result)
    conn = _open(cfg, readonly=False)
    try:
        schema.apply(conn)
        row = conn.execute("SELECT symbol, filed_at, form, items FROM filings_feed WHERE accession=?", (accession,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown accession {accession}")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO filing_signals (accession, symbol, filed_at, form, items, direction, confidence, event_type, horizon_days, rationale, "
                "numbers_cited, model, scored_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (accession, row["symbol"], row["filed_at"], row["form"], row["items"], *values),
            )
    finally:
        conn.close()


def lane_start(conn: sqlite3.Connection) -> str | None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='filing_signals'").fetchone() is None:
        return None
    return conn.execute("SELECT min(scored_at) FROM filing_signals").fetchone()[0]
