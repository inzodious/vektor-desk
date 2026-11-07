import math
import os
import sqlite3
from bisect import bisect_right
from datetime import date, timedelta

from desk.engine.returns import TRADING_DAYS, daily_returns

SP500 = ("SPY", "FXAIX", "VOO", "IVV")
LEVEL = 0.95
MONTH = 21
PRO_FORMA_YEARS = 5
CORR_TOP = 10
RATE_DAYS = 756
SCENARIOS = {
    "gfc_2008": ("2007-10-09", "2009-03-09"),
    "covid_2020": ("2020-02-19", "2020-03-23"),
    "rates_2022": ("2022-01-03", "2022-10-12"),
}
MARKET_SHOCK = -0.20
SATELLITE_SHOCK = -0.50
RATE_SHOCK_PTS = 2.0


# ---- Math ----


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def downside_dev(rets: list[float], mar: float = 0.0) -> float | None:
    if len(rets) < 2:
        return None
    return math.sqrt(sum(min(r - mar, 0.0) ** 2 for r in rets) / len(rets)) * math.sqrt(TRADING_DAYS)


def horizon_returns(rets: list[float], horizon: int) -> list[float]:
    if horizon <= 1:
        return list(rets)
    growth = [1.0]
    for r in rets:
        growth.append(growth[-1] * (1 + r))
    return [growth[i + horizon] / growth[i] - 1 for i in range(len(rets) - horizon + 1)]


def var_cvar(rets: list[float], horizon: int = 1, level: float = LEVEL) -> tuple[float | None, float | None]:
    sample = sorted(horizon_returns(rets, horizon))
    if len(sample) < 20:
        return None, None
    k = max(1, int(math.floor((1 - level) * len(sample))))
    var = -sample[k - 1]
    tail = sample[:k]
    return var, -mean(tail)


