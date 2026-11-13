import itertools
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta

from desk.engine.lab.data import FUND_KINDS, PUBLIC_COVERAGE, PUBLIC_ROLE, SCREEN_KIND, LabData, Series, gone_before
from desk.engine.lab.rulebook import HOLDOUT_YEARS, MAX_GRID, RuleError, _longest, _num, _quantiles, _r, _shift, _verdict
from desk.engine.lab.sim import DEFAULT_RATE, FUND_BPS, LTCG, STOCK_BPS, exit_haircut
from desk.engine.lab.spec import NO_PUBLIC, PUBLIC_EXITS, PUBLIC_LOADING, public_words

RULES = {
    "average_down": {"drop_pct": (10.0, 90.0)},
    "cap_position": {"cap_pct": (1.0, 90.0)},
    "harvest_return": {"drop_pct": (5.0, 90.0)},
}
REQUIRED = {"average_down": ("drop_pct",), "cap_position": ("cap_pct",), "harvest_return": ("drop_pct",)}
HORIZONS = {"average_down": (1, 3, 5), "cap_position": (3, 5), "harvest_return": (1, 3)}
ALLOWED = (1, 3, 5, 10)
BENCH = "SPY"
YEAR = 252
MIN_HISTORY = 300
MIN_PRICE = 5.0
START_PCT = 30.0
AWAY_DAYS = 31
LONG_DAYS = 365
HOLDOUT_HORIZON = 1
MIN_STARTS = 6
ROUGH_UNDER = 12
UNIT = {"average_down": "months with a case", "cap_position": "January starts", "harvest_return": "months with a case"}
SHORT_HISTORY = "the public stock list has too little history before the two-year holdout"
HIGH_WORDS = "No purchase price is known for a company picked this way, so its one-year high stands in for what was paid."
SAME_TAX = "Both sides are sold at the end and taxed. A loss counts for the tax it saves against other gains, the same on both sides."
POOLED = (
    "Cases bunch up in bad months, so each month's cases are averaged into one vote before the spread is read. "
    "Differences are after-tax dollars over the baseline, in points of the money put in."
)
BASELINE = {
    "average_down": "The same dollar put into the S&P 500 on the same day and held as long",
    "cap_position": "The same start, never trimmed",
    "harvest_return": "The same losing position, simply held",
}


@dataclass
class ListRule:
    id: str
    version: int
    rule: str
    variants: list[dict]
    horizons: list[int]
    start_pct: float
    raw: dict
    caveats: list[str] = field(default_factory=list)


@dataclass
class Case:
    sym: str
    day: str
    high: float = 0.0
    high_day: str = ""


@dataclass
class Ctx:
    data: LabData
    cal: list[str]
    spy: Series
    rate: float
    gone: str
    names: list[str]
    quarters: list[str]
    januaries: list[str]
    drops: dict[tuple[str, float], list[Case]] = field(default_factory=dict)
    runs: dict[tuple[str, str, str], float | None] = field(default_factory=dict)


# ---- Parsing ----


