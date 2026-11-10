import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import median

from desk.engine.flows import classify
from desk.engine.holdings import CASH_SYMBOLS, Prices
from desk.engine.risk import SP500
from desk.engine.shadows import TotalReturn
from desk.engine.tax import held_long

EPS = 1e-9
CENT = 0.005
LONG_TERM_FEDERAL_PCT = 15.0
RECONCILE_PCT = 1.0
TOP_SYMBOLS = 8
TOP_EVENTS = 12
BIG_BUY = 0.10
MUTUAL = re.compile(r"^[A-Z]{4}X$")
SHARE_KINDS = ("buy", "sell", "reinvest")
RANK = {"split": 0, "distribution": 1}
INTEREST = "Margin interest"
NOTE = (
    "Same deposits and withdrawals on the same dates, one rule changed. Every dollar a rule moves goes into or comes out of the index, "
    "so the gap is what the rule alone would have done. Closing prices, no taxes in the end values."
)


# ---- Rules ----


@dataclass(frozen=True)
class Rule:
    id: str = "you"
    family: str = "none"
    label: str = "What you did"
    buy_cap: float | None = None
    position_cap: float | None = None
    stop: float | None = None
    trend: int | None = None
    no_margin: bool = False
    long_term: bool = False


def presets() -> list[Rule]:
    out = [Rule("house", "house", "No single name over 10% of the account, nothing on margin", position_cap=0.10, no_margin=True)]
    for pct in (5, 10, 15, 20):
        out.append(Rule(f"buy-cap-{pct}", "buy_cap", f"No single buy over {pct}% of the account", buy_cap=pct / 100))
    for pct in (5, 10, 15, 20):
        out.append(Rule(f"position-cap-{pct}", "position_cap", f"No single name over {pct}% of the account", position_cap=pct / 100))
    for pct in (15, 20, 25, 30):
        out.append(Rule(f"stop-{pct}", "stop", f"Sell at {pct}% below what you paid", stop=pct / 100))
    out.append(Rule("trend-200", "trend", "Only hold single names above their 200-day average", trend=200))
    out.append(Rule("no-margin", "no_margin", "Nothing bought on margin", no_margin=True))
    out.append(Rule("long-term", "long_term", "Hold every sale back until a year and a day", long_term=True))
    return out


HEADLINE = "house"


# ---- Market ----


class Market:
    def __init__(self, series: dict, index: str):
        self.px = Prices(series)
        self.tr = TotalReturn(series)
        self.index = index
        self.first = self.tr.series[index][self.tr.dates[index][0]]
        self.sums: dict[str, list[float]] = {}

    def close(self, symbol: str, day: str) -> float | None:
        return self.px.close(symbol, day)

    def unit(self, day: str) -> float:
        return self.tr.price(self.index, day) or self.first

    def below_trend(self, symbol: str, day: str, n: int) -> bool:
        dates = self.tr.dates.get(symbol)
        if not dates:
            return False
        i = bisect_right(dates, day)
        if i < n:
            return False
        sums = self.sums.get(symbol)
        if sums is None:
            sums, run = [0.0], 0.0
            for d in dates:
                run += self.tr.series[symbol][d]
                sums.append(run)
            self.sums[symbol] = sums
        return self.tr.series[symbol][dates[i - 1]] < (sums[i] - sums[i - n]) / n


def long_from(acquired: str) -> str:
    a = date.fromisoformat(acquired)
    try:
        anniversary = a.replace(year=a.year + 1)
    except ValueError:
        anniversary = a.replace(year=a.year + 1, day=28)
    return (anniversary + timedelta(days=1)).isoformat()


# ---- History rows ----


