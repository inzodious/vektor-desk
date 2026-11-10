import importlib
import math
import sqlite3
from datetime import date, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import discounts
from desk.engine.core import PROFILE_ERRORS, convictions, guess_kind, latest_plan, rules_in_force, symbol_kinds
from desk.engine.lots import current_lots
from desk.engine.source import closes as mirror_closes
from desk.engine.source import open_mirror
from desk.engine.tax import held_long

YEAR = 252
VOL_DAYS = 63
RISK_DAYS = 126
MIN_DAYS = 20
SIGMA_CAP = 0.45
DISCOUNT_DAYS = 5
SIGNALS = 3
STEPS = (10, 20, 30)
METHOD = "Add zone is one to two monthly swings under the last close, trim zone one to two above. A monthly swing is 63-session daily volatility × √21."
EMPTY_NOTE = "No holdings yet. Plan facts appear after the first engine run."


class NotReady(Exception):
    pass


# ---- Inputs ----


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _r(v, n: int = 4):
    return round(v, n) if isinstance(v, int | float) else None


def held(conn: sqlite3.Connection) -> tuple[str | None, dict[str, dict], float]:
    day = conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0] if _has(conn, "holdings_daily") else None
    if day is None:
        return None, {}, 0.0
    out: dict[str, dict] = {}
    total = 0.0
    for r in conn.execute("SELECT account, symbol, shares, close, value, cost, is_cash FROM holdings_daily WHERE date=?", (day,)):
        total += r["value"]
        if r["is_cash"]:
            continue
        h = out.setdefault(r["symbol"], {"shares": 0.0, "value": 0.0, "cost": 0.0, "costed": True, "close": r["close"], "accounts": []})
        h["shares"] += r["shares"]
        h["value"] += r["value"]
        h["costed"] = h["costed"] and r["cost"] is not None
        h["cost"] += r["cost"] or 0.0
        h["accounts"].append(r["account"])
    return day, out, total


def prices(conn: sqlite3.Connection, mirror_series: dict, symbol: str) -> list[tuple[str, float]]:
    px = discounts.series(conn, symbol)
    if len(px) >= 2:
        return px
    return sorted((d, adj or c) for d, (c, adj) in (mirror_series.get(symbol) or {}).items() if c)


def names(conn: sqlite3.Connection) -> dict[str, str]:
    out = {}
    if _has(conn, "sec_tickers"):
        out |= {r[0]: r[1] for r in conn.execute("SELECT symbol, title FROM sec_tickers") if r[1]}
    if _has(conn, "sym_profiles"):
        out |= {r[0]: r[1] for r in conn.execute("SELECT symbol, name FROM sym_profiles") if r[1]}
    return out


def kinds_of(mirror: sqlite3.Connection | None, conn: sqlite3.Connection, symbols: set[str]) -> dict[str, str]:
    kinds = symbol_kinds(mirror, {}, conn) if mirror is not None else {}
    funds = {r[0] for r in conn.execute("SELECT symbol FROM sec_funds")} if _has(conn, "sec_funds") else set()
    titles = {r[0]: r[1] or "" for r in conn.execute("SELECT symbol, title FROM sec_tickers")} if _has(conn, "sec_tickers") else {}
    for s in symbols:
        if kinds.get(s, "unknown") == "unknown":
            kinds[s] = guess_kind(s, funds, titles)
    return kinds


# ---- Measures ----


def stats(px: list[tuple[str, float]]) -> dict:
    if not px:
        return {}
    closes = [p for _, p in px]
    last = closes[-1]
    out = {"price": last}
    if len(closes) < MIN_DAYS:
        return out
    year = closes[-YEAR:]
    rets = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False)][-VOL_DAYS:]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    high, low = max(year), min(year)
    out |= {
        "day_move_pct": (closes[-1] / closes[-2] - 1) * 100,
        "high_52w": high,
        "low_52w": low,
        "drop_from_high_pct": (last / high - 1) * 100,
        "above_low_pct": (last / low - 1) * 100,
        "vol_annual_pct": sd * math.sqrt(YEAR) * 100,
        "sigma_month_pct": min(sd * math.sqrt(21), SIGMA_CAP) * 100,
    }
    for n in (50, 200):
        if len(closes) >= n:
            avg = sum(closes[-n:]) / n
            out |= {f"sma_{n}": avg, f"vs_sma_{n}_pct": (last / avg - 1) * 100}
    if len(closes) > YEAR:
        out["ret_1y_pct"] = (last / closes[-YEAR - 1] - 1) * 100
    return out