def parse(raw: dict, data: LabData) -> ListRule:
    problems: list[str] = []
    rid = str(raw.get("id") or "").strip()
    if not rid:
        problems.append("a rule request needs an id")
    name = str(raw.get("rule") or "")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        problems.append("params must be an object")
        params = {}
    grid: dict[str, list[float]] = {}
    for key in REQUIRED[name]:
        if key not in params:
            problems.append(f"{name} needs params.{key}")
    for key, value in params.items():
        if key not in RULES[name]:
            problems.append(f"{name} has no param {key!r}; it takes {', '.join(RULES[name])}")
            continue
        lo, hi = RULES[name][key]
        values = value if isinstance(value, list) else [value]
        grid[key] = [x for x in (_num(v, lo, hi, f"params.{key}", problems) for v in values) if x is not None]
    keys = sorted(grid)
    combos = [dict(zip(keys, c, strict=True)) for c in itertools.product(*(grid[k] for k in keys))] if keys else [{}]
    if len(combos) > MAX_GRID:
        problems.append(f"{len(combos)} variants is over the rule grid cap of {MAX_GRID}")
    start_pct = _num(raw.get("start_pct", START_PCT), 2.0, 95.0, "start_pct", problems) or START_PCT
    if name == "cap_position" and any(v["cap_pct"] >= start_pct for v in combos if "cap_pct" in v):
        problems.append(f"cap_pct must sit under the starting {start_pct:g}%")
    try:
        horizons = sorted({int(h) for h in raw.get("horizons") or HORIZONS[name] if int(h) in ALLOWED})
    except (TypeError, ValueError):
        horizons = []
    if not horizons:
        problems.append("horizons must include 1, 3, 5 or 10")
    cover = data.coverage(PUBLIC_COVERAGE)
    if BENCH not in data.series:
        problems.append(f"{BENCH} has no bars in the lab data")
    if not cover or not _names(data):
        problems.append(NO_PUBLIC)
    elif not cover.get("enough") and int(cover.get("loading") or 0):
        problems.append(PUBLIC_LOADING.format(priced=cover["priced"], listed=cover["listed"], loading=cover["loading"]))
    if "taxable" not in str(raw.get("account") or "taxable").lower():
        problems.append("these rules are about tax and position size in a taxable account")
    if problems:
        raise RuleError(problems)
    caveats = [public_words(cover), PUBLIC_EXITS]
    if name in ("average_down", "harvest_return"):
        caveats.append(HIGH_WORDS)
    if name == "average_down":
        caveats.append("A case is the day a company first closes that far under its one-year high; it cannot count again for a year.")
    if name == "cap_position":
        caveats.append(
            f"Each case starts in January with {start_pct:g}% in one company at that day's price and the rest in the S&P 500. The capped side trims on "
            "day one and at the start of each quarter, pays tax on each trim's gain and moves the rest into the S&P 500."
        )
    if name == "harvest_return":
        caveats.append(
            "The loss is counted at your marginal rate because the stand-in purchase is under a year old. The sale money waits in the S&P 500 "
            f"for {AWAY_DAYS} days, then buys the company back, which restarts the one-year clock on the new shares."
        )
    caveats += [SAME_TAX, POOLED]
    return ListRule(rid, int(raw.get("version") or 1), name, combos, horizons, start_pct, raw, caveats)


def _names(data: LabData) -> list[str]:
    return sorted(s for s in data.series if data.roles.get(s) == PUBLIC_ROLE and data.kinds.get(s) not in FUND_KINDS)


# ---- Prices ----


def _period(day: str, width: int) -> tuple[str, int]:
    return day[:4], (int(day[5:7]) - 1) // width


def _firsts(cal: list[str], width: int, start: str) -> list[str]:
    out = []
    for i, d in enumerate(cal):
        if i:
            opens = _period(cal[i - 1], width) != _period(d, width)
        else:
            opens = (int(d[5:7]) - 1) % width == 0 and int(d[8:10]) <= 7
        if opens and d >= start:
            out.append(d)
    return out


def _grow(ctx: Ctx, sym: str, a: str, b: str) -> float | None:
    s = ctx.data.series[sym]
    i = s.index.get(a)
    if i is None or not s.open_adj[i]:
        return None
    if sym == BENCH or s.dates[-1] >= b or s.dates[-1] >= ctx.gone:
        return s.adj[s.at(b)] / s.open_adj[i]
    out = s.adj[-1] * (1 - exit_haircut(ctx.data, sym)) / s.open_adj[i]
    k = bisect_right(ctx.cal, s.dates[-1])
    m = ctx.spy.index.get(ctx.cal[k]) if k < len(ctx.cal) and ctx.cal[k] <= b else None
    return out * ctx.spy.adj[ctx.spy.at(b)] / ctx.spy.open_adj[m] if m is not None and ctx.spy.open_adj[m] else out


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _term(ctx: Ctx, bought: str, sold: str) -> float:
    return LTCG if _days(bought, sold) > LONG_DAYS else ctx.rate


