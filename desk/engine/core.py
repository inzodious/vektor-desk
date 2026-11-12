import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.decisions.plan import upcoming_deposits
from desk.decisions.profile import active_profile
from desk.decisions.rules import active_rules
from desk.engine import (
    ENGINE_VERSION,
    INBOX_AT,
    JOBS_AT,
    KEY_WORDS,
    KEYS_AT,
    bands,
    broker,
    catalog,
    fi,
    heal,
    key_fix,
    lookthrough,
    patterns,
    replay,
    risk,
    scoring,
)
from desk.engine.asof import CLOSES_LAND, ET, day_words, provisional_symbols
from desk.engine.backfill import ASK_WORDS, NO_PRICES, parked_until
from desk.engine.cash import margin_rate
from desk.engine.cash import picture as cash_picture
from desk.engine.flows import classify, income
from desk.engine.flows import store as store_flows
from desk.engine.holdings import BACKCAST, Prices, matching_close, price_series
from desk.engine.lots import current_lots, realized_rows
from desk.engine.market import BENCHMARKS, last_trading_day
from desk.engine.research import macro, research_symbols, signals
from desk.engine.returns import WINDOWS, annualize, base_index, daily_returns, drawdowns, period_mwr, twr_index, volatility, window_start
from desk.engine.shadows import TotalReturn, deposit_split, shadow
from desk.engine.source import current_rows
from desk.engine.tax import held_long, realized, wash_windows

UNITS = {"usd": 2, "pct": 4, "pts": 2, "ratio": 4, "days": 0, "count": 0, "flag": 0}
SP500 = risk.SP500
SHELTERED = ("hsa", "roth", "ira", "401k", "401(k)", "403b", "457")
ADHERENCE_WINDOWS = ("MTD", "QTD", "YTD", "1Y", "ITD")
AFTER_TAX_WINDOWS = ("YTD", "1Y", "ITD")
FUND_KINDS = {"fund", "etf", "mutual_fund", "index", "money_market"}
LISTED_FUNDS = set(BENCHMARKS) | {"DIA", "MDY", "IVV", "VOO", "VUG", "VTV", "VEA", "VWO", "BND", "SCHD", "SCHB", "SCHX", "ITOT", "IEFA", "IEMG"}
MARKET_KEYS = (
    ("TIINGO_API_KEY", "held prices only refresh when you open Escape Vektor"),
    ("FINNHUB_API_KEY", "no live quotes"),
    ("FRED_API_KEY", "no macro series"),
    ("DESK_SEC_USER_AGENT", "no SEC research or fund look-through"),
    ("ALPACA_API_KEY_ID", "no small-cap universe or filings lane"),
    ("ALPACA_API_SECRET_KEY", "no small-cap universe or filings lane"),
)
FUND_WORDS = {"ETF", "ETFS", "FUND", "FUNDS", "ISHARES", "SPDR", "PROSHARES", "INDEX"}
PROFILE_ERRORS = (sqlite3.Error, TypeError, KeyError, ValueError, OSError, AttributeError)
KEPT_ON_FAIL = ("stale", "insufficient_history")
NO_MARGIN_RATE = (
    "There is a margin debit but the margin rate could not be read from your profile, so its interest cost is unknown. "
    "Fix: open Settings and check the profile loads."
)
REFERENCE_NOTE = (
    "No plan of your own is loaded, so drift and the benchmark are measured against the built-in safe mix. "
    "It is a yardstick, not a target, and the drift rule is not judged against it."
)
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
    signals: list[tuple] | None = None
    views: dict[str, dict] = field(default_factory=dict)
    implied: dict[tuple[str, str], float] = field(default_factory=dict)
    book: broker.Book | None = None
    history: broker.History | None = None

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

    def h(self, check: str, status: str, detail: str, say: str | None = None, kind: str | None = None, job: str | None = None):
        self.health.append((self.as_of, check, status, detail, say or detail, heal.kind_of(status, kind), job if status != "ok" else None))

    def c(self, check: "Check"):
        self.h(*check, check.say, check.kind, check.job)


class Check(tuple):
    def __new__(cls, name: str, status: str, detail: str, say: str | None = None, kind: str | None = None, job: str | None = None):
        self = super().__new__(cls, (name, status, detail))
        self.say, self.kind, self.job = say, kind, job
        return self


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


def reference_mix(plan: dict) -> tuple[dict[str, float], str]:
    targets = plan_targets(plan)
    return (targets, "plan") if targets else (dict(catalog.SAFE_MIX), "safe_mix")


def reference_view(as_of: str, targets: dict[str, float], source: str) -> dict:
    own = source == "plan"
    return {
        "as_of": as_of,
        "source": source,
        "name": "Your plan" if own else "Safe mix",
        "weights": {s: round(w * 100, 4) for s, w in sorted(targets.items())},
        "judged": own,
        "note": None if own else REFERENCE_NOTE,
    }


def expense_ratios(plan: dict) -> dict[str, float]:
    return {
        str(f.get("ticker") or "").upper(): float(f["expense_ratio_pct"])
        for f in plan.get("funds") or []
        if isinstance(f.get("expense_ratio_pct"), int | float)
    }


def _table(conn, name: str) -> bool:
    return conn is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def guess_kind(symbol: str, sec_funds: set[str], sec_titles: dict[str, str]) -> str:
    if symbol in sec_funds or symbol in LISTED_FUNDS:
        return "fund"
    if len(symbol) == 5 and symbol.endswith("X") and symbol.isalpha():
        return "fund"
    if any(c.isdigit() for c in symbol) and symbol not in sec_titles:
        return "fund"
    title = sec_titles.get(symbol)
    if title is None:
        return "unknown"
    words = set(title.upper().replace(",", " ").replace(".", " ").split())
    return "fund" if words & FUND_WORDS else "stock"