def cov(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(a) != len(b):
        return None
    ma, mb = mean(a), mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (len(a) - 1)


def corr(a: list[float], b: list[float]) -> float | None:
    c, sa, sb = cov(a, b), stdev(a), stdev(b)
    if c is None or not sa or not sb:
        return None
    return max(-1.0, min(1.0, c / (sa * sb)))


def beta(a: list[float], b: list[float]) -> float | None:
    c, sb = cov(a, b), stdev(b)
    if c is None or not sb:
        return None
    return c / (sb * sb)


def sharpe(rets: list[float], rf_daily: float) -> float | None:
    s = stdev(rets)
    if not s:
        return None
    return (mean(rets) - rf_daily) / s * math.sqrt(TRADING_DAYS)


def sortino(rets: list[float], rf_daily: float) -> float | None:
    dd = downside_dev(rets, rf_daily)
    if not dd:
        return None
    return (mean(rets) - rf_daily) * TRADING_DAYS / dd


def capture(a: list[float], b: list[float]) -> tuple[float | None, float | None]:
    def ratio(pick) -> float | None:
        pairs = [(x, y) for x, y in zip(a, b, strict=True) if pick(y)]
        if len(pairs) < 5:
            return None
        ga = math.prod(1 + x for x, _ in pairs) ** (1 / len(pairs)) - 1
        gb = math.prod(1 + y for _, y in pairs) ** (1 / len(pairs)) - 1
        return ga / gb * 100 if gb else None

    return ratio(lambda y: y > 0), ratio(lambda y: y < 0)


def active_share(weights: dict[str, float], targets: dict[str, float]) -> float | None:
    if not targets or not weights:
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    w = {s: v / total for s, v in weights.items()}
    names = set(w) | set(targets)
    return 0.5 * sum(abs(w.get(s, 0.0) - targets.get(s, 0.0)) for s in names) * 100


def paired(a: list[float | None], b: list[float | None]) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for x, y in zip(a, b, strict=True):
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    return xs, ys


# ---- Price helpers ----


def market_symbol(tr) -> str | None:
    return next((s for s in SP500 if tr.starts(s)), None)


def step_returns(tr, symbol: str, days: list[str]) -> list[float | None]:
    start = tr.starts(symbol)
    out: list[float | None] = [None]
    for i in range(1, len(days)):
        if not start or start > days[i - 1]:
            out.append(None)
            continue
        p0, p1 = tr.price(symbol, days[i - 1]), tr.price(symbol, days[i])
        out.append(p1 / p0 - 1 if p0 and p1 else None)
    return out


def span_return(tr, symbol: str, a: str, b: str) -> float | None:
    start = tr.starts(symbol)
    if not start or start > a:
        return None
    p0, p1 = tr.price(symbol, a), tr.price(symbol, b)
    return p1 / p0 - 1 if p0 and p1 else None


def calendar(tr, symbols: list[str], end: str, years: int) -> list[str]:
    ref = market_symbol(tr) or next((s for s in symbols if tr.starts(s)), None)
    if not ref:
        return []
    lo = (date.fromisoformat(end) - timedelta(days=365 * years)).isoformat()
    return [d for d in tr.dates[ref] if lo <= d <= end]


def pro_forma(tr, weights: dict[str, float], leverage: float, end: str, years: int = PRO_FORMA_YEARS) -> tuple[list[str], list[float], list[float | None]]:
    mkt = market_symbol(tr)
    priced = {s: w for s, w in weights.items() if w > 0 and (tr.starts(s) or mkt)}
    if not priced:
        return [], [], []
    cal = calendar(tr, list(priced), end, years)
    if not mkt:
        first = max(tr.starts(s) for s in priced)
        cal = [d for d in cal if d >= first]
    total = sum(priced.values())
    mix = {s: w / total for s, w in priced.items()}
    mrets = step_returns(tr, mkt, cal) if mkt else [None] * len(cal)
    series = {s: [r if r is not None else m for r, m in zip(step_returns(tr, s, cal), mrets, strict=True)] for s in mix}
    days, rets, market = [], [], []
    for i in range(1, len(cal)):
        parts = [series[s][i] for s in mix]
        if any(p is None for p in parts):
            continue
        days.append(cal[i])
        rets.append(leverage * sum(mix[s] * p for s, p in zip(mix, parts, strict=True)))
        market.append(mrets[i])
    return days, rets, market


def macro_lookup(desk: sqlite3.Connection, series: str) -> tuple[list[str], list[float]]:
    if not desk.execute("SELECT 1 FROM sqlite_master WHERE name='macro_daily'").fetchone():
        return [], []
    rows = desk.execute("SELECT date, value FROM macro_daily WHERE series=? ORDER BY date", (series,)).fetchall()
    return [r["date"] for r in rows], [r["value"] for r in rows]


def as_of_value(dates: list[str], values: list[float], day: str) -> float | None:
    i = bisect_right(dates, day)
    return values[i - 1] if i else None


def risk_free_daily(desk: sqlite3.Connection, days: list[str]) -> tuple[float, str]:
    dates, values = macro_lookup(desk, "DGS3MO")
    picks = [v for v in (as_of_value(dates, values, d) for d in days) if v is not None] if dates else []
    if picks:
        return mean(picks) / 100 / TRADING_DAYS, "ok"
    try:
        pct = float(os.environ.get("DESK_RISK_FREE_PCT", ""))
        return pct / 100 / TRADING_DAYS, "modelled"
    except ValueError:
        return 0.0, "modelled"


# ---- Metrics ----


def metrics(out, desk: sqlite3.Connection, tr, *, days, values, flows_on, rows, total, kinds, targets, q):
    by_symbol: dict[str, float] = {}
    for h in rows:
        if not h["is_cash"] and h["value"] > 0:
            by_symbol[h["symbol"]] = by_symbol.get(h["symbol"], 0.0) + h["value"]
    invested = sum(by_symbol.values())
    if not invested or total <= 0:
        return
    as_of = days[-1]
    weights = {s: v / invested for s, v in by_symbol.items()}
    mkt = market_symbol(tr)
    actual = daily_returns(values, flows_on)
    mkt_actual = step_returns(tr, mkt, days) if mkt else [None] * len(days)
    act_p = [r for r in actual[1:] if r is not None]
    act_pm, act_m = paired(actual, mkt_actual)
    _, pf, pf_m = pro_forma(tr, weights, invested / total, as_of)
    pf_pm, pf_mm = paired(pf, pf_m)

    def basis(n: int, with_market: bool = False):
        if with_market:
            if len(act_pm) >= n:
                return act_pm, act_m, q, len(act_pm)
            if len(pf_pm) >= n:
                return pf_pm, pf_mm, "pro_forma", len(pf_pm)
            return None
        if len(act_p) >= n:
            return act_p, None, q, len(act_p)
        if len(pf) >= n:
            return pf, None, "pro_forma", len(pf)
        return None

    for window, n in (("63D", 63), ("252D", 252)):
        b = basis(n)
        value = downside_dev(b[0][-n:]) if b else None
        out.m("risk.downside_dev", value * 100 if value is not None else None, "pct", window=window, n_obs=n if b else len(act_p), quality=b[2] if b else "ok")

    b = basis(250)
    for window, horizon in (("1D", 1), ("1M", MONTH)):
        var, cvar = var_cvar(b[0][-TRADING_DAYS * PRO_FORMA_YEARS :], horizon) if b else (None, None)
        quality = b[2] if b else "ok"
        n_obs = len(b[0][-TRADING_DAYS * PRO_FORMA_YEARS :]) if b else len(act_p)
        out.m("risk.var95", var * 100 if var is not None else None, "pct", window=window, n_obs=n_obs, quality=quality)
        out.m("risk.cvar95", cvar * 100 if cvar is not None else None, "pct", window=window, n_obs=n_obs, quality=quality)

    b = basis(252, with_market=True)
    out.m("risk.beta", beta(b[0][-252:], b[1][-252:]) if b else None, "ratio", window="252D", n_obs=252 if b else len(act_pm), quality=b[2] if b else "ok")

    span = (date.fromisoformat(as_of) - date.fromisoformat(days[0])).days
    for window, n in (("1Y", TRADING_DAYS), ("ITD", len(act_p))):
        if span < 365 or len(act_p) < TRADING_DAYS:
            out.m("risk.sharpe", None, "ratio", window=window, n_obs=len(act_p))
            out.m("risk.sortino", None, "ratio", window=window, n_obs=len(act_p))
            continue
        sample = act_p[-n:]
        rf, rf_q = risk_free_daily(desk, days[-n:])
        quality = q if rf_q == "ok" else rf_q
        out.m("risk.sharpe", sharpe(sample, rf), "ratio", window=window, n_obs=len(sample), quality=quality)
        out.m("risk.sortino", sortino(sample, rf), "ratio", window=window, n_obs=len(sample), quality=quality)

    if len(act_pm) >= 63:
        up, down = capture(act_pm, act_m)
        out.m("bm.capture", up, "pct", scope="benchmark", scope_id="up", window="ITD", n_obs=len(act_pm), quality=q)
        out.m("bm.capture", down, "pct", scope="benchmark", scope_id="down", window="ITD", n_obs=len(act_pm), quality=q)
    out.m("bm.active_share", active_share(by_symbol, targets), "pct", quality=q)

    betas = _holding_metrics(out, tr, mkt, as_of, weights)
    _scenarios(out, desk, tr, mkt, as_of, by_symbol, total, kinds, targets, betas)


def _holding_metrics(out, tr, mkt, as_of, weights) -> dict[str, float]:
    if not mkt:
        return {}
    cal = calendar(tr, [mkt], as_of, 2)[-253:]
    mrets = step_returns(tr, mkt, cal)
    hrets = {s: step_returns(tr, s, cal) for s in weights}
    betas = {}
    for s in sorted(weights):
        a, m = paired(hrets[s], mrets)
        if len(a) < 252:
            out.m("risk.beta", None, "ratio", scope="holding", scope_id=s, window="252D", n_obs=len(a))
            continue
        betas[s] = beta(a, m)
        long_c, short_c = corr(a, m), corr(a[-63:], m[-63:])
        out.m("risk.beta", betas[s], "ratio", scope="holding", scope_id=s, window="252D", n_obs=len(a))
        out.m("risk.corr", long_c, "ratio", scope="holding", scope_id=s, window="252D", n_obs=len(a))
        out.m("risk.corr", short_c, "ratio", scope="holding", scope_id=s, window="63D", n_obs=63)
        if long_c is not None and short_c is not None:
            out.m("risk.corr_shift", short_c - long_c, "ratio", scope="holding", scope_id=s, window="63D", n_obs=len(a))
    top = sorted(weights, key=lambda s: -weights[s])[:CORR_TOP]
    for i, x in enumerate(sorted(top)):
        for y in sorted(top)[i + 1 :]:
            a, b = paired(hrets[x], hrets[y])
            if len(a) >= 252:
                out.m("risk.corr", corr(a, b), "ratio", scope="pair", scope_id=f"{x}|{y}", window="252D", n_obs=len(a))
    return betas


def _scenarios(out, desk, tr, mkt, as_of, by_symbol, total, kinds, targets, betas):
    def emit(name: str, usd: float | None, quality: str):
        out.m("risk.scenario", usd, "usd", scope="scenario", scope_id=name, quality=quality)
        out.m("risk.scenario_pct", usd / total * 100 if usd is not None else None, "pct", scope="scenario", scope_id=name, quality=quality)

    for name, (a, b) in SCENARIOS.items():
        m = span_return(tr, mkt, a, b) if mkt else None
        usd, quality = 0.0, "ok"
        for s, v in by_symbol.items():
            r = span_return(tr, s, a, b)
            if r is None:
                if m is None:
                    usd = None
                    break
                r, quality = m * betas.get(s, 1.0), "pro_forma"
            usd += v * r
        emit(name, usd, quality)
    emit("market_-20", sum(v * betas.get(s, 1.0) * MARKET_SHOCK for s, v in by_symbol.items()), "modelled")
    singles = sum(v for s, v in by_symbol.items() if kinds.get(s) == "stock" and s not in targets)
    emit("satellite_-50", singles * SATELLITE_SHOCK, "ok")
    emit("rates_+2", _rate_shock(desk, tr, mkt, as_of, by_symbol), "modelled")


def _rate_shock(desk, tr, mkt, as_of, by_symbol) -> float | None:
    dates, values = macro_lookup(desk, "DGS10")
    if not dates or not mkt:
        return None
    cal = calendar(tr, [mkt], as_of, 4)[-(RATE_DAYS + 1) :]
    levels = [as_of_value(dates, values, d) for d in cal]
    moves: list[float | None] = [None] + [b - a if a is not None and b is not None else None for a, b in zip(levels, levels[1:], strict=False)]
    usd, found = 0.0, False
    for s, v in by_symbol.items():
        r, x = paired(step_returns(tr, s, cal), moves)
        sens = beta(r, x) if len(r) >= 126 else None
        if sens is not None:
            usd += v * sens * RATE_SHOCK_PTS
            found = True
    return usd if found else None