def zones(s: dict, cost_per_share: float | None) -> dict | None:
    if "sigma_month_pct" not in s:
        return None
    price, sigma = s["price"], s["sigma_month_pct"] / 100
    levels = {
        "price": price,
        "high_52w": s["high_52w"],
        "low_52w": s["low_52w"],
        "sma_50": s.get("sma_50"),
        "sma_200": s.get("sma_200"),
        "cost_per_share": cost_per_share,
    }
    levels |= {f"down_{n}_from_high": s["high_52w"] * (1 - n / 100) for n in STEPS}
    return {
        "method": METHOD,
        "sigma_month_pct": _r(s["sigma_month_pct"]),
        "add": {"low": _r(price * (1 - 2 * sigma)), "high": _r(price * (1 - sigma))},
        "trim": {"low": _r(price * (1 + sigma)), "high": _r(price * (1 + 2 * sigma))},
        "levels": {k: _r(v) for k, v in levels.items() if v is not None},
    }


def risk_shares(series: dict[str, list[tuple[str, float]]], weights: dict[str, float]) -> dict[str, float]:
    rets: dict[str, dict[str, float]] = {}
    for sym, px in series.items():
        if weights.get(sym) and len(px) > MIN_DAYS:
            tail = px[-RISK_DAYS - 1 :]
            rets[sym] = {d: b / a - 1 for (_, a), (d, b) in zip(tail, tail[1:], strict=False) if a}
    days = sorted({d for r in rets.values() for d in r})[-RISK_DAYS:]
    if len(days) < MIN_DAYS:
        return {}
    book = [sum(weights[s] * r.get(d, 0.0) for s, r in rets.items()) for d in days]
    mean = sum(book) / len(book)
    var = sum((x - mean) ** 2 for x in book)
    if not var:
        return {}
    out = {}
    for sym, r in rets.items():
        mine = [r.get(d, 0.0) for d in days]
        m = sum(mine) / len(mine)
        out[sym] = weights[sym] * sum((a - m) * (b - mean) for a, b in zip(mine, book, strict=True)) / var * 100
    return out


def lot_rows(lots: list[dict], price: float | None, as_of: str) -> list[dict]:
    out = []
    for lot in sorted(lots, key=lambda x: (x.get("acquired") or "", x["account"])):
        acquired, shares, cost = lot.get("acquired"), lot["shares"], lot.get("cost")
        long_on = None
        if acquired:
            a = date.fromisoformat(acquired)
            try:
                anniversary = a.replace(year=a.year + 1)
            except ValueError:
                anniversary = a.replace(year=a.year + 1, day=28)
            long_on = (anniversary + timedelta(days=1)).isoformat()
        is_long = held_long(acquired, as_of)
        value = shares * price if price else None
        out.append(
            {
                "account": lot["account"],
                "acquired": acquired,
                "shares": _r(shares, 6),
                "cost": _r(cost, 2),
                "cost_per_share": _r(cost / shares) if cost is not None and shares else None,
                "value": _r(value, 2),
                "gain": _r(value - cost, 2) if value is not None and cost is not None else None,
                "term": None if is_long is None else ("long" if is_long else "short"),
                "long_term_on": long_on,
                "days_to_long_term": None if long_on is None else max(0, (date.fromisoformat(long_on) - date.fromisoformat(as_of)).days),
                "quality": lot.get("quality") or "ok",
            }
        )
    return out


# ---- Bands ----


def _profile(cfg: Config | None) -> dict | None:
    try:
        from desk.decisions import risk

        return risk.current(cfg) if cfg is not None else None
    except Exception:
        return None


def _plan_bands(cfg: Config | None) -> dict[str, dict]:
    try:
        rows = importlib.import_module("desk.decisions.plans").approved_plans(cfg) if cfg is not None else []
    except Exception:
        return {}
    items = rows.values() if isinstance(rows, dict) else rows
    return {str(p["symbol"]).upper(): p["weight_band"] for p in items if isinstance(p, dict) and p.get("symbol") and isinstance(p.get("weight_band"), dict)}