def symbol_kinds(mirror: sqlite3.Connection, targets: dict[str, float], desk: sqlite3.Connection | None = None) -> dict[str, str]:
    kinds = {}
    for p in current_rows(mirror, "priceProfiles"):
        s = str(p.get("symbol") or "").upper()
        k = str(p.get("kind") or p.get("type") or "").lower()
        if s:
            kinds[s] = "fund" if k in FUND_KINDS else ("stock" if k in ("stock", "common stock", "equity") else "unknown")
    for s in targets:
        kinds[s] = "fund"
    if desk is None:
        return kinds
    funds = {r[0] for r in desk.execute("SELECT symbol FROM sec_funds")} if _table(desk, "sec_funds") else set()
    titles = {r[0]: r[1] or "" for r in desk.execute("SELECT symbol, title FROM sec_tickers")} if _table(desk, "sec_tickers") else {}
    held = set()
    if _table(desk, "holdings_daily"):
        held = {r[0] for r in desk.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE is_cash=0 AND date=(SELECT max(date) FROM holdings_daily)")}
    for s in sorted(held | set(kinds)):
        if kinds.get(s, "unknown") == "unknown":
            kinds[s] = guess_kind(s, funds, titles)
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


def fi_goal(cfg: Config, mirror: sqlite3.Connection) -> dict | None:
    prefs = fi.fi_prefs(current_rows(mirror, "prefs"))
    if prefs is not None:
        return prefs
    try:
        from desk.decisions import profile

        read = getattr(profile, "fi_goal", None)
        goal = read(active_profile(cfg).data) if read else None
    except PROFILE_ERRORS:
        return None
    if not isinstance(goal, dict) or not isinstance(goal.get("fi_number"), int | float) or goal["fi_number"] <= 0:
        return None
    return {"target_date": None, "inflation": 0.0, "real": False} | goal


def convictions(rules: list[dict]) -> dict[str, tuple[float, float]]:
    out = {}
    for r in rules:
        if r.get("kind") != "conviction_hold" or not r.get("enabled", True) or not r.get("symbols"):
            continue
        p = r.get("params") or {}
        out[str(r["symbols"][0]).upper()] = (float(p.get("band_min_pct") or 0.0), float(p.get("band_max_pct") or 100.0))
    return out


def next_deposit(cfg: Config, plan: dict, as_of: str, now: datetime | None = None) -> tuple[float | None, str | None]:
    try:
        ahead = [d for d in upcoming_deposits(cfg, 45, now=now) if d["status"] == "expected" and d["date"] >= as_of and d.get("amount_usd")]
    except PROFILE_ERRORS:
        ahead = []
    if ahead:
        return float(ahead[0]["amount_usd"]), ahead[0]["date"]
    return None, None


# ---- The run ----


def compute(cfg: Config, mirror: sqlite3.Connection, desk: sqlite3.Connection, *, now: datetime | None = None) -> Out:
    now = now or datetime.now(UTC)
    holdings = load_holdings(desk)
    days = sorted(holdings)
    out = Out(as_of=days[-1] if days else now.date().isoformat())
    activity, out.history = broker.history(mirror, desk)
    flows = classify(activity)
    with desk:
        store_flows(desk, flows)
    if not days:
        out.h(
            "holdings",
            "fail",
            f"No holdings yet. Fix: in {JOBS_AT}, run Accounts and then Daily numbers.",
            "No holdings yet. The desk is reading your accounts now.",
            heal.BLOCKS,
            heal.ACCOUNTS,
        )
        return out
    as_of = days[-1]
    plan = latest_plan(mirror)
    targets, reference = reference_mix(plan)
    own = reference == "plan"
    kinds = symbol_kinds(mirror, targets, desk)
    out.views["reference"] = reference_view(as_of, targets, reference)

    totals = {d: sum(h["value"] for h in holdings[d]) for d in days}
    quality_by_day = {d: _day_quality(holdings[d]) for d in days}
    pflow = defaultdict(float)
    aflow: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for f in flows:
        if f["external_portfolio"]:
            pflow[f["date"]] += f["amount"]
        aflow[f["account"]][f["date"]] += f["amount"]
    out.implied = implied_flows(days, holdings, aflow, income(activity))
    for (acct, d), amount in out.implied.items():
        pflow[d] += amount
        aflow[acct][d] += amount
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

    series = price_series(mirror, desk)
    tr = TotalReturn(series)
    if out.history.rows:
        out.book = broker.build_book(activity, out.history, Prices(series).close)
    _shadow_metrics(out, days, values, flows_on, targets if own else catalog.proxied(targets)[0], tr)
    facts = profile_facts(mirror)

    now_rows = holdings[as_of]
    total = totals[as_of]
    amount, when = next_deposit(cfg, plan, as_of, now)
    _plan_metrics(out, cfg, plan, targets, kinds, now_rows, total, holdings, days, activity, q_now, amount, own)
    _margin_metrics(out, now_rows, total, cfg)
    _margin_paid(out, activity, as_of)
    _risk_metrics(out, now_rows, total, index, days, values, flows_on, q_now)
    risk.metrics(out, desk, tr, days=days, values=values, flows_on=flows_on, rows=now_rows, total=total, kinds=kinds, targets=targets, q=q_now)
    lookthrough.metrics(out, desk, kinds, {s: f["sector"] for s, f in facts.items()})
    _cost_metrics(out, plan, now_rows, total)
    for s, f in sorted(facts.items()):
        if f["yield"] is not None:
            out.m("income.yield", f["yield"], "pct", scope="holding", scope_id=s, window="TTM")
    _adherence(out, days, activity, targets, q_now if own else "modelled")
    _tax_metrics(out, cfg, mirror, desk, activity, now_rows, now)
    _after_tax(out, cfg, mirror, desk, accounts, income(activity))
    _research_metrics(out, desk, kinds)
    _flight_record(out, cfg, desk, tr, targets, kinds, now_rows)
    out.views["replay"] = _replay(out, activity, series, targets, now_rows)
    market = next((m[5] for m in out.metrics if m[0] == "value.market" and m[1] == "portfolio"), total)
    cash_in = [(f["date"], f["amount"]) for f in flows if f["external_portfolio"]]
    goal = fi_goal(cfg, mirror)
    out.views["fi"] = fi.run(out, plan, targets if own else {}, expense_ratios(plan), goal, desk, market, cash_in)
    held, cash_share, held_notes = catalog.held_mix(now_rows)
    wanted = catalog.mixes(held, cash_share, kinds)
    if "as-held" in wanted:
        wanted["as-held"]["notes"] = held_notes + wanted["as-held"]["notes"]
    with desk:
        catalog.sync(desk, wanted, now=now)
    out.views["bands"] = bands.run(
        out,
        cfg,
        desk,
        tr,
        wanted,
        value=market,
        deposits=cash_in,
        prefs=goal,
        fees=expense_ratios(plan),
        kinds=kinds,
        convictions=convictions(rules_in_force(cfg, plan)[0]),
    )
    out.views["factors"] = fi.exposure(out, tr, desk, {s: w / 100 for s, w in symbol_weights(now_rows, total).items()})
    out.m("cash.pending", amount, "usd", quality="modelled" if amount is not None else "insufficient_history")
    if when:
        out.m("cash.pending_days", (date.fromisoformat(when) - date.fromisoformat(as_of)).days, "days", quality="modelled")
    _health(out, cfg, mirror, desk, holdings, now)
    return out


def _day_quality(rows: list[dict]) -> str:
    if any(h["source"] == BACKCAST and h["quality"] == "modelled" for h in rows):
        return "modelled"
    return "pro_forma" if any(h["quality"] != "ok" for h in rows) else "ok"


def implied_flows(days: list[str], holdings: dict[str, list[dict]], aflow, income_rows) -> dict[tuple[str, str], float]:
    found: dict[tuple[str, str], float] = {}
    for i in range(1, len(days)):
        lo, hi = days[i - 1], days[i]
        today = holdings[hi]
        snapped = {h["account"] for h in today if h["source"] == "snapshot"}
        before = {h["account"] for h in holdings[lo]}
        opened = {h["account"] for h in today if h["source"] == BACKCAST} - before
        if not snapped and not opened:
            continue
        price = {h["symbol"]: h["close"] for h in today if not h["is_cash"] and h["close"]}
        for acct in sorted(snapped | before | opened):
            if acct not in snapped and acct not in opened and any(h["account"] == acct for h in today):
                continue
            prev = [h for h in holdings[lo] if h["account"] == acct]
            repriced = sum(h["value"] if h["is_cash"] else h["shares"] * (price.get(h["symbol"]) or h["close"] or 0.0) for h in prev)
            now_value = sum(h["value"] for h in today if h["account"] == acct)
            known = sum(a for d, a in aflow.get(acct, {}).items() if lo < d <= hi)
            paid = sum(a for d, ac, _, a in income_rows if ac == acct and lo < d <= hi)
            residual = now_value - repriced - known - paid
            if abs(residual) > max(1.0, abs(repriced) * 0.0005):
                found[(acct, hi)] = round(residual, 2)
    return found


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
    pic = cash_picture(holdings[as_of])
    cash_q = "modelled" if pic["modelled"] else q
    out.m("cash.share", pic["ready"] / values[-1] * 100 if values[-1] else None, "pct", quality=q)
    out.m("cash.ready", pic["ready"], "usd", quality=cash_q)
    for acct in pic["accounts"]:
        out.m("cash.ready", pic["ready_by_account"].get(acct, 0.0), "usd", scope="account", scope_id=acct, quality=cash_q)
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


def _plan_metrics(out: Out, cfg, plan, targets, kinds, rows, total, holdings, days, activity, q, amount, own=True):
    weights = symbol_weights(rows, total)
    if targets:
        ref_q = q if own else "modelled"
        drifts = {}
        for s, t in sorted(targets.items()):
            actual = weights.get(s, 0.0)
            drifts[s] = actual - t * 100
            out.m("plan.weight", actual, "pct", scope="holding", scope_id=s, quality=q)
            out.m("plan.target", t * 100, "pct", scope="holding", scope_id=s, quality=ref_q)
            out.m("plan.drift", drifts[s], "pts", scope="holding", scope_id=s, quality=ref_q)
        out.m("plan.drift_max", max(abs(v) for v in drifts.values()), "pts", quality=ref_q)
        for s, usd in sorted(deposit_split(targets, weights, total, amount or 0.0).items()):
            out.m("plan.next_deposit", usd, "usd", scope="holding", scope_id=s, quality="modelled")
        in_plan = sum(weights.get(s, 0.0) for s in targets)
        out.m("plan.in_mix", in_plan, "pct", quality=ref_q)
    singles = {s: w for s, w in weights.items() if kinds.get(s, "unknown") == "stock" and s not in targets}
    out.m("plan.single_stock", sum(singles.values()), "pct", quality=q)
    for s, w in sorted(singles.items()):
        out.m("plan.single_stock", w, "pct", scope="holding", scope_id=s, quality=q)
    unknown = sorted(s for s in weights if kinds.get(s, "unknown") == "unknown" and s not in targets)
    if unknown:
        sec = bool(os.environ.get("DESK_SEC_USER_AGENT"))
        what = "is a fund or a single stock" if len(unknown) == 1 else "are funds or single stocks"
        out.h(
            "symbol_kinds",
            "warn",
            f"Not sure whether {', '.join(unknown)} are funds or single stocks. Fix: "
            + ("the nightly research job loads SEC's ticker lists." if sec else key_fix(["DESK_SEC_USER_AGENT"])),
            f"The desk does not know yet whether {heal.listed(unknown)} {what}. "
            + ("It is looking that up." if sec else f"To let it look that up, {key_fix(['DESK_SEC_USER_AGENT'])}"),
            heal.FIXES if sec else heal.NEEDS,
            heal.RESEARCH if sec else None,
        )
    rules, source = rules_in_force(cfg, plan)
    conv = convictions(rules)
    debit = cash_picture(rows)["debit"]
    judged = []
    for rule in rules:
        breaks = _rule_breaks(rule, weights, singles, targets if own else {}, debit, holdings, days, activity, kinds, conv)
        if breaks is None:
            continue
        rule_q = q if source == "profile" else "modelled"
        out.m("plan.rules", 0 if breaks else 1, "flag", scope="rule", scope_id=rule["id"], quality=rule_q)
        out.m("plan.rule_breaks", len(breaks), "count", scope="rule", scope_id=rule["id"], quality=rule_q)
        judged.append({"id": rule["id"], "kind": rule.get("kind"), "holds": not breaks, "count": len(breaks), "breaks": breaks[:RULE_BREAKS_SHOWN]})
    out.views["rules"] = {"as_of": out.as_of, "source": source, "rules": judged}


RULE_BREAKS_SHOWN = 5


def _rule_ok(rule, weights, singles, targets, debit, holdings, days, activity, kinds, conv=None) -> bool | None:
    breaks = _rule_breaks(rule, weights, singles, targets, debit, holdings, days, activity, kinds, conv)
    return None if breaks is None else not breaks


def _rule_breaks(rule, weights, singles, targets, debit, holdings, days, activity, kinds, conv=None) -> list[str] | None:
    kind, p = rule.get("kind"), rule.get("params") or {}
    conv = conv or {}
    if kind == "conviction_hold":
        sym = str((rule.get("symbols") or [""])[0]).upper()
        if not sym or not rule.get("enabled", True):
            return None
        lo, hi, w = p.get("band_min_pct", 0), p.get("band_max_pct", 100), weights.get(sym, 0.0)
        return [] if lo <= w <= hi else [f"{sym} is {w:.1f}% of the book, outside its {lo:g} to {hi:g}% band."]
    if kind == "single_stock_band":
        names = [s for s in (rule.get("symbols") or list(singles)) if s not in conv]
        lo, hi = p.get("min_pct", 0), p.get("max_pct", 100)
        return [
            f"{s} is {singles.get(s, 0.0):.1f}% of the book, outside the {lo:g} to {hi:g}% band." for s in sorted(names) if not lo <= singles.get(s, 0.0) <= hi
        ]
    if kind == "drift_max_pts":
        if not targets:
            return None
        pts = p.get("pts", 5)
        gaps = {s: weights.get(s, 0.0) - t * 100 for s, t in sorted(targets.items())}
        return [f"{s} is {gap:+.1f} points from its target, past the {pts:g} point limit." for s, gap in gaps.items() if abs(gap) > pts]
    if kind == "cash_floor_pct":
        cash = sum(h["value"] for h in holdings[days[-1]] if h["is_cash"])
        total = sum(h["value"] for h in holdings[days[-1]])
        if not total:
            return None
        share, floor = cash / total * 100, p.get("pct", 0)
        return [] if share >= floor else [f"Cash is {share:.1f}% of the book, under the {floor:g}% floor."]
    if kind == "no_margin_buys":
        since = (date.fromisoformat(days[-1]) - timedelta(days=30)).isoformat()
        found = []
        for r in activity:
            d = str(r.get("date") or "")[:10]
            if r.get("kind") == "buy" and not r.get("core") and d > since and d in holdings:
                cash = sum(h["value"] for h in holdings[d] if h["is_cash"] and h["account"] == r.get("accountKey"))
                if cash < 0:
                    sym = str(r.get("symbol") or "").upper() or "A buy"
                    found.append((d, f"{sym} was bought on {d} with borrowed money: the account's cash was negative that day."))
        return [text for _, text in sorted(found, reverse=True)]
    if kind == "no_new_single_stocks":
        before = (date.fromisoformat(days[-1]) - timedelta(days=30)).isoformat()
        old = max((d for d in days if d <= before), default=None)
        if old is None:
            return None
        held_then = {h["symbol"] for h in holdings[old]}
        return [f"{s} is a single stock that was not held on {old}." for s in sorted(singles) if s not in held_then and s not in conv]
    return None


def _margin_metrics(out: Out, rows, total, cfg: Config | None = None):
    rate, rate_source = margin_rate(cfg)
    maint = env_float("DESK_MARGIN_MAINT_PCT") or 30.0
    pic = cash_picture(rows)
    by_acct = defaultdict(lambda: {"debit": 0.0, "value": 0.0})
    for h in rows:
        if not h["is_cash"]:
            by_acct[h["account"]]["value"] += h["value"]
    for acct in pic["accounts"]:
        by_acct[acct]["value"] += pic["ready_by_account"].get(acct, 0.0)
        by_acct[acct]["debit"] = pic["debit_by_account"].get(acct, 0.0)
    debit = pic["debit"]
    modelled = any(h["is_cash"] and h["value"] < 0 and h["quality"] == "modelled" for h in rows)
    out.m("margin.debit", debit, "usd", quality="modelled" if modelled else "ok")
    if debit > 0:
        known = rate is not None and rate_source != "default"
        out.m("margin.cost_month", debit * rate / 100 * 30 / 360 if rate is not None else None, "usd", quality="ok" if known else "modelled")
        out.m("margin.funded_share", debit / total * 100 if total else None, "pct")
        for acct, a in sorted(by_acct.items()):
            if a["debit"] > 0 and a["value"] > 0:
                drop = 1 - a["debit"] / ((1 - maint / 100) * a["value"])
                out.m("margin.call_drop", max(0.0, drop) * 100, "pct", scope="account", scope_id=acct, quality="modelled")
        if rate is None:
            out.h("margin_rate", "warn", NO_MARGIN_RATE, NO_MARGIN_RATE.replace("Fix: open", "Open"), heal.NEEDS)
        elif rate_source == "default":
            out.h("margin_rate", "ok", f"Margin interest is estimated at a typical {rate:g}% a year until you set your own rate in Settings.")
    else:
        out.m("margin.cost_month", 0.0, "usd")


def _margin_paid(out: Out, activity, as_of):
    paid = [(str(r.get("date") or "")[:10], -float(r.get("amount") or 0)) for r in activity if r.get("kind") == "margin_interest"]
    if not paid:
        return
    end = date.fromisoformat(as_of)
    for w, lo in (("YTD", f"{as_of[:4]}-01-01"), ("1Y", (end - timedelta(days=365)).isoformat())):
        picked = [usd for d, usd in paid if lo <= d <= as_of]
        out.m("margin.interest_paid", round(sum(picked), 2), "usd", window=w, n_obs=len(picked))


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
    sold = realized_rows(desk, out.book.realized if out.book else None)
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
    sold = realized_rows(desk, out.book.realized if out.book else None)
    r = realized(sold, int(as_of[:4]))
    rq = "modelled" if r["modelled"] else "ok"
    if not sold:
        rq = "insufficient_history"
    for metric_id, key in (("tax.realized_st", "st"), ("tax.realized_lt", "lt"), ("tax.wash_disallowed", "wash_disallowed")):
        out.m(metric_id, r[key] if sold else None, "usd", window="YTD", n_obs=r["rows"], quality=rq)
    lots = current_lots(desk, out.book.lots if out.book else None)
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
    lq = ("modelled" if any(lot.get("quality") == "modelled" for lot in lots) else "ok") if lots else "insufficient_history"
    out.m("tax.unrealized_st", st if lots else None, "usd", quality=lq)
    out.m("tax.unrealized_lt", lt if lots else None, "usd", quality=lq)
    today = max(as_of, now.date().isoformat())
    windows = wash_windows(activity, sold, lots, today)
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
        out.h(
            "marginal_rate",
            "warn",
            "No marginal tax rate yet. Fix: open Taxes in Escape Vektor once; the desk reads the rate from there.",
            "No tax rate yet. Open Taxes in Escape Vektor once and the desk reads it from there.",
            heal.NEEDS,
        )
    out.m("tax.harvest_value", total * rate / 100 if lots and rate is not None else None, "usd", quality="modelled")
    if source != "none":
        out.h("marginal_rate", "ok", "Marginal rate from Escape Vektor's tax estimate." if source == "escape_vektor" else "Marginal rate from your profile.")


# ---- Rule replays ----


def _replay(out: Out, activity, series, targets, rows) -> dict:
    cover = out.history.cover if out.history else {}

    def rate(scope: str, scope_id: str) -> float | None:
        return next((m[5] for m in out.metrics if m[0] == "tax.marginal_rate" and m[1] == scope and m[2] == scope_id), None)

    return replay.run(
        out.as_of,
        activity,
        cover,
        series,
        broad=LISTED_FUNDS | set(targets),
        mutual=out.history.mutual if out.history else set(),
        sheltered=account_sheltered,
        held_value=round(sum(h["value"] for h in rows if h["account"] in cover), 2) if cover else None,
        short_rate=rate("portfolio", "all"),
        state_rate=rate("tax", "state") or 0.0,
    )


# ---- Research signals and macro ----


def _flight_record(out: Out, cfg: Config, desk, tr, targets, kinds, rows):
    ref = risk.market_symbol(tr)
    cal = tr.dates.get(ref, []) if ref else sorted({d for s in targets for d in tr.dates.get(s, [])})
    rate = next((m[5] for m in out.metrics if m[0] == "tax.marginal_rate" and m[1] == "portfolio" and m[5] is not None), None)
    decisions = scoring.decision_rows(cfg)
    card = scoring.metrics(out, cfg, tr, targets, rate=rate / 100 if rate is not None else None, cal=cal, fallback=ref, rows=decisions)
    held = sorted({h["symbol"] for h in rows if not h["is_cash"]})
    watch = [r[0] for r in desk.execute("SELECT symbol FROM market_symbols WHERE role='watch'")]
    symbols = sorted({*held, *watch})
    out.views["scorecard"] = card
    out.views["patterns"] = patterns.metrics(out, desk, tr, symbols, kinds, card, decisions)


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
        sec = bool(os.environ.get("DESK_SEC_USER_AGENT"))
        fix = "the nightly research job fills them" if sec else key_fix(["DESK_SEC_USER_AGENT"]).rstrip(".")
        out.h(
            "research",
            "warn",
            f"No SEC company facts yet for {', '.join(bare[:10])}. Fix: {fix}.",
            f"Company facts for {heal.listed(bare)} are not in yet. " + ("The desk is fetching them." if sec else f"To fetch them, {fix}."),
            heal.FIXES if sec else heal.NEEDS,
            heal.RESEARCH if sec else None,
        )
    elif symbols:
        out.h("research", "ok", f"SEC company facts for {len(symbols)} stocks.", f"Company facts are in for {len(symbols)} stocks.")


# ---- Data health ----


def _closes_check(desk, rows, as_of: str) -> Check:
    held = sorted({h["symbol"] for h in rows if not h["is_cash"]})
    newest: dict[str, str] = {}
    for tbl in ("prices_daily", "price_bars"):
        if desk.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tbl,)).fetchone():
            for sym, d in desk.execute(f"SELECT symbol, max(date) FROM {tbl} GROUP BY symbol"):
                newest[sym] = max(newest.get(sym, ""), d)
    no_source, asked = set(), {}
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='market_symbols'").fetchone():
        asked = {r["symbol"]: r for r in desk.execute("SELECT symbol, priority, last_bar, fetched_at, error FROM market_symbols WHERE error IS NOT NULL")}
        no_source = {s for s, r in asked.items() if r["error"].startswith(NO_PRICES)}
    snap = {h["symbol"] for h in rows if h["source"] == "snapshot"}
    quoted = provisional_symbols(desk, as_of)
    missing = [s for s in held if s not in newest and s not in no_source and s not in quoted]
    session = last_trading_day(date.fromisoformat(as_of)).isoformat()
    stale = [s for s in held if s in newest and newest[s] < session and s not in snap and s not in quoted]
    broker = [s for s in held if s not in newest and s in no_source]
    notes, say = [], []
    kind, job = heal.FIXES, None
    keyed = bool(os.environ.get("TIINGO_API_KEY"))
    no_key = "Fix: " + key_fix(["TIINGO_API_KEY"])
    add_key = f"To get prices by itself, the desk needs you to {key_fix(['TIINGO_API_KEY'])}"
    day = heal.plain_day(session, as_of)
    if missing:
        notes.append(f"No close for {', '.join(missing)} on {as_of}. " + (f"The desk asks for them {ASK_WORDS}. Fix: nothing to do yet." if keyed else no_key))
        say.append(
            f"No price yet for {heal.listed(heal.names(desk, missing))}. "
            + (f"The desk is asking for {'it' if len(missing) == 1 else 'them'} now." if keyed else add_key)
        )
        kind, job = (heal.FIXES, heal.BACKFILL) if keyed else (heal.NEEDS, None)
    if quoted:
        notes.append(f"{day_words(as_of)} is priced from the closing quotes until {CLOSES_LAND} The day is restated as they land.")
        say.append(f"{day} is priced from closing quotes until {CLOSES_LAND}")
        if stale:
            notes.append(f"{', '.join(stale)} have no quote, so they carry their last close until then.")
            say.append(f"{_prices(desk, stale)} without a quote {'carries its' if len(stale) == 1 else 'carry their'} last close until then.")
    elif stale:
        oldest = min(newest[s] for s in stale)
        head = f"Closes for {', '.join(stale)} stop at {oldest}."
        if not keyed:
            notes.append(f"{head} {no_key}")
            say.append(f"{_prices(desk, stale)} for {day} {_be(stale)} missing. {add_key}")
            kind = heal.NEEDS
        elif oldest >= last_trading_day(date.fromisoformat(session) - timedelta(days=1)).isoformat():
            notes.append(
                f"{head} A fund's price for a day can arrive hours after the others. The desk asks for it {ASK_WORDS}, "
                "and the day's numbers follow once it lands. Fix: nothing to do yet."
            )
            say.append(f"{_prices(desk, stale)} for {day} {_be(stale)} not out yet. The desk checks every hour.")
        else:
            notes.append(f"{head} That is more than a day behind. Fix: in {JOBS_AT}, run Backfill and read its result there.")
            say.append(f"{_prices(desk, stale)} {_be(stale)} more than a day behind. The desk is asking for {'it' if len(stale) == 1 else 'them'} again now.")
            job = job or heal.BACKFILL
    notes.extend(_ask_words(s, asked[s]) for s in stale if s in asked)
    if broker:
        notes.append(f"{', '.join(broker)} have no market price anywhere, so they're valued at the broker's snapshot price.")
    status = "warn" if missing or (stale and not quoted) else "ok"
    return Check(
        "closes", status, " ".join(notes) or f"Every holding has a close on {as_of}.", " ".join(say) or f"Every holding has a price for {day}.", kind, job
    )


