import math
import sqlite3
from bisect import bisect_right
from datetime import date, timedelta
from statistics import median

from desk.engine.risk import as_of_value, macro_lookup, market_symbol

Z90 = 1.645
YEAR = 252
QUARTER = 63
DD_BUCKETS = (0.0, -5.0, -10.0, -20.0, -30.0, -100.0)
GAP_BUCKETS = (-1000.0, -10.0, 0.0, 10.0, 1000.0)
CORR_SHIFT = 0.3
EARNINGS_LOOKBACK = 8
MIN_SAMPLES = 5
PCTL_YEARS = 10
NOT = {
    "pat.mkt_drawdown": "Not a forecast for this drawdown; past ones of a similar depth, many overlapping.",
    "pat.vix_pctl": "Not a timing signal; high fear has come before both rallies and further falls.",
    "pat.curve_10y3m": "Not a recession call; the gap between inversion and anything happening has ranged from months to years.",
    "pat.hy_pctl": "Not a timing signal; spreads describe stress, they do not schedule it.",
    "pat.range_52w": "Not a buy or sell level; where this holding sat in its own range before.",
    "pat.ma200_gap": "Not a chart signal; a description of how stretched the price is.",
    "pat.vol_pctl": "Not a risk forecast; today's choppiness against this holding's own past.",
    "pat.earnings_move": "Not a prediction of the next report; the typical size of past moves.",
}


# ---- Stats ----


def wilson(k: int, n: int, z: float = Z90) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def bucket(value: float, edges: tuple[float, ...]) -> int:
    lo, hi = min(edges), max(edges)
    v = min(max(value, lo), hi)
    ordered = sorted(edges)
    for i in range(len(ordered) - 1):
        if ordered[i] <= v < ordered[i + 1] or (i == len(ordered) - 2 and v == ordered[-1]):
            return i
    return len(ordered) - 2


def quintile(p: float) -> int:
    return min(4, int(p * 5))


def base_rate(samples: list[tuple[int, float]], want: int) -> dict:
    hits = [f for b, f in samples if b == want]
    k = sum(1 for f in hits if f > 0)
    lo, hi = wilson(k, len(hits))
    return {
        "n": len(hits),
        "base_rate": round(k / len(hits), 4) if hits else None,
        "ci_low": round(lo, 4) if lo is not None else None,
        "ci_high": round(hi, 4) if hi is not None else None,
        "forward_mean_pct": round(sum(hits) / len(hits) * 100, 4) if hits else None,
    }


def month_ends(days: list[str]) -> list[int]:
    return [i for i in range(len(days) - 1) if days[i][:7] != days[i + 1][:7]]


def _pctl(window: list[float], x: float) -> float | None:
    if len(window) < 20:
        return None
    s = sorted(window)
    return bisect_right(s, x) / len(s)


# ---- Market context ----


def _closes(tr, symbol: str, end: str) -> tuple[list[str], list[float]]:
    days = [d for d in tr.dates.get(symbol, []) if d <= end]
    return days, [tr.price(symbol, d) for d in days]


def _drawdowns(px: list[float]) -> list[float]:
    peak, out = 0.0, []
    for p in px:
        peak = max(peak, p)
        out.append((p / peak - 1) * 100 if peak else 0.0)
    return out


def _record(pid: str, scope_id: str, label: str, value, unit: str, rate: dict | None, bucket_label: str | None, horizon: str) -> dict:
    rate = rate or {"n": 0, "base_rate": None, "ci_low": None, "ci_high": None, "forward_mean_pct": None}
    if rate["n"] < MIN_SAMPLES:
        rate = rate | {"base_rate": None, "ci_low": None, "ci_high": None}
    return {
        "id": pid,
        "scope_id": scope_id,
        "label": label,
        "value": round(value, 4) if isinstance(value, float) else value,
        "unit": unit,
        "bucket": bucket_label,
        "followed_by": f"higher {horizon} later",
        **rate,
        "what_it_is_not": NOT.get(pid, "Description, not a signal."),
    }


