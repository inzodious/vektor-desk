import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from desk.engine import broker
from desk.engine.market import last_trading_day
from desk.engine.source import SnapshotVersion, closes, snapshot_versions

SHARE_KINDS = {"buy", "sell", "reinvest"}
CORPORATE_KINDS = {"split", "distribution"}
STALE_MIN_ROWS = 1
STALE_SHARE = 0.6
CASH_SYMBOLS = {"SPAXX", "FDRXX", "FCASH", "CORE", "CASH", "FZFXX", "SPRXX"}


@dataclass
class Anchor:
    snapshot_id: str
    as_of: str
    date: str
    rows: dict[tuple[str, str], dict]
    quality: str


def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _is_cash(p: dict) -> bool:
    return bool(p.get("isCash")) or str(p.get("symbol") or "").upper() in CASH_SYMBOLS


# ---- Anchors from snapshot history ----


def pick_positions(v: SnapshotVersion) -> tuple[list[dict], str]:
    expected = v.snap.get("positionCount")
    rows = list(zip(v.positions, v.position_at, strict=True))
    if isinstance(expected, int) and 0 <= expected < len(rows):
        rows.sort(key=lambda r: r[1] or "", reverse=True)
        return [p for p, _ in rows[:expected]], "trimmed"
    return [p for p, _ in rows], "ok"


