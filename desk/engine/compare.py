import math
import sqlite3
from datetime import date, timedelta

from desk.engine.lookthrough import overlap
from desk.engine.returns import TRADING_DAYS, annualize, drawdowns
from desk.engine.risk import SP500, beta, corr, stdev
from desk.engine.shadows import TotalReturn

WINDOWS = ("1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "10Y", "MAX")
MAX_IDS = 5
AFTER_TAX = ("YTD", "1Y", "ITD")


class CompareError(ValueError):
    pass


# ---- Loading ----


def price_book(conn: sqlite3.Connection) -> TotalReturn:
    series: dict[str, dict[str, tuple[float, float | None]]] = {}
    for tbl in ("prices_daily", "price_bars"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tbl,)).fetchone():
            for r in conn.execute(f"SELECT symbol, date, close, adj_close FROM {tbl}"):
                series.setdefault(r["symbol"], {}).setdefault(r["date"], (r["close"], r["adj_close"]))
    return TotalReturn(series)


def _stored(conn: sqlite3.Connection, scope: str, scope_id: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT date, value FROM series_daily WHERE series_id='twr_index' AND scope=? AND scope_id=? ORDER BY date", (scope, scope_id)
    ).fetchall()
    return {r["date"]: r["value"] for r in rows}


def load(conn: sqlite3.Connection, tr: TotalReturn, key: str) -> tuple[str, dict[str, float]]:
    if key == "portfolio":
        return "portfolio", _stored(conn, "portfolio", "all")
    if ":" in key:
        scope, scope_id = key.split(":", 1)
        if scope not in ("account", "shadow"):
            raise CompareError(f"Unknown series {key}; use a ticker, portfolio, account:<key> or shadow:<name>.")
        return scope, _stored(conn, scope, scope_id)
    return "symbol", dict(tr.series.get(key, {}))


def start_for(window: str, end: date) -> date | None:
    months = {"1M": 1, "3M": 3, "6M": 6}
    years = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10}
    if window in months:
        return end - timedelta(days=round(30.44 * months[window]))
    if window in years:
        try:
            return end.replace(year=end.year - years[window])
        except ValueError:
            return end.replace(year=end.year - years[window], day=28)
    if window == "YTD":
        return end.replace(month=1, day=1) - timedelta(days=1)
    return None


# ---- Compare ----


def _rets(values: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(values, values[1:], strict=False) if a]


def _latest(conn: sqlite3.Connection, metric_id: str, scope: str, scope_id: str, window: str = "now"):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='metric_values'").fetchone():
        return None
    r = conn.execute(
        'SELECT value FROM metric_values WHERE metric_id=? AND scope=? AND scope_id=? AND "window"=? ORDER BY as_of DESC LIMIT 1',
        (metric_id, scope, scope_id, window),
    ).fetchone()
    return r["value"] if r else None


def compare(conn: sqlite3.Connection, ids: list[str], window: str = "1Y") -> dict:
    keys = list(dict.fromkeys(i.strip() if ":" in i or i.strip() == "portfolio" else i.strip().upper() for i in ids if i.strip()))
    if not 2 <= len(keys) <= MAX_IDS:
        raise CompareError(f"Compare two to {MAX_IDS} series.")
    if window not in WINDOWS:
        raise CompareError(f"window must be one of {', '.join(WINDOWS)}.")
    tr = price_book(conn)
    loaded = {k: load(conn, tr, k) for k in keys}
    missing = [k for k, (_, s) in loaded.items() if len(s) < 2]
    if missing:
        raise CompareError(f"No history for {', '.join(missing)}.")
    end = min(max(s) for _, s in loaded.values())
    first_by = {k: min(s) for k, (_, s) in loaded.items()}
    first = max(first_by.values())
    wanted = start_for(window, date.fromisoformat(end))
    clipped = wanted is not None and wanted.isoformat() < first
    start = first if wanted is None or clipped else wanted.isoformat()
    common = sorted(set.intersection(*({d for d in s if start <= d <= end} for _, s in loaded.values())))
    if len(common) < 2:
        raise CompareError("These series share fewer than two days.")
    setter = max(first_by, key=lambda k: first_by[k])
    note = f"{setter} starts on {first_by[setter]}, so the comparison starts there." if clipped else None
    series = {k: [{"date": d, "value": round(s[d] / s[common[0]] * 100, 4)} for d in common] for k, (_, s) in loaded.items()}
    mkt = next((s for s in SP500 if tr.starts(s) and tr.starts(s) <= common[0]), None)
    mrets = _rets([tr.price(mkt, d) for d in common]) if mkt else None
    ref = _rets([loaded[keys[0]][1][d] for d in common])
    span = (date.fromisoformat(common[-1]) - date.fromisoformat(common[0])).days
    table = []
    for k in keys:
        kind, s = loaded[k]
        vals = [s[d] for d in common]
        rets = _rets(vals)
        total = vals[-1] / vals[0] - 1
        ann = annualize(total, span)
        sd = stdev(rets)
        vol = sd * math.sqrt(TRADING_DAYS) if sd is not None else None
        worst, _, _ = drawdowns(vals)
        row = {
            "id": k,
            "kind": kind,
            "first": first_by[k],
            "return_pct": round(total * 100, 4),
            "ann_return_pct": round(ann * 100, 4) if ann is not None else None,
            "vol_pct": round(vol * 100, 4) if vol is not None else None,
            "mdd_pct": round(worst * 100, 4),
            "return_per_risk": round(ann / vol, 4) if ann is not None and vol else None,
            "corr": _r(corr(rets, ref)) if k != keys[0] else 1.0,
            "beta": _r(beta(rets, ref)) if k != keys[0] else 1.0,
            "corr_sp500": _r(corr(rets, mrets)) if mrets else None,
            "expense_pct": _latest(conn, "cost.expense", "holding", k) if kind == "symbol" else None,
            "yield_pct": _latest(conn, "income.yield", "holding", k, "TTM") if kind == "symbol" else None,
            "overlap_pct": None,
            "after_tax_pct": None,
        }
        if (
            kind == "symbol"
            and k != keys[0]
            and loaded[keys[0]][0] == "symbol"
            and conn.execute("SELECT 1 FROM sqlite_master WHERE name='fund_holdings'").fetchone()
        ):
            row["overlap_pct"] = _r(overlap(conn, keys[0], k))
        if kind == "account":
            at_window = "ITD" if window == "MAX" else window
            if at_window in AFTER_TAX and not clipped:
                row["after_tax_pct"] = _latest(conn, "ret.after_tax", "account", k.split(":", 1)[1], at_window)
        table.append(row)
    return {
        "ids": keys,
        "window": window,
        "start": common[0],
        "end": common[-1],
        "requested_start": wanted.isoformat() if wanted else None,
        "clipped": clipped,
        "note": note,
        "days": len(common),
        "market": mkt,
        "series": series,
        "table": table,
    }


def _r(x: float | None) -> float | None:
    return round(x, 4) if x is not None else None
