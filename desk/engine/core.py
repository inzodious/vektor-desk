import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.decisions.plan import upcoming_deposits
from desk.decisions.profile import active_profile
from desk.decisions.rules import active_rules
from desk.engine import ENGINE_VERSION, lookthrough, risk
from desk.engine.flows import classify, income
from desk.engine.flows import store as store_flows
from desk.engine.lots import current_lots
from desk.engine.research import macro, research_symbols, signals
from desk.engine.returns import WINDOWS, annualize, base_index, daily_returns, drawdowns, period_mwr, twr_index, volatility, window_start
from desk.engine.shadows import TotalReturn, deposit_split, shadow
from desk.engine.source import closes, current_rows
from desk.engine.tax import held_long, realized, wash_windows

UNITS = {"usd": 2, "pct": 4, "pts": 2, "ratio": 4, "days": 0, "count": 0}
SP500 = risk.SP500
SHELTERED = ("hsa", "roth", "ira", "401k", "401(k)", "403b", "457")
ADHERENCE_WINDOWS = ("MTD", "QTD", "YTD", "1Y", "ITD")
AFTER_TAX_WINDOWS = ("YTD", "1Y", "ITD")
FUND_KINDS = {"fund", "etf", "mutual_fund", "index", "money_market"}
PROFILE_ERRORS = (sqlite3.Error, TypeError, KeyError, ValueError, OSError, AttributeError)
DEFAULT_RULES = [
    {"id": "no-margin-buys", "kind": "no_margin_buys", "params": {}},
    {"id": "no-new-single-stocks", "kind": "no_new_single_stocks", "params": {}},
    {"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": 5}},
]


@dataclass
class Out:
    as_of: str
    metrics: list[tuple] = field(default_factory=list)
    series: list[tuple] = field(default_factory=list)
    health: list[tuple] = field(default_factory=list)
    wash: list[tuple] | None = None
    lookthrough: list[tuple] | None = None

    def m(
        self,
        metric_id: str,
        value,
        unit: str,
        *,
        scope: str = "portfolio",
        scope_id: str = "all",
        window: str = "now",
        n_obs: int | None = None,
        quality: str = "ok",
    ):
        if value is None:
            quality = "insufficient_history" if quality == "ok" else quality
        else:
            value = round(float(value), UNITS.get(unit, 4))
        self.metrics.append((metric_id, scope, scope_id, window, self.as_of, value, unit, n_obs, quality, ENGINE_VERSION))

    def s(self, series_id: str, scope: str, scope_id: str, day: str, value, quality: str = "ok"):
        if value is not None:
            self.series.append((series_id, scope, scope_id, day, round(float(value), 6), quality))

    def h(self, check: str, status: str, detail: str):
        self.health.append((self.as_of, check, status, detail))


def env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


# ---- Inputs ----


