import itertools
import math
from datetime import date
from statistics import NormalDist

EULER = 0.5772156649015329
PBO_BLOCKS = 10
N = NormalDist()


# ---- Basics ----


def rets(values: list[float | None]) -> list[float | None]:
    out: list[float | None] = []
    for a, b in zip(values, values[1:], strict=False):
        out.append(b / a - 1 if a and b is not None else None)
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sharpe_daily(r: list[float]) -> float | None:
    sd = _sd(r)
    return _mean(r) / sd if sd else None


def moments(r: list[float]) -> tuple[float, float]:
    sd = _sd(r)
    if not sd or len(r) < 3:
        return 0.0, 3.0
    m = _mean(r)
    skew = sum(((x - m) / sd) ** 3 for x in r) / len(r)
    kurt = sum(((x - m) / sd) ** 4 for x in r) / len(r)
    return skew, kurt


def cagr(values: list[float], days: list[str]) -> float | None:
    span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days
    if span <= 0 or not values[0] or values[-1] <= 0:
        return None
    total = values[-1] / values[0]
    return total ** (365.25 / span) - 1 if span >= 365 else total - 1


def drawdown(values: list[float]) -> float:
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1)
    return worst


def summary(result, *, years: float | None = None) -> dict:
    days, vals = result.days, result.values
    if len(days) < 2:
        return {"days": len(days), "return_pct": None}
    r = [x for x in rets(vals) if x is not None]
    sd = _sd(r)
    down = math.sqrt(sum(min(x, 0) ** 2 for x in r) / len(r)) if r else 0.0
    span = years or max((date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days / 365.25, 1 / 365.25)
    out = {
        "start": days[0],
        "end": days[-1],
        "days": len(days),
        "return_pct": _pct(vals[-1] / vals[0] - 1),
        "ann_return_pct": _pct(cagr(vals, days)) if span >= 1 else None,
        "vol_pct": _pct(sd * math.sqrt(252)),
        "sharpe": _r(_mean(r) / sd * math.sqrt(252)) if sd else None,
        "sortino": _r(_mean(r) * 252 / (down * math.sqrt(252))) if down else None,
        "mdd_pct": _pct(drawdown(vals)),
        "turnover_per_year": _r(result.turnover / span),
        "trades": len(result.trades),
        "costs_usd": round(result.costs, 2),
        "taxes_usd": round(result.taxes, 2),
        "delisted": sorted(set(result.delisted)),
    }
    for name, series in (("bench", result.bench), ("sp500", result.sp500)):
        pairs = [(v, b) for v, b in zip(vals, series, strict=True) if b is not None]
        if len(pairs) >= 2:
            sub_days = [d for d, b in zip(days, series, strict=True) if b is not None]
            b_vals = [b for _, b in pairs]
            s_vals = [v for v, _ in pairs]
            s_c, b_c = cagr(s_vals, sub_days), cagr(b_vals, sub_days)
            out[f"{name}_return_pct"] = _pct(b_vals[-1] / b_vals[0] - 1)
            out[f"excess_vs_{name}_pts"] = _pct(s_c - b_c) if s_c is not None and b_c is not None else None
    return out


def _pct(x):
    return round(x * 100, 4) if x is not None else None


def _r(x):
    return round(x, 4) if x is not None else None


# ---- Start-date distribution ----


def start_months(days: list[str], vals: list[float], bench: list[float | None], years: int) -> dict:
    idx = {d: i for i, d in enumerate(days)}
    firsts, seen = [], set()
    for d in days:
        if d[:7] not in seen:
            seen.add(d[:7])
            firsts.append(d)
    excess = []
    for d in firsts:
        y, m = int(d[:4]), int(d[5:7])
        target = f"{y + years:04d}-{m:02d}-01"
        j = next((idx[x] for x in days[idx[d] :] if x >= target), None)
        if j is None:
            break
        i = idx[d]
        if bench[i] is None or bench[j] is None or not vals[i]:
            continue
        s = (vals[j] / vals[i]) ** (1 / years) - 1
        b = (bench[j] / bench[i]) ** (1 / years) - 1
        excess.append((s - b) * 100)
    if not excess:
        return {"years": years, "starts": 0}
    ordered = sorted(excess)

    def q(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1)))]

    return {
        "years": years,
        "starts": len(excess),
        "mean_pts": round(_mean(excess), 4),
        "p5_pts": round(q(0.05), 4),
        "p95_pts": round(q(0.95), 4),
        "share_positive": round(sum(1 for x in excess if x > 0) / len(excess), 4),
    }


# ---- Overfitting ----


def expected_max_sharpe(var_sr: float, trials: int) -> float:
    if trials < 2 or var_sr <= 0:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER) * N.inv_cdf(1 - 1 / trials) + EULER * N.inv_cdf(1 - 1 / (trials * math.e)))


def deflated_sharpe(sr: float, trials: int, var_sr: float, n_obs: int, skew: float, kurt: float) -> float | None:
    if n_obs < 30:
        return None
    sr0 = expected_max_sharpe(var_sr, trials)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if denom <= 0:
        return None
    return N.cdf((sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def pbo(matrix: list[list[float]], blocks: int = PBO_BLOCKS) -> float | None:
    if len(matrix) < 2:
        return None
    t = min(len(r) for r in matrix)
    if t < blocks * 10:
        return None
    size = t // blocks
    stats = []
    for row in matrix:
        cells = []
        for b in range(blocks):
            chunk = row[b * size : (b + 1) * size]
            cells.append((sum(chunk), sum(x * x for x in chunk), len(chunk)))
        stats.append(cells)

    def sr(cells):
        n = sum(c[2] for c in cells)
        s = sum(c[0] for c in cells)
        ss = sum(c[1] for c in cells)
        m = s / n
        var = (ss - n * m * m) / (n - 1) if n > 1 else 0.0
        return m / math.sqrt(var) if var > 0 else 0.0

    below = total = 0
    for train in itertools.combinations(range(blocks), blocks // 2):
        test = [b for b in range(blocks) if b not in train]
        is_sr = [sr([cells[b] for b in train]) for cells in stats]
        best = max(range(len(stats)), key=lambda i: is_sr[i])
        oos = [sr([cells[b] for b in test]) for cells in stats]
        rank = sum(1 for x in oos if x < oos[best]) + 0.5 * (sum(1 for x in oos if x == oos[best]) - 1)
        omega = (rank + 1) / (len(stats) + 1)
        total += 1
        if math.log(omega / (1 - omega)) <= 0:
            below += 1
    return below / total if total else None
