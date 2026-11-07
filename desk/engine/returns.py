import math
from datetime import date, timedelta

TRADING_DAYS = 252


# ---- Windows ----


def window_start(window: str, end: date, first: date) -> date | None:
    if window == "1D":
        return None
    if window == "1W":
        return end - timedelta(days=7)
    if window == "MTD":
        return end.replace(day=1) - timedelta(days=1)
    if window == "QTD":
        q = (end.month - 1) // 3 * 3 + 1
        return end.replace(month=q, day=1) - timedelta(days=1)
    if window == "YTD":
        return end.replace(month=1, day=1) - timedelta(days=1)
    if window == "1Y":
        return _years_back(end, 1)
    if window == "3Y":
        return _years_back(end, 3)
    if window == "ITD":
        return first
    raise ValueError(window)


def _years_back(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:
        return d.replace(year=d.year - n, day=28)


WINDOWS = ("1D", "1W", "MTD", "QTD", "YTD", "1Y", "3Y", "ITD")


def base_index(dates: list[str], window: str) -> int | None:
    if len(dates) < 2:
        return None
    end = date.fromisoformat(dates[-1])
    first = date.fromisoformat(dates[0])
    if window == "1D":
        return len(dates) - 2
    start = window_start(window, end, first)
    if start < first:
        return None
    iso = start.isoformat()
    idx = max((i for i, d in enumerate(dates) if d <= iso), default=None)
    return idx if idx is not None and idx < len(dates) - 1 else None


# ---- Time-weighted return ----


def daily_returns(values: list[float], flows: list[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for i in range(1, len(values)):
        prev = values[i - 1]
        out.append((values[i] - flows[i]) / prev - 1 if prev > 0 else None)
    return out


def twr_index(values: list[float], flows: list[float]) -> list[float]:
    idx = [1.0]
    for r in daily_returns(values, flows)[1:]:
        idx.append(idx[-1] * (1 + r) if r is not None else idx[-1])
    return idx


def annualize(total: float, days: int) -> float | None:
    if days < 365 or total <= -1:
        return None
    return (1 + total) ** (365.0 / days) - 1


# ---- Money-weighted return ----


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if len(cashflows) < 2 or not any(a < 0 for _, a in cashflows) or not any(a > 0 for _, a in cashflows):
        return None
    t0 = min(d for d, _ in cashflows)

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in cashflows)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def period_mwr(dates: list[str], values: list[float], flows: list[float], i0: int) -> float | None:
    cf = [(date.fromisoformat(dates[i0]), -values[i0])]
    cf += [(date.fromisoformat(dates[i]), -flows[i]) for i in range(i0 + 1, len(dates)) if flows[i]]
    cf.append((date.fromisoformat(dates[-1]), values[-1]))
    days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[i0])).days
    rate = xirr(cf)
    if rate is None:
        return None
    return rate if days >= 365 else (1 + rate) ** (days / 365.0) - 1


# ---- Risk on an index ----


def drawdowns(index: list[float]) -> tuple[float, float, int]:
    peak, worst, current, longest, run = -math.inf, 0.0, 0.0, 0, 0
    for v in index:
        if v >= peak:
            peak, run = v, 0
        else:
            run += 1
        dd = v / peak - 1 if peak > 0 else 0.0
        worst = min(worst, dd)
        current = dd
        longest = max(longest, run)
    return worst, current, longest


def volatility(rets: list[float]) -> float | None:
    clean = [r for r in rets if r is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    var = sum((r - mean) ** 2 for r in clean) / (len(clean) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)
