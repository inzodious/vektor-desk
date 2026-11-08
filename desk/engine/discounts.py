import json
import math
import sqlite3
from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine.backfill import add_symbols

QUALITY = ("VOO", "VTI", "QQQ", "VXUS", "QUAL", "SCHD", "VGT", "FTEC", "SMH", "MSFT", "AAPL", "GOOGL", "AMZN", "NVDA", "ASML", "COST", "V", "JPM")
LISTS = ("held", "watchlist", "quality")
HIGH_DAYS = 252
Z_DAYS = 252
MIN_DAYS = 60
Z_HIT = -2.0
MOVE_HIT = -1.0
STEPS = (-10.0, -20.0, -30.0)
MAX_HITS = 10
PENDING_DAYS = 5
VAL_YEARS = 5
VERDICTS = ("buy", "wait", "avoid")
CASE_MAX = 400
RISKS_MAX = 240
RULE = (
    f"After the close: a down day of {abs(Z_HIT):.0f}+ standard deviations of its last year and {abs(MOVE_HIT):.0f}% or more, "
    "or a first close 10, 20 or 30% under its 52-week high"
)


class NotReady(Exception):
    pass


# ---- Prices ----


def series(conn: sqlite3.Connection, symbol: str) -> list[tuple[str, float]]:
    rows = conn.execute("SELECT date, coalesce(adj_close, close), close FROM price_bars WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
    if not rows:
        rows = conn.execute("SELECT date, coalesce(adj_close, close), close FROM alpaca_bars WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
    out = [(r[0], float(r[1])) for r in rows if r[1]]
    scale = float(rows[-1][1]) / float(rows[-1][2]) if rows and rows[-1][2] else 1.0
    last = out[-1][0] if out else ""
    for r in conn.execute("SELECT date, close FROM prices_daily WHERE symbol=? AND date > ? ORDER BY date", (symbol, last)):
        if r[1]:
            out.append((r[0], float(r[1]) * scale))
    return out


# ---- Measures ----


def measures(px: list[tuple[str, float]]) -> dict | None:
    if len(px) < MIN_DAYS:
        return None
    closes = [p for _, p in px]
    rets = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False)]
    today, prior = rets[-1], rets[-Z_DAYS - 1 : -1]
    sd = math.sqrt(sum(r * r for r in prior) / len(prior)) if prior else 0.0
    high = max(closes[-HIGH_DAYS:])
    high_before = max(closes[-HIGH_DAYS - 1 : -1])
    drop = (closes[-1] / high - 1) * 100
    drop_before = (closes[-2] / high_before - 1) * 100
    ret_1y = (closes[-1] / closes[-HIGH_DAYS] - 1) * 100 if len(closes) >= HIGH_DAYS else None
    return {
        "as_of": px[-1][0],
        "price": closes[-1],
        "day_move_pct": today * 100,
        "move_z": today / sd if sd else None,
        "high_52w": high,
        "drop_from_high_pct": drop,
        "drop_before_pct": drop_before,
        "ret_1y_pct": ret_1y,
    }


def reason(m: dict) -> str | None:
    crossed = [s for s in STEPS if m["drop_from_high_pct"] <= s < m["drop_before_pct"]]
    if crossed:
        return f"crossed_{abs(int(min(crossed)))}"
    if m["move_z"] is not None and m["move_z"] <= Z_HIT and m["day_move_pct"] <= MOVE_HIT:
        return "big_down_day"
    return None


def _annual_eps(conn: sqlite3.Connection, symbol: str) -> list[tuple[str, float]]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='fundamentals'").fetchone():
        return []
    out = []
    for r in conn.execute(
        "SELECT start, period_end, coalesce(filed, period_end), value FROM fundamentals WHERE symbol=? AND concept='eps_diluted' ORDER BY 3", (symbol,)
    ):
        if r[0] and 350 <= (date.fromisoformat(r[1]) - date.fromisoformat(r[0])).days <= 380:
            out.append((r[2], float(r[3])))
    return out