def market(tr, desk: sqlite3.Connection, as_of: str) -> list[dict]:
    ref = market_symbol(tr)
    if not ref:
        return []
    days, px = _closes(tr, ref, as_of)
    if len(days) < YEAR + 2:
        return []
    ends = month_ends(days)
    fwd = {}
    for i in ends:
        j = bisect_right(days, (date.fromisoformat(days[i]) + timedelta(days=365)).isoformat()) - 1
        if (date.fromisoformat(days[i]) + timedelta(days=365)).isoformat() <= days[-1]:
            fwd[i] = px[j] / px[i] - 1
    out = []
    dd = _drawdowns(px)
    edges = DD_BUCKETS
    want = bucket(dd[-1], edges)
    samples = [(bucket(dd[i], edges), f) for i, f in fwd.items()]
    lo, hi = sorted(edges)[want], sorted(edges)[want + 1]
    out.append(_record("pat.mkt_drawdown", ref, "S&P 500 drawdown from its high", dd[-1], "pct", base_rate(samples, want), f"{hi:g} to {lo:g}%", "12 months"))

    def pctl_series(series: str, label: str, pid: str):
        dates, values = macro_lookup(desk, series)
        if len(dates) < 250:
            return
        cut = (date.fromisoformat(as_of) - timedelta(days=365 * PCTL_YEARS)).isoformat()
        now_v = as_of_value(dates, values, as_of)
        window = [v for d, v in zip(dates, values, strict=True) if cut <= d <= as_of]
        now_p = _pctl(window, now_v) if now_v is not None else None
        if now_p is None:
            return
        samples = []
        for i, f in fwd.items():
            d = days[i]
            v = as_of_value(dates, values, d)
            lo_cut = (date.fromisoformat(d) - timedelta(days=365 * PCTL_YEARS)).isoformat()
            a, b = bisect_right(dates, lo_cut), bisect_right(dates, d)
            p = _pctl(values[a:b], v) if v is not None else None
            if p is not None:
                samples.append((quintile(p), f))
        q = quintile(now_p)
        out.append(_record(pid, series, label, now_p * 100, "pct", base_rate(samples, q), f"quintile {q + 1} of 5", "12 months"))

    pctl_series("VIXCLS", "VIX percentile over 10 years", "pat.vix_pctl")
    pctl_series("BAMLH0A0HYM2", "High-yield spread percentile over 10 years", "pat.hy_pctl")
    d10, v10 = macro_lookup(desk, "DGS10")
    d3, v3 = macro_lookup(desk, "DGS3MO")
    if d10 and d3:
        a, b = as_of_value(d10, v10, as_of), as_of_value(d3, v3, as_of)
        if a is not None and b is not None:
            samples = []
            for i, f in fwd.items():
                x, y = as_of_value(d10, v10, days[i]), as_of_value(d3, v3, days[i])
                if x is not None and y is not None:
                    samples.append((int(x - y < 0), f))
            inv = int(a - b < 0)
            out.append(
                _record(
                    "pat.curve_10y3m",
                    "curve",
                    "10-year minus 3-month yield",
                    a - b,
                    "pts",
                    base_rate(samples, inv),
                    "inverted" if inv else "not inverted",
                    "12 months",
                )
            )
    return out


# ---- Holdings ----


