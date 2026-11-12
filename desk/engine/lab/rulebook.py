import itertools
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from desk.engine.lab import stats
from desk.engine.lab.data import FUND_KINDS, LabData
from desk.engine.lab.sim import DEFAULT_RATE, FUND_BPS, _year_tax
from desk.engine.shadows import deposit_split

RULES = {
    "rebalance_band": {"band_pts": (1.0, 25.0)},
    "deposit_steering": {},
    "harvest": {"threshold_usd": (50.0, 100_000.0)},
    "margin": {"dip_pct": (5.0, 60.0), "borrow_pct": (1.0, 50.0), "rate_pct": (0.0, 30.0)},
    "dip_reserve": {"hold_pct": (5.0, 90.0), "dip_pct": (5.0, 60.0)},
    "spread": {"months": (2.0, 36.0)},
}
REQUIRED = {
    "rebalance_band": ("band_pts",),
    "harvest": ("threshold_usd",),
    "margin": ("dip_pct", "borrow_pct", "rate_pct"),
    "dip_reserve": ("hold_pct", "dip_pct"),
    "spread": ("months",),
}
SCALAR = ("rate_pct",)
DEFAULT_DEPOSIT = 1_000.0
DEFAULT_START = 10_000.0
ORDINARY_OFFSET = 3_000.0
MAINTENANCE = 0.30
RESTORE = 0.35
MAX_GRID = 12
HOLDOUT_YEARS = 2
SHELTERED = ("hsa", "ira", "roth", "401k", "401(k)")


class RuleError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Rule:
    id: str
    version: int
    rule: str
    variants: list[dict]
    mix: dict[str, float]
    horizons: list[int]
    deposit: float
    start_value: float
    taxable: bool
    raw: dict
    caveats: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    days: list[str]
    equity: list[float]
    twr: list[float]
    contributed: float = 0.0
    taxes: float = 0.0
    benefits: float = 0.0
    interest: float = 0.0
    costs: float = 0.0
    traded: float = 0.0
    trades: int = 0
    harvested: float = 0.0
    margin_calls: int = 0
    after_liq: float = 0.0


# ---- Parsing ----


def _num(value, lo: float, hi: float, what: str, problems: list[str]) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        problems.append(f"{what}: {value!r} is not a number")
        return None
    if not lo <= x <= hi:
        problems.append(f"{what}: {x:g} must sit between {lo:g} and {hi:g}")
        return None
    return x


def parse(raw: dict, data: LabData) -> Rule:
    problems: list[str] = []
    rid = str(raw.get("id") or "").strip()
    if not rid:
        problems.append("a rule request needs an id")
    name = str(raw.get("rule") or "")
    if name not in RULES:
        problems.append(f"rule must be one of {', '.join(RULES)}")
        raise RuleError(problems)
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        problems.append("params must be an object")
        params = {}
    grid: dict[str, list[float]] = {}
    for key in REQUIRED.get(name, ()):
        if key not in params:
            problems.append(f"{name} needs params.{key}")
    for key, value in params.items():
        if key not in RULES[name]:
            problems.append(f"{name} has no param {key!r}; it takes {', '.join(RULES[name]) or 'none'}")
            continue
        lo, hi = RULES[name][key]
        if key in SCALAR and isinstance(value, list):
            problems.append(f"{key} is a fact, not a dial; give one number")
            continue
        values = value if isinstance(value, list) else [value]
        grid[key] = [x for x in (_num(v, lo, hi, f"params.{key}", problems) for v in values) if x is not None]
    keys = sorted(grid)
    combos = [dict(zip(keys, c, strict=True)) for c in itertools.product(*(grid[k] for k in keys))] if keys else [{}]
    if len(combos) > MAX_GRID:
        problems.append(f"{len(combos)} variants is over the rule grid cap of {MAX_GRID}")
    mix_raw = raw.get("mix") or data.plan_mix
    mix = {str(s).upper(): float(w) for s, w in (mix_raw or {}).items() if float(w) > 0}
    if not mix:
        problems.append("there is no plan mix in the lab data, so the request needs a mix of funds")
    for sym in mix:
        if sym not in data.series:
            problems.append(f"{sym} has no bars in the lab data")
        elif data.kinds.get(sym, "unknown") not in FUND_KINDS and sym not in data.plan_mix:
            problems.append(f"{sym} is not a fund; rule backtests run on the plan's funds")
    horizons = sorted({int(h) for h in raw.get("horizons") or [5, 10] if int(h) in (3, 5, 10)})
    if not horizons:
        problems.append("horizons must include 3, 5 or 10")
    account = str(raw.get("account") or "taxable").lower()
    taxable = not any(k in account for k in SHELTERED)
    if name == "harvest" and not taxable:
        problems.append("tax-loss harvesting only means something in a taxable account")
    deposit = _num(raw.get("deposit_monthly", DEFAULT_DEPOSIT), 0.0, 1_000_000.0, "deposit_monthly", problems)
    start_value = _num(raw.get("start_value", DEFAULT_START), 0.0, 100_000_000.0, "start_value", problems)
    if deposit == 0 and name in ("deposit_steering", "dip_reserve"):
        problems.append(f"{name.replace('_', ' ')} needs a monthly deposit above zero")
    if start_value == 0 and name == "spread":
        problems.append("spreading a lump sum needs a start_value above zero")
    if problems:
        raise RuleError(problems)
    total = sum(mix.values())
    caveats = [
        "Dividends sit inside adjusted prices, so dividend tax is not charged, the same for both sides.",
        "Both sides are sold at the end and taxed, so a deferred gain is not counted as a win.",
    ]
    if name == "harvest":
        caveats.append("Harvest sells into a close substitute fund, modelled as the same returns with a new basis; wash-sale timing is assumed handled.")
    if name in ("dip_reserve", "spread"):
        caveats.append("Money held back earns the three-month Treasury rate until it is invested.")
    if name == "margin":
        caveats.append("Margin interest is charged at the given rate on a 360-day year and not deducted; a margin call sells at 30% equity, back to 35%.")
    return Rule(rid, int(raw.get("version") or 1), name, combos, {s: w / total for s, w in mix.items()}, horizons, deposit, start_value, taxable, raw, caveats)


