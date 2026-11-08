import json
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta

from desk.engine.filings import _text
from desk.engine.lane import entry_session
from desk.engine.market import ProviderError
from desk.engine.research import SEC_GAP, SEC_SUBMISSIONS, sec_agent

CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"
SUBMISSIONS_FILE = "https://data.sec.gov/submissions/{name}"
CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)
RELEASE_DAYS = 50
PER_RUN = 300
REFRESH_DAYS = 30
SINCE = "2015-01-01"
MIN_PRICE = 1.0
RULE = "Quarterly diluted EPS (basic if none) as first filed, against the same quarter a year earlier, scaled by the close before the news"


# ---- Parsing ----


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def first_filed(body: dict) -> list[dict]:
    units = (body or {}).get("units") or {}
    facts = units.get("USD/shares") or next(iter(units.values()), [])
    seen: dict[tuple[str, str], dict] = {}
    for f in facts:
        if str(f.get("form") or "").upper() not in FORMS or not f.get("start") or not f.get("end") or f.get("val") is None or not f.get("filed"):
            continue
        key = (f["start"], f["end"])
        if key not in seen or f["filed"] < seen[key]["filed"]:
            seen[key] = {"start": f["start"], "end": f["end"], "val": float(f["val"]), "filed": f["filed"], "form": f["form"], "accn": f.get("accn")}
    return sorted(seen.values(), key=lambda f: (f["end"], f["start"]))


def quarters(facts: list[dict]) -> dict[str, dict]:
    q = {f["end"]: f for f in facts if QUARTER_DAYS[0] <= _days(f["start"], f["end"]) <= QUARTER_DAYS[1]}
    for fy in (f for f in facts if YEAR_DAYS[0] <= _days(f["start"], f["end"]) <= YEAR_DAYS[1]):
        if fy["end"] in q:
            continue
        inside = [x for x in q.values() if fy["start"] <= x["start"] and x["end"] < fy["end"]]
        if len(inside) == 3:
            q[fy["end"]] = {"start": max(x["end"] for x in inside), "end": fy["end"], "val": fy["val"] - sum(x["val"] for x in inside), "filed": fy["filed"]}
            q[fy["end"]] |= {"form": fy["form"], "accn": fy.get("accn"), "derived": True}
    return q


def releases(body: dict, extra: list[dict] | None = None) -> list[str]:
    out = []
    for block in [((body or {}).get("filings") or {}).get("recent") or {}, *(extra or [])]:
        forms, items, stamps, dates = (block.get(k) or [] for k in ("form", "items", "acceptanceDateTime", "filingDate"))
        for i, form in enumerate(forms):
            if str(form).upper() in ("8-K", "8-K/A") and "2.02" in str(items[i] if i < len(items) else ""):
                out.append(str(stamps[i] if i < len(stamps) and stamps[i] else (dates[i] if i < len(dates) else "")))
    return sorted(s for s in out if s)


def _stamp(text: str) -> datetime:
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return t if t.tzinfo else datetime.combine(t.date(), datetime.max.time().replace(microsecond=0), UTC)


def known_for(q: dict, release_times: list[str]) -> tuple[str, str]:
    filed = q["filed"]
    lo = q["end"]
    hits = [r for r in release_times if lo < r[:10] <= filed and _days(r[:10], filed) <= RELEASE_DAYS]
    when = hits[0] if hits else filed
    return entry_session(_stamp(when)).isoformat(), "release" if hits else "filing"


# ---- Fetch ----


def targets(conn: sqlite3.Connection) -> dict[int, str]:
    out: dict[int, str] = {}
    for r in conn.execute("SELECT issuer_cik, symbol, max(filed_date) FROM insider_buys GROUP BY issuer_cik, symbol ORDER BY 3"):
        out[r[0]] = r[1]
    names = {r[0] for r in conn.execute("SELECT symbol FROM alpaca_history")}
    keep = {c: s for c, s in out.items() if s in names}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='universe_daily'").fetchone():
        day = conn.execute("SELECT max(date) FROM universe_daily").fetchone()[0]
        for r in conn.execute("SELECT cik, symbol FROM universe_daily WHERE date=?", (day,)):
            keep.setdefault(r[0], r[1])
    return keep


def _json(http, url: str, agent: str) -> dict | None:
    body = _text(http, url, agent)
    return json.loads(body) if body else None