def load_holdings(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM holdings_daily ORDER BY date"):
        by_day[r["date"]].append(dict(r))
    return dict(by_day)


def latest_plan(mirror: sqlite3.Connection) -> dict:
    plans = list(current_rows(mirror, "plans"))
    if not plans:
        return {}
    best = max(plans, key=lambda p: (str(p.get("loadedAt") or ""), str(p.get("id") or "")))
    return best.get("plan") or {}


def plan_targets(plan: dict) -> dict[str, float]:
    out = {}
    for f in plan.get("funds") or []:
        t = str(f.get("ticker") or "").upper()
        w = f.get("target_weight")
        if t and isinstance(w, int | float) and w > 0:
            out[t] = float(w)
    total = sum(out.values())
    return {s: w / total for s, w in out.items()} if total else {}


def expense_ratios(plan: dict) -> dict[str, float]:
    return {
        str(f.get("ticker") or "").upper(): float(f["expense_ratio_pct"])
        for f in plan.get("funds") or []
        if isinstance(f.get("expense_ratio_pct"), int | float)
    }


def symbol_kinds(mirror: sqlite3.Connection, targets: dict[str, float]) -> dict[str, str]:
    kinds = {}
    for p in current_rows(mirror, "priceProfiles"):
        s = str(p.get("symbol") or "").upper()
        k = str(p.get("kind") or p.get("type") or "").lower()
        if s:
            kinds[s] = "fund" if k in FUND_KINDS else ("stock" if k in ("stock", "common stock", "equity") else "unknown")
    for s in targets:
        kinds[s] = "fund"
    return kinds


def profile_facts(mirror: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for p in current_rows(mirror, "priceProfiles"):
        s = str(p.get("symbol") or "").upper()
        body = p.get("profile") if isinstance(p.get("profile"), dict) else p
        if not s:
            continue
        y = body.get("dividendYield")
        out[s] = {"sector": lookthrough.sector_of(body.get("industry")), "yield": float(y) if isinstance(y, int | float) else None}
    return out


def account_sheltered(account: str) -> bool:
    low = account.lower()
    return any(low.startswith(k) or f"-{k}" in low or f" {k}" in low for k in SHELTERED)


def rules_in_force(cfg: Config, plan: dict) -> tuple[list[dict], str]:
    try:
        _, rules = active_rules(cfg)
        return rules, "profile"
    except PROFILE_ERRORS:
        g = plan.get("guardrails") or {}
        rules = list(DEFAULT_RULES)
        if isinstance(g.get("max_single_stock_weight"), int | float):
            rules.append({"id": "single-stock-band", "kind": "single_stock_band", "params": {"min_pct": 0, "max_pct": g["max_single_stock_weight"] * 100}})
        if isinstance(g.get("drift_alert_pct_points"), int | float):
            rules[2] = {"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": g["drift_alert_pct_points"]}}
        return rules, "plan"


def next_deposit(cfg: Config, plan: dict, as_of: str, now: datetime | None = None) -> tuple[float | None, str | None]:
    try:
        ahead = [d for d in upcoming_deposits(cfg, 45, now=now) if d["status"] == "expected" and d["date"] >= as_of and d.get("amount_usd")]
    except PROFILE_ERRORS:
        ahead = []
    if ahead:
        return float(ahead[0]["amount_usd"]), ahead[0]["date"]
    return plan_deposit(plan, as_of)


def plan_deposit(plan: dict, as_of: str) -> tuple[float | None, str | None]:
    month = as_of[:7]
    for m in sorted(plan.get("monthly_plan") or [], key=lambda m: str(m.get("month"))):
        if str(m.get("month")) > month and isinstance(m.get("contribution"), int | float):
            return float(m["contribution"]), f"{m['month']}-01"
    acct = (plan.get("accounts") or {}).get("individual") or {}
    if isinstance(acct.get("monthly_contribution"), int | float):
        d = date.fromisoformat(as_of)
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        return float(acct["monthly_contribution"]), nxt.isoformat()
    return None, None


# ---- The run ----


def compute(cfg: Config, mirror: sqlite3.Connection, desk: sqlite3.Connection, *, now: datetime | None = None) -> Out:
    now = now or datetime.now(UTC)
    holdings = load_holdings(desk)
    days = sorted(holdings)
    out = Out(as_of=days[-1] if days else now.date().isoformat())
    activity = list(current_rows(mirror, "activity"))
    flows = classify(activity)
    with desk:
        store_flows(desk, flows)
    if not days:
        out.h("holdings", "fail", "No holdings yet; the holdings job has not produced a day.")
        return out
    as_of = days[-1]
    plan = latest_plan(mirror)
    targets = plan_targets(plan)
    kinds = symbol_kinds(mirror, targets)

    totals = {d: sum(h["value"] for h in holdings[d]) for d in days}
    quality_by_day = {d: ("pro_forma" if any(h["quality"] != "ok" for h in holdings[d]) else "ok") for d in days}
    pflow = defaultdict(float)
    aflow: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for f in flows:
        if f["external_portfolio"]:
            pflow[f["date"]] += f["amount"]
        aflow[f["account"]][f["date"]] += f["amount"]
    flows_on = [_flows_between(days, pflow, i) for i in range(len(days))]
    values = [totals[d] for d in days]
    q_now = quality_by_day[as_of]

    _value_metrics(out, days, values, flows_on, holdings, q_now, income(activity))
    index = _return_metrics(out, days, values, flows_on, "portfolio", "all", q_now)
    for d, v, ix in zip(days, values, index, strict=True):
        out.s("value", "portfolio", "all", d, v, quality_by_day[d])
        out.s("twr_index", "portfolio", "all", d, ix, quality_by_day[d])
    accounts = []
    for acct in sorted({h["account"] for d in days for h in holdings[d]}):
        a_values = [sum(h["value"] for h in holdings[d] if h["account"] == acct) for d in days]
        a_flows = [_flows_between(days, aflow[acct], i) for i in range(len(days))]
        first = next((i for i, v in enumerate(a_values) if v > 0), None)
        if first is None:
            continue
        out.m("value.market", a_values[-1], "usd", scope="account", scope_id=acct, quality=q_now)
        a_index = _return_metrics(out, days[first:], a_values[first:], a_flows[first:], "account", acct, q_now)
        for d, v, ix in zip(days[first:], a_values[first:], a_index, strict=True):
            out.s("value", "account", acct, d, v, quality_by_day[d])
            out.s("twr_index", "account", acct, d, ix, quality_by_day[d])
        accounts.append((acct, days[first:], a_values[first:], a_index))

    price_series = closes(mirror)
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='price_bars'").fetchone():
        for r in desk.execute("SELECT symbol, date, close, adj_close FROM price_bars"):
            price_series.setdefault(r["symbol"], {}).setdefault(r["date"], (r["close"], r["adj_close"]))
    tr = TotalReturn(price_series)
    _shadow_metrics(out, days, values, flows_on, targets, tr)
    facts = profile_facts(mirror)

    now_rows = holdings[as_of]
    total = totals[as_of]
    amount, when = next_deposit(cfg, plan, as_of, now)
    _plan_metrics(out, cfg, plan, targets, kinds, now_rows, total, holdings, days, activity, q_now, amount)
    _margin_metrics(out, now_rows, total)
    _risk_metrics(out, now_rows, total, index, days, values, flows_on, q_now)
    risk.metrics(out, desk, tr, days=days, values=values, flows_on=flows_on, rows=now_rows, total=total, kinds=kinds, targets=targets, q=q_now)
    lookthrough.metrics(out, desk, kinds, {s: f["sector"] for s, f in facts.items()})
    _cost_metrics(out, plan, now_rows, total)
    for s, f in sorted(facts.items()):
        if f["yield"] is not None:
            out.m("income.yield", f["yield"], "pct", scope="holding", scope_id=s, window="TTM")
    _adherence(out, days, activity, targets, q_now)
    _tax_metrics(out, cfg, mirror, desk, activity, now_rows, now)
    _after_tax(out, cfg, mirror, desk, accounts, income(activity))
    _research_metrics(out, desk, kinds)
    out.m("cash.pending", amount, "usd", quality="modelled" if amount is not None else "insufficient_history")
    if when:
        out.m("cash.pending_days", (date.fromisoformat(when) - date.fromisoformat(as_of)).days, "days", quality="modelled")
    _health(out, cfg, mirror, desk, holdings, now)
    return out


def _flows_between(days: list[str], flows: dict[str, float], i: int) -> float:
    if i == 0:
        return 0.0
    lo, hi = days[i - 1], days[i]
    return sum(a for d, a in flows.items() if lo < d <= hi)


def _value_metrics(out: Out, days, values, flows_on, holdings, q, income_rows):
    as_of = days[-1]
    out.m("value.market", values[-1], "usd", quality=q)
    by_symbol: dict[str, float] = defaultdict(float)
    for h in holdings[as_of]:
        if not h["is_cash"]:
            by_symbol[h["symbol"]] += h["value"]
    for sym, v in sorted(by_symbol.items()):
        out.m("value.market", v, "usd", scope="holding", scope_id=sym, quality=q)
        out.m("value.weight", v / values[-1] * 100 if values[-1] else None, "pct", scope="holding", scope_id=sym, quality=q)
    out.m("value.day_change", values[-1] - values[-2] - flows_on[-1] if len(values) > 1 else None, "usd", quality=q)
    cash = sum(h["value"] for h in holdings[as_of] if h["is_cash"] and h["value"] > 0)
    debit = -sum(h["value"] for h in holdings[as_of] if h["is_cash"] and h["value"] < 0)
    out.m("cash.share", cash / values[-1] * 100 if values[-1] else None, "pct", quality=q)
    out.m("cash.ready", cash - debit, "usd", quality=q)
    for w in WINDOWS:
        i0 = base_index(days, w)
        if i0 is None:
            continue
        net = sum(flows_on[i0 + 1 :])
        out.m("flow.net_contrib", net, "usd", window=w, n_obs=len(days) - i0 - 1, quality=q)
        out.m("value.gain", values[-1] - values[i0] - net, "usd", window=w, n_obs=len(days) - i0 - 1, quality=q)
        inc = sum(a for d, _, _, a in income_rows if days[i0] < d <= as_of)
        out.m("income.dividends", inc, "usd", window=w, quality=q)
    year_ago = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
    out.m("income.dividends", sum(a for d, _, _, a in income_rows if year_ago < d <= as_of), "usd", window="TTM", quality=q)


def _return_metrics(out: Out, days, values, flows_on, scope, scope_id, q) -> list[float]:
    index = twr_index(values, flows_on)
    for w in WINDOWS:
        i0 = base_index(days, w)
        if i0 is None:
            continue
        n = len(days) - i0 - 1
        total = index[-1] / index[i0] - 1
        span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[i0])).days
        out.m("ret.twr", total * 100, "pct", scope=scope, scope_id=scope_id, window=w, n_obs=n, quality=q)
        if w in ("3Y", "ITD"):
            ann = annualize(total, span)
            if ann is not None:
                out.m("ret.twr_ann", ann * 100, "pct", scope=scope, scope_id=scope_id, window=w, n_obs=n, quality=q)
        mwr = period_mwr(days, values, flows_on, i0)
        out.m("ret.mwr", None if mwr is None else mwr * 100, "pct", scope=scope, scope_id=scope_id, window=w, n_obs=n, quality=q)
    return index


