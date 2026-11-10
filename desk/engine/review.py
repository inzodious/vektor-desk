import hashlib
import json
import math
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import broker, catalog
from desk.engine.bands import limit
from desk.engine.core import PROFILE_ERRORS, convictions, latest_plan, rules_in_force
from desk.engine.holdings import BACKCAST, CASH_SYMBOLS, bar_series, price_series
from desk.engine.lots import realized_rows
from desk.engine.market import ET, trading_day
from desk.engine.shadows import TotalReturn

PACK_VERSION = 1
KINDS = ("day", "week", "month", "year")
BENCHMARK = "SPY"
MOVERS = 5
LIST_CAP = 60
INDEX_CAP = {"day": 260, "week": 156, "month": 120, "year": 40}
MIN_VOL_DAYS = 5
PRICED_SHARE = 0.8
SPLIT_TOLERANCE = 0.03
FLOW_DUST = 0.05
CLOSE_TIME = time(16, 15)
QUALITY_ORDER = ("ok", "trimmed", "pro_forma", "modelled", "mismatch", "stale", "insufficient_history")
EMPTY_NOTE = "No reviews yet. The first one is written after the 5:20 PM engine run on a trading day."
LIMITS = {"headline": 120, "what_happened": 700, "why": 700, "against_decisions": 500}
WATCH_MAX, WATCH_LEN, STEPS_MAX, STEP_LEN = 4, 160, 3, 200


class NotReady(Exception):
    pass


# ---- Periods ----


def _next_trading(d: date) -> date:
    d += timedelta(days=1)
    while not trading_day(d):
        d += timedelta(days=1)
    return d


def _bounds(kind: str, d: date) -> tuple[date, date]:
    if kind == "day":
        return d, d
    if kind == "week":
        lo = d - timedelta(days=d.weekday())
        hi = lo + timedelta(days=6)
    elif kind == "month":
        lo = d.replace(day=1)
        hi = (lo.replace(year=lo.year + 1, month=1) if lo.month == 12 else lo.replace(month=lo.month + 1)) - timedelta(days=1)
    else:
        lo, hi = date(d.year, 1, 1), date(d.year, 12, 31)
    while not trading_day(lo):
        lo += timedelta(days=1)
    while not trading_day(hi):
        hi -= timedelta(days=1)
    return lo, hi


def periods(kind: str, first: str, last: str) -> list[tuple[str, str]]:
    d, stop = date.fromisoformat(first), date.fromisoformat(last)
    while not trading_day(d):
        d += timedelta(days=1)
    out = []
    while d <= stop:
        lo, hi = _bounds(kind, d)
        if hi >= lo:
            out.append((lo.isoformat(), hi.isoformat()))
        d = _next_trading(max(hi, d))
    return out


def label(kind: str, start: str, end: str) -> str:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if kind == "day":
        return f"{e:%a %b} {e.day}, {e.year}"
    if kind == "week":
        return f"Week of {s:%b} {s.day}, {s.year}"
    if kind == "month":
        return f"{e:%B} {e.year}"
    return str(e.year)


# ---- Data ----


@dataclass
class Data:
    cfg: Config | None
    days: list[str]
    value: dict[str, float]
    index: dict[str, float]
    quality: dict[str, str]
    accounts: dict[str, dict[str, tuple[float, float]]]
    holdings: dict[str, list[dict]]
    tr: TotalReturn
    activity: list[dict]
    flows: list[dict]
    realized: list[dict]
    mixes: dict[str, dict]
    names: dict[str, str]
    rules: list[dict]
    decisions: list[dict]
    scored: list[dict]
    bands: dict
    fi: dict
    profile: dict | None
    ledgers: dict[tuple[str, int], list[tuple[str, float]]]
    portfolios: list[dict]
    discounts: list[dict]
    filings: list[dict]
    earnings: list[dict]
    pnl: dict[tuple[str, str], dict[str, tuple[float, float]]] = field(default_factory=dict)
    dip_days: list[str] = field(default_factory=list)
    dip_cash: list[float] = field(default_factory=list)


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _rows(conn: sqlite3.Connection, table: str, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)] if _has(conn, table) else []


def _view(conn: sqlite3.Connection, name: str) -> dict:
    row = conn.execute("SELECT body FROM engine_views WHERE name=?", (name,)).fetchone() if _has(conn, "engine_views") else None
    return json.loads(row[0]) if row else {}


def _profile(cfg: Config | None) -> dict | None:
    if cfg is None:
        return None
    try:
        from desk.decisions import risk as profile_risk

        return profile_risk.current(cfg)
    except Exception:
        return None


