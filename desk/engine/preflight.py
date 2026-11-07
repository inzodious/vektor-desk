import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.decisions.profile import active_profile
from desk.engine import ENGINE_VERSION, schema
from desk.engine.core import (
    PROFILE_ERRORS,
    deposit_split,
    env_float,
    latest_plan,
    marginal_rate,
    next_deposit,
    plan_targets,
    rules_in_force,
    symbol_kinds,
    symbol_weights,
)
from desk.engine.lots import current_lots
from desk.engine.market import latest_close
from desk.engine.source import closes, current_rows, open_mirror
from desk.engine.tax import LOT_METHODS, pick_lots, shared, split_gain, wash_check, wash_windows

LAMPS = (
    ("concentration", "Concentration"),
    ("drift_after", "Drift after"),
    ("funding", "Funding"),
    ("wash_sales", "Wash sales"),
    ("lots_tax", "Lots and tax"),
    ("plan_rules", "Plan rules"),
)
RANK = {"ok": 0, "watch": 1, "act": 2}
STATUS = {0: "clear", 1: "flagged", 2: "blocked"}
SELL_KINDS = ("sell", "trim", "harvest")


class PreflightError(ValueError):
    pass


@dataclass
class Context:
    as_of: str
    rows: list[dict]
    targets: dict[str, float] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)
    prices: dict[str, float] = field(default_factory=dict)
    lots: list[dict] = field(default_factory=list)
    has_lots: bool = False
    windows: list[dict] = field(default_factory=list)
    upcoming: list[tuple[str, str, float]] = field(default_factory=list)
    wash_accounts: list[str] = field(default_factory=list)
    lot_method: str = "highest_cost"
    margin_rate: float | None = None
    maint: float = 30.0
    next_deposit: tuple[float | None, str | None] = (None, None)
    satellite_cap: float | None = None
    tax_rate: float | None = None
    quality: str = "ok"


# ---- Picture before and after ----


def picture(rows: list[dict], ctx: Context) -> dict:
    total = sum(r["value"] for r in rows)
    weights = symbol_weights(rows, total)
    singles = {s: w for s, w in weights.items() if ctx.kinds.get(s, "unknown") == "stock" and s not in ctx.targets}
    drift = {s: weights.get(s, 0.0) - t * 100 for s, t in ctx.targets.items()}
    debit, gross, call = 0.0, {}, {}
    for r in rows:
        gross.setdefault(r["account"], [0.0, 0.0])
        if r["is_cash"] and r["value"] < 0:
            gross[r["account"]][0] -= r["value"]
        else:
            gross[r["account"]][1] += r["value"]
    for acct, (d, v) in gross.items():
        debit += d
        if d > 0 and v > 0:
            call[acct] = max(0.0, 1 - d / ((1 - ctx.maint / 100) * v)) * 100
    cash = sum(r["value"] for r in rows if r["is_cash"])
    return {
        "total": total,
        "weights": weights,
        "singles": singles,
        "single_stock": sum(singles.values()),
        "top1": max(weights.values(), default=0.0),
        "drift": drift,
        "drift_max": max((abs(v) for v in drift.values()), default=None),
        "debit": debit,
        "call_drop": call,
        "cash_share": cash / total * 100 if total else None,
    }


def _match(want: str, key: str) -> bool:
    w, k = want.lower().replace(" ", ""), key.lower().replace(" ", "")
    return w in k or k in w


def pick_account(want: str | None, rows: list[dict], symbol: str, side: str) -> str:
    accounts = sorted({r["account"] for r in rows})
    held = defaultdict(float)
    for r in rows:
        if r["symbol"] == symbol and r["value"] > 0:
            held[r["account"]] += r["value"]
    holding = sorted(held, key=lambda a: -held[a])
    if want:
        hits = [a for a in accounts if _match(want, a)]
        if hits:
            return next((a for a in hits if a in holding), hits[0])
        return want
    if side == "sell" and holding:
        return holding[0]
    return next((a for a in accounts if a.startswith("individual")), accounts[0] if accounts else "individual")