def _num(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def prepare(activity: list[dict], cover: dict, close, as_of: str) -> tuple[list[dict], dict[tuple[str, str], float], int]:
    rows, skipped = [], 0
    for seq, r in enumerate(activity):
        acct, day = str(r.get("accountKey") or ""), str(r.get("date") or "")[:10]
        if acct not in cover or len(day) != 10 or day > as_of:
            continue
        kind = r.get("kind")
        sym = str(r.get("symbol") or "").upper()
        if r.get("core") or sym in CASH_SYMBOLS:
            continue
        amount = _num(r.get("amount")) or 0.0
        qty = _num(r.get("quantity"))
        if kind in SHARE_KINDS + ("split", "distribution"):
            if not sym:
                continue
            if kind in SHARE_KINDS and not qty:
                px = close(sym, day) if amount else None
                if not px:
                    skipped += 1
                    continue
                qty = -amount / px
            if not qty:
                continue
            if kind in SHARE_KINDS:
                kind = "sell" if qty < 0 else ("reinvest" if kind == "reinvest" else "buy")
        elif not amount:
            continue
        rank = RANK.get(kind, 3 if kind == "sell" else (4 if kind in ("buy", "reinvest") else (2 if amount > 0 else 5)))
        rows.append({"acct": acct, "day": day, "kind": kind, "sym": sym, "qty": qty, "amount": amount, "px": _num(r.get("price")), "rank": rank, "seq": seq})
    rows.sort(key=lambda r: (r["day"], r["rank"], r["seq"]))
    start: dict[tuple[str, str], float] = defaultdict(float)
    by_day: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] in ("buy", "sell", "reinvest"):
            by_day[(r["acct"], r["day"], r["sym"])].append(r)
    run: dict[tuple[str, str], float] = defaultdict(float)
    seen_day: dict[tuple[str, str], str] = {}
    for r in rows:
        if r["qty"] is None or r["kind"] not in ("buy", "sell", "reinvest", "split", "distribution"):
            continue
        key = (r["acct"], r["sym"])
        if r["kind"] in ("buy", "sell", "reinvest") and seen_day.get(key) != r["day"]:
            seen_day[key] = r["day"]
            group = by_day[(r["acct"], r["day"], r["sym"])]
            sold = -sum(x["qty"] for x in group if x["qty"] < 0)
            if sold > run[key] + EPS and any(x["qty"] > 0 for x in group):
                for x in group:
                    if x["qty"] > 0:
                        x["rank"] = 2.5
        run[key] += r["qty"]
    rows.sort(key=lambda r: (r["day"], r["rank"], r["seq"]))
    run.clear()
    for r in rows:
        if r["qty"] is None or r["kind"] not in ("buy", "sell", "reinvest", "split", "distribution"):
            continue
        key = (r["acct"], r["sym"])
        run[key] += r["qty"]
        if run[key] < -EPS:
            start[key] = max(start[key], -run[key])
    return rows, {k: v for k, v in start.items() if v > EPS}, skipped


# ---- One replay ----


