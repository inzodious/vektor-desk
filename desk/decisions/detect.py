import statistics
from collections import Counter
from datetime import date

SERIES_TOLERANCE = 0.05
MIN_SERIES = 3
STALE_DAYS = 45
STEADY_SHARE = 0.7


# ---- Cadence ----


def _steady(gaps: list[int], lo: int, hi: int) -> bool:
    return sum(lo <= g <= hi for g in gaps) / len(gaps) >= STEADY_SHARE


def cadence(days: list[date]) -> dict | None:
    days = sorted(set(days))
    if len(days) < MIN_SERIES:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    med = statistics.median(gaps)
    weekend = "after" if sum(d.weekday() == 0 for d in days) > sum(d.weekday() == 4 for d in days) else "before"
    if 5 <= med <= 9:
        return {"cadence": "weekly", "anchor": days[-1].isoformat()} if _steady(gaps, 5, 9) else None
    if 12 <= med <= 16:
        weekday_share = Counter(d.weekday() for d in days).most_common(1)[0][1] / len(days)
        if _steady(gaps, 13, 15) and weekday_share >= STEADY_SHARE:
            return {"cadence": "biweekly", "anchor": days[-1].isoformat()}
        low = [d.day for d in days if d.day <= 15]
        high = [d.day for d in days if d.day > 15]
        if low and high and _steady(gaps, 10, 20):
            pick = [Counter(low).most_common(1)[0][0], Counter(high).most_common(1)[0][0]]
            return {"cadence": "semimonthly", "days": pick, "weekend": weekend}
        return None
    if 26 <= med <= 35 and _steady(gaps, 26, 35):
        return {"cadence": "monthly", "days": [Counter(d.day for d in days).most_common(1)[0][0]], "weekend": weekend}
    return None


# ---- Series ----


def _groups(items: list[tuple[date, float]]) -> list[list[tuple[date, float]]]:
    groups: list[list[tuple[date, float]]] = []
    for d, amount in sorted(items, key=lambda x: (x[1], x[0])):
        if groups and amount <= groups[-1][0][1] * (1 + SERIES_TOLERANCE):
            groups[-1].append((d, amount))
        else:
            groups.append([(d, amount)])
    return groups


def _hit(group: list[tuple[date, float]], today: date) -> tuple[dict | None, bool]:
    if len(group) < MIN_SERIES:
        return None, False
    found = cadence([d for d, _ in group])
    if found is None:
        return None, False
    last = max(d for d, _ in group)
    if (today - last).days > STALE_DAYS:
        return None, True
    return {**found, "amount_usd": round(statistics.median(a for _, a in group)), "observed": len(group), "last": last.isoformat()}, False


def series(items: list[tuple[date, float]], today: date) -> tuple[list[dict], int, int]:
    found, used, stale = [], 0, 0
    for g in sorted(_groups(items), key=len, reverse=True):
        hit, old = _hit(g, today)
        stale += old
        if hit:
            found.append(hit)
            used += len(g)
    if not found and not stale:
        hit, old = _hit(items, today)
        stale += old
        if hit:
            found.append(hit)
            used = len(items)
    return sorted(found, key=lambda x: -x["amount_usd"]), len(items) - used, stale


def slug(key: str, taken: list[dict]) -> str:
    base = key.split("-")[0].lower() or "deposit"
    used = {d["id"] for d in taken}
    name, n = base, 2
    while name in used:
        name, n = f"{base}-{n}", n + 1
    return name


def schedule(money_in: list[dict], today: date) -> list[dict]:
    by_account: dict[str, list[tuple[date, float]]] = {}
    for x in money_in:
        by_account.setdefault(x["accountKey"], []).append((date.fromisoformat(x["date"]), x["amount"]))
    out: list[dict] = []
    for key in sorted(by_account):
        for hit in series(by_account[key], today)[0]:
            out.append({"id": slug(key, out), "account": key, **hit})
    return out
