import math
import sqlite3
from datetime import date, timedelta

YIELD = "fund.earnings_yield"
MARGIN = "fund.op_margin"
FEATURES = (YIELD, MARGIN)
COVERAGE = "public_fundamentals"
TABLE = "fundamentals"
LAG_DAYS = 75
SAME_QUARTER_DAYS = 10
YEAR_SPAN = (250, 300)
ENOUGH = 0.9
ODD_YIELD = 0.5
MIN_YEARS = 4.5
SPLIT_MIN = 1.5
TODAYS_SHARES, AS_REPORTED = "todays_shares", "as_reported"
SUMS = ("eps", "revenue", "operating_income")
QUARTER = ("period_end", "reported", *SUMS)

# ---- Trailing four quarters, known from the day the last of them was reported ----


def _day(text: str) -> date:
    return date.fromisoformat(str(text)[:10])


def years(start: str, end: str) -> float:
    return (_day(end) - _day(start)).days / 365.25


def merged(quarters: list[dict]) -> list[dict]:
    out: list[dict] = []
    for q in sorted((q for q in quarters if q.get("period_end")), key=lambda q: q["period_end"]):
        if out and (_day(q["period_end"]) - _day(out[-1]["period_end"])).days <= SAME_QUARTER_DAYS:
            out[-1] = {k: out[-1].get(k) if out[-1].get(k) is not None else q.get(k) for k in {*out[-1], *q}}
        else:
            out.append(dict(q))
    return out


def known(q: dict) -> tuple[str, bool]:
    if q.get("reported"):
        return str(q["reported"])[:10], False
    return (_day(q["period_end"]) + timedelta(days=LAG_DAYS)).isoformat(), True


def trailing(quarters: list[dict]) -> list[dict]:
    qs = merged(quarters)
    out: dict[str, dict] = {}
    last = ""
    for n in range(3, len(qs)):
        four = qs[n - 3 : n + 1]
        if not YEAR_SPAN[0] <= (_day(four[-1]["period_end"]) - _day(four[0]["period_end"])).days <= YEAR_SPAN[1]:
            continue
        days = [known(q) for q in four]
        day = last = max(last, max(d for d, _ in days))
        total = {k: sum(q[k] for q in four) if all(q.get(k) is not None for q in four) else None for k in SUMS}
        margin = total["operating_income"] / total["revenue"] if total["operating_income"] is not None and (total["revenue"] or 0) > 0 else None
        if total["eps"] is None and margin is None:
            continue
        out[day] = {"known": day, "eps": total["eps"], "margin": margin, "lagged": days[-1][1]}
    return [out[d] for d in sorted(out)]


# ---- The close on a day in the share count the earnings are quoted in ----


def split_closes(conn: sqlite3.Connection, symbol: str, days: list[str], basis: str) -> dict[str, float]:
    want = sorted(set(days), reverse=True)
    out: dict[str, float] = {}
    factor, k = 1.0, 0
    for day, close, split in conn.execute("SELECT date, close, split_factor FROM price_bars WHERE symbol=? ORDER BY date DESC", (symbol,)):
        while k < len(want) and want[k] >= day:
            if close:
                out[want[k]] = close / factor
            k += 1
        if k == len(want):
            break
        if day <= basis:
            factor *= split or 1.0
    return out


# ---- Which share count the source quotes old EPS in, read off the splits themselves ----


def splits(conn: sqlite3.Connection, symbol: str, basis: str) -> list[tuple[str, float]]:
    q = "SELECT date, split_factor FROM price_bars WHERE symbol=? AND split_factor IS NOT NULL AND split_factor != 1 AND date <= ? ORDER BY date"
    return [(r[0], float(r[1])) for r in conn.execute(q, (symbol, basis)) if r[1] and r[1] > 0]


def split_votes(quarters: list[dict], cuts: list[tuple[str, float]]) -> tuple[int, int]:
    qs = [q for q in merged(quarters) if q.get("eps") is not None]
    days = [known(q)[0] for q in qs]
    today = first = 0
    for day, factor in cuts:
        n = next((i for i, d in enumerate(days) if d > day), None)
        if n is None or n < 4 or 1 / SPLIT_MIN < factor < SPLIT_MIN or qs[n]["eps"] <= 0 or qs[n - 4]["eps"] <= 0:
            continue
        ratio = qs[n - 4]["eps"] / qs[n]["eps"]
        if abs(math.log(ratio)) <= abs(math.log(ratio / factor)):
            today += 1
        else:
            first += 1
    return today, first