def _shadow_metrics(out: Out, days, values, flows_on, targets, tr):
    benches = []
    if targets:
        benches.append(("plan_shadow", targets))
    sp = next((s for s in SP500 if tr.starts(s) and tr.starts(s) <= days[0]), None)
    if sp:
        benches.append(("sp500_shadow", {sp: 1.0}))
    for name, weights in benches:
        series, quality, _ = shadow(days, values[0], flows_on, weights, tr)
        if series[-1] is None:
            out.m(f"bm.{name}", None, "usd", scope="shadow", scope_id=name)
            continue
        for d, v, ix in zip(days, series, twr_index(series, flows_on), strict=True):
            out.s("value", "shadow", name, d, v, quality)
            out.s("twr_index", "shadow", name, d, ix, quality)
        out.m(f"bm.{name}", series[-1], "usd", scope="shadow", scope_id=name, quality=quality)
        for w in WINDOWS:
            i0 = base_index(days, w)
            if i0 is None or series[i0] in (None, 0):
                continue
            actual_gain = values[-1] - values[i0] - sum(flows_on[i0 + 1 :])
            shadow_gain = series[-1] - series[i0] - sum(flows_on[i0 + 1 :])
            out.m("bm.excess", actual_gain - shadow_gain, "usd", scope="shadow", scope_id=name, window=w, quality=quality)
        s_rets = daily_returns(series, flows_on)
        a_rets = daily_returns(values, flows_on)
        diffs = [a - b for a, b in zip(a_rets, s_rets, strict=True) if a is not None and b is not None]
        if len(diffs) >= 63:
            te = volatility(diffs)
            out.m(
                "bm.tracking_error", te * 100 if te is not None else None, "pct", scope="shadow", scope_id=name, window="ITD", n_obs=len(diffs), quality=quality
            )