def _prices(desk, symbols: list[str]) -> str:
    funds = all(len(s) == 5 and s.endswith("X") for s in symbols)
    if len(symbols) == 1:
        return f"The price of {heal.names(desk, symbols)[0]}"
    return f"{heal.count(len(symbols))} {'fund prices' if funds else 'prices'}"


def _be(symbols: list[str]) -> str:
    return "is" if len(symbols) == 1 else "are"


def _ask_words(symbol: str, row) -> str:
    until = parked_until(row)
    if until is None:
        return f"The last ask for {symbol} failed ({row['error']}); it is asked again at the next run."
    return f"Tiingo had no prices for {symbol} at the last ask; it is asked again on {day_words(until.astimezone(ET).date().isoformat())}."


def _snapshot_age(rows, day: str, series) -> str | None:
    session = last_trading_day(date.fromisoformat(day)).isoformat()
    priced = [h for h in rows if not h["is_cash"] and h["shares"] and h["reported_value"] and series.get(h["symbol"])]
    newest = {h["symbol"]: max(d for d in series[h["symbol"]] if d <= day) for h in priced if any(d <= day for d in series[h["symbol"]])}
    hits = [matching_close(series[h["symbol"]], h["reported_value"] / h["shares"], newest[h["symbol"]]) for h in priced if h["symbol"] in newest]
    hits = [d for d in hits if d and d < session]
    if not priced or len(hits) * 2 < len(priced):
        return None
    return max(set(hits), key=hits.count)