class Sim:
    def __init__(self, rows, seeds, mkt: Market, days: list[str], single, sheltered, rule: Rule):
        self.rows, self.mkt, self.days, self.single, self.sheltered, self.rule = rows, mkt, days, single, sheltered, rule
        self.lots: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.late: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.cash: dict[str, float] = defaultdict(float)
        self.fin: dict[tuple[str, str], list[float]] = {}
        self.spare: dict[str, float] = defaultdict(float)
        self.last: dict[str, float] = {}
        self.debit: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self.gains = {"you": {"short": 0.0, "long": 0.0}, "rule": {"short": 0.0, "long": 0.0}}
        self.events: list[dict] = []
        self.buys: list[dict] = []
        self.margin = {"days": 0, "peak": 0.0, "interest": 0.0}
        for (acct, sym), shares in seeds.items():
            self.lots[(acct, sym)].append({"acquired": None, "b": shares, "v": shares, "cost_b": 0.0, "cost_v": 0.0})

    # ---- Financing ----

    def _put(self, acct: str, key: str, usd: float, day: str) -> None:
        f = self.fin.setdefault((acct, key), [0.0, 0.0])
        f[1] += usd
        self.spare[acct] += usd
        self._settle(acct, day)

    def _settle(self, acct: str, day: str) -> None:
        mine = [f for (a, _), f in self.fin.items() if a == acct and abs(f[1]) > EPS]
        if not mine:
            return
        unit = self.mkt.unit(day)
        for f in mine:
            if f[1] < 0:
                f[0] += f[1] / unit
                self.spare[acct] -= f[1]
                f[1] = 0.0
        ceiling = max(0.0, -self.cash[acct]) if self.rule.no_margin else 0.0
        extra = self.spare[acct] - ceiling
        if extra <= EPS:
            return
        total = sum(f[1] for f in mine if f[1] > 0)
        for f in mine:
            if f[1] > 0:
                part = extra * f[1] / total
                f[1] -= part
                f[0] += part / unit
        self.spare[acct] -= extra

    # ---- Prices and values ----

    def _px(self, sym: str, day: str) -> float:
        return self.mkt.close(sym, day) or self.last.get(sym) or 0.0

    def values(self, day: str) -> tuple[float, float]:
        you = rule = sum(self.cash.values())
        for (_, sym), held in self.lots.items():
            b = sum(lot["b"] for lot in held)
            v = sum(lot["v"] for lot in held)
            if b > EPS or v > EPS:
                px = self._px(sym, day)
                you += b * px
                rule += v * px
        for (_, sym), items in self.late.items():
            if items:
                rule += sum(x["shares"] for x in items) * self._px(sym, day)
        unit = self.mkt.unit(day)
        rule += sum(f[0] * unit + f[1] for f in self.fin.values())
        return you, rule

    def _held(self, key: tuple[str, str]) -> tuple[float, float]:
        held = self.lots.get(key) or []
        return sum(lot["b"] for lot in held), sum(lot["v"] for lot in held) + sum(x["shares"] for x in self.late.get(key) or [])

    def _position(self, sym: str, day: str) -> float:
        shares = sum(self._held(k)[1] for k in list(self.lots) if k[1] == sym)
        return shares * self._px(sym, day)

    def _gain(self, who: str, acct: str, acquired: str | None, sold: str, gain: float) -> None:
        if acquired is None or self.sheltered(acct):
            return
        self.gains[who]["long" if held_long(acquired, sold) else "short"] += gain

    def _event(self, day: str, sym: str, what: str, usd: float) -> None:
        self.events.append({"date": day, "symbol": sym, "what": what, "usd": round(usd, 2)})

    # ---- Rows ----

    def _buy(self, r: dict) -> None:
        acct, sym, day, qty = r["acct"], r["sym"], r["day"], r["qty"]
        cost = -r["amount"] if r["amount"] < 0 else qty * (r["px"] or 0.0)
        key = (acct, sym)
        take, why = 1.0, None
        rule = self.rule
        if r["kind"] == "reinvest":
            b, v = self._held(key)
            take = v / b if b > EPS else 1.0
        elif cost > 0:
            total = None
            if self.single(sym):
                total = self.values(day)[1]
                self.buys.append({"date": day, "symbol": sym, "usd": cost, "total": total, "margin": self.cash[acct] < cost - CENT})
            if rule.no_margin:
                room = max(0.0, self.cash[acct] + self.spare[acct])
                if room < cost - CENT:
                    take, why = room / cost, "margin"
            if total is not None:
                if rule.trend and self.mkt.below_trend(sym, day, rule.trend):
                    take, why = 0.0, "trend"
                if (rule.buy_cap or rule.position_cap) and total > 0:
                    room = rule.buy_cap * total if rule.buy_cap else float("inf")
                    if rule.position_cap:
                        room = min(room, max(0.0, rule.position_cap * total - self._position(sym, day)))
                    if room < cost * take - CENT:
                        take, why = room / cost, "cap"
        self.cash[acct] -= cost
        self.lots[key].append({"acquired": day, "b": qty, "v": qty * take, "cost_b": cost, "cost_v": cost * take})
        if qty > EPS and cost > 0:
            self.last[sym] = cost / qty
        if why:
            self._event(day, sym, why, cost * (1 - take))
        self._put(acct, sym, cost * (1 - take), day)

    def _sell(self, r: dict) -> None:
        acct, sym, day = r["acct"], r["sym"], r["day"]
        qty = -r["qty"]
        proceeds = r["amount"] if r["amount"] > 0 else qty * (r["px"] or 0.0)
        px = proceeds / qty
        key = (acct, sym)
        held = self.lots[key]
        left, got, waiting = qty, 0.0, 0.0
        while left > EPS and held:
            lot = held[0]
            x = min(lot["b"], left)
            g = x / lot["b"] if lot["b"] > EPS else 1.0
            v, cost_v, cost_b = lot["v"] * g, lot["cost_v"] * g, lot["cost_b"] * g
            self._gain("you", acct, lot["acquired"], day, x * px - cost_b)
            if v > EPS:
                if self.rule.long_term and lot["acquired"] and not held_long(lot["acquired"], day):
                    self.late[key].append({"acquired": lot["acquired"], "shares": v, "cost": cost_v, "due": long_from(lot["acquired"])})
                    waiting += v * px
                else:
                    got += v * px
                    self._gain("rule", acct, lot["acquired"], day, v * px - cost_v)
            lot["b"] -= x
            lot["v"] -= v
            lot["cost_b"] -= cost_b
            lot["cost_v"] -= cost_v
            left -= x
            if lot["b"] <= EPS:
                held.pop(0)
        self.cash[acct] += proceeds
        self.last[sym] = px
        if waiting:
            self._event(day, sym, "wait", waiting)
        self._put(acct, sym, got - px * (qty - left), day)

    def _scale(self, key: tuple[str, str], ratio: float) -> None:
        for lot in self.lots.get(key) or []:
            lot["b"] *= ratio
            lot["v"] *= ratio
        for x in self.late.get(key) or []:
            x["shares"] *= ratio

    def _distribution(self, r: dict) -> None:
        key = (r["acct"], r["sym"])
        b, _ = self._held(key)
        if b > EPS:
            self._scale(key, max(0.0, (b + r["qty"]) / b))
        elif r["qty"] > 0:
            self.lots[key].append({"acquired": r["day"], "b": r["qty"], "v": r["qty"], "cost_b": 0.0, "cost_v": 0.0})

    def _split(self, group: list[dict]) -> None:
        old = [r for r in group if r["qty"] < 0]
        new = [r for r in group if r["qty"] > 0]
        for o, n in zip(old, new, strict=False):
            src, dst = (o["acct"], o["sym"]), (n["acct"], n["sym"])
            ratio = n["qty"] / -o["qty"]
            self._scale(src, ratio)
            if o["sym"] in self.last:
                self.last[n["sym"]] = self.last[o["sym"]] / ratio
            if src == dst:
                continue
            self.lots[dst] = sorted(self.lots.pop(src, []) + self.lots.get(dst, []), key=lambda lot: lot["acquired"] or "")
            self.late[dst] = self.late.pop(src, []) + self.late.get(dst, [])
            f = self.fin.pop(src, None)
            if f:
                g = self.fin.setdefault(dst, [0.0, 0.0])
                g[0] += f[0]
                g[1] += f[1]
        for r in old[len(new) :] + new[len(old) :]:
            self._distribution(r)

    def _cash_row(self, r: dict) -> None:
        acct, kind, amount, day = r["acct"], r["kind"], r["amount"], r["day"]
        self.cash[acct] += amount
        if kind == "dividend" and r["sym"]:
            b, v = self._held((acct, r["sym"]))
            if b > EPS and abs(v - b) > EPS:
                self._put(acct, r["sym"], amount * (v / b - 1), day)
                return
        if kind == "margin_interest" and amount < 0:
            self.margin["interest"] -= amount
            owed, mine = self.debit[acct]
            self.debit[acct] = [0.0, 0.0]
            if self.rule.no_margin and owed > EPS:
                self._put(acct, INTEREST, -amount * (1 - min(1.0, mine / owed)), day)
                return
        self._settle(acct, day)

    def _apply(self, r: dict, group: list[dict] | None) -> None:
        kind = r["kind"]
        if kind == "split":
            if group is not None:
                self._split(group)
        elif kind == "distribution":
            self._distribution(r)
        elif kind in ("buy", "reinvest"):
            self._buy(r)
        elif kind == "sell":
            self._sell(r)
        else:
            self._cash_row(r)

    # ---- Daily checks ----

    def _mature(self, day: str) -> None:
        for (acct, sym), items in self.late.items():
            due = [x for x in items if x["due"] <= day]
            if not due:
                continue
            px = self._px(sym, day)
            for x in due:
                self._gain("rule", acct, x["acquired"], day, x["shares"] * px - x["cost"])
            self.late[(acct, sym)] = [x for x in items if x["due"] > day]
            self._put(acct, sym, sum(x["shares"] for x in due) * px, day)

    def _exits(self, day: str) -> None:
        rule = self.rule
        for (acct, sym), held in self.lots.items():
            shares = sum(lot["v"] for lot in held)
            if shares <= EPS or not self.single(sym):
                continue
            px = self.mkt.close(sym, day)
            if not px:
                continue
            cost = sum(lot["cost_v"] for lot in held)
            hit = None
            if rule.stop and cost > 0 and px <= cost / shares * (1 - rule.stop):
                hit = "stop"
            elif rule.trend and self.mkt.below_trend(sym, day, rule.trend):
                hit = "trend"
            if not hit:
                continue
            for lot in held:
                if lot["v"] > EPS:
                    self._gain("rule", acct, lot["acquired"], day, lot["v"] * px - lot["cost_v"])
                    lot["v"], lot["cost_v"] = 0.0, 0.0
            self._event(day, sym, hit, shares * px)
            self._put(acct, sym, shares * px, day)

    def run(self, sample: set[str]) -> dict:
        rule = self.rule
        i, n = 0, len(self.rows)
        series = []
        for day in self.days:
            done_splits: set[tuple[str, str]] = set()
            while i < n and self.rows[i]["day"] <= day:
                r = self.rows[i]
                group = None
                if r["kind"] == "split" and (r["acct"], r["day"]) not in done_splits:
                    done_splits.add((r["acct"], r["day"]))
                    group = [x for x in self.rows[i:] if x["day"] == r["day"] and x["acct"] == r["acct"] and x["kind"] == "split"]
                self._apply(r, group)
                i += 1
            if rule.long_term:
                self._mature(day)
            if rule.stop or rule.trend:
                self._exits(day)
            owing = False
            for acct, cash in self.cash.items():
                if cash < -CENT:
                    owing = True
                    self.debit[acct][0] -= cash
                    self.debit[acct][1] += max(0.0, -(cash + self.spare[acct]))
            debt = -sum(c for c in self.cash.values() if c < 0)
            if owing:
                self.margin["days"] += 1
                self.margin["peak"] = max(self.margin["peak"], debt)
            if day in sample:
                series.append(self.values(day))
        return {"series": series, "end": self.values(self.days[-1])}

    def effects(self, day: str) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        unit = self.mkt.unit(day)
        for (_, sym), held in self.lots.items():
            gap = sum(lot["v"] - lot["b"] for lot in held)
            if abs(gap) > EPS:
                out[sym] += gap * self._px(sym, day)
        for (_, sym), items in self.late.items():
            if items:
                out[sym] += sum(x["shares"] for x in items) * self._px(sym, day)
        for (_, key), f in self.fin.items():
            out[key] += f[0] * unit + f[1]
        return {k: v for k, v in out.items() if abs(v) >= CENT}