def _series(desk: sqlite3.Connection) -> list:
    if not _has(desk, "series_daily"):
        return []
    return desk.execute(
        "SELECT series_id, scope, scope_id, date, value, quality FROM series_daily "
        "WHERE series_id IN ('value', 'twr_index') AND scope IN ('portfolio', 'account') ORDER BY date"
    ).fetchall()


def load(cfg: Config | None, mirror: sqlite3.Connection | None, desk: sqlite3.Connection) -> Data:
    value, index, quality = {}, {}, {}
    accounts: dict[str, dict[str, list[float | None]]] = {}
    for r in _series(desk):
        sid, scope, scope_id, d, v, q = r
        if scope == "portfolio":
            (value if sid == "value" else index)[d] = v
            if sid == "value":
                quality[d] = q
        else:
            slot = accounts.setdefault(scope_id, {}).setdefault(d, [None, None])
            slot[0 if sid == "value" else 1] = v
    days = sorted(d for d in value if d in index)
    by_day: dict[str, list[dict]] = {}
    for r in desk.execute("SELECT date, account, symbol, shares, close, value, is_cash FROM holdings_daily ORDER BY date"):
        by_day.setdefault(r["date"], []).append(dict(r))
    series = price_series(mirror, desk) if mirror is not None else bar_series(desk)
    for r in _rows(desk, "prices_daily", "SELECT symbol, date, close, adj_close FROM prices_daily"):
        series.setdefault(r["symbol"], {}).setdefault(r["date"], (r["close"], r["adj_close"]))
    activity, _ = broker.history(mirror, desk)
    plan = latest_plan(mirror) if mirror is not None else {}
    try:
        rules = rules_in_force(cfg, plan)[0] if cfg is not None else []
    except PROFILE_ERRORS:
        rules = []
    names = {r["symbol"]: r["title"] for r in _rows(desk, "sec_tickers", "SELECT symbol, title FROM sec_tickers") if r["title"]}
    names |= {r["symbol"]: r["name"] for r in _rows(desk, "sym_profiles", "SELECT symbol, name FROM sym_profiles") if r["name"]}
    ledgers: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for r in _rows(desk, "paper_ledger_daily", "SELECT strategy_id, version, date, value FROM paper_ledger_daily ORDER BY date"):
        ledgers.setdefault((r["strategy_id"], r["version"]), []).append((r["date"], r["value"]))
    listed = catalog.latest(desk) if _has(desk, "catalog_strategies") else {}
    mixes = {k: listed[k]["mix"] for k in catalog.NAMES if k in listed and listed[k]["retired_at"] is None}
    data = Data(
        cfg=cfg,
        days=days,
        value=value,
        index=index,
        quality=quality,
        accounts={a: {d: (v[0], v[1]) for d, v in ds.items() if v[0] is not None and v[1] is not None} for a, ds in accounts.items()},
        holdings=by_day,
        tr=TotalReturn(series),
        activity=sorted(activity, key=lambda r: str(r.get("date") or "")),
        flows=_rows(desk, "cash_flows", "SELECT date, account, amount, kind FROM cash_flows WHERE external_portfolio=1 ORDER BY date, account"),
        realized=realized_rows(desk),
        mixes=mixes,
        names=names,
        rules=rules,
        decisions=_rows(desk, "decisions", "SELECT id, created_at, origin, kind, title, symbol, status FROM decisions ORDER BY created_at"),
        scored=_view(desk, "scorecard").get("decisions") or [],
        bands=_view(desk, "bands"),
        fi=_view(desk, "fi"),
        profile=_profile(cfg),
        ledgers=ledgers,
        portfolios=_rows(desk, "paper_portfolios", "SELECT strategy_id, version, title, status, summary FROM paper_portfolios ORDER BY strategy_id"),
        discounts=_rows(desk, "discount_signals", "SELECT as_of, symbol, reason, drop_from_high_pct FROM discount_signals ORDER BY as_of"),
        filings=_rows(desk, "filing_signals", "SELECT symbol, filed_at, form, event_type, direction FROM filing_signals ORDER BY filed_at"),
        earnings=_rows(desk, "earnings", "SELECT symbol, date, eps_actual, eps_estimate FROM earnings ORDER BY date"),
    )
    dip = catalog.Dip()
    for day in data.tr.dates.get(catalog.BENCHMARK, []):
        data.dip_days.append(day)
        data.dip_cash.append(dip.step(data.tr.series[catalog.BENCHMARK][day]))
    return data


# ---- Pieces ----


def _r(v, n: int = 2):
    return round(v, n) if v is not None else None


def _worst(qualities) -> str:
    seen = [q for q in qualities if q in QUALITY_ORDER]
    return max(seen, key=QUALITY_ORDER.index) if seen else "ok"