def _value_check(rows, day: str, series=None) -> Check:
    mism = [h for h in rows if h["quality"] == "mismatch"]
    if mism:
        return Check(
            "value",
            "fail",
            f"The {day} snapshot's positions don't add up to its account totals. Fix: in {JOBS_AT}, run Accounts; if it repeats, check Escape Vektor.",
            f"Your broker's positions and account totals for {heal.plain_day(day)} do not add up, so values cannot be trusted yet. "
            "The desk is reading your accounts again.",
            heal.BLOCKS,
            heal.ACCOUNTS,
        )
    bad, gaps = [], []
    for acct in sorted({h["account"] for h in rows}):
        mine = [h for h in rows if h["account"] == acct]
        calc = sum(h["value"] for h in mine)
        rep = sum(h["reported_value"] or 0 for h in mine)
        if abs(calc - rep) > max(1.0, abs(rep) * 0.0005):
            bad.append(f"{acct} {calc:,.2f} vs {rep:,.2f}")
            for h in mine:
                if not h["is_cash"] and h["shares"] and h["reported_value"] is not None and h["close"]:
                    broker = h["reported_value"] / h["shares"]
                    if abs(broker - h["close"]) > max(0.01, broker * 0.0005):
                        gaps.append((abs(h["value"] - h["reported_value"]), f"{h['symbol']} {h['close']:,.2f} vs {broker:,.2f}"))
    if not bad:
        return Check("value", "ok", f"Values match the broker on {day}.", f"Values match your broker for {heal.plain_day(day)}.")
    top = ", ".join(g for _, g in sorted(gaps, reverse=True)[:3])
    why = f" Biggest price gaps (close vs broker): {top}." if top else ""
    age = _snapshot_age(rows, day, series or {})
    if age:
        return Check(
            "value",
            "warn",
            f"{'; '.join(bad)}. The {day} snapshot carries {age} closes, so the broker figures are older than the desk's.{why} "
            "Fix: nothing to do; the desk values at the newer closes and the next sync catches up.",
            f"Your broker's figures still use {heal.plain_day(age, day)}'s prices and the desk uses newer ones, so the totals differ a little. "
            "It clears with the next account read.",
            heal.FIXES,
        )
    return Check(
        "value",
        "warn",
        f"{'; '.join(bad)}.{why} Fix: the broker priced at a different time than the close; it clears with the next snapshot.",
        "Your broker priced a few holdings at a different time than the market close, so the totals differ a little. It clears with the next account read.",
        heal.FIXES,
    )


