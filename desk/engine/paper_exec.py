import math
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from desk.engine import alpaca, catalog, lane
from desk.engine.market import ProviderError, session
from desk.paper_check import NotPaper, paper_base

BUDGET_ENV = "DESK_PAPER_BUDGET"
KILL_ENV = "DESK_PAPER_EXECUTE"
MAX_ENV = "DESK_PAPER_MAX_STRATEGIES"
DEFAULT_BUDGET = 1000.0
BUDGET_CAP = 5000.0
DEFAULT_MAX = 20
CASH_BUFFER = 1.02
ORDER_DAYS = 30
REBAL_MIN_USD = 25.0
REBAL_SHARE = 0.10
LIVE = ("paper", "eligible")


# ---- Settings ----


def budget() -> float:
    try:
        value = float(os.environ.get(BUDGET_ENV, "") or DEFAULT_BUDGET)
    except ValueError:
        value = DEFAULT_BUDGET
    return max(0.0, min(value, BUDGET_CAP))


def max_strategies() -> int:
    try:
        return max(1, int(os.environ.get(MAX_ENV, "") or DEFAULT_MAX))
    except ValueError:
        return DEFAULT_MAX


def enabled() -> bool:
    return os.environ.get(KILL_ENV, "1").strip() not in ("0", "false", "no", "off")


# ---- Alpaca paper trading API ----


class Broker:
    def __init__(self, http, hdrs: dict):
        self.http, self.hdrs, self.base = http, hdrs, paper_base()

    def _call(self, method: str, path: str, *, params=None, body=None):
        url = paper_base(self.base) + path
        fn = getattr(self.http, method)
        kwargs = {"headers": self.hdrs, "timeout": 30}
        if params is not None:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        res = fn(url, **kwargs)
        if res.status_code in (401, 403) and method != "post":
            raise ProviderError(f"Alpaca paper refused the keys ({res.status_code})")
        if method == "post" and res.status_code >= 300:
            return {"status": "rejected", "message": _message(res)}
        if res.status_code >= 300:
            raise ProviderError(f"Alpaca paper {path} {res.status_code}")
        return res.json()

    def account(self) -> dict:
        return self._call("get", "/v2/account") or {}

    def positions(self) -> dict[str, float]:
        return {str(p["symbol"]).upper(): float(p.get("qty") or 0) for p in self._call("get", "/v2/positions") or []}

    def order(self, body: dict) -> dict:
        return self._call("post", "/v2/orders", body=body) or {}

    def orders(self, after: str) -> list[dict]:
        return self._call("get", "/v2/orders", params={"status": "all", "after": after, "limit": 500, "direction": "desc"}) or []


def _message(res) -> str:
    try:
        body = res.json()
    except ValueError:
        body = {}
    text = str((body or {}).get("message") or f"HTTP {res.status_code}")
    return ("duplicate: " + text) if "client_order_id" in text else text[:200]


def client_id(day: str, symbol: str, side: str) -> str:
    return f"vd-{day}-{symbol}-{side}"[:48]


# ---- Prices ----