def day_flow(data: Data, a: str, b: str) -> float:
    r = data.index[b] / data.index[a] if data.index[a] else 1.0
    f = data.value[b] - data.value[a] * r
    return 0.0 if abs(f) < FLOW_DUST else f


def pair_pnl(data: Data, a: str, b: str) -> dict[str, tuple[float, float]]:
    key = (a, b)
    if key in data.pnl:
        return data.pnl[key]
    after = {(h["account"], h["symbol"]): h for h in data.holdings.get(b, [])}
    out: dict[str, tuple[float, float]] = {}
    for h in data.holdings.get(a, []):
        if h["is_cash"] or not h["shares"]:
            continue
        sym = h["symbol"]
        now = after.get((h["account"], sym))
        c0, c1 = h["close"], now["close"] if now else None
        if c0 and c1 and now["shares"]:
            ratio = now["shares"] / h["shares"]
            split = abs(ratio - 1) > 0.2 and abs(ratio * c1 / c0 - 1) < SPLIT_TOLERANCE
            pnl = now["value"] - h["value"] if split else h["shares"] * (c1 - c0)
        elif now and now["shares"] == h["shares"]:
            pnl = now["value"] - h["value"]
        else:
            ret = _ret(data, sym, a, b)
            pnl = h["value"] * ret if ret is not None else 0.0
        was = out.get(sym, (0.0, 0.0))
        out[sym] = (was[0] + pnl, was[1] + max(h["value"], 0.0))
    data.pnl[key] = out
    return out


def _ret(data: Data, sym: str, a: str, b: str) -> float | None:
    p0, p1 = data.tr.price(sym, a), data.tr.price(sym, b)
    return p1 / p0 - 1 if p0 and p1 else None


def _dip_cash(data: Data, day: str) -> float:
    i = bisect_right(data.dip_days, day)
    return data.dip_cash[i - 1] if i else catalog.DIP_CASH


def mix_return(data: Data, mix: dict, a: str, b: str) -> float | None:
    got = {s: (w, _ret(data, s, a, b)) for s, w in mix["weights"].items()}
    priced = sum(w for w, r in got.values() if r is not None)
    if priced < PRICED_SHARE:
        return None
    cash = _dip_cash(data, a) if mix.get("steps") else mix.get("cash", 0.0)
    return (1 - cash) * sum(w * r for w, r in got.values() if r is not None) / priced


def comparators(data: Data) -> list[tuple[str, str, str, object]]:
    out = [("spy", "S&P 500", "benchmark", lambda a, b: _ret(data, BENCHMARK, a, b))]
    for sid, mix in data.mixes.items():
        out.append((sid, catalog.NAMES.get(sid, sid), "mix", lambda a, b, m=mix: mix_return(data, m, a, b)))
    return out


def versus(data: Data, span: list[str], start: float, end: float, change: float) -> list[dict]:
    rows = []
    for cid, name, kind, fn in comparators(data):
        w, total, ok = start, 1.0, True
        for a, b in zip(span, span[1:], strict=False):
            r = fn(a, b)
            if r is None:
                ok = False
                break
            total *= 1 + r
            w = w * (1 + r) + day_flow(data, a, b)
        if not ok:
            continue
        ret = (total - 1) * 100
        rows.append(
            {
                "id": cid,
                "name": name,
                "kind": kind,
                "return_pct": _r(ret, 4),
                "excess_pts": _r(change - ret, 4),
                "value_end": _r(w),
                "diff_usd": _r(end - w),
            }
        )
    return rows


def movers(data: Data, span: list[str], start: float, gain: float) -> tuple[dict, dict[str, float]]:
    total: dict[str, float] = {}
    growth: dict[str, float] = {}
    for a, b in zip(span, span[1:], strict=False):
        for sym, (pnl, base) in pair_pnl(data, a, b).items():
            total[sym] = total.get(sym, 0.0) + pnl
            if base:
                growth[sym] = growth.get(sym, 1.0) * (1 + pnl / base)
    last = data.holdings.get(span[-1], [])
    worth = sum(h["value"] for h in last)
    weights: dict[str, float] = {}
    for h in last:
        if not h["is_cash"] and worth:
            weights[h["symbol"]] = weights.get(h["symbol"], 0.0) + h["value"] / worth * 100

    def row(sym: str, usd: float) -> dict:
        ret = growth[sym] - 1 if sym in growth else _ret(data, sym, span[0], span[-1])
        return {
            "symbol": sym,
            "name": data.names.get(sym),
            "contribution_usd": _r(usd),
            "contribution_pts": _r(usd / start * 100, 4) if start else None,
            "return_pct": _r(ret * 100, 4) if ret is not None else None,
            "weight_pct": _r(weights.get(sym, 0.0), 4),
        }

    ranked = sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
    up = [row(s, v) for s, v in ranked if v > 0.005][:MOVERS]
    down = [row(s, v) for s, v in reversed(ranked) if v < -0.005][:MOVERS]
    return {"up": up, "down": down, "other_usd": _r(gain - sum(total.values())), "count": len(total)}, weights