LOT_METHOD = "FIFO for stocks and ETFs, average cost for mutual funds"


def _history_check(h: broker.History | None) -> Check:
    if h is None or not h.rows:
        return Check("history", "ok", "No Fidelity history imported, so Escape Vektor's activity is used as is.")
    info = broker.summary(h)
    span = f"{info['start']} to {info['end']}"
    detail = f"Fidelity history {span}: {info['rows']} rows over {', '.join(info['accounts'])}; {info['matched']} Escape Vektor rows replaced."
    if h.kept:
        shown = ", ".join(
            f"{r.get('date')} {r.get('accountKey')} {r.get('kind')} {r.get('symbol') or 'cash'} {float(r.get('amount') or 0):+,.2f}" for r in h.kept[:3]
        )
        detail += f" {len(h.kept)} Escape Vektor rows inside those dates had no broker match and are kept as they are ({shown})."
    if not h.unmapped:
        return Check("history", "ok", detail, f"Your Fidelity history is loaded, from {heal.plain_day(info['start'])} to {heal.plain_day(info['end'])}.")
    return Check(
        "history",
        "warn",
        f"{detail} But no Escape Vektor account ends with the same 4 digits as {', '.join(h.unmapped)}. "
        f"Fix: check the account names in Escape Vektor, then upload the Fidelity history JSON again in {INBOX_AT}.",
        "Part of your Fidelity history belongs to an account the desk cannot match. "
        f"Check the account names in Escape Vektor, then upload the history again in {INBOX_AT}.",
        heal.NEEDS,
    )