def symbol_weights(rows, total) -> dict[str, float]:
    w = defaultdict(float)
    for h in rows:
        if not h["is_cash"] and total:
            w[h["symbol"]] += h["value"] / total * 100
    return dict(w)


def _plan_metrics(out: Out, cfg, plan, targets, kinds, rows, total, holdings, days, activity, q, amount):
    weights = symbol_weights(rows, total)
    if targets:
        drifts = {}
        for s, t in sorted(targets.items()):
            actual = weights.get(s, 0.0)
            drifts[s] = actual - t * 100
            out.m("plan.weight", actual, "pct", scope="holding", scope_id=s, quality=q)
            out.m("plan.target", t * 100, "pct", scope="holding", scope_id=s, quality=q)
            out.m("plan.drift", drifts[s], "pts", scope="holding", scope_id=s, quality=q)
        out.m("plan.drift_max", max(abs(v) for v in drifts.values()), "pts", quality=q)
        for s, usd in sorted(deposit_split(targets, weights, total, amount or 0.0).items()):
            out.m("plan.next_deposit", usd, "usd", scope="holding", scope_id=s, quality="modelled")
        in_plan = sum(weights.get(s, 0.0) for s in targets)
        out.m("plan.in_mix", in_plan, "pct", quality=q)
    singles = {s: w for s, w in weights.items() if kinds.get(s, "unknown") == "stock" and s not in targets}
    out.m("plan.single_stock", sum(singles.values()), "pct", quality=q)
    for s, w in sorted(singles.items()):
        out.m("plan.single_stock", w, "pct", scope="holding", scope_id=s, quality=q)
    unknown = sorted(s for s in weights if kinds.get(s, "unknown") == "unknown" and s not in targets)
    if unknown:
        out.h("symbol_kinds", "warn", f"Not sure whether these are funds or single stocks: {', '.join(unknown)}.")
    rules, source = rules_in_force(cfg, plan)
    debit = -sum(h["value"] for h in rows if h["is_cash"] and h["value"] < 0)
    for rule in rules:
        ok = _rule_ok(rule, weights, singles, targets, debit, holdings, days, activity, kinds)
        if ok is not None:
            out.m("plan.rules", 1 if ok else 0, "count", scope="rule", scope_id=rule["id"], quality=q if source == "profile" else "modelled")


