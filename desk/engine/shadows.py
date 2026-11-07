from bisect import bisect_right


class TotalReturn:
    def __init__(self, series: dict[str, dict[str, tuple[float, float | None]]]):
        self.series = {s: {d: (adj if adj else c) for d, (c, adj) in ds.items()} for s, ds in series.items()}
        self.dates = {s: sorted(ds) for s, ds in self.series.items()}

    def price(self, symbol: str, day: str) -> float | None:
        dates = self.dates.get(symbol)
        if not dates:
            return None
        i = bisect_right(dates, day)
        return self.series[symbol][dates[i - 1]] if i else None

    def starts(self, symbol: str) -> str | None:
        dates = self.dates.get(symbol)
        return dates[0] if dates else None


def shadow(dates: list[str], start_value: float, flows: list[float], weights: dict[str, float], tr: TotalReturn) -> tuple[list[float | None], str, dict]:
    priced = {s: w for s, w in weights.items() if w > 0 and tr.starts(s) and tr.starts(s) <= dates[0]}
    if not priced:
        return [None] * len(dates), "insufficient_history", {}
    total = sum(priced.values())
    mix = {s: w / total for s, w in priced.items()}
    quality = "ok" if len(priced) == len([w for w in weights.values() if w > 0]) else "pro_forma"
    units = {s: 0.0 for s in mix}
    out: list[float | None] = []
    for i, day in enumerate(dates):
        cash = start_value if i == 0 else flows[i]
        if cash:
            held = {s: units[s] * tr.price(s, day) for s in mix}
            value = sum(held.values())
            if cash > 0 and value > 0:
                split = deposit_split(mix, {s: v / value * 100 for s, v in held.items()}, value, cash)
                for s, usd in split.items():
                    units[s] += usd / tr.price(s, day)
            elif cash > 0 or value <= 0:
                for s, w in mix.items():
                    units[s] += cash * w / tr.price(s, day)
            else:
                scale = max(0.0, 1 + cash / value)
                for s in mix:
                    units[s] *= scale
        out.append(round(sum(units[s] * tr.price(s, day) for s in mix), 2))
    return out, quality, mix


def deposit_split(targets: dict[str, float], weights: dict[str, float], total: float, amount: float) -> dict[str, float]:
    if amount <= 0 or not targets:
        return {}
    new_total = total + amount
    gaps = {s: max(0.0, t * new_total - weights.get(s, 0.0) / 100 * total) for s, t in targets.items()}
    need = sum(gaps.values())
    if need <= 0:
        return {s: round(amount * t, 2) for s, t in targets.items()}
    if need >= amount:
        return {s: round(amount * g / need, 2) for s, g in gaps.items() if g > 0}
    left = amount - need
    return {s: round(gaps[s] + left * t, 2) for s, t in targets.items()}