def account_rows(data: Data, base: str, as_of: str) -> list[dict]:
    out = []
    for acct, series in sorted(data.accounts.items()):
        days = sorted(series)
        i, j = bisect_right(days, base), bisect_right(days, as_of)
        span = days[max(i - 1, 0) : j]
        if len(span) < 2:
            continue
        (v0, x0), (v1, x1) = series[span[0]], series[span[-1]]
        flow = 0.0
        for a, b in zip(span, span[1:], strict=False):
            (va, xa), (vb, xb) = series[a], series[b]
            day = vb - va * (xb / xa if xa else 1.0)
            flow += 0.0 if abs(day) < FLOW_DUST else day
        out.append(
            {
                "account": acct,
                "start": _r(v0),
                "end": _r(v1),
                "change_usd": _r(v1 - v0),
                "change_pct": _r((x1 / x0 - 1) * 100 if x0 else 0.0, 4),
                "net_flows": _r(flow),
            }
        )
    return out


def _in(d: str, base: str, as_of: str, partial: bool) -> bool:
    d = str(d or "")[:10]
    return (base <= d if partial else base < d) and d <= as_of


def _activity(data: Data, base: str, as_of: str, partial: bool) -> tuple[dict, list[dict]]:
    income = {"dividends": 0.0, "interest": 0.0, "margin_interest": 0.0}
    trades = []
    for r in data.activity:
        if not _in(r.get("date"), base, as_of, partial):
            continue
        kind, amount = r.get("kind"), float(r.get("amount") or 0)
        if kind in ("dividend", "in_lieu"):
            income["dividends"] += amount
        elif kind == "interest":
            income["interest"] += amount
        elif kind == "margin_interest":
            income["margin_interest"] += -amount
        elif kind in ("buy", "sell") and not r.get("core") and str(r.get("symbol") or "").upper() not in CASH_SYMBOLS and r.get("symbol"):
            qty = r.get("quantity")
            trades.append(
                {
                    "date": str(r["date"])[:10],
                    "account": r.get("accountKey"),
                    "symbol": str(r["symbol"]).upper(),
                    "side": kind,
                    "shares": _r(abs(float(qty)), 6) if qty else None,
                    "price": _r(float(r["price"]), 4) if r.get("price") else None,
                    "amount": _r(amount),
                }
            )
    return {k: _r(v) for k, v in income.items()}, trades


def risk_block(data: Data, span: list[str], weights: dict[str, float], latest: bool) -> dict:
    rets = [(b, data.index[b] / data.index[a] - 1) for a, b in zip(span, span[1:], strict=False) if data.index[a]]
    peak, mdd = data.index[span[0]], 0.0
    for d in span:
        peak = max(peak, data.index[d])
        if peak:
            mdd = min(mdd, data.index[d] / peak - 1)
    vol = None
    if len(rets) >= MIN_VOL_DAYS:
        xs = [r for _, r in rets]
        mean = sum(xs) / len(xs)
        vol = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) * math.sqrt(252) * 100
    best = max(rets, key=lambda x: x[1], default=None)
    worst = min(rets, key=lambda x: x[1], default=None)
    band = None
    if latest and data.profile:
        held = next((r for r in data.bands.get("rows") or [] if r.get("id") == "as-held" and r.get("status") == "ok"), {})
        band = {
            "band": data.profile.get("band"),
            "label": data.profile.get("label") or data.profile.get("name"),
            "worst_year_loss_pct": limit(data.profile),
            "fit": held.get("fit"),
            "worst_year_p10_pct": held.get("worst_year_p10_pct"),
        }
    held_convictions = []
    for sym, (lo, hi) in sorted(convictions(data.rules).items()):
        w = weights.get(sym, 0.0)
        held_convictions.append(
            {"symbol": sym, "weight_pct": _r(w, 4), "band_min_pct": lo, "band_max_pct": hi, "status": "under" if w < lo else ("over" if w > hi else "inside")}
        )
    return {
        "max_drawdown_pct": _r(mdd * 100, 4),
        "volatility_pct": _r(vol, 4),
        "best_day": {"date": best[0], "pct": _r(best[1] * 100, 4)} if best else None,
        "worst_day": {"date": worst[0], "pct": _r(worst[1] * 100, 4)} if worst else None,
        "band": band,
        "convictions": held_convictions,
    }