# ---- Simulation ----


def _months(cal: list[str]) -> set[str]:
    out, seen = set(), set()
    for d in cal:
        if d[:7] not in seen:
            seen.add(d[:7])
            out.add(d)
    return out


def simulate(data: LabData, rule: Rule, params: dict | None, start: str, end: str, *, rate: float) -> Outcome:
    cal = [d for d in data.calendar if start <= d <= end and all(data.series[s].dates[0] <= d for s in rule.mix)]
    out = Outcome(cal, [], [])
    if len(cal) < 2:
        return out
    params = params or {}
    firsts = _months(cal)
    syms = list(rule.mix)
    series = {s: data.series[s] for s in syms}
    cash, loan = rule.start_value, 0.0
    out.contributed = rule.start_value
    slices = int(params.get("months") or 0) if rule.rule == "spread" else 0
    reserve = rule.start_value * (1 - 1 / slices) if slices else 0.0
    part = rule.start_value / slices if slices else 0.0
    qty = {s: 0.0 for s in syms}
    lots: dict[str, list[list]] = {s: [] for s in syms}
    realized = {"st": 0.0, "lt": 0.0}
    carry = 0.0
    pending: str | None = None
    borrowed, peak, level, prev = False, 0.0, 1.0, None
    units: dict[str, float] = {}

    def px_at(day: str, field_: str) -> dict[str, float]:
        out_ = {}
        for s in syms:
            ser = series[s]
            i = ser.index.get(day)
            if i is None:
                i = ser.at(day)
                out_[s] = ser.adj[i] if i is not None else 0.0
            else:
                out_[s] = ser.open_adj[i] if field_ == "open" else ser.adj[i]
        return out_

    def gross(px: dict[str, float]) -> float:
        return sum(qty[s] * px[s] for s in syms)

    def sell(sym: str, n: float, px: float, day: str) -> float:
        nonlocal cash
        n = min(n, qty[sym])
        left = n
        d = date.fromisoformat(day)
        while left > 1e-12 and lots[sym]:
            lot = lots[sym][0]
            take = min(left, lot[1])
            realized["lt" if (d - lot[3]).days > 365 else "st"] += take * (px - lot[2])
            lot[1] -= take
            left -= take
            if lot[1] <= 1e-12:
                lots[sym].pop(0)
        qty[sym] -= n
        fee = n * px * FUND_BPS / 10_000
        cash += n * px - fee
        out.costs += fee
        out.traded += n * px
        out.trades += 1
        return n * px - fee

    def buy(sym: str, dollars: float, px: float, day: str):
        nonlocal cash
        dollars = min(dollars, cash - reserve)
        if dollars < 1.0 or not px:
            return
        fee = dollars * FUND_BPS / 10_000
        n = (dollars - fee) / px
        lots[sym].append([day, n, px, date.fromisoformat(day)])
        qty[sym] += n
        cash -= dollars
        out.costs += fee
        out.traded += dollars
        out.trades += 1

    def invest(day: str, px: dict[str, float]):
        free = cash - reserve
        if free < 1.0:
            return
        if rule.rule == "deposit_steering":
            total = gross(px)
            weights = {s: qty[s] * px[s] / total * 100 for s in syms} if total else {}
            split = deposit_split(rule.mix, weights, total, free)
        else:
            split = {s: free * w for s, w in rule.mix.items()}
        for s, dollars in split.items():
            buy(s, dollars, px[s], day)

    for k, day in enumerate(cal):
        if pending:
            px = px_at(day, "open")
            if pending == "band":
                total = gross(px) + cash
                for s, w in rule.mix.items():
                    if qty[s] * px[s] > w * total + 1.0 and px[s]:
                        sell(s, (qty[s] * px[s] - w * total) / px[s], px[s], day)
                for s, w in rule.mix.items():
                    if w * total > qty[s] * px[s] + 1.0:
                        buy(s, w * total - qty[s] * px[s], px[s], day)
            elif pending == "harvest":
                for s in syms:
                    basis = sum(lot[1] * lot[2] for lot in lots[s])
                    if qty[s] and px[s] and qty[s] * px[s] - basis <= -params["threshold_usd"]:
                        out.harvested += basis - qty[s] * px[s]
                        buy(s, sell(s, qty[s], px[s], day), px[s], day)
            elif pending == "borrow":
                amount = (gross(px) + cash - loan) * params["borrow_pct"] / 100
                loan += amount
                cash += amount
            elif pending == "release":
                reserve = 0.0
            invest(day, px)
            pending = None
        if loan > 0 and k:
            charge = loan * params["rate_pct"] / 100 / 360 * (date.fromisoformat(day) - date.fromisoformat(cal[k - 1])).days
            loan += charge
            out.interest += charge
        if reserve > 0 and k:
            rf = data.macro_at("DGS3MO", day)
            if rf:
                earned = reserve * rf / 100 / 252
                cash += earned
                reserve += earned
        flow = 0.0
        if day in firsts and k:
            deposit = rule.deposit
            if loan > 0:
                pay = min(loan, deposit)
                loan -= pay
                deposit -= pay
            cash += deposit
            flow = rule.deposit
            out.contributed += rule.deposit
            if rule.rule == "dip_reserve":
                reserve += deposit * params["hold_pct"] / 100
            elif slices:
                reserve = max(0.0, reserve - part) if reserve > part * 1.5 else 0.0
        px = px_at(day, "adj")
        g = gross(px)
        if loan > 0 and g and (g + cash - loan) / g < MAINTENANCE:
            out.margin_calls += 1
            raise_ = max(0.0, g - (g + cash - loan) / RESTORE)
            for s in syms:
                if px[s] and qty[s]:
                    sell(s, raise_ * qty[s] * px[s] / g / px[s], px[s], day)
            pay = min(loan, max(cash, 0.0))
            loan -= pay
            cash -= pay
            g = gross(px)
        value = g + cash - loan
        if not units or day in firsts:
            base = sum(units[s] * px[s] for s in units) if units else 1.0
            units = {s: base * w / px[s] for s, w in rule.mix.items() if px[s]}
        bench = sum(units[s] * px[s] for s in units)
        peak = max(peak, bench)
        dd = (bench / peak - 1) * 100 if peak else 0.0
        if rule.taxable and k < len(cal) - 1 and cal[k + 1][:4] != day[:4]:
            tax, carry = _year_tax(realized, carry, rate)
            use = min(-carry, ORDINARY_OFFSET) if carry < 0 else 0.0
            carry += use
            cash += use * rate - tax
            value += use * rate - tax
            out.taxes += tax
            out.benefits += use * rate
            realized = {"st": 0.0, "lt": 0.0}
        if prev:
            level *= (value - flow) / prev
        out.twr.append(level)
        out.equity.append(value)
        prev = value if value > 0 else None
        if k == len(cal) - 1:
            break
        if rule.rule == "margin":
            if not borrowed and loan <= 0 and dd <= -params["dip_pct"]:
                pending, borrowed = "borrow", True
            elif borrowed and dd > -params["dip_pct"] / 2:
                borrowed = False
        if rule.rule == "dip_reserve" and pending is None and reserve >= 1.0 and dd <= -params["dip_pct"]:
            pending = "release"
        if pending is None and day in firsts:
            pending = "invest"
            if rule.rule == "rebalance_band" and g > 0:
                drift = max(abs(qty[s] * px[s] / g - w) * 100 for s, w in rule.mix.items())
                if drift > params["band_pts"]:
                    pending = "band"
            elif rule.rule == "harvest":
                pending = "harvest"
    last = cal[-1]
    px = px_at(last, "adj")
    for s in syms:
        if qty[s] and px[s]:
            sell(s, qty[s], px[s], last)
    tax = 0.0
    if rule.taxable:
        tax, carry = _year_tax(realized, carry, rate)
        out.taxes += tax
    out.after_liq = cash - tax - loan
    return out