def _modelled_check(out: Out, lots: list[dict], rows: list[dict]) -> Check:
    accounts = {lot["account"] for lot in lots}
    held = defaultdict(float)
    for h in rows:
        if not h["is_cash"] and h["account"] in accounts:
            held[(h["account"], h["symbol"])] += h["shares"]
    lot_sh = defaultdict(float)
    for lot in lots:
        lot_sh[(lot["account"], lot["symbol"])] += lot["shares"]
    keys = sorted(set(held) | set(lot_sh))
    diffs = [
        f"{a} {s}: lots {lot_sh.get((a, s), 0):g} vs held {held.get((a, s), 0):g}" for a, s in keys if abs(lot_sh.get((a, s), 0) - held.get((a, s), 0)) > 1e-3
    ]
    rebuilt = {lot["account"] for lot in lots if lot.get("quality") == "modelled"}
    notes = [f"{a} {s} {text}" for (a, s), text in sorted((out.book.notes if out.book else {}).items()) if a in rebuilt]
    head = f"Lots rebuilt from the Fidelity history ({LOT_METHOD})"
    if not diffs and not notes:
        return Check("shares", "ok", f"{head} match holdings.", "Tax lots rebuilt from your Fidelity history match what you hold.")
    body = "; ".join(diffs[:8] + notes[:5])
    return Check(
        "shares",
        "warn",
        f"{head}: {body}. Fix: upload a lot export CSV in {INBOX_AT}; it wins over the rebuilt lots.",
        f"Tax lots rebuilt from your Fidelity history do not quite match what you hold. To settle it, upload a lot export in {INBOX_AT}.",
        heal.NEEDS,
    )