def _rule_ok(rule, weights, singles, targets, debit, holdings, days, activity, kinds) -> bool | None:
    kind, p = rule.get("kind"), rule.get("params") or {}
    if kind == "single_stock_band":
        names = rule.get("symbols") or list(singles)
        return all(p.get("min_pct", 0) <= singles.get(s, 0.0) <= p.get("max_pct", 100) for s in names) if names else True
    if kind == "drift_max_pts":
        return all(abs(weights.get(s, 0.0) - t * 100) <= p.get("pts", 5) for s, t in targets.items()) if targets else None
    if kind == "cash_floor_pct":
        cash = sum(h["value"] for h in holdings[days[-1]] if h["is_cash"])
        total = sum(h["value"] for h in holdings[days[-1]])
        return cash / total * 100 >= p.get("pct", 0) if total else None
    if kind == "no_margin_buys":
        since = (date.fromisoformat(days[-1]) - timedelta(days=30)).isoformat()
        for r in activity:
            d = str(r.get("date") or "")[:10]
            if r.get("kind") == "buy" and not r.get("core") and d > since and d in holdings:
                cash = sum(h["value"] for h in holdings[d] if h["is_cash"] and h["account"] == r.get("accountKey"))
                if cash < 0:
                    return False
        return True
    if kind == "no_new_single_stocks":
        before = (date.fromisoformat(days[-1]) - timedelta(days=30)).isoformat()
        old = max((d for d in days if d <= before), default=None)
        if old is None:
            return None
        held_then = {h["symbol"] for h in holdings[old]}
        return all(s in held_then for s in singles)
    return None


def _margin_metrics(out: Out, rows, total):
    rate = env_float("DESK_MARGIN_RATE_PCT")
    maint = env_float("DESK_MARGIN_MAINT_PCT") or 30.0
    by_acct = defaultdict(lambda: {"debit": 0.0, "value": 0.0})
    for h in rows:
        a = by_acct[h["account"]]
        a["value"] += h["value"] if not (h["is_cash"] and h["value"] < 0) else 0.0
        if h["is_cash"] and h["value"] < 0:
            a["debit"] -= h["value"]
    debit = sum(a["debit"] for a in by_acct.values())
    out.m("margin.debit", debit, "usd")
    if debit > 0:
        out.m("margin.cost_month", debit * rate / 100 * 30 / 360 if rate is not None else None, "usd", quality="ok" if rate is not None else "modelled")
        out.m("margin.funded_share", debit / total * 100 if total else None, "pct")
        for acct, a in sorted(by_acct.items()):
            if a["debit"] > 0 and a["value"] > 0:
                drop = 1 - a["debit"] / ((1 - maint / 100) * a["value"])
                out.m("margin.call_drop", max(0.0, drop) * 100, "pct", scope="account", scope_id=acct, quality="modelled")
        if rate is None:
            out.h("margin_rate", "warn", "There is a margin debit but DESK_MARGIN_RATE_PCT is not set, so its interest cost is unknown.")
    else:
        out.m("margin.cost_month", 0.0, "usd")


def _risk_metrics(out: Out, rows, total, index, days, values, flows_on, q):
    w = sorted(symbol_weights(rows, total).values(), reverse=True)
    invested = sum(w)
    out.m("risk.top1", w[0] if w else 0.0, "pct", quality=q)
    out.m("risk.top5", sum(w[:5]), "pct", quality=q)
    shares = [x / invested for x in w] if invested else []
    out.m("risk.eff_n", 1 / sum(x * x for x in shares) if shares else None, "ratio", quality=q)
    worst, current, longest = drawdowns(index)
    out.m("risk.mdd", worst * 100, "pct", window="ITD", n_obs=len(index), quality=q)
    out.m("risk.dd_now", current * 100, "pct", quality=q)
    out.m("risk.mdd_days", longest, "days", window="ITD", quality=q)
    rets = daily_returns(values, flows_on)[1:]
    for window, n in (("63D", 63), ("252D", 252)):
        if len(rets) >= n:
            v = volatility(rets[-n:])
            out.m("risk.vol", v * 100 if v is not None else None, "pct", window=window, n_obs=n, quality=q)
        else:
            out.m("risk.vol", None, "pct", window=window, n_obs=len(rets), quality="insufficient_history")