def _metrics(o: Outcome) -> dict:
    if len(o.days) < 2:
        return {"days": len(o.days)}
    years = max((date.fromisoformat(o.days[-1]) - date.fromisoformat(o.days[0])).days / 365.25, 1 / 365.25)
    avg = sum(o.equity) / len(o.equity) if o.equity else 0.0
    return {
        "start": o.days[0],
        "end": o.days[-1],
        "contributed": round(o.contributed, 2),
        "end_value": round(o.equity[-1], 2),
        "after_liquidation": round(o.after_liq, 2),
        "taxes": round(o.taxes, 2),
        "loss_offset_benefit": round(o.benefits, 2),
        "interest": round(o.interest, 2),
        "costs": round(o.costs, 2),
        "trades": o.trades,
        "turnover_per_year": round(o.traded / avg / years, 4) if avg else None,
        "twr_ann_pct": stats._pct(o.twr[-1] ** (1 / years) - 1) if o.twr and o.twr[-1] > 0 else None,
        "mdd_pct": stats._pct(stats.drawdown(o.twr)),
        "harvested_losses": round(o.harvested, 2),
        "margin_calls": o.margin_calls,
    }


def _diff(a: Outcome, b: Outcome) -> float | None:
    if not b.contributed or len(a.days) < 2:
        return None
    return (a.after_liq - b.after_liq) / b.contributed * 100