def decision_block(data: Data, base: str, as_of: str, partial: bool) -> dict:
    keys = ("id", "origin", "kind", "symbol", "title", "status")
    made = [{"date": d["created_at"][:10]} | {k: d[k] for k in keys} for d in data.decisions if _in(d["created_at"], base, as_of, partial)]
    matured = []
    for s in data.scored:
        for horizon, v in (s.get("scores") or {}).items():
            if v.get("usd") is not None and _in(v.get("end"), base, as_of, partial):
                row = {k: s.get(k) for k in ("id", "symbol", "kind", "origin")}
                matured.append(row | {"horizon": horizon, "usd": v["usd"], "end": v["end"]})
    return {"made": made[:LIST_CAP], "matured": matured[:LIST_CAP]}


def paper_block(data: Data, base: str, as_of: str) -> list[dict]:
    out = []
    for p in data.portfolios:
        led = data.ledgers.get((p["strategy_id"], p["version"])) or []
        days = [d for d, _ in led]
        i, j = bisect_right(days, base), bisect_right(days, as_of)
        if j <= i:
            continue
        v0, v1 = led[max(i - 1, 0)][1], led[j - 1][1]
        summary = json.loads(p["summary"] or "{}")
        out.append(
            {
                "id": p["strategy_id"],
                "name": p["title"] or p["strategy_id"],
                "kind": summary.get("kind") if summary.get("kind") in ("lane", "mix") else "strategy",
                "status": p["status"],
                "return_pct": _r((v1 / v0 - 1) * 100, 4) if v0 else None,
                "value_end": _r(v1),
            }
        )
    return sorted(out, key=lambda r: (-(r["return_pct"] or 0), r["id"]))


def event_rows(data: Data, base: str, as_of: str, partial: bool, held: set[str]) -> list[dict]:
    out = []
    for s in data.discounts:
        if _in(s["as_of"], base, as_of, partial):
            detail = f"{s['reason'].replace('_', ' ')}, {s['drop_from_high_pct']:.1f}% from its high"
            out.append({"date": s["as_of"], "type": "discount", "symbol": s["symbol"], "detail": detail})
    for f in data.filings:
        if f["symbol"] in held and _in(f["filed_at"], base, as_of, partial):
            detail = f"{f['form']} {f['event_type']}, scored {f['direction']:+d}"
            out.append({"date": f["filed_at"][:10], "type": "filing", "symbol": f["symbol"], "detail": detail})
    for e in data.earnings:
        if e["symbol"] in held and _in(e["date"], base, as_of, partial):
            detail = "reported earnings"
            if e["eps_actual"] is not None and e["eps_estimate"] is not None:
                detail = f"EPS {e['eps_actual']:g} against {e['eps_estimate']:g} expected"
            out.append({"date": e["date"], "type": "earnings", "symbol": e["symbol"], "detail": detail})
    return sorted(out, key=lambda r: (r["date"], r["type"], r["symbol"]))[:LIST_CAP]


# ---- Pack ----


def _prev_trading(d: date) -> date:
    d -= timedelta(days=1)
    while not trading_day(d):
        d -= timedelta(days=1)
    return d


def build_pack(data: Data, kind: str, start: str, end: str) -> dict | None:
    days = data.days
    j = bisect_right(days, min(end, days[-1]))
    i = bisect_right(days, _prev_trading(date.fromisoformat(start)).isoformat())
    if not j:
        return None
    partial = i == 0
    base = days[0] if partial else days[i - 1]
    as_of = days[j - 1]
    if as_of <= base:
        return None
    span = days[max(i - 1, 0) : j]
    v0, v1 = data.value[base], data.value[as_of]
    change = (data.index[as_of] / data.index[base] - 1) * 100 if data.index[base] else 0.0
    flows = sum(day_flow(data, a, b) for a, b in zip(span, span[1:], strict=False))
    gain = v1 - v0 - flows
    vs = versus(data, span, v0, v1, change)
    moved, weights = movers(data, span, v0, gain)
    income, trades = _activity(data, base, as_of, partial)
    sold = [r for r in data.realized if r.get("gain") is not None and _in(r.get("sold"), base, as_of, partial)]
    st = sum(r["gain"] for r in sold if r.get("term") == "short")
    lt = sum(r["gain"] for r in sold if r.get("term") == "long")
    latest = as_of == days[-1]
    risk = risk_block(data, span, weights, latest)
    fi_number = data.fi.get("fi_number")
    fi = None
    if isinstance(fi_number, int | float) and fi_number > 0:
        fi = {
            "fi_number": fi_number,
            "progress_start_pct": _r(v0 / fi_number * 100, 4),
            "progress_end_pct": _r(v1 / fi_number * 100, 4),
            "change_pts": _r((v1 - v0) / fi_number * 100, 4),
        }
    held = {h["symbol"] for d in span for h in data.holdings.get(d, []) if not h["is_cash"]}
    pack = {
        "version": PACK_VERSION,
        "kind": kind,
        "start": start,
        "end": end,
        "as_of": as_of,
        "label": label(kind, start, end),
        "quality": _worst(data.quality.get(d) for d in span),
        "coverage": {
            "full": not partial,
            "base": base,
            "days": len(span) - 1,
            "note": f"The desk's history starts {base}, so this covers {base} to {as_of} only." if partial else None,
        },
        "value": {"start": _r(v0), "end": _r(v1), "change_usd": _r(v1 - v0), "change_pct": _r(change, 4), "net_flows": _r(flows), "gain_usd": _r(gain)},
        "vs": vs,
        "movers": moved,
        "accounts": account_rows(data, base, as_of),
        "income": income,
        "flows": [f for f in data.flows if _in(f["date"], base, as_of, partial)][:LIST_CAP],
        "trades": trades[:LIST_CAP],
        "trade_count": len(trades),
        "realized": {"short_term": _r(st), "long_term": _r(lt), "total": _r(st + lt), "sales": len(sold)},
        "risk": risk,
        "decisions": decision_block(data, base, as_of, partial),
        "paper": paper_block(data, base, as_of),
        "fi": fi,
        "events": event_rows(data, base, as_of, partial, held),
    }
    pack["numbers"] = numbers(pack)
    return pack