def valuation(conn: sqlite3.Connection, symbol: str, px: list[tuple[str, float]]) -> dict:
    cut = (date.fromisoformat(px[-1][0]) - timedelta(days=365 * VAL_YEARS)).isoformat()
    months: dict[str, tuple[str, float]] = {}
    for d, p in px:
        if d >= cut:
            months[d[:7]] = (d, p)
    eps = _annual_eps(conn, symbol)
    stamps = [e[0] for e in eps]
    if eps and eps[-1][1] > 0:
        hist = []
        for d, p in months.values():
            i = bisect_right(stamps, d)
            if i and eps[i - 1][1] > 0:
                hist.append(p / eps[i - 1][1])
        now = px[-1][1] / eps[-1][1]
        metric = "pe_annual"
    else:
        avg = sum(p for _, p in months.values()) / len(months)
        hist = [p / avg - 1 for _, p in months.values()]
        now = px[-1][1] / avg - 1
        metric = "price_vs_5y_avg"
    pctile = sum(1 for h in hist if h <= now) / len(hist) if hist else None
    return {"metric": metric, "value": round(now, 4), "pctile_own": round(pctile, 4) if pctile is not None else None}


# ---- Scan ----


def universe(conn: sqlite3.Connection) -> dict[str, str]:
    out: dict[str, str] = {}
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if day:
        for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0 AND value > 0", (day,)):
            out.setdefault(r[0], "held")
    for r in conn.execute("SELECT symbol FROM market_symbols WHERE role='watch' ORDER BY symbol"):
        out.setdefault(r[0], "watchlist")
    for s in QUALITY:
        out.setdefault(s, "quality")
    return out


def _name(conn: sqlite3.Connection, symbol: str) -> str | None:
    for q in ("SELECT name FROM sym_profiles WHERE symbol=?", "SELECT title FROM sec_tickers WHERE symbol=?"):
        r = conn.execute(q, (symbol,)).fetchone()
        if r and r[0]:
            return r[0]
    return None


def _r(v, n=4):
    return round(v, n) if v is not None else None


def scan(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    names = universe(conn)
    add_symbols(conn, [s for s, lst in names.items() if lst == "quality"], "universe", now=now)
    hits, scanned, short = [], 0, []
    for sym, lst in names.items():
        px = series(conn, sym)
        m = measures(px)
        if m is None:
            short.append(sym)
            continue
        scanned += 1
        why = reason(m)
        if why is None:
            continue
        val = valuation(conn, sym, px)
        numbers = {
            "price": _r(m["price"]),
            "day_move_pct": _r(m["day_move_pct"]),
            "drop_from_high_pct": _r(m["drop_from_high_pct"]),
            "move_z": _r(m["move_z"]),
            "high_52w": _r(m["high_52w"]),
            "ret_1y_pct": _r(m["ret_1y_pct"]),
            "valuation_value": val["value"],
            "valuation_pctile": val["pctile_own"],
        }
        hits.append(
            {
                "signal_id": f"{m['as_of']}-{sym}",
                "as_of": m["as_of"],
                "symbol": sym,
                "name": _name(conn, sym),
                "list": lst,
                "reason": why,
                "price": numbers["price"],
                "drop_from_high_pct": numbers["drop_from_high_pct"],
                "move_z": numbers["move_z"],
                "valuation": val,
                "numbers": numbers,
            }
        )
    hits.sort(key=lambda h: (h["drop_from_high_pct"], LISTS.index(h["list"]), h["symbol"]))
    hits = hits[:MAX_HITS]
    as_of = max((h["as_of"] for h in hits), default=None) or _latest_day(conn)
    stamp = now.isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO discount_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    h["signal_id"],
                    h["as_of"],
                    h["symbol"],
                    h["name"],
                    h["list"],
                    h["reason"],
                    h["price"],
                    h["drop_from_high_pct"],
                    h["move_z"],
                    json.dumps(h["valuation"]),
                    json.dumps(h["numbers"]),
                    stamp,
                )
                for h in hits
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO discount_scans VALUES (?, ?, ?, ?, ?)", (as_of or now.date().isoformat(), stamp, scanned, len(hits), json.dumps(short[:50]))
        )
    return {"ok": True, "as_of": as_of, "scanned": scanned, "hits": len(hits), "short_history": len(short)}


def _latest_day(conn: sqlite3.Connection) -> str | None:
    return conn.execute("SELECT max(date) FROM price_bars").fetchone()[0]


# ---- Seam for the agents ----


def _ready(conn: sqlite3.Connection) -> None:
    if (
        not conn.execute("SELECT 1 FROM sqlite_master WHERE name='discount_scans'").fetchone()
        or not conn.execute("SELECT 1 FROM discount_scans LIMIT 1").fetchone()
    ):
        raise NotReady("The discount scanner has not run yet.")