# ---- Cases ----


def _drops(ctx: Ctx, sym: str, drop_pct: float) -> list[Case]:
    key = (sym, drop_pct)
    if key in ctx.drops:
        return ctx.drops[key]
    s = ctx.data.series[sym]
    out, window, last, was = [], deque(), None, False
    for i, px in enumerate(s.adj):
        while window and s.adj[window[-1]] <= px:
            window.pop()
        window.append(i)
        if window[0] <= i - YEAR:
            window.popleft()
        high = s.adj[window[0]]
        under = bool(high) and px / high - 1 <= -drop_pct / 100
        fresh, was = under and not was, under
        if not fresh or i < MIN_HISTORY or i + 1 >= len(s.dates) or px < MIN_PRICE or (last is not None and i - last < YEAR):
            continue
        last = i
        out.append(Case(sym, s.dates[i + 1], high, s.dates[window[0]]))
    ctx.drops[key] = out
    return out


def _seeds(ctx: Ctx, rule: ListRule, params: dict) -> list[Case]:
    if rule.rule == "cap_position":
        out = []
        for day in ctx.januaries:
            for sym in ctx.names:
                s = ctx.data.series[sym]
                i = s.index.get(day)
                if i is not None and s.open_adj[i] >= MIN_PRICE:
                    out.append(Case(sym, day))
        return out
    return sorted((c for sym in ctx.names for c in _drops(ctx, sym, params["drop_pct"])), key=lambda c: (c.day, c.sym))


# ---- Outcomes ----


def _average_down(ctx: Ctx, rule: ListRule, params: dict, c: Case, end: str):
    stock, index = _grow(ctx, c.sym, c.day, end), _grow(ctx, BENCH, c.day, end)
    if stock is None or index is None:
        return None
    a = stock * (1 - STOCK_BPS / 10_000) ** 2
    b = index * (1 - FUND_BPS / 10_000) ** 2
    return ((a - (a - 1) * LTCG) - (b - (b - 1) * LTCG)) * 100, None, None


def _held(ctx: Ctx, sym: str, t0: str, t1: str, start: float, cap: float | None) -> float | None:
    s, spy = ctx.data.series[sym], ctx.spy
    i0, j0 = s.index.get(t0), spy.index.get(t0)
    if i0 is None or j0 is None or not s.open_adj[i0] or not spy.open_adj[j0]:
        return None
    sb, fb = STOCK_BPS / 10_000, FUND_BPS / 10_000
    p0 = s.open_adj[i0]
    n = start * (1 - sb) / p0
    lots = [[t0, (1 - start) * (1 - fb) / spy.open_adj[j0], spy.open_adj[j0]]]
    dead = s.dates[-1] < t1 and s.dates[-1] < ctx.gone
    k = bisect_right(ctx.cal, s.dates[-1])
    left = ctx.cal[k] if dead and k < len(ctx.cal) and ctx.cal[k] <= t1 else None
    checks = ctx.quarters[bisect_left(ctx.quarters, t0) : bisect_left(ctx.quarters, t1)] if cap is not None else []
    for day in sorted({*checks, left} - {None}):
        j = spy.index.get(day)
        if n <= 0 or j is None:
            continue
        q = spy.open_adj[j]
        if day == left:
            got = n * s.adj[-1] * (1 - exit_haircut(ctx.data, sym))
            net = got - (got - n * p0) * _term(ctx, t0, day)
            lots.append([day, net * (1 - fb) / q, q])
            n = 0.0
            continue
        i = s.index.get(day)
        if i is None or (left and day > left):
            continue
        p = s.open_adj[i]
        worth = n * p
        total = worth + sum(lot[1] for lot in lots) * q
        if worth > cap * total * (1 + 1e-9):
            r = _term(ctx, t0, day)
            cost = sb + (p - p0) / p * r
            cost += fb * (1 - cost)
            sold = (worth - cap * total) / (1 - cap * cost) / p
            net = sold * p * (1 - sb) - sold * (p - p0) * r
            lots.append([day, net * (1 - fb) / q, q])
            n -= sold
    out = 0.0
    if n > 0:
        if dead and left is None:
            worth = n * s.adj[-1] * (1 - exit_haircut(ctx.data, sym))
        else:
            worth = n * s.adj[s.at(t1)] * (1 - sb)
        out += worth - (worth - n * p0) * _term(ctx, t0, t1)
    q1 = spy.adj[spy.at(t1)]
    for day, shares, px in lots:
        worth = shares * q1 * (1 - fb)
        out += worth - (worth - shares * px) * _term(ctx, day, t1)
    return out