def numbers(pack: dict) -> dict:
    v = pack["value"]
    out = {
        "start_value": v["start"],
        "end_value": v["end"],
        "change_usd": v["change_usd"],
        "change_pct": v["change_pct"],
        "net_flows": v["net_flows"],
        "gain_usd": v["gain_usd"],
        "dividends": pack["income"]["dividends"],
        "interest": pack["income"]["interest"],
        "margin_interest": pack["income"]["margin_interest"],
        "realized_st": pack["realized"]["short_term"],
        "realized_lt": pack["realized"]["long_term"],
        "trades": pack["trade_count"],
        "max_drawdown_pct": pack["risk"]["max_drawdown_pct"],
        "volatility_pct": pack["risk"]["volatility_pct"],
        "other_usd": pack["movers"]["other_usd"],
    }
    for row in pack["vs"]:
        out[f"vs.{row['id']}.pts"] = row["excess_pts"]
        out[f"vs.{row['id']}.return_pct"] = row["return_pct"]
        out[f"vs.{row['id']}.usd"] = row["diff_usd"]
    for row in pack["movers"]["up"] + pack["movers"]["down"]:
        out[f"contrib.{row['symbol']}.usd"] = row["contribution_usd"]
        out[f"ret.{row['symbol']}.pct"] = row["return_pct"]
        out[f"weight.{row['symbol']}.pct"] = row["weight_pct"]
    for c in pack["risk"]["convictions"]:
        out[f"weight.{c['symbol']}.pct"] = c["weight_pct"]
    for p in pack["paper"]:
        out[f"paper.{p['id']}.pct"] = p["return_pct"]
    if pack["fi"]:
        out["fi_progress_pct"] = pack["fi"]["progress_end_pct"]
        out["fi_change_pts"] = pack["fi"]["change_pts"]
    if pack["risk"]["band"]:
        out["band_worst_year_loss_pct"] = pack["risk"]["band"]["worst_year_loss_pct"]
        out["book_worst_year_p10_pct"] = pack["risk"]["band"]["worst_year_p10_pct"]
    for d in pack["decisions"]["matured"]:
        out[f"score.{d['id']}.{d['horizon']}.usd"] = d["usd"]
    return {k: v for k, v in out.items() if v is not None}


def digest(pack: dict) -> str:
    return hashlib.sha256(json.dumps(pack, sort_keys=True).encode()).hexdigest()[:16]


# ---- Job ----


def _settled(latest: str, now: datetime) -> str:
    t = now.astimezone(ET)
    today = t.date().isoformat()
    if latest < today or t.time() >= CLOSE_TIME or not trading_day(t.date()):
        return latest
    return (date.fromisoformat(latest) - timedelta(days=1)).isoformat()


SEEN_PATHS = {"full": "coverage.full", "base": "coverage.base", "v0": "value.start", "v1": "value.end", "pct": "value.change_pct"}
SEEN = ", ".join(["as_of"] + [f"json_extract(pack, '$.{path}') AS {name}" for name, path in SEEN_PATHS.items()])


def _backcast_end(desk: sqlite3.Connection) -> str | None:
    return desk.execute("SELECT max(date) FROM holdings_daily WHERE source=?", (BACKCAST,)).fetchone()[0]