def _cost_metrics(out: Out, plan, rows, total):
    ratios = expense_ratios(plan)
    for s, r in sorted(ratios.items()):
        out.m("cost.expense", r, "pct", scope="holding", scope_id=s)
    invested = {h["symbol"]: 0.0 for h in rows if not h["is_cash"]}
    for h in rows:
        if not h["is_cash"]:
            invested[h["symbol"]] += h["value"]
    known = {s: v for s, v in invested.items() if s in ratios}
    if not known:
        out.m("cost.expense", None, "pct")
        return
    usd = sum(v * ratios[s] / 100 for s, v in known.items())
    base = sum(known.values())
    q = "ok" if len(known) == len(invested) else "pro_forma"
    out.m("cost.expense", usd / base * 100, "pct", quality=q)
    out.m("cost.expense_usd", usd, "usd", window="1Y", quality=q)


def _adherence(out: Out, days, activity, targets, q):
    if not targets:
        return
    buys = []
    for r in activity:
        d, amt = str(r.get("date") or "")[:10], r.get("amount")
        sym = str(r.get("symbol") or "").upper()
        if r.get("kind") == "buy" and not r.get("core") and sym and isinstance(amt, int | float) and amt < 0:
            buys.append((d, sym, -float(amt)))
    end, first = date.fromisoformat(days[-1]), date.fromisoformat(days[0])
    for w in ADHERENCE_WINDOWS:
        lo = window_start(w, end, first).isoformat()
        picked = [(s, a) for d, s, a in buys if lo < d <= days[-1]]
        spent = sum(a for _, a in picked)
        value = sum(a for s, a in picked if s in targets) / spent * 100 if spent else None
        out.m("plan.adherence", value, "pct", window=w, n_obs=len(picked), quality=q if value is not None else "insufficient_history")


def _after_tax(out: Out, cfg, mirror, desk, accounts, income_rows):
    federal, state, _ = marginal_rate(cfg, mirror)
    rate = None if federal is None else (federal + state) / 100
    ltcg = (env_float("DESK_LTCG_RATE_PCT") or 15.0) / 100
    sold = [dict(r) for r in desk.execute("SELECT account, sold, gain, term FROM realized_lots")]
    for acct, a_days, a_values, a_index in accounts:
        sheltered = account_sheltered(acct)
        end, first = date.fromisoformat(a_days[-1]), date.fromisoformat(a_days[0])
        for w in AFTER_TAX_WINDOWS:
            i0 = base_index(a_days, w)
            if i0 is None or not a_values[i0]:
                continue
            twr = (a_index[-1] / a_index[i0] - 1) * 100
            if sheltered:
                out.m("ret.after_tax", twr, "pct", scope="account", scope_id=acct, window=w, quality="modelled")
                continue
            if rate is None:
                out.m("ret.after_tax", None, "pct", scope="account", scope_id=acct, window=w, quality="modelled")
                continue
            lo = window_start(w, end, first).isoformat()
            divs = sum(a for d, ac, _, a in income_rows if ac == acct and lo < d <= a_days[-1])
            st = sum(r["gain"] or 0 for r in sold if r["account"] == acct and lo < (r["sold"] or "") <= a_days[-1] and r["term"] != "long")
            lt = sum(r["gain"] or 0 for r in sold if r["account"] == acct and lo < (r["sold"] or "") <= a_days[-1] and r["term"] == "long")
            drag = (divs * rate + max(st, 0.0) * rate + max(lt, 0.0) * ltcg) / a_values[i0] * 100
            out.m("ret.after_tax", twr - drag, "pct", scope="account", scope_id=acct, window=w, quality="modelled")


# ---- Tax ----


RAISE_USD = 1000.0


def marginal_rate(cfg: Config, mirror: sqlite3.Connection | None) -> tuple[float | None, float | None, str]:
    for p in current_rows(mirror, "prefs") if mirror else []:
        if p.get("key") != "taxEngine":
            continue
        res = (p.get("value") or {}).get("res") or {}
        raise_, fed = res.get("raise") or {}, (res.get("federal") or {}).get("tax")
        if res.get("ok") and isinstance(raise_.get("federal"), int | float) and isinstance(fed, int | float):
            federal = max(0.0, (raise_["federal"] - fed) / RAISE_USD * 100)
            state_now, state_up = res.get("stateTax"), raise_.get("state")
            state = max(0.0, (state_up - state_now) / RAISE_USD * 100) if isinstance(state_now, int | float) and isinstance(state_up, int | float) else 0.0
            return round(federal, 2), round(state, 2), "escape_vektor"
    try:
        pct = active_profile(cfg).get("tax", "marginal_rate_pct")
    except PROFILE_ERRORS:
        pct = None
    pct = pct if isinstance(pct, int | float) else env_float("DESK_MARGINAL_RATE_PCT")
    return (float(pct), 0.0, "setting") if pct is not None else (None, None, "none")