def price(conn: sqlite3.Connection, symbol: str) -> float | None:
    for table in ("alpaca_bars", "price_bars"):
        row = conn.execute(f"SELECT close FROM {table} WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
        if row and row[0]:
            return float(row[0])
    row = conn.execute("SELECT value / shares FROM paper_positions WHERE symbol=? AND shares > 0 ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
    return float(row[0]) if row and row[0] else None


def open_on(conn: sqlite3.Connection, symbol: str, day: str) -> float | None:
    for table in ("alpaca_bars", "price_bars"):
        row = conn.execute(f"SELECT coalesce(open, close) FROM {table} WHERE symbol=? AND date=?", (symbol, day)).fetchone()
        if row and row[0]:
            return float(row[0])
    return None


def tradable(conn: sqlite3.Connection) -> set[str] | None:
    rows = conn.execute("SELECT symbol FROM alpaca_assets WHERE tradable=1").fetchall()
    return {r[0] for r in rows} if rows else None


# ---- Sub-ledgers ----


@dataclass
class Book:
    strategy_id: str
    version: int
    kind: str
    status: str
    sleeve: float
    cash: float
    held: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def value(self, px) -> float:
        return self.cash + sum(q * (px(s) or 0.0) for s, q in self.held.items())


def books(conn: sqlite3.Connection, sleeve: float) -> dict[tuple[str, int], Book]:
    out: dict[tuple[str, int], Book] = {}
    lanes = {v.id for v in lane.variants(conn)}
    mixes = {r[0] for r in conn.execute("SELECT DISTINCT id FROM catalog_strategies")}
    for r in conn.execute("SELECT strategy_id, version, status FROM paper_portfolios ORDER BY started, strategy_id"):
        kind = "lane" if r["strategy_id"] in lanes else ("mix" if r["strategy_id"] in mixes else "strategy")
        out[(r["strategy_id"], r["version"])] = Book(r["strategy_id"], r["version"], kind, r["status"], sleeve, sleeve)
    for r in conn.execute("SELECT strategy_id, version, symbol, filled_qty, price FROM paper_legs WHERE filled_qty IS NOT NULL AND price IS NOT NULL"):
        b = out.get((r["strategy_id"], r["version"]))
        if b is None:
            continue
        b.held[r["symbol"]] = b.held.get(r["symbol"], 0.0) + r["filled_qty"]
        b.cash -= r["filled_qty"] * r["price"]
    for b in out.values():
        b.held = {s: round(q, 6) for s, q in b.held.items() if abs(q) > 1e-6}
    return out


# ---- Targets per strategy ----


def lane_wants(conn: sqlite3.Connection, b: Book, spec: lane.LaneSpec, now: datetime, px, ok) -> dict[str, float]:
    if b.status not in LIVE:
        return {}
    want = lane.targets(conn, now, spec)
    out = {s: q for s, q in b.held.items() if s in want}
    slot = b.sleeve / spec.max_names
    cash = b.cash + sum(q * (px(s) or 0) for s, q in b.held.items() if s not in want)
    for sym in sorted(want):
        if sym in out:
            continue
        p = px(sym)
        if not p or (ok is not None and sym not in ok):
            b.skipped.append(sym)
            continue
        qty = math.floor(min(slot, cash / CASH_BUFFER) / p)
        if qty >= 1:
            out[sym] = float(qty)
            cash -= qty * p
    return out


def strategy_wants(conn: sqlite3.Connection, b: Book, px, ok) -> dict[str, float]:
    if b.status not in LIVE:
        return {}
    if b.held and b.kind == "mix" and catalog.is_hold(conn, b.strategy_id, b.version):
        return dict(b.held)
    row = conn.execute("SELECT value FROM paper_portfolios WHERE strategy_id=? AND version=?", (b.strategy_id, b.version)).fetchone()
    pos = conn.execute("SELECT symbol, value FROM paper_positions WHERE strategy_id=? AND version=?", (b.strategy_id, b.version)).fetchall()
    total = (row[0] if row and row[0] else None) or sum(r["value"] or 0 for r in pos)
    if not total:
        return dict(b.held)
    worth = b.value(px)
    out: dict[str, float] = {}
    for r in pos:
        sym, p = r["symbol"], px(r["symbol"])
        if not p or (ok is not None and sym not in ok):
            b.skipped.append(sym)
            continue
        goal = (r["value"] or 0) / total * worth
        qty = float(math.floor(goal / CASH_BUFFER / p))
        have = b.held.get(sym, 0.0)
        if have and abs(qty - have) * p < max(REBAL_MIN_USD, REBAL_SHARE * goal):
            qty = have
        if qty >= 1:
            out[sym] = qty
    return out


def legs_for(b: Book, want: dict[str, float]) -> dict[str, float]:
    out = {}
    for sym in sorted(set(b.held) | set(want)):
        delta = round(want.get(sym, 0.0) - b.held.get(sym, 0.0), 6)
        if abs(delta) > 1e-6:
            out[sym] = delta
    return out


def net_orders(legs: dict[tuple[str, int], dict[str, float]], day: str) -> list[dict]:
    by_symbol: dict[str, float] = defaultdict(float)
    for per in legs.values():
        for sym, q in per.items():
            by_symbol[sym] += q
    out = []
    for sym, q in sorted(by_symbol.items()):
        q = round(q, 6)
        if abs(q) < 1e-6:
            continue
        side = "buy" if q > 0 else "sell"
        qty = f"{abs(q):.6f}".rstrip("0").rstrip(".")
        out.append({"symbol": sym, "side": side, "qty": qty, "type": "market", "time_in_force": "day", "client_order_id": client_id(day, sym, side)})
    return out


def clamp(orders: list[dict], held: dict[str, float]) -> list[dict]:
    out = []
    for o in orders:
        if o["side"] == "sell":
            have = held.get(o["symbol"], 0.0)
            if have <= 0:
                continue
            if float(o["qty"]) > have:
                o = o | {"qty": f"{have:.6f}".rstrip("0").rstrip(".")}
        out.append(o)
    return out


# ---- Fills back into legs ----


def allocate(conn: sqlite3.Connection) -> None:
    legs = defaultdict(list)
    for r in conn.execute("SELECT * FROM paper_legs"):
        legs[(r["date"], r["symbol"])].append(dict(r))
    orders = {(r["date"], r["symbol"]): dict(r) for r in conn.execute("SELECT * FROM paper_orders")}
    updates = []
    for (day, sym), group in legs.items():
        o = orders.get((day, sym))
        buys = sum(g["qty"] for g in group if g["qty"] > 0)
        sells = -sum(g["qty"] for g in group if g["qty"] < 0)
        crossed = min(buys, sells)
        if o is None:
            p = open_on(conn, sym, day)
            for g in group:
                updates.append((g["qty"] if p else None, p, "crossed" if p else "waiting", day, g["strategy_id"], g["version"], sym))
            continue
        filled = o["filled_qty"] or 0.0
        p = o["filled_avg_price"] or (open_on(conn, sym, day) if crossed else None)
        same, other = (buys, sells) if o["side"] == "buy" else (sells, buys)
        share = (crossed + filled) / same if same else 0.0
        for g in group:
            is_same = (g["qty"] > 0) == (o["side"] == "buy")
            got = g["qty"] * share if is_same else g["qty"]
            known = p is not None and (filled or not is_same)
            updates.append((round(got, 6) if known else None, p if known else None, o["status"], day, g["strategy_id"], g["version"], sym))
    with conn:
        conn.executemany("UPDATE paper_legs SET filled_qty=?, price=?, status=? WHERE date=? AND strategy_id=? AND version=? AND symbol=?", updates)


def reconcile(conn: sqlite3.Connection, broker: Broker, now: datetime) -> int:
    after = (now - timedelta(days=ORDER_DAYS)).isoformat(timespec="seconds")
    ours = {r[0] for r in conn.execute("SELECT client_order_id FROM paper_orders")}
    n = 0
    with conn:
        for o in broker.orders(after):
            cid = str(o.get("client_order_id") or "")
            if cid not in ours:
                continue
            n += conn.execute(
                "UPDATE paper_orders SET status=?, filled_qty=?, filled_avg_price=?, filled_at=?, alpaca_id=coalesce(alpaca_id, ?), updated_at=? "
                "WHERE client_order_id=?",
                (
                    o.get("status"),
                    float(o["filled_qty"]) if o.get("filled_qty") else None,
                    float(o["filled_avg_price"]) if o.get("filled_avg_price") else None,
                    o.get("filled_at"),
                    o.get("id"),
                    now.isoformat(timespec="seconds"),
                    cid,
                ),
            ).rowcount
    allocate(conn)
    return n


def mark(conn: sqlite3.Connection, all_books: dict[tuple[str, int], Book], day: str, px) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO paper_ledger_daily VALUES (?, ?, ?, ?, ?, ?)",
            [
                (b.strategy_id, b.version, day, round(b.cash, 2), round(b.value(px) - b.cash, 2), round(b.value(px), 2))
                for b in all_books.values()
                if b.held or b.cash != b.sleeve
            ],
        )


# ---- Run ----


def place(conn: sqlite3.Connection, broker: Broker, day: str, now: datetime, all_books: dict[tuple[str, int], Book], px) -> tuple[list[dict], dict]:
    specs = {(v.id, v.version): v for v in lane.variants(conn)}
    ok = tradable(conn)
    active = [b for b in all_books.values() if b.status in LIVE or b.held][: max_strategies()]
    legs: dict[tuple[str, int], dict[str, float]] = {}
    for b in active:
        key = (b.strategy_id, b.version)
        want = lane_wants(conn, b, specs[key], now, px, ok) if key in specs else strategy_wants(conn, b, px, ok)
        per = legs_for(b, want)
        if per:
            legs[key] = per
    orders = clamp(net_orders(legs, day), broker.positions())
    stamp = now.isoformat(timespec="seconds")
    placed = []
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO paper_legs (date, strategy_id, version, symbol, qty, status) VALUES (?, ?, ?, ?, ?, 'planned')",
            [(day, sid, ver, sym, q) for (sid, ver), per in legs.items() for sym, q in per.items()],
        )
        for o in orders:
            sent = broker.order(o)
            status = str(sent.get("status") or "new")
            conn.execute(
                "INSERT OR IGNORE INTO paper_orders (client_order_id, date, symbol, side, qty, status, submitted_at, updated_at, alpaca_id, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (o["client_order_id"], day, o["symbol"], o["side"], float(o["qty"]), status, stamp, stamp, sent.get("id"), sent.get("message")),
            )
            conn.execute("UPDATE paper_legs SET client_order_id=? WHERE date=? AND symbol=?", (o["client_order_id"], day, o["symbol"]))
            placed.append({"symbol": o["symbol"], "side": o["side"], "qty": o["qty"], "status": status, "message": sent.get("message")})
    skipped = {f"{b.strategy_id}@{b.version}": sorted(set(b.skipped)) for b in active if b.skipped}
    return placed, {"strategies": len(active), "legs": sum(len(p) for p in legs.values()), "skipped": skipped}