def apply_trade(rows: list[dict], t: dict) -> list[dict]:
    after = [dict(r) for r in rows]
    acct, symbol, amount, shares = t["account"], t["symbol"], t["amount_usd"], t["shares"]
    pos = next((r for r in after if r["account"] == acct and r["symbol"] == symbol and not r["is_cash"]), None)
    if pos is None:
        pos = {"account": acct, "symbol": symbol, "shares": 0.0, "value": 0.0, "is_cash": 0}
        after.append(pos)
    cash = max((r for r in after if r["account"] == acct and r["is_cash"]), key=lambda r: r["value"], default=None)
    if cash is None:
        cash = {"account": acct, "symbol": "CASH", "shares": 0.0, "value": 0.0, "is_cash": 1}
        after.append(cash)
    if t["side"] == "buy":
        pos["value"] += amount
        pos["shares"] += shares
        if t["funding"] != "deposit":
            cash["value"] -= amount
    else:
        pos["value"] -= amount
        pos["shares"] -= shares
        cash["value"] += amount
    return after


# ---- Lamps ----


def _band(ctx: Context, symbol: str) -> float | None:
    caps = [r.get("params", {}).get("max_pct") for r in ctx.rules if r.get("kind") == "single_stock_band" and (not r.get("symbols") or symbol in r["symbols"])]
    caps = [c for c in caps if isinstance(c, int | float)]
    return min(caps) if caps else ctx.satellite_cap


def _has_rule(ctx: Context, kind: str) -> dict | None:
    return next((r for r in ctx.rules if r.get("kind") == kind), None)


def lamp_concentration(ctx, t, before, after):
    s, side = t["symbol"], t["side"]
    b, a = before["weights"].get(s, 0.0), after["weights"].get(s, 0.0)
    kind = ctx.kinds.get(s, "unknown")
    if kind == "stock" and s not in ctx.targets:
        if side == "buy" and b == 0 and _has_rule(ctx, "no_new_single_stocks"):
            return "act", f"{s} would be a new single stock, and the rules say no new ones.", b, a
        total_b, total_a = before["single_stock"], after["single_stock"]
        if side == "buy" and ctx.satellite_cap is not None and total_a > ctx.satellite_cap and total_a > total_b:
            return "act", f"Single stocks would be {total_a:.1f}% of the portfolio, past the {ctx.satellite_cap:g}% satellite cap.", b, a
        cap = _band(ctx, s)
        if cap is not None and a > cap and a > b:
            return ("act" if side == "buy" else "watch"), f"{s} would be {a:.1f}% of the portfolio, past its {cap:g}% band.", b, a
        return "ok", f"{s} goes from {b:.1f}% to {a:.1f}%.", b, a
    if kind == "unknown" and s not in ctx.targets and side == "buy":
        return "watch", f"Not sure whether {s} is a fund or a single stock, so its band can't be checked.", b, a
    return "ok", f"{s} goes from {b:.1f}% to {a:.1f}%; the largest holding would be {after['top1']:.1f}%.", b, a


def lamp_drift(ctx, t, before, after):
    b, a = before["drift_max"], after["drift_max"]
    if b is None:
        return "ok", "No plan mix to drift from yet.", b, a
    rule = _has_rule(ctx, "drift_max_pts")
    limit = (rule or {}).get("params", {}).get("pts", 5)
    if a > limit and a > b + 0.05:
        return "watch", f"Largest drift grows from {b:.1f} to {a:.1f} points, past the {limit:g}-point limit.", b, a
    if a < b - 0.05:
        return "ok", f"Closes drift from {b:.1f} to {a:.1f} points.", b, a
    return "ok", f"Largest drift stays near {a:.1f} points.", b, a


