import csv
import io
import re
import sqlite3
import time
import zipfile
from datetime import UTC, date, datetime, timedelta

from desk.engine import NO_SEC, backfill, skip
from desk.engine.market import ProviderError
from desk.engine.research import SEC_GAP, _get, sec_agent, sec_ciks

FRAME = "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY{year}Q{q}I.json"
FRAMES = ((2010, 3), (2010, 4), (2011, 1), (2011, 2))
FILING = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}"
TIINGO_TICKERS = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
AS_OF = "2011-06-30"
TESTS_FROM = "2012-01-03"
SIZE = 200
SMALLER = 150
ROOM = 220
ENOUGH_PCT = 90.0
FLOAT_MIN, FLOAT_MAX = 1e9, 7e11
FRESH_DAYS = 6
TRADING_DAYS = 10
PRICED, LATE, MISSING, NO_TICKER, UNASKED = "priced", "late", "missing", "no_ticker", "unasked"
SEC_LIST, FILING_PAGE, FILING_FILE = "sec_list", "filing_page", "filing_file"
PAGE = "R1.htm"
PAGE_SYMBOL = re.compile(r"Trading Symbol(?:(?!</tr>).)*?<td[^>]*>\s*([A-Za-z]{1,5}(?:[.\-][A-Za-z])?)\s*<", re.S | re.I)
FILE_SYMBOL = re.compile(r"^([a-z]{1,5})-\d{8}\.xml$", re.I)
GIVE_UP = ("rate limit", "did not answer")
NOT_RUN = "The public stock list has not been built yet."

# ---- The 200 largest companies of mid-2011 ----


def _reach(who: str, fn):
    try:
        return fn()
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        raise ProviderError(f"{who} did not answer") from e


def largest(http, agent: str, sleep=time.sleep, size: int = SIZE) -> list[dict]:
    mid = date.fromisoformat(AS_OF)
    best: dict[int, dict] = {}
    for year, q in FRAMES:
        body = _reach("The SEC", lambda y=year, n=q: _get(http, FRAME.format(year=y, q=n), "SEC", headers={"User-Agent": agent})) or {}
        sleep(SEC_GAP)
        for r in body.get("data") or []:
            try:
                cik, val, end = int(r["cik"]), float(r["val"]), str(r["end"])[:10]
                gap = abs((date.fromisoformat(end) - mid).days)
            except (KeyError, TypeError, ValueError):
                continue
            if not FLOAT_MIN <= val <= FLOAT_MAX:
                continue
            if cik not in best or gap < best[cik]["gap"]:
                best[cik] = {
                    "cik": cik,
                    "name": str(r.get("entityName") or cik),
                    "float_usd": val,
                    "float_at": end,
                    "accn": str(r.get("accn") or ""),
                    "gap": gap,
                }
    if not best:
        raise ProviderError("The SEC has no public float figures for 2011")
    ranked = sorted(best.values(), key=lambda r: (-r["float_usd"], r["cik"]))[:size]
    return [{k: v for k, v in r.items() if k != "gap"} | {"rank": i} for i, r in enumerate(ranked, 1)]


# ---- Tickers ----


def tiingo_listing(http) -> dict[str, list[tuple[str, str]]]:
    res = _reach("Tiingo's ticker list", lambda: http.get(TIINGO_TICKERS, timeout=120))
    if res.status_code != 200:
        raise ProviderError(f"Tiingo's ticker list answered {res.status_code}")

    def rows() -> list[dict]:
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ProviderError("Tiingo's ticker list has no table in it")
            return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8", "replace"))))

    out: dict[str, list[tuple[str, str]]] = {}
    for r in _reach("Tiingo's ticker list", rows):
        start, end = (r.get("startDate") or "")[:10], (r.get("endDate") or "")[:10]
        if (r.get("assetType") or "").lower() != "stock" or (r.get("priceCurrency") or "").upper() != "USD" or not start or not end or not r.get("ticker"):
            continue
        out.setdefault(shape(r["ticker"]), []).append((start, end))
    if not out:
        raise ProviderError("Tiingo's ticker list is empty")
    return out


