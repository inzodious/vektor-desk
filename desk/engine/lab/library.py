import math
import re

from desk.engine.lab.data import Series

SKIP = 21
FEATURES = {
    "ret": "Total return over the window (dividends reinvested)",
    "ret_skip": "Total return over the window, skipping the most recent month (12-1 momentum)",
    "vol": "Annualized volatility of daily returns over the window",
    "ma_gap": "Distance of the close from its moving average over the window",
    "range_52w": "Position between the window's low (0) and high (1); 252 days is the 52-week range",
    "dd": "Drawdown from the window's high",
}
TRANSFORMS = {
    "raw": "The value itself",
    "rank": "Cross-sectional percentile, higher value ranks higher",
    "inverse_rank": "Cross-sectional percentile, lower value ranks higher (low volatility, deep drawdown)",
    "zscore": "Cross-sectional z-score",
    "inverse": "The value times -1",
}
WINDOWS = ("21d", "63d", "126d", "252d", "1m", "3m", "6m", "12m", "1y")


def window_days(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([dmy])\s*", str(text).lower())
    if not m:
        raise ValueError(f"window {text!r} must look like 63d, 6m or 1y")
    n, unit = int(m.group(1)), m.group(2)
    days = n * {"d": 1, "m": 21, "y": 252}[unit]
    if not 5 <= days <= 1260:
        raise ValueError(f"window {text!r} must be between 5 trading days and 5 years")
    return days


def catalog() -> list[dict]:
    return [
        {"metric_id": k, "description": v, "window_options": list(WINDOWS), "transforms": list(TRANSFORMS), "point_in_time": True, "kind": "price"}
        for k, v in FEATURES.items()
    ]


def lookback(metric_id: str, days: int) -> int:
    return days + SKIP if metric_id == "ret_skip" else days


def value(metric_id: str, s: Series, i: int, days: int) -> float | None:
    need = lookback(metric_id, days)
    if i < need:
        return None
    a = s.adj
    if metric_id == "ret":
        return a[i] / a[i - days] - 1 if a[i - days] else None
    if metric_id == "ret_skip":
        return a[i - SKIP] / a[i - days - SKIP] - 1 if a[i - days - SKIP] else None
    window = a[i - days + 1 : i + 1]
    if metric_id == "vol":
        rets = [y / x - 1 for x, y in zip(a[i - days : i], a[i - days + 1 : i + 1], strict=True) if x]
        if len(rets) < 2:
            return None
        m = sum(rets) / len(rets)
        return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1) * 252)
    if metric_id == "ma_gap":
        avg = sum(window) / len(window)
        return a[i] / avg - 1 if avg else None
    if metric_id == "range_52w":
        lo, hi = min(window), max(window)
        return (a[i] - lo) / (hi - lo) if hi > lo else 0.5
    if metric_id == "dd":
        hi = max(window)
        return a[i] / hi - 1 if hi else None
    raise ValueError(f"unknown feature {metric_id}")


def transform(name: str, values: dict[str, float]) -> dict[str, float]:
    if name == "raw":
        return dict(values)
    if name == "inverse":
        return {k: -v for k, v in values.items()}
    if name in ("rank", "inverse_rank"):
        sign = 1 if name == "rank" else -1
        ordered = sorted(values, key=lambda k: (sign * values[k], k))
        n = len(ordered)
        return {k: (i + 1) / n for i, k in enumerate(ordered)}
    if name == "zscore":
        if len(values) < 2:
            return {k: 0.0 for k in values}
        m = sum(values.values()) / len(values)
        sd = math.sqrt(sum((v - m) ** 2 for v in values.values()) / (len(values) - 1))
        return {k: (v - m) / sd if sd else 0.0 for k, v in values.items()}
    raise ValueError(f"unknown transform {name}")