def _revised(old: sqlite3.Row, data: Data, cast: str | None) -> bool:
    base = old["base"]
    if base is None:
        return False
    if not old["full"] and data.days[0] < base:
        return True
    if cast is None or base > cast:
        return False
    if any(abs((data.value.get(d) or 0.0) - (v or 0.0)) > 0.005 for d, v in ((base, old["v0"]), (old["as_of"], old["v1"]))):
        return True
    i0, i1 = data.index.get(base), data.index.get(old["as_of"])
    return bool(i0 and i1) and old["pct"] is not None and abs((i1 / i0 - 1) * 100 - old["pct"]) > 0.0001


def run(cfg: Config | None, mirror: sqlite3.Connection | None, desk: sqlite3.Connection, *, now: datetime | None = None, rebuild: bool = False) -> dict:
    now = now or datetime.now(UTC)
    data = load(cfg, mirror, desk)
    if len(data.days) < 2:
        return {"ok": True, "skipped": "The value series has under two days; run the daily engine first.", "written": 0}
    first, latest = data.days[0], data.days[-1]
    settled = _settled(latest, now)
    stamp = now.isoformat(timespec="seconds")
    have = {(r["kind"], r["end"]): r for r in desk.execute(f'SELECT kind, "end", final, version, {SEEN} FROM period_reviews')}
    cast = _backcast_end(desk)
    written: dict[str, int] = {}
    kept = 0
    rows = []
    for kind in KINDS:
        for start, end in periods(kind, first, latest):
            old = have.get((kind, end))
            if old and old["final"] and old["version"] == PACK_VERSION and not rebuild and not _revised(old, data, cast):
                kept += 1
                continue
            closed = end <= settled
            pack = build_pack(data, kind, start, end)
            if pack is None:
                continue
            rows.append((kind, start, end, pack["as_of"], int(closed), int(closed and latest > end), PACK_VERSION, digest(pack), json.dumps(pack), stamp))
            written[kind] = written.get(kind, 0) + 1
    with desk:
        desk.executemany("INSERT OR REPLACE INTO period_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        desk.execute("INSERT OR REPLACE INTO review_runs VALUES (1, ?, ?, ?)", (stamp, latest, sum(written.values())))
    return {"ok": True, "as_of": latest, "written": sum(written.values()), "kept": kept, "kinds": written}


# ---- Seam for the debrief desk ----


def _ready(conn: sqlite3.Connection) -> None:
    if not _has(conn, "review_runs") or not conn.execute("SELECT 1 FROM review_runs LIMIT 1").fetchone():
        raise NotReady("The review job has not run yet.")


def _latest(conn: sqlite3.Connection, kind: str) -> sqlite3.Row | None:
    return conn.execute('SELECT * FROM period_reviews WHERE kind=? ORDER BY "end" DESC LIMIT 1', (kind,)).fetchone()


def pending(cfg: Config) -> list[dict]:
    if not cfg.desk_db.exists():
        raise NotReady("The engine has not run yet.")
    conn = connect(cfg.desk_db, readonly=True)
    try:
        _ready(conn)
        out = []
        for kind in KINDS:
            r = _latest(conn, kind)
            if r is None:
                continue
            d = conn.execute('SELECT pack_digest FROM period_debriefs WHERE kind=? AND "end"=?', (kind, r["end"])).fetchone()
            if d and d[0] == r["digest"]:
                continue
            out.append(
                {
                    "kind": kind,
                    "start": r["start"],
                    "end": r["end"],
                    "closed": bool(r["closed"]),
                    "digest": r["digest"],
                    "debrief_digest": d[0] if d else None,
                    "pack": json.loads(r["pack"]),
                }
            )
    finally:
        conn.close()
    return out


def _text(result: dict, key: str, cap: int, errors: list[str]) -> None:
    if not isinstance(result.get(key), str) or not result[key].strip() or len(result[key]) > cap:
        errors.append(f"{key} must be text of at most {cap} characters")


def check(result: dict, pack: dict, current: str) -> list[str]:
    errors: list[str] = []
    for key, cap in LIMITS.items():
        _text(result, key, cap, errors)
    watch = result.get("watch")
    if not isinstance(watch, list) or len(watch) > WATCH_MAX or any(not isinstance(w, str) or not w.strip() or len(w) > WATCH_LEN for w in watch):
        errors.append(f"watch must be at most {WATCH_MAX} strings of at most {WATCH_LEN} characters")
    steps = result.get("next_steps")
    if not isinstance(steps, list) or len(steps) > STEPS_MAX:
        errors.append(f"next_steps must be a list of at most {STEPS_MAX}")
    else:
        for s in steps:
            ok = isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip() and len(s["text"]) <= STEP_LEN
            if not ok or not (s.get("symbol") is None or isinstance(s.get("symbol"), str)):
                errors.append(f"each next step needs text of at most {STEP_LEN} characters and a symbol or null")
                break
    cited = result.get("numbers_cited")
    if not isinstance(cited, list) or any(c not in pack["numbers"] for c in cited):
        errors.append("numbers_cited must list keys from the pack's numbers")
    if result.get("pack_digest") != current:
        errors.append("pack_digest is not the current digest of this pack")
    for key in ("model", "written_at"):
        if not isinstance(result.get(key), str) or not result[key]:
            errors.append(f"{key} is required")
    return errors


def record(cfg: Config, kind: str, end: str, result: dict) -> bool:
    if not cfg.desk_db.exists():
        raise NotReady("The engine has not run yet.")
    conn = connect(cfg.desk_db)
    try:
        _ready(conn)
        row = conn.execute('SELECT digest, pack FROM period_reviews WHERE kind=? AND "end"=?', (kind, end)).fetchone()
        if row is None:
            raise ValueError(f"no {kind} review ends {end}")
        errors = check(result or {}, json.loads(row["pack"]), row["digest"])
        if errors:
            raise ValueError("; ".join(errors))
        body = {k: result[k] for k in (*LIMITS, "watch", "numbers_cited")}
        body["next_steps"] = [{"text": s["text"].strip(), "symbol": (s.get("symbol") or None)} for s in result["next_steps"]]
        run_id = str(result["run_id"]) if result.get("run_id") is not None else None
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO period_debriefs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, end, row["digest"], json.dumps(body), result["written_at"], result["model"], run_id),
            )
    finally:
        conn.close()
    return True