def shape(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def filing_symbols(http, agent: str, cik: int, accn: str, sleep=time.sleep) -> list[tuple[str, str]]:
    acc = accn.replace("-", "")
    if not acc:
        return []
    body = _get(http, FILING.format(cik=cik, acc=acc, name="index.json"), "SEC", headers={"User-Agent": agent}) or {}
    sleep(SEC_GAP)
    files = [str(i.get("name") or "") for i in (body.get("directory") or {}).get("item") or []]
    out = []
    if PAGE in files:
        res = http.get(FILING.format(cik=cik, acc=acc, name=PAGE), headers={"User-Agent": agent}, timeout=60)
        sleep(SEC_GAP)
        if res.status_code == 429:
            raise ProviderError("SEC rate limit")
        found = PAGE_SYMBOL.search(res.text) if res.status_code == 200 else None
        if found:
            out.append((shape(found.group(1)), FILING_PAGE))
    for name in files:
        found = FILE_SYMBOL.match(name)
        if found:
            out.append((shape(found.group(1)), FILING_FILE))
            break
    return out


def pick(listing: dict[str, list[tuple[str, str]]], candidates: list[tuple[str, str]]) -> dict:
    spans = [(start, sym, source, end) for sym, source in candidates for start, end in listing.get(sym, ())]
    covering = sorted(s for s in spans if s[0] <= TESTS_FROM <= s[3])
    if covering:
        start, sym, source, end = covering[0]
        return {"symbol": sym, "source": source, "first_bar": start, "last_bar": end, "state": PRICED}
    if spans:
        start, sym, source, end = max(spans, key=lambda s: s[3])
        return {"symbol": sym, "source": source, "first_bar": start, "last_bar": end, "state": LATE}
    if candidates:
        return {"symbol": candidates[0][0], "source": candidates[0][1], "first_bar": None, "last_bar": None, "state": MISSING}
    return {"symbol": None, "source": None, "first_bar": None, "last_bar": None, "state": NO_TICKER}


def resolve(http, agent: str, top: list[dict], listing: dict, by_cik: dict[int, list[str]], sleep=time.sleep) -> list[dict]:
    newest = max(end for spans in listing.values() for _, end in spans)
    live = (date.fromisoformat(newest) - timedelta(days=TRADING_DAYS)).isoformat()
    out, asking = [], True
    for row in top:
        known = [(s, SEC_LIST) for s in sorted(by_cik.get(row["cik"], ()), key=lambda s: (len(s), s))]
        got = pick(listing, known)
        if got["state"] != PRICED and asking:
            try:
                filed = _reach("The SEC", lambda r=row: filing_symbols(http, agent, r["cik"], r["accn"], sleep))
                got = pick(listing, known + [c for c in filed if c not in known])
            except ProviderError as e:
                asking = not any(w in str(e) for w in GIVE_UP)
        if got["state"] != PRICED and not asking:
            got = got | {"state": UNASKED}
        out.append(row | got | {"trading": int(got["state"] == PRICED and got["last_bar"] >= live)})
    return out


# ---- Store and report ----


def store(conn: sqlite3.Connection, rows: list[dict], now: datetime) -> None:
    stamp = now.isoformat(timespec="seconds")
    cols = ("rank", "cik", "name", "float_usd", "float_at", "accn", "symbol", "source", "first_bar", "last_bar", "state", "trading")
    with conn:
        conn.execute("DELETE FROM public_stocks")
        conn.executemany(
            f"INSERT INTO public_stocks ({', '.join(cols)}, fetched_at) VALUES ({', '.join('?' * len(cols))}, ?)",
            [(*(r[c] for c in cols), stamp) for r in rows],
        )
        conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('sec', ?, NULL, 1)", (stamp,))


def names(conn: sqlite3.Connection) -> list[dict]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='public_stocks'").fetchone() is None:
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM public_stocks ORDER BY rank")]


def fresh(conn: sqlite3.Connection, now: datetime) -> bool:
    rows = names(conn)
    if not rows or any(r["state"] == UNASKED for r in rows):
        return False
    return rows[0]["fetched_at"] >= (now - timedelta(days=FRESH_DAYS)).isoformat(timespec="seconds")


def room(conn: sqlite3.Connection, rows: list[dict], now: datetime) -> dict:
    limit, used = backfill.limits()["month_symbols"], backfill.usage(conn, now)["month_symbols"]
    asked = backfill.month_symbols(conn, now)
    left = max(0, limit - used)
    return {
        "limit": limit,
        "used": used,
        "left": left,
        "new_names": sum(1 for r in rows if r["state"] == PRICED and r["symbol"] not in asked),
        "size": SIZE if left >= ROOM else SMALLER,
    }


def summary(conn: sqlite3.Connection, rows: list[dict], now: datetime) -> dict:
    priced = [r for r in rows if r["state"] == PRICED]

    def label(r: dict) -> str:
        return f"{r['name']} ({r['symbol']})" if r["symbol"] else r["name"]

    out = {
        "as_of": AS_OF,
        "tests_from": TESTS_FROM,
        "wanted": SIZE,
        "listed": len(rows),
        "with_ticker": sum(1 for r in rows if r["symbol"]),
        "priced": len(priced),
        "priced_pct": round(100 * len(priced) / len(rows), 1) if rows else 0.0,
        "still_trading": sum(1 for r in priced if r["trading"]),
        "stopped": sum(1 for r in priced if not r["trading"]),
        "from_sec_list": sum(1 for r in priced if r["source"] == SEC_LIST),
        "from_filing_page": sum(1 for r in priced if r["source"] == FILING_PAGE),
        "from_filing_file": sum(1 for r in priced if r["source"] == FILING_FILE),
        "no_ticker": [label(r) for r in rows if r["state"] == NO_TICKER],
        "not_at_tiingo": [label(r) for r in rows if r["state"] == MISSING],
        "history_too_short": [label(r) for r in rows if r["state"] == LATE],
        "not_asked": [label(r) for r in rows if r["state"] == UNASKED],
        "check_by_eye": [label(r) for r in priced if r["source"] != SEC_LIST and r["trading"]],
        "tiingo": room(conn, rows, now),
    }
    out["enough"] = out["priced_pct"] >= ENOUGH_PCT
    return out | {"detail": words(out)}


def words(s: dict) -> str:
    if not s["listed"]:
        return NOT_RUN
    head = f"Of the {s['listed']} largest US companies of mid-2011, {s['with_ticker']} have a ticker"
    parts = [f"{head} and Tiingo prices {s['priced']} of them from January 2012 ({s['priced_pct']:g}%)."]
    if s["listed"] < s["wanted"]:
        parts.append(f"The SEC lists only {s['listed']} of the {s['wanted']} asked for.")
    if s["stopped"]:
        parts.append(f"{s['stopped']} of the priced names have since stopped trading.")
    if s["not_asked"]:
        parts.append(f"The SEC did not answer for {len(s['not_asked'])}; the next run tries them again.")
    parts.append("That is enough to test on." if s["enough"] else "That is under 90%, so stock screens stay research only.")
    t = s["tiingo"]
    parts.append(f"Tiingo has room for {t['left']} more names this month and the list needs {t['new_names']}.")
    return " ".join(parts)


# ---- Job ----


def run(conn: sqlite3.Connection, http, *, now: datetime | None = None, sleep=time.sleep) -> dict:
    now = now or datetime.now(UTC)
    agent = sec_agent()
    if not agent:
        return skip(NO_SEC)
    if fresh(conn, now):
        return {"ok": True, "fresh": True} | summary(conn, names(conn), now)
    try:
        top = largest(http, agent, sleep)
        listing = tiingo_listing(http)
        by_cik: dict[int, list[str]] = {}
        for symbol, cik in _reach("The SEC", lambda: sec_ciks(conn, http, agent, now, sleep)).items():
            by_cik.setdefault(cik, []).append(shape(symbol))
        rows = resolve(http, agent, top, listing, by_cik, sleep)
    except ProviderError as e:
        return {"ok": False, "error": f"{e}. The public stock list was left as it was."}
    store(conn, rows, now)
    return {"ok": True, "fresh": False} | summary(conn, names(conn), now)


# ---- Seam for the API ----


def view(conn: sqlite3.Connection | None, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = names(conn) if conn is not None else []
    if not rows:
        return {"as_of": AS_OF, "tests_from": TESTS_FROM, "wanted": SIZE, "listed": 0, "detail": NOT_RUN, "fetched_at": None, "names": []}
    keep = ("rank", "name", "cik", "float_usd", "float_at", "symbol", "source", "first_bar", "last_bar", "state", "trading")
    return summary(conn, rows, now) | {"fetched_at": rows[0]["fetched_at"], "names": [{k: r[k] for k in keep} for r in rows]}