def fetch(conn: sqlite3.Connection, http, agent: str, *, now: datetime, sleep=time.sleep) -> dict:
    stale = (now - timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds")
    done = {r[0]: r[1] for r in conn.execute("SELECT cik, fetched_at FROM earnings_ciks")}
    want = targets(conn)
    todo = sorted((c for c in want if c not in done or done[c] < stale), key=lambda c: (c in done, done.get(c, ""), c))[:PER_RUN]
    facts_n = releases_n = 0
    for cik in todo:
        body = None
        for concept in CONCEPTS:
            body = _json(http, CONCEPT_URL.format(cik=cik, concept=concept), agent)
            sleep(SEC_GAP)
            if body:
                break
        facts = first_filed(body or {})
        sub = _json(http, SEC_SUBMISSIONS.format(cik=cik), agent) or {}
        sleep(SEC_GAP)
        extra = []
        for f in (sub.get("filings") or {}).get("files") or []:
            if str(f.get("filingTo") or "") >= SINCE and f.get("name"):
                extra.append(_json(http, SUBMISSIONS_FILE.format(name=f["name"]), agent) or {})
                sleep(SEC_GAP)
        times = releases(sub, extra)
        stamp = now.isoformat(timespec="seconds")
        with conn:
            conn.execute("DELETE FROM eps_facts WHERE cik=?", (cik,))
            conn.executemany(
                "INSERT INTO eps_facts VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(cik, f["start"], f["end"], f["val"], f["filed"], f["form"], f.get("accn")) for f in facts],
            )
            conn.execute("DELETE FROM earnings_releases WHERE cik=?", (cik,))
            conn.executemany("INSERT OR IGNORE INTO earnings_releases VALUES (?, ?)", [(cik, t) for t in times])
            conn.execute("INSERT OR REPLACE INTO earnings_ciks VALUES (?, ?, ?, ?, ?)", (cik, want[cik], stamp, len(facts), len(times)))
        facts_n += len(facts)
        releases_n += len(times)
    left = sum(1 for c in want if c not in done) - sum(1 for c in todo if c not in done)
    return {"companies": len(todo), "facts": facts_n, "releases": releases_n, "left": max(0, left)}


# ---- Events ----


def _close_before(conn: sqlite3.Connection, symbol: str, day: str) -> float | None:
    row = conn.execute("SELECT close FROM alpaca_bars WHERE symbol=? AND date<? ORDER BY date DESC LIMIT 1", (symbol, day)).fetchone()
    return float(row[0]) if row and row[0] else None


def build_events(conn: sqlite3.Connection) -> int:
    rows = []
    for c in conn.execute("SELECT cik, symbol FROM earnings_ciks").fetchall():
        cik, sym = c[0], c[1]
        facts = [dict(r) for r in conn.execute("SELECT start, end, val, filed, form, accn FROM eps_facts WHERE cik=? ORDER BY end", (cik,))]
        times = [r[0] for r in conn.execute("SELECT accepted FROM earnings_releases WHERE cik=? ORDER BY accepted", (cik,))]
        q = quarters(facts)
        ends = sorted(q)
        for end in ends:
            if end < SINCE:
                continue
            target = date.fromisoformat(end) - timedelta(days=365)
            prior = next((q[e] for e in ends if abs((date.fromisoformat(e) - target).days) <= 20 and e < end), None)
            if prior is None or prior["filed"] > q[end]["filed"]:
                continue
            known, source = known_for(q[end], times)
            px = _close_before(conn, sym, known)
            if not px or px < MIN_PRICE:
                continue
            surprise = (q[end]["val"] - prior["val"]) / px
            rows.append((sym, cik, end, known, source, round(q[end]["val"], 4), round(prior["val"], 4), round(px, 4), round(surprise, 6)))
    with conn:
        conn.execute("DELETE FROM earnings_events")
        conn.executemany("INSERT OR REPLACE INTO earnings_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def coverage(conn: sqlite3.Connection, limit: int = 20) -> dict:
    names = {r[0]: r[1] for r in conn.execute("SELECT symbol, min(known) FROM earnings_events GROUP BY symbol")}
    want = targets(conn)
    fetched = {r[0] for r in conn.execute("SELECT cik FROM earnings_ciks")}
    spans = {r[0]: r[1] for r in conn.execute("SELECT symbol, max(date) FROM alpaca_bars GROUP BY symbol")}
    ended = [s for s, first in names.items() if spans.get(s) and spans[s] < (date.fromisoformat(first) + timedelta(days=365)).isoformat()]
    unpriced = sorted(s for c, s in want.items() if c in fetched and s not in spans)
    pending = sum(1 for c in want if c not in fetched)
    return {
        "clusters": len(want),
        "priced": len(want) - len(unpriced) - pending,
        "unpriced": len(unpriced),
        "pending": pending,
        "ended_within_a_year": len(ended),
        "unpriced_symbols": unpriced[:limit],
        "events": conn.execute("SELECT count(*) FROM earnings_events").fetchone()[0],
    }


# ---- Nightly job ----


def run(conn: sqlite3.Connection, http, *, now: datetime, sleep=time.sleep) -> dict:
    agent = sec_agent()
    if not agent:
        return {"ok": True, "skipped": "DESK_SEC_USER_AGENT is not set"}
    out: dict = {"ok": True}
    try:
        out["fetch"] = fetch(conn, http, agent, now=now, sleep=sleep)
    except ProviderError as e:
        out = {"ok": False, "error": str(e)}
    out["events"] = build_events(conn)
    return out