# ---- API views ----


def _debrief(conn: sqlite3.Connection, kind: str, end: str) -> dict | None:
    d = conn.execute('SELECT * FROM period_debriefs WHERE kind=? AND "end"=?', (kind, end)).fetchone()
    if d is None:
        return None
    return json.loads(d["body"]) | {"model": d["model"], "written_at": d["written_at"], "pack_digest": d["pack_digest"]}


def review_view(conn: sqlite3.Connection | None, kind: str, end: str | None = None) -> dict:
    empty = {"kind": kind, "start": None, "end": end, "as_of": None, "closed": False, "final": False, "computed_at": None, "digest": None}
    empty |= {"pack": None, "debrief": None}
    if kind not in KINDS:
        return empty | {"note": f"kind must be one of {', '.join(KINDS)}"}
    if conn is None or not _has(conn, "period_reviews"):
        return empty | {"note": EMPTY_NOTE}
    row = conn.execute('SELECT * FROM period_reviews WHERE kind=? AND "end"=?', (kind, end)).fetchone() if end else _latest(conn, kind)
    if row is None:
        return empty | {"note": EMPTY_NOTE if end is None else f"No {kind} review ends {end}."}
    debrief = _debrief(conn, kind, row["end"])
    if debrief:
        debrief["stale"] = debrief["pack_digest"] != row["digest"]
    return {
        "kind": kind,
        "start": row["start"],
        "end": row["end"],
        "as_of": row["as_of"],
        "closed": bool(row["closed"]),
        "final": bool(row["final"]),
        "computed_at": row["computed_at"],
        "digest": row["digest"],
        "pack": json.loads(row["pack"]),
        "debrief": debrief,
    }


def index_view(conn: sqlite3.Connection | None) -> dict:
    out = {"as_of": None, "kinds": {k: [] for k in KINDS}, "note": EMPTY_NOTE}
    if conn is None or not _has(conn, "period_reviews"):
        return out
    told = {(r[0], r[1]) for r in conn.execute('SELECT kind, "end" FROM period_debriefs')}
    for kind in KINDS:
        sql = 'SELECT kind, start, "end", as_of, closed, final, pack FROM period_reviews WHERE kind=? ORDER BY "end" DESC LIMIT ?'
        for r in conn.execute(sql, (kind, INDEX_CAP[kind])):
            value = json.loads(r["pack"])["value"]
            out["kinds"][kind].append(
                {
                    "start": r["start"],
                    "end": r["end"],
                    "as_of": r["as_of"],
                    "label": label(kind, r["start"], r["end"]),
                    "closed": bool(r["closed"]),
                    "final": bool(r["final"]),
                    "change_usd": value["change_usd"],
                    "change_pct": value["change_pct"],
                    "has_debrief": (kind, r["end"]) in told,
                }
            )
    run_row = conn.execute("SELECT as_of FROM review_runs").fetchone() if _has(conn, "review_runs") else None
    out["as_of"] = run_row[0] if run_row else None
    if any(out["kinds"].values()):
        out["note"] = None
    return out
