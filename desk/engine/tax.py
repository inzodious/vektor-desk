from datetime import date, timedelta

WASH_DAYS = 30
LOT_METHODS = ("highest_cost", "lowest_cost", "fifo", "lifo", "tax_efficient")
SIMILAR = (frozenset({"FXAIX", "VOO", "IVV", "SPY", "VFIAX", "SWPPX", "SPLG"}), frozenset({"FZROX", "FSKAX", "VTI", "VTSAX", "ITOT", "SCHB"}))
BUY_KINDS = {"buy", "reinvest"}


# ---- Lots ----


def held_long(acquired: str | None, on: str) -> bool | None:
    if not acquired:
        return None
    a, d = date.fromisoformat(acquired), date.fromisoformat(on)
    try:
        anniversary = a.replace(year=a.year + 1)
    except ValueError:
        anniversary = a.replace(year=a.year + 1, day=28)
    return d > anniversary


def _cps(lot: dict) -> float:
    if lot.get("cost_per_share") is not None:
        return float(lot["cost_per_share"])
    return float(lot.get("cost") or 0) / lot["shares"] if lot.get("shares") else 0.0


def order_lots(lots: list[dict], method: str, price: float, on: str) -> list[dict]:
    if method == "lowest_cost":
        return sorted(lots, key=_cps)
    if method == "fifo":
        return sorted(lots, key=lambda lot: lot.get("acquired") or "")
    if method == "lifo":
        return sorted(lots, key=lambda lot: lot.get("acquired") or "", reverse=True)
    if method == "tax_efficient":

        def rank(lot):
            gain = price - _cps(lot)
            long = held_long(lot.get("acquired"), on)
            group = (0 if not long else 1) if gain < 0 else (2 if long else 3)
            return (group, gain)

        return sorted(lots, key=rank)
    return sorted(lots, key=_cps, reverse=True)


def pick_lots(lots: list[dict], shares: float, price: float, method: str, on: str) -> tuple[list[dict], float]:
    picked, left = [], shares
    for lot in order_lots([lot for lot in lots if lot.get("shares", 0) > 0], method, price, on):
        if left <= 1e-9:
            break
        take = min(left, lot["shares"])
        cost = _cps(lot) * take
        proceeds = price * take
        long = held_long(lot.get("acquired"), on)
        picked.append(
            {
                "acquired": lot.get("acquired"),
                "shares": round(take, 6),
                "cost": round(cost, 2),
                "proceeds": round(proceeds, 2),
                "gain": round(proceeds - cost, 2),
                "term": "long" if long else ("short" if long is not None else (lot.get("term") or "unknown")),
            }
        )
        left -= take
    return picked, max(0.0, round(left, 6))


def split_gain(picked: list[dict]) -> tuple[float, float]:
    st = sum(p["gain"] for p in picked if p["term"] != "long")
    lt = sum(p["gain"] for p in picked if p["term"] == "long")
    return round(st, 2), round(lt, 2)


# ---- Realized ----


def realized(rows: list[dict], year: int) -> dict:
    out = {"st": 0.0, "lt": 0.0, "wash_disallowed": 0.0, "rows": 0, "unknown": 0, "modelled": 0}
    seen = set()
    for r in rows:
        if str(r.get("sold") or "")[:4] != str(year):
            continue
        key = (r["account"], r["symbol"], r["acquired"], r["sold"], r["shares"], r["proceeds"])
        if key in seen:
            continue
        seen.add(key)
        if r.get("gain") is None and r.get("cost") is None:
            out["unknown"] += 1
            continue
        gain = r["gain"] if r.get("gain") is not None else (r["proceeds"] or 0) - (r["cost"] or 0)
        long = r["term"] == "long" or (r["term"] is None and held_long(r["acquired"], r["sold"]))
        out["lt" if long else "st"] += gain
        out["wash_disallowed"] += r.get("wash_disallowed") or 0
        out["rows"] += 1
        out["modelled"] += int(r.get("quality") == "modelled")
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in out.items()}


# ---- Wash-sale windows ----


def _clears(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=WASH_DAYS + 1)).isoformat()


