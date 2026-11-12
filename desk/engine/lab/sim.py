from dataclasses import dataclass, field
from datetime import date

from desk.engine.lab import library as features
from desk.engine.lab.data import FRENCH_KIND, FUND_KINDS, SMALL_CAPS, LabData
from desk.engine.lab.spec import Spec, Variant, french_members

START_CASH = 10_000.0
FUND_BPS = 5.0
STOCK_BPS = 15.0
THIN_BPS = 25.0
THIN_DOLLARS = 20_000_000.0
DELIST_HAIRCUT = 0.30
LTCG = 0.15
DEFAULT_RATE = 0.24
VOL_WINDOW = 63
SP500 = ("SPY", "FXAIX", "VOO", "IVV")


@dataclass
class Result:
    days: list[str]
    values: list[float]
    bench: list[float | None]
    sp500: list[float | None]
    trades: list[tuple] = field(default_factory=list)
    turnover: float = 0.0
    costs: float = 0.0
    taxes: float = 0.0
    rebalances: int = 0
    delisted: list[str] = field(default_factory=list)
    holdings: dict[str, float] = field(default_factory=dict)
    cash: float = 0.0


# ---- Helpers ----


def _period(day: str, code: str) -> tuple:
    d = date.fromisoformat(day)
    if code == "W":
        return d.isocalendar()[:2]
    if code == "Q":
        return d.year, (d.month - 1) // 3
    return d.year, d.month


def signal_days(cal: list[str], code: str) -> set[str]:
    return {a for a, b in zip(cal, cal[1:], strict=False) if _period(a, code) != _period(b, code)}


def universe(data: LabData, spec: Spec, day: str) -> list[str]:
    u = spec.universe
    if u["kind"] == "fund_list":
        return [s for s in u["symbols"] if s in data.series]
    if u["kind"] == FRENCH_KIND:
        return french_members(data.french(u["set"]), u.get("members") or [])
    if u["kind"] == SMALL_CAPS:
        month = day[:7]
        out = []
        for sym, months in data.smallcap.items():
            s = data.series.get(sym)
            i = s.index.get(day) if s else None
            if month in months and i is not None and s.adj[i] >= u["min_price"]:
                out.append(sym)
        return sorted(out)
    out = []
    for sym, s in data.series.items():
        if data.kinds.get(sym) in FUND_KINDS or sym in data.plan_mix:
            continue
        if data.roles.get(sym) not in ("universe", "held", "watch"):
            continue
        i = s.index.get(day)
        if i is not None and i >= u["min_history_days"] and s.adj[i] >= u["min_price"]:
            out.append(sym)
    return out


def _bps(data: LabData, sym: str, i: int) -> float:
    if data.kinds.get(sym) in (*FUND_KINDS, FRENCH_KIND) or sym in data.plan_mix:
        return FUND_BPS
    s = data.series[sym]
    vols = [v * p for v, p in zip(s.volume[max(0, i - 20) : i + 1], s.adj[max(0, i - 20) : i + 1], strict=True) if v]
    if vols and sum(vols) / len(vols) < THIN_DOLLARS:
        return THIN_BPS
    return STOCK_BPS


def _price(data: LabData, sym: str, day: str, field_: str = "adj") -> float | None:
    s = data.series.get(sym)
    if not s:
        return None
    i = s.index.get(day)
    if i is None:
        i = s.at(day)
        if i is None:
            return None
        return s.adj[i]
    return s.open_adj[i] if field_ == "open" else s.adj[i]


def _events(data: LabData, metric: str, sym: str):
    if metric in features.EARNINGS_FEATURES:
        return data.earnings.get(sym)
    return data.insider.get(sym)


def _passes(data: LabData, spec: Spec, sym: str, s, i: int) -> bool:
    for metric, days, lo, hi in spec.filters:
        x = features.value(metric, s, i, days, _events(data, metric, sym))
        if x is None or (lo is not None and x < lo) or (hi is not None and x > hi):
            return False
    return True