def lamp_funding(ctx, t, before, after):
    b, a = before["debit"], after["debit"]
    added = a - b
    if t["side"] == "buy" and (t["funding"] == "margin" or added > 0.005):
        cost = added * ctx.margin_rate / 100 * 30 / 360 if ctx.margin_rate is not None else None
        money = f", about ${cost:,.0f} a month in interest." if cost is not None else ". Set DESK_MARGIN_RATE_PCT to see the interest in dollars."
        covered = t["amount_usd"] - added
        lead = f"Cash covers ${covered:,.0f}; the other ${added:,.0f} goes on margin" if covered > 0.5 else f"All ${added:,.0f} goes on margin"
        drop = after["call_drop"].get(t["account"])
        tail = f" A {drop:.0f}% drop would bring a margin call." if drop is not None else ""
        return "act", f"{lead}{money}{tail}", b, a
    if t["side"] == "buy" and t["funding"] == "deposit":
        _, when = ctx.next_deposit
        return "ok", f"Waits for the {when} deposit." if when else "Paid from a deposit.", b, a
    if t["side"] == "sell" and b > 0:
        return "ok", f"Proceeds pay the margin debit down from ${b:,.0f} to ${a:,.0f}.", b, a
    return "ok", "Paid from settled cash." if t["side"] == "buy" else "Proceeds go to cash.", b, a


def lamp_lots(ctx, t, before, after):
    if t["side"] == "buy":
        return "ok", f"Opens a new lot at about ${t['price']:,.2f}.", None, None, None
    lots = [lot for lot in ctx.lots if lot["symbol"] == t["symbol"] and _match(t["account"], lot["account"])]
    if not ctx.has_lots or not lots:
        tax = {"lot_method": t["lot_method"], "lots": []}
        return "watch", "No lot export for this holding yet, so the gain and lot pick can't be checked.", None, None, tax
    picked, short = pick_lots(lots, t["shares"], t["price"], t["lot_method"], ctx.as_of)
    st, lt = split_gain(picked)
    tax = {"lot_method": t["lot_method"], "lots": picked, "realized_st": st, "realized_lt": lt, "realized": round(st + lt, 2)}
    words = f"Short-term {_usd(st)}, long-term {_usd(lt)} using {t['lot_method'].replace('_', ' ')} lots."
    if short > 0:
        return "watch", f"The lot export covers {t['shares'] - short:g} of {t['shares']:g} shares; export lots again. {words}", st + lt, None, tax
    if t["kind"] == "harvest" and st + lt >= 0:
        return "watch", f"This sale realizes a gain, not a loss. {words}", st + lt, None, tax
    return "ok", words, st + lt, None, tax


def _usd(v: float) -> str:
    return f"-${-v:,.0f}" if v < 0 else f"${v:,.0f}"


def rule_state(rule: dict, pic: dict, t: dict | None, ctx: Context, before: dict) -> tuple[bool | None, float | None]:
    kind, p = rule.get("kind"), rule.get("params") or {}
    if kind == "single_stock_band":
        names = rule.get("symbols") or list(pic["singles"])
        worst = max((pic["singles"].get(s, 0.0) for s in names), default=0.0)
        return all(p.get("min_pct", 0) <= pic["singles"].get(s, 0.0) <= p.get("max_pct", 100) for s in names), worst
    if kind == "drift_max_pts":
        return (None, None) if pic["drift_max"] is None else (pic["drift_max"] <= p.get("pts", 5), pic["drift_max"])
    if kind == "cash_floor_pct":
        return (None, None) if pic["cash_share"] is None else (pic["cash_share"] >= p.get("pct", 0), -pic["cash_share"])
    if kind == "no_margin_buys":
        if t is None or t["side"] != "buy":
            return True, None
        return not (t["funding"] == "margin" or pic["debit"] > before["debit"] + 0.005), None
    if kind == "no_new_single_stocks":
        if t is None or t["side"] != "buy":
            return True, None
        s = t["symbol"]
        return not (ctx.kinds.get(s) == "stock" and s not in ctx.targets and before["weights"].get(s, 0.0) == 0), None
    return None, None