def similar(a: str, b: str) -> bool:
    return a != b and any(a in g and b in g for g in SIMILAR)


def wash_windows(activity: list[dict], realized_rows: list[dict], lots: list[dict], today: str) -> list[dict]:
    since = (date.fromisoformat(today) - timedelta(days=WASH_DAYS)).isoformat()
    out: dict[tuple, dict] = {}
    for r in realized_rows:
        sold = str(r.get("sold") or "")[:10]
        gain = r.get("gain")
        if gain is None:
            gain = (r.get("proceeds") or 0) - (r.get("cost") or 0)
        if sold and since <= sold <= today and gain < 0:
            key = (r["symbol"], "loss_sale", sold, r["account"])
            w = out.setdefault(key, {"symbol": r["symbol"], "kind": "loss_sale", "date": sold, "clears": _clears(sold), "account": r["account"], "amount": 0.0})
            w["amount"] = round(w["amount"] + gain, 2)
    buys = [
        (str(a.get("date") or "")[:10], str(a.get("symbol") or "").upper(), str(a.get("accountKey") or "account"), abs(float(a.get("amount") or 0)))
        for a in activity
        if a.get("kind") in BUY_KINDS and not a.get("core") and a.get("symbol")
    ]
    buys += [(lot["acquired"], lot["symbol"], lot["account"], float(lot.get("cost") or 0)) for lot in lots if lot.get("acquired")]
    for day, symbol, account, amount in buys:
        if day and since <= day <= today:
            key = (symbol, "recent_buy", day, account)
            if key not in out:
                out[key] = {"symbol": symbol, "kind": "recent_buy", "date": day, "clears": _clears(day), "account": account, "amount": round(amount, 2)}
    return sorted(out.values(), key=lambda w: (w["clears"], w["symbol"], w["kind"]))


def shared(windows: list[dict], accounts: list[str] | None, trade_account: str | None) -> list[dict]:
    if not accounts:
        return windows
    keep = [a.lower().replace(" ", "") for a in accounts] + ([trade_account.lower()] if trade_account else [])
    return [w for w in windows if any(k in w["account"].lower() or w["account"].lower() in k for k in keep)]


def wash_check(symbol: str, side: str, loss: bool, windows: list[dict], upcoming: list[tuple[str, str, float]], today: str) -> tuple[str, str, str | None]:
    if side == "buy":
        same = [w for w in windows if w["kind"] == "loss_sale" and w["symbol"] == symbol]
        if same:
            w = max(same, key=lambda w: w["clears"])
            return "act", f"Buying now washes the ${-w['amount']:,.0f} loss from {w['date']}. Clear on {w['clears']}.", w["clears"]
        near = [w for w in windows if w["kind"] == "loss_sale" and similar(w["symbol"], symbol)]
        if near:
            w = max(near, key=lambda w: w["clears"])
            return "watch", f"{w['symbol']} was sold at a loss on {w['date']} and may count as the same fund. Clear on {w['clears']}.", w["clears"]
        return "ok", "No loss sale of this symbol in the last 30 days.", None
    if not loss:
        return "ok", "This sale is a gain, so wash-sale rules do not apply.", None
    same = [w for w in windows if w["kind"] == "recent_buy" and w["symbol"] == symbol]
    if same:
        w = max(same, key=lambda w: w["clears"])
        return "act", f"Bought on {w['date']} in {w['account']}; a loss sale before {w['clears']} is a wash sale.", w["clears"]
    ahead = [(d, s) for d, s, usd in upcoming if usd > 0 and (s == symbol or similar(s, symbol)) and d <= _clears(today)]
    if ahead:
        d, s = min(ahead)
        return "watch", f"The {d} deposit buys {s}. Route it elsewhere until {_clears(today)} to keep this loss.", _clears(today)
    near = [w for w in windows if w["kind"] == "recent_buy" and similar(w["symbol"], symbol)]
    if near:
        w = max(near, key=lambda w: w["clears"])
        return "watch", f"{w['symbol']} was bought on {w['date']} and may count as the same fund. Clear on {w['clears']}.", w["clears"]
    return "ok", f"No buys of {symbol} in the last 30 days or scheduled in the next 30.", _clears(today)