def _flows_check(implied: dict[tuple[str, str], float], holdings, cover: dict[str, tuple[str, str]] | None = None) -> Check:
    snaps = [d for d in holdings if any(h["source"] == "snapshot" for h in holdings[d])]
    if not snaps:
        return Check("flows", "ok", "No snapshots yet.", "No account reads yet.")
    last = max(snaps)
    mine = {a: v for (a, d), v in implied.items() if d == last}
    if not mine:
        return Check(
            "flows", "ok", f"The {last} snapshot matches prices plus recorded activity.", "Your latest account read matches prices plus recorded activity."
        )
    covered = sorted(a for a in mine if a in (cover or {}) and cover[a][0] <= last <= cover[a][1])
    other = sorted(a for a in mine if a not in covered)

    def parts(accounts: list[str]) -> str:
        return "; ".join(f"{a} {mine[a]:+,.2f}" for a in accounts)

    counted = "counted as money in or out, not return (deposits, payroll contributions or a margin buy Escape Vektor didn't log)"
    if covered:
        rest = f" Also {parts(other)} in accounts with no Fidelity history, {counted}." if other else ""
        several = len(covered) > 1
        return Check(
            "flows",
            "ok",
            f"The {last} snapshot moved {parts(covered)} beyond prices and recorded activity, and Fidelity history covers {', '.join(covered)} on that day. "
            "A history lists a day's deposits, dividends and interest a day or two later, so no upload clears this today; counted as money in or out "
            f"until a later history shows what it was. If it is still there in a history exported two days later, it is a missing or misread row.{rest}",
            f"{heal.count(len(covered))} Fidelity account{'s' if several else ''} moved by more than prices and your recorded activity explain. "
            "Fidelity lists a day's deposits and dividends a day or two later, so the desk counts the difference as money in or out "
            f"until a later history shows what it was.",
        )
    return Check(
        "flows",
        "ok",
        f"The {last} snapshot moved {parts(other)} beyond prices and recorded activity; {counted}.",
        "Money the desk had not seen recorded, such as a deposit or a payroll contribution, was counted as money in or out, not as return.",
    )