def holding(tr, desk: sqlite3.Connection, symbol: str, as_of: str) -> list[dict]:
    days, px = _closes(tr, symbol, as_of)
    if len(days) < YEAR + QUARTER:
        return []
    out = []
    fwd = {i: px[i + QUARTER] / px[i] - 1 for i in month_ends(days) if i + QUARTER < len(days) and i >= YEAR}

    def pos(i: int) -> float | None:
        w = px[i - YEAR + 1 : i + 1]
        lo, hi = min(w), max(w)
        return (px[i] - lo) / (hi - lo) if hi > lo else None

    now = pos(len(px) - 1)
    if now is not None:
        samples = [(quintile(p), f) for i, f in fwd.items() if (p := pos(i)) is not None]
        q = quintile(now)
        out.append(
            _record("pat.range_52w", symbol, "Position in the 52-week range", now * 100, "pct", base_rate(samples, q), f"quintile {q + 1} of 5", "3 months")
        )
    if len(px) >= 200:

        def gap(i: int) -> float | None:
            if i < 199:
                return None
            avg = sum(px[i - 199 : i + 1]) / 200
            return (px[i] / avg - 1) * 100 if avg else None

        g = gap(len(px) - 1)
        if g is not None:
            b = bucket(g, GAP_BUCKETS)
            samples = [(bucket(x, GAP_BUCKETS), f) for i, f in fwd.items() if (x := gap(i)) is not None]
            edges = sorted(GAP_BUCKETS)
            label = f"{max(edges[b], -10):g} to {min(edges[b + 1], 10):g}%" if 0 < b < len(edges) - 2 else ("below -10%" if b == 0 else "above +10%")
            out.append(_record("pat.ma200_gap", symbol, "Distance from the 200-day average", g, "pct", base_rate(samples, b), label, "3 months"))

    def vol(i: int) -> float | None:
        if i < QUARTER:
            return None
        r = [px[k] / px[k - 1] - 1 for k in range(i - QUARTER + 1, i + 1)]
        m = sum(r) / len(r)
        return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) * YEAR)

    ends = month_ends(days)
    hist = [(i, v) for i in ends if (v := vol(i)) is not None]
    v_now = vol(len(px) - 1)
    window = [v for i, v in hist if i >= len(px) - 5 * YEAR]
    p_now = _pctl(window, v_now) if v_now is not None else None
    if p_now is not None:
        samples = []
        for i, f in fwd.items():
            past = [v for k, v in hist if i - 5 * YEAR <= k <= i]
            p = _pctl(past, vol(i)) if vol(i) is not None else None
            if p is not None:
                samples.append((quintile(p), f))
        q = quintile(p_now)
        out.append(
            _record(
                "pat.vol_pctl",
                symbol,
                "Realized volatility percentile over 5 years",
                p_now * 100,
                "pct",
                base_rate(samples, q),
                f"quintile {q + 1} of 5",
                "3 months",
            )
        )
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='earnings'").fetchone():
        dates = [
            r[0] for r in desk.execute("SELECT date FROM earnings WHERE symbol=? AND date <= ? ORDER BY date DESC LIMIT ?", (symbol, as_of, EARNINGS_LOOKBACK))
        ]
        moves = []
        for e in dates:
            i = bisect_right(days, e) - 1
            before = i - 1 if i >= 0 and days[i] == e else i
            after = bisect_right(days, e)
            if before >= 0 and after < len(days):
                moves.append(abs(px[after] / px[before] - 1) * 100)
        if moves:
            rec = _record("pat.earnings_move", symbol, f"Average move on the last {len(moves)} earnings", sum(moves) / len(moves), "pct", None, None, "")
            out.append(rec | {"n": len(moves), "followed_by": None})
    return out


# ---- Drawdowns and seasonality ----


def drawdown_table(tr, symbol: str, as_of: str) -> dict | None:
    days, px = _closes(tr, symbol, as_of)
    if len(days) < YEAR:
        return None
    dd = _drawdowns(px)
    now = dd[-1]
    threshold = min(now, -5.0)
    episodes, peak_i, trough, start = [], 0, 0.0, None
    for i, x in enumerate(dd):
        if x == 0.0:
            if start is not None and trough <= threshold:
                episodes.append({"peak": days[peak_i], "depth_pct": round(trough, 2), "days_to_recover": i - peak_i})
            peak_i, trough, start = i, 0.0, None
            continue
        start = start if start is not None else i
        trough = min(trough, x)
    open_now = start is not None
    recov = [e["days_to_recover"] for e in episodes]
    return {
        "symbol": symbol,
        "drawdown_pct": round(now, 2),
        "threshold_pct": round(threshold, 2),
        "episodes": len(episodes),
        "median_days_to_recover": median(recov) if recov else None,
        "longest_days_to_recover": max(recov) if recov else None,
        "deepest_pct": round(min((e["depth_pct"] for e in episodes), default=0.0), 2) if episodes else None,
        "open": open_now,
        "since": days[0],
        "note": "Trading days from the old high back to it, for past drawdowns at least this deep. A base-rate table, not a call on this one.",
    }


def seasonality(tr, symbol: str, as_of: str) -> list[dict]:
    days, px = _closes(tr, symbol, as_of)
    ends = month_ends(days)
    by_month: dict[int, list[float]] = {}
    for a, b in zip(ends, ends[1:], strict=False):
        by_month.setdefault(int(days[b][5:7]), []).append(px[b] / px[a] - 1)
    return [
        {"month": m, "mean_pct": round(sum(xs) / len(xs) * 100, 4), "n": len(xs), "share_up": round(sum(1 for x in xs if x > 0) / len(xs), 4)}
        for m, xs in sorted(by_month.items())
    ]


# ---- Behavior ----