def lamp_rules(ctx, t, before, after):
    broke, stale, checked = [], [], 0
    for rule in ctx.rules:
        b_ok, b_m = rule_state(rule, before, None, ctx, before)
        a_ok, a_m = rule_state(rule, after, t, ctx, before)
        if a_ok is None:
            continue
        checked += 1
        if a_ok:
            continue
        worse = b_ok or (a_m is not None and b_m is not None and a_m > b_m + 1e-6) or rule.get("kind") in ("no_margin_buys", "no_new_single_stocks")
        (broke if worse else stale).append(rule["id"])
    if broke:
        return ("act" if t["side"] == "buy" else "watch"), f"Breaks {', '.join(broke)}.", checked - len(broke) - len(stale), checked - len(broke) - len(stale)
    if stale:
        return "watch", f"Already off before this trade, and no worse: {', '.join(stale)}.", checked - len(stale), checked - len(stale)
    return "ok", f"All {checked} rules hold.", checked, checked


# ---- Preflight ----


def normalize(trade: dict, ctx: Context) -> dict:
    symbol = str(trade.get("symbol") or "").upper().strip()
    kind = str(trade.get("kind") or "").lower()
    side = trade.get("side") or ("sell" if kind in SELL_KINDS else "buy" if kind in ("buy", "deposit_route") else None)
    if side not in ("buy", "sell", None):
        raise PreflightError("side must be buy or sell")
    funding = str(trade.get("funding") or ("deposit" if kind == "deposit_route" else "cash")).lower()
    method = str(trade.get("lot_method") or ctx.lot_method).lower()
    method = method if method in LOT_METHODS else "highest_cost"
    out = {"kind": kind or side, "symbol": symbol, "side": side, "funding": funding, "lot_method": method}
    if side is None:
        return {**out, "account": trade.get("account"), "shares": None, "amount_usd": None, "price": ctx.prices.get(symbol)}
    if not symbol:
        raise PreflightError("A trade needs a symbol")
    out["account"] = pick_account(trade.get("account"), ctx.rows, symbol, side)
    price = trade.get("limit") if isinstance(trade.get("limit"), int | float) and trade["limit"] > 0 else ctx.prices.get(symbol)
    shares, amount = trade.get("shares"), trade.get("amount_usd")
    if not price:
        raise PreflightError(f"No price for {symbol} yet")
    if side == "sell" and not shares and not amount:
        held = sum(r["shares"] for r in ctx.rows if r["account"] == out["account"] and r["symbol"] == symbol)
        shares = held if held > 0 else None
    if shares:
        amount = float(shares) * price
    elif amount:
        shares = float(amount) / price
    else:
        raise PreflightError("A trade needs shares or a dollar amount")
    if side == "sell":
        held = sum(r["shares"] for r in ctx.rows if r["account"] == out["account"] and r["symbol"] == symbol)
        if held <= 0:
            raise PreflightError(f"{symbol} is not held in {out['account']}")
        if shares > held + 1e-6:
            shares, amount = held, held * price
    return {**out, "shares": round(float(shares), 6), "amount_usd": round(float(amount), 2), "price": round(float(price), 4)}


def preflight(ctx: Context, trade: dict) -> dict:
    t = normalize(trade, ctx)
    before = picture(ctx.rows, ctx)
    if t["side"] is None:
        lights = [{"id": i, "label": label, "status": "ok", "before": None, "after": None, "detail": "Nothing to trade."} for i, label in LAMPS]
        return _result(ctx, t, lights, before, before, {"wash_clear_date": None})
    after = picture(apply_trade(ctx.rows, t), ctx)
    lights = []
    for (lamp_id, label), fn in zip(LAMPS[:3], (lamp_concentration, lamp_drift, lamp_funding), strict=True):
        status, detail, b, a = fn(ctx, t, before, after)
        lights.append({"id": lamp_id, "label": label, "status": status, "before": _r(b), "after": _r(a), "detail": detail})
    l_status, l_detail, gain, _, tax = lamp_lots(ctx, t, before, after)
    tax = tax or {"lot_method": t["lot_method"], "lots": []}
    loss = t["side"] == "sell" and (gain < 0 if gain is not None else t["kind"] == "harvest")
    windows = shared(ctx.windows, ctx.wash_accounts, t["account"])
    w_status, w_detail, clear = wash_check(t["symbol"], t["side"], loss, windows, ctx.upcoming, ctx.as_of)
    if t["side"] == "sell" and loss:
        tax["harvest_loss"] = round(-gain, 2) if gain is not None else None
        tax["harvest_value"] = round(-gain * ctx.tax_rate / 100, 2) if gain is not None and ctx.tax_rate is not None else None
    tax["wash_clear_date"] = clear if (t["side"] == "buy" and w_status != "ok") or loss else None
    lights.append({"id": "wash_sales", "label": "Wash sales", "status": w_status, "before": None, "after": None, "detail": w_detail, "clears": clear})
    lights.append({"id": "lots_tax", "label": "Lots and tax", "status": l_status, "before": None, "after": _r(gain), "detail": l_detail})
    r_status, r_detail, b, a = lamp_rules(ctx, t, before, after)
    lights.append({"id": "plan_rules", "label": "Plan rules", "status": r_status, "before": b, "after": a, "detail": r_detail})
    return _result(ctx, t, lights, before, after, tax)