def _shift(day: str, years: int) -> str:
    d = date.fromisoformat(day)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:
        return d.replace(year=d.year + years, day=28).isoformat()


def _quantiles(xs: list[float]) -> dict:
    ordered = sorted(xs)

    def q(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1)))], 4)

    return {
        "starts": len(xs),
        "mean_pts": round(sum(xs) / len(xs), 4),
        "p5_pts": q(0.05),
        "p50_pts": q(0.5),
        "p95_pts": q(0.95),
        "share_better": round(sum(1 for x in xs if x > 0) / len(xs), 4),
    }


# ---- Run ----


def evaluate(data: LabData, rule: Rule, date_range: dict | None = None) -> dict:
    rate = float(data.settings.get("marginal_rate_pct") or DEFAULT_RATE * 100) / 100
    first = max(data.series[s].dates[0] for s in rule.mix)
    cal = [d for d in data.calendar if d >= first]
    if len(cal) < 2:
        raise RuleError(["the mix has no common history in the lab data"])
    holdout = _shift(cal[-1], -HOLDOUT_YEARS)
    date_range = date_range or {}
    start = max(str(date_range.get("start") or cal[0]), cal[0])
    end = min(str(date_range.get("end") or cal[-1]), (date.fromisoformat(holdout) - timedelta(days=1)).isoformat())
    if end <= start:
        raise RuleError([f"the mix's history starts {cal[0]}, too late for anything before the two-year holdout"])
    starts = sorted(d for d in _months([d for d in cal if start <= d <= end]))
    horizons = []
    by_variant: dict[str, dict] = {json.dumps(v, sort_keys=True): {"params": v, "horizons": []} for v in rule.variants}
    for years in rule.horizons:
        diffs: dict[str, list[float]] = {k: [] for k in by_variant}
        for s0 in starts:
            s1 = _shift(s0, years)
            if s1 > end:
                break
            base = _baseline(data, rule, s0, s1, rate)
            for key, v in by_variant.items():
                o = simulate(data, rule, v["params"], s0, s1, rate=rate)
                d = _diff(o, base)
                if d is not None:
                    diffs[key].append(d)
        for key, v in by_variant.items():
            v["horizons"].append({"years": years, **(_quantiles(diffs[key]) if diffs[key] else {"starts": 0})})
        horizons.append(years)
    base_full = _baseline(data, rule, start, end, rate)
    base_hold = _baseline(data, rule, holdout, cal[-1], rate)
    for v in by_variant.values():
        full = simulate(data, rule, v["params"], start, end, rate=rate)
        hold = simulate(data, rule, v["params"], holdout, cal[-1], rate=rate)
        v["full"] = _metrics(full)
        v["full_diff_pts"] = _r(_diff(full, base_full))
        v["holdout"] = _metrics(hold)
        v["holdout_diff_pts"] = _r(_diff(hold, base_hold))
        v["verdict"] = _verdict(v)
    best = max(by_variant.values(), key=lambda v: _longest(v).get("p50_pts", float("-inf")))
    return {
        "rule": rule.rule,
        "windows": {"start": start, "end": end, "holdout_start": holdout, "last": cal[-1]},
        "mix": {s: round(w, 4) for s, w in rule.mix.items()},
        "deposit_monthly": rule.deposit,
        "start_value": rule.start_value,
        "taxable": rule.taxable,
        "baseline": {"description": _baseline_text(rule.rule), "full": _metrics(base_full), "holdout": _metrics(base_hold)},
        "variants": list(by_variant.values()),
        "best": best["params"],
        "verdict": best["verdict"],
        "trials": len(rule.variants),
        "caveats": rule.caveats
        + ["Differences are after-liquidation dollars over the baseline, in points of money put in, for every start month in the horizon."],
    }