def behavior(card: dict, tr, desk: sqlite3.Connection, kinds: dict[str, str], as_of: str) -> dict:
    mine = [s for s in card.get("decisions", []) if s["origin"] == "you"]

    def score90(s):
        v = s["scores"].get("90D")
        return v["usd"] if v and v["usd"] is not None else None

    groups: dict[str, list[float]] = {}
    for s in mine:
        if s["kind"] != "buy" or not s["start"] or score90(s) is None:
            continue
        i = bisect_right(tr.dates.get(s["symbol"], []), s["start"]) - 1
        dates = tr.dates.get(s["symbol"], [])
        trail = None
        if i >= 21:
            trail = tr.price(s["symbol"], dates[i - 1]) / tr.price(s["symbol"], dates[i - 21]) - 1
        label = "after_drop" if trail is not None and trail <= -0.05 else ("after_rise" if trail is not None and trail >= 0.05 else "flat")
        groups.setdefault(label, []).append(score90(s))
    funding = card.get("funding", {})
    cut = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
    trades = [s for s in mine if s["start"] and s["start"] >= cut and s["kind"] in ("buy", "sell", "trim", "harvest", "rebalance")]
    held = []
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='realized_lots'").fetchone():
        for r in desk.execute("SELECT symbol, acquired, sold FROM realized_lots WHERE acquired IS NOT NULL AND sold IS NOT NULL"):
            if kinds.get(r["symbol"], "stock") == "stock":
                held.append((date.fromisoformat(r["sold"]) - date.fromisoformat(r["acquired"])).days)

    def stat(xs):
        return {"n": len(xs), "mean_usd": round(sum(xs) / len(xs), 2) if xs else None, "total_usd": round(sum(xs), 2)}

    return {
        "buys_by_setup": {k: stat(v) for k, v in sorted(groups.items())},
        "funding": funding,
        "trades_per_month": round(len(trades) / 12, 2),
        "single_stock_hold_days_median": median(held) if held else None,
        "single_stock_sales": len(held),
        "note": "Each of your buys scored against the same dollars in the plan at 90 days, grouped by what the stock did in the month before.",
    }


def funding_split(rows: list[dict], card: dict) -> dict:
    by_id = {s["id"]: s for s in card.get("decisions", [])}
    groups: dict[str, list[float]] = {}
    for d in rows:
        if d["origin"] != "you" or d["kind"] not in ("buy", "deposit_route"):
            continue
        v = (by_id.get(d["id"], {}).get("scores") or {}).get("90D")
        if not v or v["usd"] is None:
            continue
        key = "margin" if d.get("funding") == "margin" else ("scheduled" if d["kind"] == "deposit_route" or d.get("funding") == "deposit" else "off_schedule")
        groups.setdefault(key, []).append(v["usd"])
    return {k: {"n": len(v), "mean_usd": round(sum(v) / len(v), 2), "total_usd": round(sum(v), 2)} for k, v in sorted(groups.items())}


# ---- Engine hook ----


def metrics(out, desk: sqlite3.Connection, tr, symbols: list[str], kinds: dict[str, str], card: dict, rows: list[dict]) -> dict:
    as_of = out.as_of
    found = market(tr, desk, as_of)
    per_holding = {s: holding(tr, desk, s, as_of) for s in symbols}
    ref = market_symbol(tr)
    dds = [
        t for t in ([drawdown_table(tr, ref, as_of)] if ref else []) + [drawdown_table(tr, s, as_of) for s in symbols if kinds.get(s) in ("fund", "etf")] if t
    ]
    shifts = [{"symbol": m[2], "shift": m[5], "n": m[7]} for m in out.metrics if m[0] == "risk.corr_shift" and m[5] is not None and abs(m[5]) >= CORR_SHIFT]
    card = card | {"funding": funding_split(rows, card)}
    view = {
        "as_of": as_of,
        "market": found,
        "holdings": per_holding,
        "drawdowns": dds,
        "seasonality": {s: seasonality(tr, s, as_of) for s in symbols},
        "seasonality_note": "Description, never a signal.",
        "corr_shifts": shifts,
        "behavior": behavior(card, tr, desk, kinds, as_of),
        "left_out": "Day-of-week and calendar effects, chart patterns, and anything found by searching many rules on the same data.",
    }
    rows_out = []
    for p in found + [p for ps in per_holding.values() for p in ps]:
        rows_out.append((p["id"], p["scope_id"], as_of, p["value"], p["base_rate"], p["ci_low"], p["ci_high"], p["n"], p["what_it_is_not"]))
    out.signals = rows_out
    return view