def band(symbol: str, weight: float, kind: str, conv: dict, rules: list[dict], profile: dict | None, plan_bands: dict) -> dict:
    lo, hi, source = None, None, "none"
    plan = plan_bands.get(symbol)
    if plan and isinstance(plan.get("max_pct"), int | float):
        lo, hi, source = float(plan.get("min_pct") or 0.0), float(plan["max_pct"]), "plan"
    elif symbol in conv:
        (lo, hi), source = conv[symbol], "conviction"
    elif kind == "stock":
        rule = next((r for r in rules if r.get("kind") == "single_stock_band" and r.get("enabled", True)), None)
        cap = (rule.get("params") or {}).get("max_pct") if rule else None
        if isinstance(cap, int | float):
            lo, hi, source = float((rule.get("params") or {}).get("min_pct") or 0.0), float(cap), "single_stock_band"
        elif profile and isinstance(profile.get("single_stock_max_pct"), int | float):
            lo, hi, source = 0.0, float(profile["single_stock_max_pct"]), "risk_band"
    status = "inside"
    if hi is not None and weight > hi:
        status = "over"
    elif lo is not None and weight < lo and weight > 0:
        status = "under"
    return {
        "source": source,
        "min_pct": lo,
        "max_pct": hi,
        "weight_pct": _r(weight),
        "status": status,
        "room_pct": _r(hi - weight) if hi is not None else None,
        "risk_band": {"band": profile.get("band"), "label": profile.get("label"), "single_stock_max_pct": profile.get("single_stock_max_pct")}
        if profile
        else None,
    }


# ---- Rows ----


def _discount(conn: sqlite3.Connection, symbol: str, as_of: str) -> dict:
    empty = {"active": False, "signal_id": None, "reason": None, "as_of": None}
    if not _has(conn, "discount_signals"):
        return empty
    cut = (date.fromisoformat(as_of) - timedelta(days=DISCOUNT_DAYS)).isoformat()
    r = conn.execute(
        "SELECT signal_id, reason, as_of FROM discount_signals WHERE symbol=? AND as_of >= ? ORDER BY as_of DESC LIMIT 1", (symbol, cut)
    ).fetchone()
    return {"active": True, "signal_id": r["signal_id"], "reason": r["reason"], "as_of": r["as_of"]} if r else empty


def _earnings(conn: sqlite3.Connection, symbol: str, as_of: str) -> dict | None:
    if not _has(conn, "earnings"):
        return None
    r = conn.execute("SELECT date, hour, eps_estimate FROM earnings WHERE symbol=? AND date >= ? ORDER BY date LIMIT 1", (symbol, as_of)).fetchone()
    return (
        {"date": r["date"], "hour": r["hour"], "eps_estimate": r["eps_estimate"], "days": (date.fromisoformat(r["date"]) - date.fromisoformat(as_of)).days}
        if r
        else None
    )