def _r(v):
    return None if v is None else round(float(v), 4)


def _result(ctx, t, lights, before, after, tax) -> dict:
    worst = max((RANK[light["status"]] for light in lights), default=0)
    acct = t.get("account")
    rows = [
        ("value.market", before["total"], after["total"], "ok"),
        ("risk.top1", before["top1"], after["top1"], _flag(lights, "concentration")),
        ("plan.single_stock", before["single_stock"], after["single_stock"], _flag(lights, "concentration")),
        ("plan.drift_max", before["drift_max"], after["drift_max"], _flag(lights, "drift_after")),
        ("margin.debit", before["debit"], after["debit"], _flag(lights, "funding")),
        ("margin.cost_month", _month_cost(ctx, before["debit"]), _month_cost(ctx, after["debit"]), _flag(lights, "funding")),
        ("margin.call_drop", before["call_drop"].get(acct), after["call_drop"].get(acct), _flag(lights, "funding")),
        ("cash.share", before["cash_share"], after["cash_share"], "ok"),
    ]
    if tax.get("realized") is not None:
        rows.append(("tax.realized", None, tax["realized"], _flag(lights, "lots_tax")))
    return {
        "status": STATUS[worst],
        "as_of": ctx.as_of,
        "engine_version": ENGINE_VERSION,
        "quality": ctx.quality,
        "trade": t,
        "lights": lights,
        "tax": tax,
        "metrics": [{"metric_id": m, "before": _r(b), "after": _r(a), "flag": f} for m, b, a, f in rows],
    }


def _month_cost(ctx: Context, debit: float) -> float | None:
    return round(debit * ctx.margin_rate / 100 * 30 / 360, 2) if ctx.margin_rate is not None else None


def _flag(lights, lamp_id) -> str:
    return next((light["status"] for light in lights if light["id"] == lamp_id), "ok")


# ---- Loading and storing ----