# ---- The view ----


def _weekly(days: list[str]) -> list[str]:
    out = [d for d, nxt in zip(days, days[1:], strict=False) if date.fromisoformat(d).isocalendar()[:2] != date.fromisoformat(nxt).isocalendar()[:2]]
    return out + days[-1:]


def _index_only(flows: list[dict], seeds_value: float, mkt: Market, days: list[str], sample: list[str]) -> tuple[list[float], float]:
    units = seeds_value / mkt.unit(days[0])
    by_day: dict[str, float] = defaultdict(float)
    for f in flows:
        by_day[f["date"]] += f["amount"]
    pending = sorted(by_day.items())
    out, i, want = [], 0, set(sample)
    for day in days:
        while i < len(pending) and pending[i][0] <= day:
            units += pending[i][1] / mkt.unit(pending[i][0])
            i += 1
        if day in want:
            out.append(round(units * mkt.unit(day), 2))
    return out, round(units * mkt.unit(days[-1]), 2)


def _tax(gains: dict, rates: tuple[float, float] | None) -> float | None:
    if rates is None:
        return None
    return round(gains["short"] * rates[0] / 100 + gains["long"] * rates[1] / 100, 2)


def _sizing(buys: list[dict]) -> dict:
    by_day: dict[tuple[str, str], dict] = {}
    for b in buys:
        cur = by_day.setdefault((b["date"], b["symbol"]), {"date": b["date"], "symbol": b["symbol"], "usd": 0.0, "total": b["total"], "margin": False})
        cur["usd"] += b["usd"]
        cur["margin"] = cur["margin"] or b["margin"]
    sized = [{**b, "pct": b["usd"] / b["total"] * 100} for b in by_day.values() if b["total"] and b["total"] > 0]
    if not sized:
        return {"buys": 0, "median_pct": None, "over_10": 0, "on_margin": 0, "largest": None}
    top = max(sized, key=lambda b: b["pct"])
    return {
        "buys": len(sized),
        "median_pct": round(median(b["pct"] for b in sized), 2),
        "over_10": sum(1 for b in sized if b["pct"] > BIG_BUY * 100),
        "on_margin": sum(1 for b in sized if b["margin"]),
        "largest": {"date": top["date"], "symbol": top["symbol"], "pct": round(top["pct"], 2), "usd": round(top["usd"], 2)},
    }