def _tax_metrics(out: Out, cfg: Config, mirror, desk, activity, rows, now: datetime):
    as_of = out.as_of
    files = {r["kind"] for r in desk.execute("SELECT DISTINCT kind FROM lot_files")}
    r = realized(desk, int(as_of[:4]))
    rq = "ok" if "realized" in files else "insufficient_history"
    for metric_id, key in (("tax.realized_st", "st"), ("tax.realized_lt", "lt"), ("tax.wash_disallowed", "wash_disallowed")):
        out.m(metric_id, r[key] if "realized" in files else None, "usd", window="YTD", n_obs=r["rows"], quality=rq)
    lots = current_lots(desk) if "lots" in files else []
    prices = {h["symbol"]: h["close"] for h in rows if not h["is_cash"] and h["close"]}
    st = lt = 0.0
    losses: dict[tuple[str, str], float] = defaultdict(float)
    for lot in lots:
        price = prices.get(lot["symbol"])
        if price is None or lot["cost"] is None:
            continue
        gain = lot["shares"] * price - lot["cost"]
        if held_long(lot["acquired"], as_of):
            lt += gain
        else:
            st += gain
        if gain < 0:
            losses[(lot["account"], lot["symbol"])] += gain
    lq = "ok" if lots else "insufficient_history"
    out.m("tax.unrealized_st", st if lots else None, "usd", quality=lq)
    out.m("tax.unrealized_lt", lt if lots else None, "usd", quality=lq)
    realized_rows = [dict(x) for x in desk.execute("SELECT * FROM realized_lots")]
    today = max(as_of, now.date().isoformat())
    windows = wash_windows(activity, realized_rows, lots, today)
    out.wash = [(as_of, w["symbol"], w["kind"], w["date"], w["clears"], w["account"], w["amount"]) for w in windows]
    clears: dict[str, str] = {}
    for w in windows:
        clears[w["symbol"]] = max(clears.get(w["symbol"], ""), w["clears"])
    for sym, day in sorted(clears.items()):
        out.m("tax.wash_window", (date.fromisoformat(day) - date.fromisoformat(today)).days, "days", scope="holding", scope_id=sym)
    try:
        threshold = float(active_profile(cfg).get("tax", "harvest_threshold_usd", default=250) or 250)
    except PROFILE_ERRORS:
        threshold = 250.0
    bought = {w["symbol"] for w in windows if w["kind"] == "recent_buy"}
    total = 0.0
    for (_, sym), loss in sorted(losses.items()):
        if -loss >= threshold and sym not in bought:
            total += -loss
            out.m("tax.harvestable", -loss, "usd", scope="holding", scope_id=sym, quality=lq)
    out.m("tax.harvestable", total if lots else None, "usd", quality=lq)
    federal, state, source = marginal_rate(cfg, mirror)
    rate = None if federal is None else federal + state
    out.m("tax.marginal_rate", rate, "pct", quality="modelled")
    if federal is not None:
        out.m("tax.marginal_rate", federal, "pct", scope="tax", scope_id="federal", quality="modelled")
        out.m("tax.marginal_rate", state, "pct", scope="tax", scope_id="state", quality="modelled")
    else:
        out.h("marginal_rate", "warn", "No marginal tax rate yet: open Taxes in Escape Vektor once, or set tax.marginal_rate_pct in desk.yaml.")
    out.m("tax.harvest_value", total * rate / 100 if lots and rate is not None else None, "usd", quality="modelled")
    if source != "none":
        out.h("marginal_rate", "ok", "Marginal rate from Escape Vektor's tax estimate." if source == "escape_vektor" else "Marginal rate from desk.yaml.")


# ---- Research signals and macro ----


def _research_metrics(out: Out, desk, kinds):
    symbols = research_symbols(desk, kinds)
    prev = desk.execute("SELECT max(as_of) FROM metric_values WHERE as_of < ?", (out.as_of,)).fetchone()[0]
    for metric_id, sym, value, unit, window, n in signals(desk, symbols, out.as_of, prev):
        out.m(metric_id, value, unit, scope="holding", scope_id=sym, window=window, n_obs=n)
    for metric_id, name, value, unit in macro(desk, out.as_of):
        out.m(metric_id, value, unit, scope="macro", scope_id=name)
    covered = {r[0] for r in desk.execute("SELECT DISTINCT symbol FROM fundamentals")}
    bare = [s for s in symbols if s not in covered]
    if bare:
        out.h("research", "warn", f"No SEC company facts yet for {', '.join(bare[:10])}; the nightly research job fills them.")
    elif symbols:
        out.h("research", "ok", f"SEC company facts for {len(symbols)} stocks.")