def load_context(cfg: Config, mirror: sqlite3.Connection | None, desk: sqlite3.Connection, *, now: datetime | None = None) -> Context:
    now = now or datetime.now(UTC)
    day = desk.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        raise PreflightError("No holdings yet; the engine has not run")
    rows = [dict(r) for r in desk.execute("SELECT * FROM holdings_daily WHERE date=?", (day,))]
    plan = latest_plan(mirror) if mirror else {}
    targets = plan_targets(plan)
    kinds = symbol_kinds(mirror, targets, desk) if mirror else dict.fromkeys(targets, "fund")
    rules, _ = rules_in_force(cfg, plan)
    try:
        profile = active_profile(cfg)
        tax = profile.get("tax", default={}) or {}
        cap = profile.get("opportunity", "satellite_cap_pct")
    except PROFILE_ERRORS:
        tax, cap = {}, None
    has_lots = desk.execute("SELECT 1 FROM lot_files WHERE kind='lots' LIMIT 1").fetchone() is not None
    lots = current_lots(desk) if has_lots else []
    realized_rows = [dict(r) for r in desk.execute("SELECT * FROM realized_lots")]
    activity = list(current_rows(mirror, "activity")) if mirror else []
    today = max(day, now.date().isoformat())
    ctx = Context(as_of=day, rows=rows, targets=targets, kinds=kinds, rules=rules, lots=lots, has_lots=has_lots)
    ctx.windows = wash_windows(activity, realized_rows, lots, today)
    ctx.wash_accounts = list(tax.get("wash_sale_accounts") or [])
    ctx.lot_method = tax.get("lot_method") or "highest_cost"
    ctx.margin_rate = env_float("DESK_MARGIN_RATE_PCT")
    ctx.satellite_cap = float(cap) if isinstance(cap, int | float) else None
    federal, state, _ = marginal_rate(cfg, mirror)
    ctx.tax_rate = None if federal is None else federal + state
    ctx.maint = env_float("DESK_MARGIN_MAINT_PCT") or 30.0
    ctx.quality = "pro_forma" if any(r["quality"] != "ok" for r in rows) else "ok"
    ctx.prices = _prices(desk, mirror, rows, now)
    ctx.next_deposit = next_deposit(cfg, plan, day, now)
    amount, when = ctx.next_deposit
    if amount and when and targets:
        weights = symbol_weights(rows, sum(r["value"] for r in rows))
        ctx.upcoming = [(when, s, usd) for s, usd in deposit_split(targets, weights, sum(r["value"] for r in rows), amount).items()]
    since = (date.fromisoformat(today) - timedelta(days=120)).isoformat()
    reinvest = {str(a.get("symbol") or "").upper() for a in activity if a.get("kind") == "reinvest" and str(a.get("date") or "") >= since}
    upcoming_day = (date.fromisoformat(today) + timedelta(days=30)).isoformat()
    ctx.upcoming += [(upcoming_day, s, 1.0) for s in sorted(reinvest)]
    return ctx


def _prices(desk: sqlite3.Connection, mirror: sqlite3.Connection | None, rows: list[dict], now: datetime) -> dict[str, float]:
    out = {s: ds[max(ds)][0] for s, ds in (closes(mirror) if mirror else {}).items() if ds}
    out.update({r["symbol"]: r["close"] for r in rows if not r["is_cash"] and r["close"]})
    cut = (now - timedelta(hours=18)).isoformat(timespec="seconds")
    for r in desk.execute(
        "SELECT q.symbol, q.price FROM quotes_live q "
        "JOIN (SELECT symbol, max(fetched_at) f FROM quotes_live WHERE source='finnhub' AND fetched_at >= ? GROUP BY symbol) m "
        "ON m.symbol=q.symbol AND m.f=q.fetched_at",
        (cut,),
    ):
        out[r["symbol"]] = r["price"]
    return _Prices(desk, out)


class _Prices(dict):
    def __init__(self, desk, known):
        super().__init__(known)
        self.desk = desk

    def get(self, symbol, default=None):
        if symbol in self:
            return self[symbol]
        last = latest_close(self.desk, symbol) if self.desk else None
        self[symbol] = last[1] if last else None
        return self[symbol] if self[symbol] is not None else default


def store(desk: sqlite3.Connection, ticket_id: str, result: dict, at: str) -> None:
    with desk:
        desk.execute("DELETE FROM preflight WHERE ticket_id=?", (ticket_id,))
        desk.executemany(
            "INSERT INTO preflight (ticket_id, metric_id, before, after, flag, at, engine_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(ticket_id, m["metric_id"], m["before"], m["after"], m["flag"], at, ENGINE_VERSION) for m in result["metrics"]],
        )


def check_trade(cfg: Config, trade: dict, ticket_id: str | None = None, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        schema.apply(desk)
        result = preflight(load_context(cfg, mirror, desk, now=now), trade)
        if ticket_id:
            store(desk, ticket_id, result, now.isoformat(timespec="seconds"))
        return result
    finally:
        desk.close()
        if mirror:
            mirror.close()