def _cap_position(ctx: Ctx, rule: ListRule, params: dict, c: Case, end: str):
    key = (c.sym, c.day, end)
    if key not in ctx.runs:
        ctx.runs[key] = _held(ctx, c.sym, c.day, end, rule.start_pct / 100, None)
    run = ctx.runs[key]
    capped = _held(ctx, c.sym, c.day, end, rule.start_pct / 100, params["cap_pct"] / 100)
    return ((capped - run) * 100, None, None) if run is not None and capped is not None else None


def _harvest_return(ctx: Ctx, rule: ListRule, params: dict, c: Case, end: str):
    s, spy = ctx.data.series[c.sym], ctx.spy
    i, j = s.index.get(c.day), spy.index.get(c.day)
    back = ctx.cal[min(len(ctx.cal) - 1, bisect_left(ctx.cal, (date.fromisoformat(c.day) + timedelta(days=AWAY_DAYS)).isoformat()))]
    whole = _grow(ctx, c.sym, c.day, end)
    if i is None or j is None or whole is None or not c.high or back >= end or _days(c.day, back) < AWAY_DAYS:
        return None
    sb, fb = STOCK_BPS / 10_000, FUND_BPS / 10_000
    now = s.open_adj[i] / c.high
    hold = now * whole * (1 - sb)
    hold_after = hold - (hold - 1) * _term(ctx, c.high_day, end)
    sold = now * (1 - sb)
    saved = (1 - sold) * _term(ctx, c.high_day, c.day)
    k = bisect_left(s.dates, back)
    again = s.dates[k] if k < len(s.dates) and s.dates[k] < end else None
    m = spy.index.get(again) if again else None
    if again and m is None:
        return None
    away = sold * (1 - fb) * (spy.open_adj[m] if again else spy.adj[spy.at(end)]) / spy.open_adj[j] * (1 - fb)
    away_tax = (away - sold) * _term(ctx, c.day, again or end)
    if again:
        rest = _grow(ctx, c.sym, again, end)
        if rest is None:
            return None
        ended = away * (1 - sb) * rest * (1 - sb)
        after = ended - (ended - away) * _term(ctx, again, end) - away_tax + saved
    else:
        ended = away
        after = ended - away_tax + saved
    total, tracking = (after - hold_after) * 100, (ended - hold) * 100
    return total, total - tracking, tracking


OUTCOME = {"average_down": _average_down, "cap_position": _cap_position, "harvest_return": _harvest_return}


# ---- Run ----


def _summary(got: list[tuple]) -> dict:
    months: dict[str, list[tuple]] = {}
    for month, _, *vals in got:
        months.setdefault(month, []).append(vals)
    if len(months) < MIN_STARTS:
        return {"starts": 0, "too_few": len(months), "cases": len(got)}
    pooled = [[sum(v[k] for v in vals) / len(vals) if vals[0][k] is not None else None for k in range(3)] for vals in months.values()]
    cases = _quantiles([g[2] for g in got])
    out = _quantiles([p[0] for p in pooled]) | {
        "cases": cases["starts"],
        "names": len({g[1] for g in got}),
        "case_p5_pts": cases["p5_pts"],
        "case_p50_pts": cases["p50_pts"],
        "case_p95_pts": cases["p95_pts"],
        "case_share_better": cases["share_better"],
        "case_share_worse": cases["share_worse"],
    }
    if pooled[0][1] is not None:
        out |= {"tax_pts": round(sum(p[1] for p in pooled) / len(pooled), 4), "tracking_pts": round(sum(p[2] for p in pooled) / len(pooled), 4)}
    return out