def _signals(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    if not _has(conn, "filing_signals"):
        return []
    sql = (
        "SELECT accession, form, filed_at, direction, confidence, event_type, horizon_days, rationale "
        "FROM filing_signals WHERE symbol=? ORDER BY filed_at DESC, accession LIMIT ?"
    )
    return [dict(r) for r in conn.execute(sql, (symbol, SIGNALS))]


def _wash(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    if not _has(conn, "wash_windows"):
        return []
    return [dict(r) for r in conn.execute("SELECT kind, date, clears, account, amount FROM wash_windows WHERE symbol=? ORDER BY clears, kind", (symbol,))]


def build(cfg: Config | None, mirror: sqlite3.Connection | None, conn: sqlite3.Connection, symbol: str | None = None) -> tuple[str | None, list[dict]]:
    as_of, book, total = held(conn)
    if as_of is None:
        return None, []
    wanted = sorted(book) if symbol is None else [symbol.upper()]
    mirror_series = mirror_closes(mirror) if mirror is not None else {}
    series = {s: prices(conn, mirror_series, s) for s in sorted(set(book) | set(wanted))}
    weights = {s: h["value"] / total for s, h in book.items()} if total else {}
    shares_of_risk = risk_shares(series, weights)
    plan = latest_plan(mirror) if mirror is not None else {}
    try:
        rules = rules_in_force(cfg, plan)[0] if cfg is not None else []
    except PROFILE_ERRORS:
        rules = []
    kinds = kinds_of(mirror, conn, set(book) | set(wanted))
    conv, profile, plan_bands, titles = convictions(rules), _profile(cfg), _plan_bands(cfg), names(conn)
    lots: dict[str, list[dict]] = {}
    for lot in current_lots(conn):
        lots.setdefault(lot["symbol"], []).append(lot)
    rows = []
    for sym in wanted:
        h = book.get(sym) or {"shares": 0.0, "value": 0.0, "cost": 0.0, "costed": False, "close": None, "accounts": []}
        px = series.get(sym) or []
        s = stats(px)
        price = h["close"] or s.get("price")
        mine = lot_rows(lots.get(sym, []), price, as_of)
        lot_cost = sum(x["cost"] for x in mine if x["cost"] is not None) if mine and all(x["cost"] is not None for x in mine) else None
        cost = lot_cost if lot_cost is not None else (h["cost"] if h["costed"] and h["shares"] else None)
        weight = weights.get(sym, 0.0) * 100
        value = h["value"]
        cps = cost / h["shares"] if cost is not None and h["shares"] else None
        z = zones(s | ({"price": price} if price else {}), cps) if price else None
        val = discounts.valuation(conn, sym, px) if len(px) >= MIN_DAYS else None
        numbers = {
            "price": price,
            "shares": h["shares"],
            "value": value,
            "weight_pct": weight,
            "cost_basis": cost,
            "cost_per_share": cps,
            "unrealized_usd": value - cost if cost is not None else None,
            "unrealized_pct": (value / cost - 1) * 100 if cost else None,
            "long_term_shares": sum(x["shares"] for x in mine if x["term"] == "long") if mine else None,
            "short_term_shares": sum(x["shares"] for x in mine if x["term"] == "short") if mine else None,
            "long_term_gain": sum(x["gain"] or 0.0 for x in mine if x["term"] == "long") if mine else None,
            "short_term_gain": sum(x["gain"] or 0.0 for x in mine if x["term"] == "short") if mine else None,
            "risk_share_pct": shares_of_risk.get(sym),
            "valuation_value": val["value"] if val else None,
            "valuation_pctile": val["pctile_own"] if val else None,
        }
        numbers |= {k: v for k, v in s.items() if k != "price"}
        if z:
            numbers |= {"add_low": z["add"]["low"], "add_high": z["add"]["high"], "trim_low": z["trim"]["low"], "trim_high": z["trim"]["high"]}
        rows.append(
            {
                "symbol": sym,
                "name": titles.get(sym),
                "kind": kinds.get(sym, "unknown"),
                "as_of": as_of,
                "price_as_of": px[-1][0] if px else None,
                "held": bool(h["shares"]),
                "accounts": sorted(set(h["accounts"])),
                "numbers": {k: _r(v) for k, v in numbers.items() if v is not None},
                "lots": mine,
                "wash_windows": _wash(conn, sym),
                "zones": z,
                "discount": _discount(conn, sym, as_of),
                "next_earnings": _earnings(conn, sym, as_of),
                "filing_signals": _signals(conn, sym),
                "valuation": val,
                "band": band(sym, weight, kinds.get(sym, "unknown"), conv, rules, profile, plan_bands),
            }
        )
    return as_of, rows


def facts(cfg: Config, symbol: str | None = None) -> list[dict]:
    if not cfg.desk_db.exists():
        raise NotReady("The engine has not run yet.")
    conn = connect(cfg.desk_db, readonly=True)
    mirror = open_mirror(cfg)
    try:
        as_of, rows = build(cfg, mirror, conn, symbol)
    finally:
        conn.close()
        if mirror is not None:
            mirror.close()
    if as_of is None:
        raise NotReady("The engine has not run yet.")
    return rows


def view(cfg: Config, symbol: str | None = None) -> dict:
    try:
        rows = facts(cfg, symbol)
    except NotReady:
        return {"as_of": None, "rows": [], "note": EMPTY_NOTE}
    return {"as_of": rows[0]["as_of"] if rows else None, "rows": rows, "note": None if rows else EMPTY_NOTE}