def _row(rule: Rule, sim: Sim, result: dict, base_gains: dict, rates, day: str) -> dict:
    you, mine = result["end"]
    effects = sorted(sim.effects(day).items(), key=lambda kv: -abs(kv[1]))
    shown = [{"symbol": s, "usd": round(v, 2)} for s, v in effects[:TOP_SYMBOLS]]
    rest = sum(v for _, v in effects[TOP_SYMBOLS:])
    if abs(rest) >= CENT:
        shown.append({"symbol": "Everything else", "usd": round(rest, 2)})
    tax_rule, tax_you = _tax(sim.gains["rule"], rates), _tax(base_gains, rates)
    params = {k: v for k, v in asdict(rule).items() if k not in ("id", "family", "label") and v}
    return {
        "id": rule.id,
        "family": rule.family,
        "label": rule.label,
        "params": params,
        "end_value": round(mine, 2),
        "change_usd": round(mine - you, 2),
        "change_pct": round((mine / you - 1) * 100, 2) if you > 0 else None,
        "helped_usd": round(sum(v for _, v in effects if v > 0), 2),
        "hurt_usd": round(sum(v for _, v in effects if v < 0), 2),
        "by_symbol": shown,
        "actions": len(sim.events),
        "moved_usd": round(sum(e["usd"] for e in sim.events), 2),
        "events": sorted(sim.events, key=lambda e: -e["usd"])[:TOP_EVENTS],
        "realized": {k: round(v, 2) for k, v in sim.gains["rule"].items()},
        "tax_usd": tax_rule,
        "tax_change_usd": round(tax_rule - tax_you, 2) if tax_rule is not None else None,
        "values": [round(v, 2) for _, v in result["series"]],
    }