def _hit(r: sqlite3.Row) -> dict:
    return {
        "signal_id": r["signal_id"],
        "symbol": r["symbol"],
        "name": r["name"],
        "as_of": r["as_of"],
        "list": r["list"],
        "reason": r["reason"],
        "price": r["price"],
        "drop_from_high_pct": r["drop_from_high_pct"],
        "move_z": r["move_z"],
        "valuation": json.loads(r["valuation"]),
        "numbers": json.loads(r["numbers"]),
    }


def pending(cfg: Config, limit: int = MAX_HITS) -> list[dict]:
    if not cfg.desk_db.exists():
        raise NotReady("The engine has not run yet.")
    conn = connect(cfg.desk_db, readonly=True)
    try:
        _ready(conn)
        last = conn.execute("SELECT max(as_of) FROM discount_scans").fetchone()[0]
        cut = (date.fromisoformat(last) - timedelta(days=PENDING_DAYS)).isoformat()
        rows = conn.execute(
            "SELECT * FROM discount_signals WHERE as_of >= ? AND signal_id NOT IN (SELECT signal_id FROM discount_cases) "
            "ORDER BY drop_from_high_pct, as_of DESC, symbol LIMIT ?",
            (cut, max(0, int(limit))),
        ).fetchall()
    finally:
        conn.close()
    return [_hit(r) for r in rows]


def _check(case: dict, numbers: dict) -> list[str]:
    errors = []
    if case.get("verdict") not in VERDICTS:
        errors.append("verdict must be buy, wait or avoid")
    for key, cap in (("case", CASE_MAX), ("risks", RISKS_MAX)):
        if not isinstance(case.get(key), str) or not case[key].strip() or len(case[key]) > cap:
            errors.append(f"{key} must be text of at most {cap} characters")
    conf = case.get("confidence")
    if not isinstance(conf, int | float) or isinstance(conf, bool) or not 0 <= conf <= 1:
        errors.append("confidence must be between 0 and 1")
    h = case.get("horizon_days")
    if not isinstance(h, int) or isinstance(h, bool) or h < 1:
        errors.append("horizon_days must be a whole number of at least 1")
    cited = case.get("numbers_cited")
    if not isinstance(cited, list) or any(c not in numbers for c in cited):
        errors.append("numbers_cited must list keys from the hit's numbers")
    for key in ("model", "written_at"):
        if not isinstance(case.get(key), str) or not case[key]:
            errors.append(f"{key} is required")
    return errors


def record(cfg: Config, signal_id: str, case: dict) -> bool:
    conn = connect(cfg.desk_db)
    try:
        _ready(conn)
        row = conn.execute("SELECT numbers FROM discount_signals WHERE signal_id=?", (signal_id,)).fetchone()
        if row is None:
            raise ValueError(f"no discount signal {signal_id}")
        errors = _check(case or {}, json.loads(row[0]))
        if errors:
            raise ValueError("; ".join(errors))
        with conn:
            n = conn.execute(
                "INSERT OR IGNORE INTO discount_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    signal_id,
                    case["verdict"],
                    case["case"].strip(),
                    case["risks"].strip(),
                    float(case["confidence"]),
                    case["horizon_days"],
                    json.dumps(case["numbers_cited"]),
                    case["model"],
                    case["written_at"],
                    case.get("run_id"),
                ),
            ).rowcount
    finally:
        conn.close()
    return n == 1


# ---- API view ----


def view(conn: sqlite3.Connection | None, days: int = 10) -> dict:
    empty = {"as_of": None, "scanned": 0, "rule": RULE, "rows": [], "note": "The discount scanner runs after the close on weekdays."}
    if conn is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='discount_scans'").fetchone():
        return empty
    scan_row = conn.execute("SELECT * FROM discount_scans ORDER BY as_of DESC LIMIT 1").fetchone()
    if scan_row is None:
        return empty
    cut = (date.fromisoformat(scan_row["as_of"]) - timedelta(days=days)).isoformat()
    cases = {r["signal_id"]: dict(r) for r in conn.execute("SELECT * FROM discount_cases")}
    rows = []
    for r in conn.execute("SELECT * FROM discount_signals WHERE as_of >= ? ORDER BY as_of DESC, drop_from_high_pct", (cut,)):
        hit = _hit(r)
        c = cases.get(r["signal_id"])
        if c:
            c["numbers_cited"] = json.loads(c["numbers_cited"])
            c["case"] = c.pop("case_text")
            c.pop("signal_id")
        rows.append(hit | {"case": c})
    note = None if rows else "No discounts in the last 10 days."
    return {"as_of": scan_row["as_of"], "scanned": scan_row["scanned"], "rule": RULE, "rows": rows, "note": note}