def aggregate(positions: list[dict]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for p in positions:
        symbol = str(p.get("symbol") or "").upper()
        account = str(p.get("accountKey") or "account")
        if not symbol:
            continue
        cash = _is_cash(p)
        value = _num(p.get("value")) or 0.0
        qty = value if cash else _num(p.get("quantity"))
        cur = out.setdefault((account, symbol), {"shares": 0.0, "value": 0.0, "cost": None, "is_cash": cash})
        cur["shares"] += qty or 0.0
        cur["value"] += value
        cost = _num(p.get("cost"))
        if cost is not None:
            cur["cost"] = (cur["cost"] or 0.0) + cost
    return out


def price_date(rows: dict[tuple[str, str], dict], day: str, prices: "Prices | None") -> str:
    if prices is None:
        return day
    after = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    found, priced = [], 0
    for (_, sym), h in rows.items():
        if h["is_cash"] or not h["shares"] or not h["value"] or not prices.dates.get(sym):
            continue
        priced += 1
        hit = prices.older_match(sym, h["value"] / h["shares"], after)
        if hit is not None:
            found.append(hit)
    if not found:
        return day
    top, n = Counter(found).most_common(1)[0]
    return top if top < day and n >= max(STALE_MIN_ROWS, priced * STALE_SHARE) else day


def anchors(versions: dict[str, SnapshotVersion], prices: "Prices | None" = None) -> tuple[list[Anchor], list[tuple]]:
    by_date: dict[str, Anchor] = {}
    records = []
    for v in versions.values():
        as_of = str(v.snap.get("asOf") or "")
        if len(as_of) < 10:
            continue
        chosen, quality = pick_positions(v)
        rows = aggregate(chosen)
        total = _num(v.snap.get("total"))
        if total is not None and rows and abs(sum(r["value"] for r in rows.values()) - total) > max(1.0, abs(total) * 0.0005):
            quality = "mismatch"
        records.append(
            [
                v.snapshot_id,
                as_of,
                as_of[:10],
                v.snap.get("source"),
                total,
                len(chosen),
                v.snap.get("positionCount"),
                v.first_seen,
                v.last_seen,
                int(v.alive),
                0,
                quality,
            ]
        )
        if not rows:
            continue
        day = price_date(rows, as_of[:10], prices)
        records[-1][2] = day
        a = Anchor(v.snapshot_id, as_of, day, rows, quality)
        cur = by_date.get(a.date)
        if cur is None or (a.as_of[:10] == a.date, a.as_of, a.snapshot_id) > (cur.as_of[:10] == cur.date, cur.as_of, cur.snapshot_id):
            by_date[a.date] = a
    picked = {a.snapshot_id for a in by_date.values()}
    for r in records:
        r[10] = int(r[0] in picked)
    return sorted(by_date.values(), key=lambda a: a.date), [tuple(r) for r in records]


# ---- Roll forward by activity ----


def activity_by_date(rows) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if len(d) == 10:
            out[d].append(r)
    return out


def apply_activity(held: dict[tuple[str, str], dict], rows: list[dict], price=None) -> bool:
    moved = False
    for r in rows:
        account = str(r.get("accountKey") or "account")
        symbol = str(r.get("symbol") or "").upper()
        kind = r.get("kind")
        qty = _num(r.get("quantity"))
        amount = _num(r.get("amount")) or 0.0
        core = bool(r.get("core")) or symbol in CASH_SYMBOLS
        if kind in SHARE_KINDS and symbol and not core and not qty:
            px = price(symbol) if price and amount else None
            if not px:
                continue
            qty = -amount / px
        if kind in SHARE_KINDS | CORPORATE_KINDS and symbol and not core and qty:
            cur = held.setdefault((account, symbol), {"shares": 0.0, "value": 0.0, "cost": None, "is_cash": False})
            cur["shares"] += qty
            moved = True
        if core or not amount:
            continue
        cash_key = next((k for k, v in held.items() if k[0] == account and v["is_cash"]), (account, "CASH"))
        cur = held.setdefault(cash_key, {"shares": 0.0, "value": 0.0, "cost": None, "is_cash": True})
        cur["shares"] += amount
        moved = True
    return moved


# ---- Daily holdings ----


def matching_close(series: dict[str, tuple], price: float, before: str, lookback: int = 10) -> str | None:
    days = sorted(d for d in series if d < before)[-lookback:]
    for d in reversed(days):
        c = series[d][0]
        if c and abs(c - price) <= max(0.005, abs(price) * 0.0002):
            return d
    return None


class Prices:
    def __init__(self, series: dict[str, dict[str, tuple[float, float | None]]]):
        self.dates = {s: sorted(d) for s, d in series.items()}
        self.series = series

    def close(self, symbol: str, day: str) -> float | None:
        found = self.dated(symbol, day)
        return found[1] if found else None

    def dated(self, symbol: str, day: str) -> tuple[str, float] | None:
        dates = self.dates.get(symbol)
        if not dates:
            return None
        i = bisect_right(dates, day)
        return (dates[i - 1], self.series[symbol][dates[i - 1]][0]) if i else None

    def older_match(self, symbol: str, price: float, before: str) -> str | None:
        return matching_close(self.series.get(symbol, {}), price, before)

    def calendar(self) -> set[str]:
        return {d for ds in self.dates.values() for d in ds}


def bar_series(desk: sqlite3.Connection) -> dict[str, dict[str, tuple[float, float | None]]]:
    out: dict[str, dict[str, tuple[float, float | None]]] = {}
    if desk.execute("SELECT 1 FROM sqlite_master WHERE name='price_bars'").fetchone():
        for r in desk.execute("SELECT symbol, date, close, adj_close FROM price_bars"):
            out.setdefault(r["symbol"], {})[r["date"]] = (r["close"], r["adj_close"])
    return out


def merge(mirror_series: dict, bars: dict) -> dict[str, dict[str, tuple[float, float | None]]]:
    out = {s: dict(ds) for s, ds in mirror_series.items()}
    for s, ds in bars.items():
        out.setdefault(s, {}).update(ds)
    return out


def price_series(mirror: sqlite3.Connection, desk: sqlite3.Connection) -> dict[str, dict[str, tuple[float, float | None]]]:
    return merge(closes(mirror), bar_series(desk))


def build_days(anchor_list: list[Anchor], prices: Prices, through: str | None = None) -> list[str]:
    if not anchor_list:
        return []
    start = anchor_list[0].date
    days = {a.date for a in anchor_list} | prices.calendar()
    end = max(days | ({through} if through else set()))
    return sorted(d for d in days if start <= d <= end)


def _anchor_price(a: Anchor, symbol: str) -> float | None:
    for (_, sym), h in a.rows.items():
        if sym == symbol and h["shares"] and not h["is_cash"]:
            return h["value"] / h["shares"]
    return None


def unit_prices(anchor_list: list[Anchor]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, dict[str, float]] = {}
    for a in anchor_list:
        for (_, sym), h in a.rows.items():
            if not h["is_cash"] and h["shares"] and h["value"]:
                out.setdefault(sym, {})[a.date] = h["value"] / h["shares"]
    return {s: sorted(ds.items()) for s, ds in out.items()}


def between(units: list[tuple[str, float]] | None, day: str, index: dict[str, int]) -> float | None:
    if not units:
        return None
    i = bisect_right([d for d, _ in units], day)
    if i == 0 or i == len(units):
        return None
    (d0, p0), (d1, p1) = units[i - 1], units[i]
    if d0 not in index or d1 not in index or d0 == day:
        return None
    return p0 + (p1 - p0) * (index[day] - index[d0]) / (index[d1] - index[d0])


def holdings_rows(anchor_list: list[Anchor], prices: Prices, activity: dict[str, list[dict]], days: list[str]) -> list[tuple]:
    out = []
    anchor_dates = [a.date for a in anchor_list]
    act_dates = sorted(activity)
    units = unit_prices(anchor_list)
    index = {d: i for i, d in enumerate(days)}
    for day in days:
        a = anchor_list[bisect_right(anchor_dates, day) - 1]
        held = {k: dict(v) for k, v in a.rows.items()}
        source, quality = "snapshot", a.quality
        if day != a.date:
            source, quality = "rolled", "pro_forma"
            lo, hi = bisect_right(act_dates, a.date), bisect_right(act_dates, day)
            for d in act_dates[lo:hi]:
                apply_activity(held, activity[d], lambda sym, d=d, a=a: prices.close(sym, d) or _anchor_price(a, sym))
        for (account, symbol), h in sorted(held.items()):
            row_quality = quality
            if h["is_cash"]:
                close, value = 1.0, round(h["shares"], 2)
            else:
                found = prices.dated(symbol, day)
                base = a.rows.get((account, symbol))
                implied = base["value"] / base["shares"] if base and base["shares"] else None
                close = found[1] if found else None
                lagging = found is not None and found[0] < last_trading_day(date.fromisoformat(day)).isoformat()
                if source == "snapshot" and implied is not None and lagging and not prices.older_match(symbol, implied, found[0]):
                    close = implied
                elif close is None:
                    close = between(units.get(symbol), day, index) or implied
                    row_quality = "pro_forma" if quality in ("ok", "trimmed") else quality
                value = round(h["shares"] * close, 2) if close is not None else round(h["value"], 2)
            if abs(h["shares"]) < 1e-9 and abs(value) < 0.005:
                continue
            reported = round(h["value"], 2) if source == "snapshot" else None
            out.append((day, account, symbol, round(h["shares"], 6), close, value, h["cost"], reported, int(h["is_cash"]), source, a.as_of, row_quality))
    return out


def rebuild(mirror: sqlite3.Connection, desk: sqlite3.Connection, *, through: str | None = None) -> dict:
    versions = snapshot_versions(mirror)
    series = closes(mirror)
    bars = bar_series(desk)
    prices = Prices(merge(series, bars))
    anchor_list, records = anchors(versions, prices)
    activity = activity_by_date(broker.activity(mirror, desk))
    days = build_days(anchor_list, prices, through)
    rows = holdings_rows(anchor_list, prices, activity, days)
    with desk:
        desk.execute("DELETE FROM engine_snapshots")
        desk.executemany("INSERT INTO engine_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", records)
        desk.execute("DELETE FROM prices_daily WHERE source='mirror'")
        desk.executemany(
            "INSERT OR REPLACE INTO prices_daily (symbol, date, close, adj_close, source) VALUES (?, ?, ?, ?, 'mirror')",
            ((s, d, c, adj) for s, ds in series.items() for d, (c, adj) in ds.items() if d not in bars.get(s, {})),
        )
        desk.execute("DELETE FROM holdings_daily")
        desk.executemany("INSERT INTO holdings_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {
        "snapshots": len(records),
        "anchors": len(anchor_list),
        "days": len(days),
        "rows": len(rows),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "symbols_priced": len(series),
    }