def run(
    as_of: str,
    activity: list[dict],
    cover: dict[str, tuple[str, str]],
    series: dict,
    *,
    broad: set[str] = frozenset(),
    mutual: set[str] = frozenset(),
    sheltered=lambda acct: False,
    held_value: float | None = None,
    short_rate: float | None = None,
    state_rate: float = 0.0,
) -> dict:
    empty = {"as_of": as_of, "status": "not_ready", "quality": "insufficient_history", "variants": [], "note": NOTE}
    if not cover:
        return empty | {"reason": "No Fidelity history yet. Upload the activity export in Settings and the replay runs with the next engine pass."}
    index = next((s for s in SP500 if series.get(s)), None)
    if index is None:
        return empty | {"reason": "No S&P 500 prices yet, so there is nowhere to send the dollars a rule moves. They arrive with the nightly backfill."}
    mkt = Market(series, index)
    rows, seeds, skipped = prepare(activity, cover, mkt.close, as_of)
    if not rows:
        return empty | {"reason": "The history has no trades or cash moves yet."}
    start = rows[0]["day"]
    days = [d for d in mkt.tr.dates[index] if start <= d <= as_of]
    if not days or days[-1] != as_of:
        days.append(as_of)
    traded = sorted({r["sym"] for r in rows if r["kind"] in ("buy", "sell", "reinvest")})
    unpriced = [s for s in traded if not series.get(s)]
    funds = set(broad) | set(mutual) | set(SP500)

    def single(sym: str) -> bool:
        return sym not in funds and not MUTUAL.match(sym) and bool(series.get(sym))

    sample = _weekly(days)
    want = set(sample)
    rates = (short_rate, LONG_TERM_FEDERAL_PCT + state_rate) if short_rate is not None else None
    base = Sim(rows, seeds, mkt, days, single, sheltered, Rule())
    base_result = base.run(want)
    you_end = base_result["end"][0]
    seeds_value = sum(shares * (mkt.close(sym, start) or 0.0) for (_, sym), shares in seeds.items())
    flows = [f for f in classify([r for r in activity if str(r.get("accountKey") or "") in cover]) if f["external_portfolio"] and f["date"] <= as_of]
    index_values, index_end = _index_only(flows, seeds_value, mkt, days, sample)
    variants = []
    for rule in presets():
        sim = Sim(rows, seeds, mkt, days, single, sheltered, rule)
        variants.append(_row(rule, sim, sim.run(want), base.gains["you"], rates, as_of))
    gap = None if held_value is None else round(you_end - held_value, 2)
    off = gap is not None and abs(gap) > max(5.0, abs(held_value) * RECONCILE_PCT / 100)
    late = mkt.tr.dates[index][0] > start
    quality = "pro_forma" if unpriced or late else ("modelled" if off or seeds else "ok")
    notes = []
    if late:
        notes.append(f"{index} prices start on {mkt.tr.dates[index][0]}, after the history does, so the index stands still before that.")
    if unpriced:
        notes.append(f"No prices yet for {', '.join(unpriced)}, so those names sit at their last trade price and no rule touches them.")
    if seeds:
        held = sorted({s for _, s in seeds})
        one = len(held) == 1
        notes.append(
            f"{', '.join(held)} {'was' if one else 'were'} held before the history starts, so {'its' if one else 'their'} first shares have no buy to cap."
        )
    if skipped:
        notes.append(f"{skipped} trade{'s' if skipped != 1 else ''} had no share count and no price, and {'were' if skipped != 1 else 'was'} left out.")
    if off:
        notes.append("The replayed end value is more than 1% away from today's holdings, so read the gaps as estimates.")
    return {
        "as_of": as_of,
        "status": "partial" if unpriced or late else "ok",
        "quality": quality,
        "start": start,
        "end": as_of,
        "index": index,
        "accounts": sorted(cover),
        "headline": HEADLINE,
        "dates": sample,
        "you": {
            "end_value": round(you_end, 2),
            "values": [round(v, 2) for v, _ in base_result["series"]],
            "realized": {k: round(v, 2) for k, v in base.gains["you"].items()},
            "tax_usd": _tax(base.gains["you"], rates),
            "holdings_value": held_value,
            "gap_usd": gap,
        },
        "index_only": {"end_value": index_end, "values": index_values},
        "sizing": _sizing(base.buys),
        "margin": {"days": base.margin["days"], "peak_usd": round(base.margin["peak"], 2), "interest_usd": round(base.margin["interest"], 2)},
        "tax_rates": {"short_pct": rates[0], "long_pct": rates[1]} if rates else None,
        "variants": variants,
        "unpriced": unpriced,
        "notes": notes,
        "note": NOTE,
    }