def run(conn: sqlite3.Connection, http, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    hdrs = alpaca.headers()
    if hdrs is None:
        return {"ok": True, "skipped": "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set"}
    try:
        broker = Broker(http, hdrs)
        account = broker.account()
        if not str(account.get("account_number") or "").startswith("PA"):
            return {"ok": False, "error": "refused: the account isn't an Alpaca paper account (number doesn't start with PA)"}
        built = lane.rebuild(conn)
        s = session(now)
        cache: dict[str, float | None] = {}

        def px(sym: str) -> float | None:
            if sym not in cache:
                cache[sym] = price(conn, sym)
            return cache[sym]

        mixes = catalog.rebuild(conn, budget(), px, now=now)

        placed: list[dict] = []
        info: dict = {}
        already = conn.execute("SELECT 1 FROM paper_legs WHERE date=? LIMIT 1", (s.day,)).fetchone() is not None
        if s.state == "pre" and enabled() and not already:
            placed, info = place(conn, broker, s.day, now, books(conn, budget()), px)
        synced = reconcile(conn, broker, now)
        all_books = books(conn, budget())
        mark(conn, all_books, s.day, px)
    except (ProviderError, NotPaper) as e:
        return {"ok": False, "error": str(e)}
    note = None
    if not enabled():
        note = f"{KILL_ENV}=0, so no orders were sent"
    elif already and s.state == "pre":
        note = f"orders for {s.day} were already placed"
    return {
        "ok": True,
        "session": s.state,
        "lane": built,
        "catalog": mixes,
        "orders": placed,
        "reconciled": synced,
        "budget": budget(),
        "books": len(all_books),
        "note": note,
        **({"plan": info} if info else {}),
    }