# ---- Data health ----


def _health(out: Out, cfg: Config, mirror, desk, holdings, now: datetime):
    if any(r[0] == "tables" for r in mirror.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        row = mirror.execute("SELECT mirrored_at FROM tables WHERE tbl='snapshots'").fetchone()
        if row and row["mirrored_at"]:
            age = (now - datetime.fromisoformat(row["mirrored_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            status = "ok" if age <= cfg.stale_hours else "fail"
            out.h("freshness", status, f"Mirror pulled {age:.1f} hours ago (limit {cfg.stale_hours:g}).")
        else:
            out.h("freshness", "fail", "The mirror has never pulled snapshots.")
    as_of = out.as_of
    rows = holdings[as_of]
    unpriced = sorted(h["symbol"] for h in rows if not h["is_cash"] and h["quality"] == "pro_forma" and h["source"] == "snapshot")
    out.h("closes", "warn" if unpriced else "ok", f"No close for {', '.join(unpriced)} on {as_of}." if unpriced else f"Every holding has a close on {as_of}.")
    snap_days = [d for d in holdings if any(h["source"] == "snapshot" for h in holdings[d])]
    if snap_days:
        d = max(snap_days)
        bad = []
        for acct in sorted({h["account"] for h in holdings[d]}):
            calc = sum(h["value"] for h in holdings[d] if h["account"] == acct)
            rep = sum(h["reported_value"] or 0 for h in holdings[d] if h["account"] == acct)
            if abs(calc - rep) > max(1.0, abs(rep) * 0.0005):
                bad.append(f"{acct} {calc:,.2f} vs {rep:,.2f}")
        mism = [h for h in holdings[d] if h["quality"] == "mismatch"]
        status = "fail" if bad or mism else "ok"
        detail = "; ".join(bad) if bad else ("Snapshot positions don't add up to its total." if mism else f"Values match the broker on {d}.")
        out.h("value", status, detail)
    lots = []
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='lots'").fetchone():
        lots = current_lots(desk)
    if lots:
        held = defaultdict(float)
        for h in rows:
            if not h["is_cash"]:
                held[(h["account"], h["symbol"])] += h["shares"]
        lot_sh = defaultdict(float)
        for lot in lots:
            lot_sh[(lot["account"], lot["symbol"])] += lot["shares"]
        diffs = [
            f"{a} {s}: lots {lot_sh[(a, s)]:g} vs held {held.get((a, s), 0):g}" for a, s in sorted(lot_sh) if abs(lot_sh[(a, s)] - held.get((a, s), 0)) > 1e-4
        ]
        newest = max(str(lot["as_of"] or "") for lot in lots)
        status = "ok" if not diffs else ("warn" if newest < as_of else "fail")
        out.h("shares", status, "; ".join(diffs[:10]) if diffs else "Lot shares match holdings.")
    else:
        out.h("shares", "warn", "No lot export yet; tax lots and wash-sale checks need one.")


# ---- Store ----


def store(desk: sqlite3.Connection, out: Out) -> dict:
    if any(h[2] == "fail" for h in out.health):
        out.metrics = [m[:8] + (("stale" if m[8] == "ok" else m[8]),) + m[9:] for m in out.metrics]
    with desk:
        desk.execute("DELETE FROM metric_values WHERE as_of=?", (out.as_of,))
        desk.executemany("INSERT INTO metric_values VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", out.metrics)
        desk.execute("DELETE FROM series_daily")
        desk.executemany("INSERT OR REPLACE INTO series_daily VALUES (?, ?, ?, ?, ?, ?)", out.series)
        desk.execute("DELETE FROM data_health WHERE as_of=?", (out.as_of,))
        desk.executemany("INSERT INTO data_health VALUES (?, ?, ?, ?)", out.health)
        if out.lookthrough is not None:
            desk.execute("DELETE FROM lookthrough")
            desk.executemany("INSERT OR REPLACE INTO lookthrough VALUES (?, ?, ?, ?, ?, ?)", out.lookthrough)
        if out.wash is not None:
            desk.execute("DELETE FROM wash_windows")
            desk.executemany("INSERT OR REPLACE INTO wash_windows VALUES (?, ?, ?, ?, ?, ?, ?)", out.wash)
    worst = "fail" if any(h[2] == "fail" for h in out.health) else ("warn" if any(h[2] == "warn" for h in out.health) else "ok")
    return {"as_of": out.as_of, "metrics": len(out.metrics), "series": len(out.series), "health": worst, "checks": {h[1]: h[2] for h in out.health}}