def _baseline(data: LabData, rule: Rule, start: str, end: str, rate: float) -> Outcome:
    plain = Rule(rule.id, rule.version, "deposit_only", [{}], rule.mix, rule.horizons, rule.deposit, rule.start_value, rule.taxable, rule.raw)
    return simulate(data, plain, {}, start, end, rate=rate)


def _baseline_text(name: str) -> str:
    return {
        "margin": "Same deposits split pro rata, never borrowing",
        "dip_reserve": "Same deposits invested in full every month, nothing held back",
        "spread": "The whole sum invested on the first day",
        "harvest": "Same deposits split pro rata, never harvesting",
    }.get(name, "Deposits split pro rata to the mix, never selling")


def _longest(v: dict) -> dict:
    return next((h for h in sorted(v["horizons"], key=lambda h: -h["years"]) if h.get("starts")), {})


def _verdict(v: dict) -> str:
    h = _longest(v)
    if not h:
        return "inconclusive"
    hold = v.get("holdout_diff_pts")
    if h["p5_pts"] > 0 and (hold is None or hold >= 0):
        return "helps"
    if h["p95_pts"] < 0:
        return "hurts"
    return "no_clear_edge"


def _r(x):
    return round(x, 4) if x is not None else None


def run(conn, data: LabData, request: dict, *, now: datetime) -> dict:
    stamp = now.isoformat(timespec="seconds")
    raw = {k: v for k, v in request.items() if k not in ("request", "written_at")}
    rid, version = str(raw.get("id") or "unknown"), int(raw.get("version") or 1)
    try:
        rule = parse(raw, data)
        body = evaluate(data, rule, raw.get("date_range"))
    except RuleError as e:
        body = {"strategy_id": rid, "version": version, "kind": "rejected", "result_at": stamp, "problems": e.problems}
        with conn:
            conn.execute("INSERT OR REPLACE INTO lab_results VALUES (?, ?, 'rejected', ?, ?)", (rid, version, stamp, json.dumps(body)))
        return body
    body = {"strategy_id": rid, "version": version, "kind": "rule", "result_at": stamp, "request": raw, **body}
    with conn:
        conn.execute("INSERT OR REPLACE INTO lab_results VALUES (?, ?, 'rule', ?, ?)", (rid, version, stamp, json.dumps(body)))
        for v in body["variants"]:
            conn.execute(
                "INSERT INTO strategy_trials (strategy_id, version, params, window, kind, metrics, run_at) VALUES (?, ?, ?, ?, 'rule', ?, ?)",
                (rid, version, json.dumps(v["params"], sort_keys=True), f"{body['windows']['start']}..{body['windows']['end']}", json.dumps(v["full"]), stamp),
            )
    return body