def pick(data: LabData, spec: Spec, v: Variant, day: str, held: set[str]) -> dict[str, float]:
    raw: dict[str, list[float]] = {}
    for sym in universe(data, spec, day):
        s = data.series[sym]
        i = s.index.get(day)
        if i is None:
            continue
        vals = [features.value(m, s, i, w, _events(data, m, sym)) for (m, _, _), w in zip(spec.signals, v.windows, strict=True)]
        if any(x is None for x in vals) or not _passes(data, spec, sym, s, i):
            continue
        raw[sym] = vals
    if not raw:
        return {}
    score = {sym: 0.0 for sym in raw}
    for j, (_, _, t) in enumerate(spec.signals):
        for sym, x in features.transform(t, {sym: vals[j] for sym, vals in raw.items()}).items():
            score[sym] += x / len(spec.signals)
    ranked = sorted(score, key=lambda k: (-score[k], k))
    eligible = [s for s in ranked if v.min_signal is None or not raw[s] or raw[s][0] > v.min_signal]
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    keep = [s for s in ranked if s in held and s in eligible and v.hold_rank and rank[s] <= v.hold_rank][: v.top_n]
    chosen = keep + [s for s in eligible if s not in keep][: v.top_n - len(keep)]
    if not chosen:
        return {}
    if spec.weights is not None:
        cap = spec.constraints["max_position_pct"] / 100
        return {s: min(spec.weights[s], cap) for s in chosen if spec.weights.get(s)}
    if spec.sizing == "inverse_vol":
        inv = {}
        for s in chosen:
            ser = data.series[s]
            vol = features.value("vol", ser, ser.index[day], VOL_WINDOW)
            inv[s] = 1 / vol if vol else 0.0
        total = sum(inv.values()) or 1.0
        w = {s: x / total for s, x in inv.items()}
    elif spec.sizing == "rank":
        pts = {s: len(chosen) - i for i, s in enumerate(chosen)}
        total = sum(pts.values())
        w = {s: x / total for s, x in pts.items()}
    else:
        w = {s: 1 / len(chosen) for s in chosen}
    fill = len(chosen) / v.top_n
    cap = spec.constraints["max_position_pct"] / 100
    return {s: min(x * fill, cap) for s, x in w.items() if x > 0}


def _benchmark(data: LabData, spec: Spec) -> dict[str, float]:
    if spec.benchmark and spec.benchmark in data.series:
        return {spec.benchmark: 1.0}
    mix = {s: w for s, w in data.plan_mix.items() if s in data.series}
    if mix:
        total = sum(mix.values())
        return {s: w / total for s, w in mix.items()}
    sp = next((s for s in SP500 if s in data.series), None)
    return {sp: 1.0} if sp else {}


def _index(data: LabData, weights: dict[str, float], cal: list[str]) -> list[float | None]:
    if not weights:
        return [None] * len(cal)
    out: list[float | None] = []
    level, units, month = None, {}, None
    for day in cal:
        prices = {s: _price(data, s, day) for s in weights}
        if any(p is None for p in prices.values()) or any(data.series[s].dates[0] > day for s in weights):
            out.append(None)
            continue
        if level is None or _period(day, "M") != month:
            level = sum(units[s] * prices[s] for s in units) if units else 1.0
            units = {s: level * w / prices[s] for s, w in weights.items()}
            month = _period(day, "M")
        level = sum(units[s] * prices[s] for s in units)
        out.append(level)
    first = next((x for x in out if x), None)
    return [x / first if x is not None and first else None for x in out]


# ---- Run ----