def _market_keys() -> Check:
    need = [(k, why) for k, why in MARKET_KEYS if not os.environ.get(k)]
    if not need:
        return Check("market_keys", "ok", "Tiingo, Finnhub, FRED, SEC and Alpaca paper are all set.", "Every data source is set up.")
    gaps = "; ".join(f"{KEY_WORDS[k]} ({why})" for k, why in need)
    several = len(need) > 1
    return Check(
        "market_keys",
        "warn",
        f"Missing {gaps}. Fix: {key_fix([k for k, _ in need])}",
        f"{heal.count(len(need))} data source{'s are' if several else ' is'} not set up, so parts of the desk are off. "
        f"Add {'them' if several else 'it'} in {KEYS_AT}.",
        heal.NEEDS,
    )


def _health(out: Out, cfg: Config, mirror, desk, holdings, now: datetime):
    if any(r[0] == "tables" for r in mirror.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        row = mirror.execute("SELECT mirrored_at FROM tables WHERE tbl='snapshots'").fetchone()
        if row and row["mirrored_at"]:
            age = (now - datetime.fromisoformat(row["mirrored_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            status = "ok" if age <= cfg.stale_hours else "fail"
            fix = "" if status == "ok" else f" Fix: in {JOBS_AT}, run Accounts and read its result there."
            ago = "under an hour ago" if age < 1 else f"{age:.0f} hour{'' if round(age) == 1 else 's'} ago"
            say = f"Your accounts were read {ago}."
            if status != "ok":
                say = f"Your accounts were last read {ago}, so these numbers are old. The desk is reading them again now."
            out.h("freshness", status, f"Mirror pulled {age:.1f} hours ago (limit {cfg.stale_hours:g}).{fix}", say, heal.BLOCKS, heal.ACCOUNTS)
        else:
            out.h(
                "freshness",
                "fail",
                f"The mirror has never pulled snapshots. Fix: in {JOBS_AT}, run Accounts and read its result there.",
                "Your accounts have not been read yet. The desk is reading them now.",
                heal.BLOCKS,
                heal.ACCOUNTS,
            )
    as_of = out.as_of
    rows = holdings[as_of]
    out.c(_closes_check(desk, rows, as_of))
    out.c(_flows_check(out.implied, holdings, out.history.cover if out.history else None))
    snap_days = [d for d in holdings if any(h["source"] == "snapshot" for h in holdings[d])]
    if snap_days:
        out.c(_value_check(holdings[max(snap_days)], max(snap_days), price_series(mirror, desk)))
    out.c(_market_keys())
    out.c(_history_check(out.history))
    lots = current_lots(desk, out.book.lots if out.book else None)
    modelled = any(lot.get("quality") == "modelled" for lot in lots)
    if lots and modelled:
        out.c(_modelled_check(out, lots, rows))
    elif lots:
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
        detail = "Lot shares match holdings."
        say = "Your tax lots match what you hold."
        if diffs:
            detail = "; ".join(diffs[:10]) + f". Fix: upload a fresh lot export in {INBOX_AT}."
            say = f"Your lot export no longer matches what you hold, so tax figures are off. Upload a fresh one in {INBOX_AT}."
        out.h("shares", status, detail, say, heal.BLOCKS if status == "fail" else heal.NEEDS)
    else:
        out.h(
            "shares",
            "warn",
            f"No lots yet, so tax lots and wash-sale checks are off. Fix: upload the Fidelity history JSON or a lot export CSV in {INBOX_AT}.",
            f"No tax lots yet, so tax and wash-sale checks are off. Upload your Fidelity history or a lot export in {INBOX_AT}.",
            heal.NEEDS,
        )


# ---- Store ----


def store(desk: sqlite3.Connection, out: Out) -> dict:
    if any(h[2] == "fail" for h in out.health):
        out.metrics = [m[:8] + ((m[8] if m[8] in KEPT_ON_FAIL else "stale"),) + m[9:] for m in out.metrics]
    with desk:
        desk.execute("DELETE FROM metric_values WHERE as_of=?", (out.as_of,))
        desk.executemany("INSERT INTO metric_values VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", out.metrics)
        desk.execute("DELETE FROM series_daily")
        desk.executemany("INSERT OR REPLACE INTO series_daily VALUES (?, ?, ?, ?, ?, ?)", out.series)
        desk.execute("DELETE FROM data_health WHERE as_of=?", (out.as_of,))
        desk.executemany("INSERT INTO data_health (as_of, check_name, status, detail, say, kind, job) VALUES (?, ?, ?, ?, ?, ?, ?)", out.health)
        if out.lookthrough is not None:
            desk.execute("DELETE FROM lookthrough")
            desk.executemany("INSERT OR REPLACE INTO lookthrough VALUES (?, ?, ?, ?, ?, ?)", out.lookthrough)
        if out.signals is not None:
            desk.execute("DELETE FROM signals WHERE as_of=?", (out.as_of,))
            desk.executemany("INSERT OR REPLACE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", out.signals)
        for name, body in out.views.items():
            desk.execute("INSERT OR REPLACE INTO engine_views VALUES (?, ?, ?)", (name, out.as_of, json.dumps(body)))
        if out.book is not None:
            broker.store(desk, out.book, out.as_of)
        if out.wash is not None:
            desk.execute("DELETE FROM wash_windows")
            desk.executemany("INSERT OR REPLACE INTO wash_windows VALUES (?, ?, ?, ?, ?, ?, ?)", out.wash)
    worst = heal.overall([{"status": h[2], "kind": h[5]} for h in out.health])
    return {"as_of": out.as_of, "metrics": len(out.metrics), "series": len(out.series), "health": worst, "checks": {h[1]: h[2] for h in out.health}}