def restated(quarters: list[dict], cuts: list[tuple[str, float]]) -> list[dict]:
    out = []
    for q in quarters:
        if q.get("eps") is None or not q.get("period_end"):
            out.append(q)
            continue
        day = known(q)[0]
        out.append(q | {"eps": q["eps"] / math.prod(f for d, f in cuts if d > day)})
    return out


# ---- Rows and coverage for the lab export (public list names only) ----


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None


def quarter_starts(first: str, last: str) -> list[str]:
    out, d = [first], _day(first)
    y, m = d.year, (d.month - 1) // 3 * 3 + 1
    while True:
        y, m = (y + 1, 1) if m == 10 else (y, m + 3)
        day = date(y, m, 1).isoformat()
        if day > last:
            return out
        out.append(day)


def first_covered(firsts: dict[str, str], spans: dict[str, tuple[str, str]], tests_from: str, end: str) -> str | None:
    for day in quarter_starts(tests_from, end):
        live = [s for s, (a, b) in spans.items() if a <= day <= b]
        if live and sum(1 for s in live if firsts.get(s, "9") <= day) >= ENOUGH * len(live):
            return day
    return None


def build(desk: sqlite3.Connection, public, spans: dict[str, tuple[str, str]], tests_from: str | None) -> tuple[list[tuple], dict | None]:
    from desk.engine.backfill import TICKER

    names = sorted(s for s in public if s in spans)
    if not names or not _has(desk, "av_quarters") or not _has(desk, "av_fetches"):
        return [], None
    fetched = {r[0]: str(r[1])[:10] for r in desk.execute("SELECT symbol, fetched_at FROM av_fetches")}
    loaded: dict[str, tuple[list[dict], list[tuple[str, float]]]] = {}
    today = first = 0
    for sym in names:
        if sym not in fetched:
            continue
        asked = desk.execute("SELECT period_end, reported, eps, revenue, operating_income FROM av_quarters WHERE symbol=? ORDER BY period_end", (sym,))
        quarters = [dict(zip(QUARTER, r, strict=True)) for r in asked]
        cuts = splits(desk, sym, fetched[sym])
        loaded[sym] = (quarters, cuts)
        a, b = split_votes(quarters, cuts)
        today, first = today + a, first + b
    basis = AS_REPORTED if first > today else TODAYS_SHARES
    rows: list[tuple] = []
    firsts: dict[str, dict[str, str]] = {YIELD: {}, MARGIN: {}}
    lagged = odd = 0
    for sym, (quarters, cuts) in loaded.items():
        made = trailing(restated(quarters, cuts) if basis == AS_REPORTED else quarters)
        closes = split_closes(desk, sym, [r["known"] for r in made if r["eps"] is not None], fetched[sym])
        for r in made:
            px = closes.get(r["known"])
            ey = r["eps"] / px if r["eps"] is not None and px else None
            if ey is not None and abs(ey) > ODD_YIELD:
                ey, odd = None, odd + 1
            if ey is None and r["margin"] is None:
                continue
            lagged += int(r["lagged"])
            rows.append((sym, r["known"], ey, r["margin"]))
            for key, x in ((YIELD, ey), (MARGIN, r["margin"])):
                if x is not None:
                    firsts[key].setdefault(sym, r["known"])
    listed = {s: spans[s] for s in names}
    end = max(b for _, b in listed.values())
    start = max(str(tests_from or ""), min(a for a, _ in listed.values()))
    cover = {
        "listed": len(names),
        "asked": sum(1 for s in names if s in fetched),
        "loading": sum(1 for s in names if s not in fetched and TICKER.match(s)),
        "lagged": lagged,
        "odd": odd,
        "eps_basis": basis,
        "split_votes": [today, first],
    }
    for key in FEATURES:
        cover[key] = {"have": len(firsts[key]), "from": first_covered(firsts[key], listed, start, end)}
    return rows, cover