def evaluate(data: LabData, rule: ListRule) -> dict:
    cal = data.calendar_for(SCREEN_KIND)
    cover = data.coverage(PUBLIC_COVERAGE) or {}
    if len(cal) < 2:
        raise RuleError([SHORT_HISTORY])
    holdout = _shift(cal[-1], -HOLDOUT_YEARS)
    start = max(str(cover.get("tests_from") or cal[0]), cal[0])
    end = (date.fromisoformat(holdout) - timedelta(days=1)).isoformat()
    if end <= start:
        raise RuleError([SHORT_HISTORY])
    rate = float(data.settings.get("marginal_rate_pct") or DEFAULT_RATE * 100) / 100
    ctx = Ctx(data, cal, data.series[BENCH], rate, gone_before(cal), _names(data), _firsts(cal, 3, start), _firsts(cal, 12, start))
    outcome = OUTCOME[rule.rule]
    variants = []
    for params in rule.variants:
        seeds = [c for c in _seeds(ctx, rule, params) if c.day >= start]
        horizons = []
        for years in rule.horizons:
            got = []
            for c in seeds:
                t1 = _shift(c.day, years)
                res = outcome(ctx, rule, params, c, t1) if t1 <= end else None
                if res is not None:
                    got.append((c.day[:7], c.sym, *res))
            horizons.append({"years": years, **_summary(got)})
        held = []
        for c in seeds:
            t1 = _shift(c.day, HOLDOUT_HORIZON)
            res = outcome(ctx, rule, params, c, t1) if c.day >= holdout and t1 <= cal[-1] else None
            if res is not None:
                held.append((c.day[:7], c.sym, *res))
        hold = _summary(held)
        v = {"params": params, "horizons": horizons, "holdout": hold, "holdout_diff_pts": _r(hold.get("mean_pts"))}
        longest = _longest(v)
        v |= {"full": {k: longest.get(k) for k in ("years", "starts", "cases", "names")}, "full_diff_pts": _r(longest.get("mean_pts")), "verdict": _verdict(v)}
        variants.append(v)
    best = max(variants, key=lambda v: _longest(v).get("p50_pts", float("-inf")))
    starts = _longest(best).get("starts")
    rough = [f"Only {starts} {UNIT[rule.rule]} fit before the two-year holdout and their windows overlap, so read this as a rough guide."]
    return {
        "rule": rule.rule,
        "across": "public_stock_list",
        "windows": {"start": start, "end": end, "holdout_start": holdout, "last": cal[-1]},
        "names": len(ctx.names),
        "start_pct": rule.start_pct if rule.rule == "cap_position" else None,
        "marginal_rate_pct": round(rate * 100, 2),
        "taxable": True,
        "baseline": {"description": BASELINE[rule.rule]},
        "variants": variants,
        "best": best["params"],
        "verdict": best["verdict"],
        "trials": len(variants),
        "caveats": rule.caveats + (rough if starts and starts < ROUGH_UNDER else []),
        PUBLIC_COVERAGE: cover,
    }


def describe() -> dict:
    return {
        "request": '{"request": "rule", "id": "cap-test", "rule": "cap_position", "params": {"cap_pct": [25, 10]}, "horizons": [3, 5]}',
        "rules": {k: list(v) for k, v in RULES.items()},
        "optional": "start_pct (cap_position only, default 30), horizons from 1, 3, 5 and 10",
        "notes": "each runs across every company on the public stock list against the S&P 500 or against doing nothing, pooled by month; "
        "average_down and harvest_return use the one-year high as the purchase price; no mix, deposits or account apply",
    }