def simulate(
    data: LabData, spec: Spec, v: Variant, start: str, end: str, *, cost_mult: float = 1.0, rate: float | None = None, delist_haircut: float = DELIST_HAIRCUT
) -> Result:
    kind = spec.universe.get("kind")
    last_day = data.end_for(kind)
    cal = [d for d in data.calendar_for(kind) if start <= d <= end]
    if len(cal) < 2:
        return Result(cal, [START_CASH] * len(cal), [None] * len(cal), [None] * len(cal))
    rate = rate if rate is not None else float(data.settings.get("marginal_rate_pct") or DEFAULT_RATE * 100) / 100
    signals = signal_days(cal, spec.rebalance)
    cash, shares = START_CASH, {}
    lots: dict[str, list[list]] = {}
    realized = {"st": 0.0, "lt": 0.0}
    carry = 0.0
    out = Result(cal, [], [], [])
    pending: dict[str, float] | None = None
    traded = 0.0
    for k, day in enumerate(cal):
        for sym in list(shares):
            s = data.series[sym]
            if s.dates[-1] < day and s.dates[-1] < last_day:
                px = s.adj[-1] * (1 - delist_haircut)
                cash += _sell(lots, sym, shares.pop(sym), px, day, realized)
                out.delisted.append(sym)
        if pending is not None:
            value = cash + sum(n * (_price(data, s, day, "open") or 0.0) for s, n in shares.items())
            orders = []
            for sym in set(shares) | set(pending):
                px = _price(data, sym, day, "open")
                if not px:
                    continue
                want = pending.get(sym, 0.0) * value / px
                delta = want - shares.get(sym, 0.0)
                if abs(delta * px) >= 1.0:
                    orders.append((delta, sym, px))
            for delta, sym, px in sorted(orders):
                gross = abs(delta) * px
                fee = gross * _bps(data, sym, data.series[sym].at(day)) / 10_000 * cost_mult
                if delta < 0:
                    cash += _sell(lots, sym, -delta, px, day, realized) - fee
                    left = shares.get(sym, 0.0) + delta
                    if left > 1e-9:
                        shares[sym] = left
                    else:
                        shares.pop(sym, None)
                else:
                    cash -= gross + fee
                    shares[sym] = shares.get(sym, 0.0) + delta
                    lots.setdefault(sym, []).append([day, delta, px])
                out.costs += fee
                traded += gross
                out.trades.append((day, sym, "buy" if delta > 0 else "sell", round(abs(delta), 6), round(px, 4), round(fee, 4)))
            out.turnover += traded / value if value > 0 else 0.0
            traded = 0.0
            pending = None
            out.rebalances += 1
        if kind == FRENCH_KIND:
            rf = data.factors.get("rf", {}).get(day)
            if cash > 0 and rf and k:
                cash *= 1 + rf / 100
        else:
            rf = data.macro_at("DGS3MO", day)
            if cash > 0 and rf and k:
                cash *= 1 + rf / 100 / 252
        value = cash + sum(n * (_price(data, s, day) or 0.0) for s, n in shares.items())
        last_of_year = k == len(cal) - 1 or cal[k + 1][:4] != day[:4]
        if spec.taxable and last_of_year and k < len(cal) - 1:
            tax, carry = _year_tax(realized, carry, rate)
            cash -= tax
            value -= tax
            out.taxes += tax
            realized = {"st": 0.0, "lt": 0.0}
        out.values.append(value)
        if day in signals and k < len(cal) - 1:
            pending = pick(data, spec, v, day, set(shares))
    bench = _benchmark(data, spec)
    out.bench = _index(data, bench, cal)
    sp = next((s for s in SP500 if s in data.series), None)
    out.sp500 = _index(data, {sp: 1.0}, cal) if sp else [None] * len(cal)
    out.holdings = {s: round(n, 6) for s, n in shares.items()}
    out.cash = cash
    return out


def _sell(lots: dict, sym: str, qty: float, px: float, day: str, realized: dict) -> float:
    left = qty
    queue = lots.get(sym, [])
    while left > 1e-12 and queue:
        lot = queue[0]
        take = min(left, lot[1])
        gain = take * (px - lot[2])
        long = (date.fromisoformat(day) - date.fromisoformat(lot[0])).days > 365
        realized["lt" if long else "st"] += gain
        lot[1] -= take
        left -= take
        if lot[1] <= 1e-12:
            queue.pop(0)
    return qty * px


def _year_tax(realized: dict, carry: float, rate: float) -> tuple[float, float]:
    st, lt = realized["st"], realized["lt"]
    loss = min(st, 0.0) + min(lt, 0.0) + carry
    st_pos, lt_pos = max(st, 0.0), max(lt, 0.0)
    use = min(-loss, st_pos)
    st_pos -= use
    loss += use
    use = min(-loss, lt_pos)
    lt_pos -= use
    loss += use
    return st_pos * rate + lt_pos * LTCG, loss
