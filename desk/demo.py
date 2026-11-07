import argparse
import json
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from desk.config import Config
from desk.mirror.firestore import Row
from desk.mirror.store import MirrorStore

# ---- The synthetic world ----

SYMBOLS = {
    "FXAIX": {"start": 170.0, "drift": 0.10, "vol": 0.16, "yield": 0.013, "name": "Synthetic 500 Index Fund"},
    "FTEC": {"start": 140.0, "drift": 0.14, "vol": 0.26, "yield": 0.006, "name": "Synthetic Tech Index ETF"},
    "VXUS": {"start": 58.0, "drift": 0.06, "vol": 0.15, "yield": 0.030, "name": "Synthetic International ETF"},
    "BND": {"start": 72.0, "drift": 0.02, "vol": 0.05, "yield": 0.035, "name": "Synthetic Bond ETF"},
    "ACME": {"start": 25.0, "drift": 0.05, "vol": 0.55, "yield": 0.0, "name": "Acme Rockets Inc"},
}
CASH = "SPAXX"
PLAN_MIX = {"FXAIX": 0.60, "FTEC": 0.20, "VXUS": 0.15, "BND": 0.05}
ACCOUNTS = {
    "individual-0001": {"kind": "individual", "name": "Individual", "last4": "0001"},
    "hsa-0002": {"kind": "hsa", "name": "Health Savings Account", "last4": "0002"},
}
MONTHLY = {"individual-0001": 500.0, "hsa-0002": 100.0}
MERCHANTS = [
    ("Orbit Grocery", "Groceries", 60, 160),
    ("Comet Coffee", "Dining", 4, 14),
    ("Launchpad Fuel", "Transportation", 30, 60),
    ("Nebula Streaming", "Subscriptions", 12, 12),
    ("Apogee Power Co", "Utilities", 80, 140),
    ("Starboard Rent", "Housing", 1400, 1400),
]


def doc_id(key) -> str:
    return quote(json.dumps(key, separators=(",", ":")), safe="")


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def r2(x: float) -> float:
    return round(x + 0.0, 2)


def r6(x: float) -> float:
    return round(x + 0.0, 6)


def stamp(d: date, hour: int = 21) -> str:
    return datetime(d.year, d.month, d.day, hour, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Book:
    shares: dict = field(default_factory=lambda: defaultdict(float))
    cost: dict = field(default_factory=lambda: defaultdict(float))
    cash: dict = field(default_factory=lambda: defaultdict(float))


def price_paths(days: list[date], rng: random.Random) -> dict[str, dict[date, float]]:
    paths = {}
    for sym, s in SYMBOLS.items():
        p, out = s["start"], {}
        dt = 1 / 252
        for d in days:
            shock = rng.gauss(0, 1)
            if sym == "ACME" and rng.random() < 0.01:
                shock -= 6
            p *= math.exp((s["drift"] - s["vol"] ** 2 / 2) * dt + s["vol"] * math.sqrt(dt) * shock)
            out[d] = round(p, 2)
        paths[sym] = out
    return paths


# ---- Building the mirror ----


def ensure_demo(cfg: Config) -> Config:
    marker = cfg.data_dir / "demo-built"
    today = date.today().isoformat()
    if not cfg.mirror_db.exists() or not marker.exists() or marker.read_text() != today:
        build_demo_mirror(cfg.mirror_db)
        marker.write_text(today)
    return cfg


def build_demo_mirror(path: Path, *, today: date | None = None, years: int = 2, seed: int = 7) -> Path:
    today = today or date.today()
    rng = random.Random(seed)  # noqa: S311
    start = today - timedelta(days=365 * years)
    days = business_days(start, today)
    prices = price_paths(days, rng)
    book = Book()
    weeks: dict[date, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    snap_id = pos_id = txn_id = 0
    first_month = days[0].replace(day=1)
    acme_sold = False

    def week_of(d: date) -> date:
        return d + timedelta(days=(4 - d.weekday()) % 7)

    def add(tbl: str, key, row: dict, d: date) -> None:
        weeks[week_of(d)][tbl].append(Row(id=doc_id(key), json=json.dumps(row, separators=(",", ":")), at=stamp(d)))

    def activity(d: date, acct: str, kind: str, action: str, amount: float, symbol=None, qty=None, price=None, n=1) -> None:
        key = f"{d.isoformat()}-{kind}-{acct}-{symbol or 'cash'}-{n}"
        a = ACCOUNTS[acct]
        add(
            "activity",
            key,
            {
                "key": key,
                "date": d.isoformat(),
                "settle": (d + timedelta(days=1)).isoformat(),
                "accountKey": acct,
                "accountKind": a["kind"],
                "accountName": a["name"],
                "kind": kind,
                "action": action,
                "symbol": symbol,
                "description": SYMBOLS.get(symbol, {}).get("name") if symbol else None,
                "quantity": qty,
                "price": price,
                "fees": 0,
                "amount": r2(amount),
                "core": symbol == CASH,
            },
            d,
        )

    def buy(d: date, acct: str, sym: str, dollars: float, kind: str = "buy") -> None:
        px = prices[sym][d]
        qty = r6(dollars / px)
        book.shares[(acct, sym)] += qty
        book.cost[(acct, sym)] += dollars
        book.cash[acct] -= dollars
        action = f"YOU BOUGHT {SYMBOLS[sym]['name'].upper()} ({sym})" if kind == "buy" else f"REINVESTMENT {sym}"
        activity(d, acct, kind, action, -dollars, sym, qty, px)

    month_seen: set[tuple[int, int]] = set()
    for d in days:
        ym = (d.year, d.month)
        if ym not in month_seen:
            month_seen.add(ym)
            for acct, amt in MONTHLY.items():
                book.cash[acct] += amt
                activity(d, acct, "deposit", "CONTRIBUTION" if acct.startswith("hsa") else "EFT RECEIVED", amt)
                for sym, w in PLAN_MIX.items():
                    buy(d, acct, sym, r2(amt * w))
            if len(month_seen) == 2:
                book.cash["individual-0001"] += 1000
                activity(d, "individual-0001", "deposit", "EFT RECEIVED", 1000, n=2)
                buy(d, "individual-0001", "ACME", 1000)
            if d.month in (3, 6, 9, 12):
                for (acct, sym), qty in list(book.shares.items()):
                    y = SYMBOLS[sym]["yield"]
                    if not y or qty <= 0:
                        continue
                    div = r2(qty * prices[sym][d] * y / 4)
                    if div < 0.01:
                        continue
                    book.cash[acct] += div
                    activity(d, acct, "dividend", f"DIVIDEND RECEIVED {sym}", div, sym)
                    buy(d, acct, sym, div, kind="reinvest")
        if not acme_sold and d >= today - timedelta(days=120):
            acct, qty = "individual-0001", book.shares[("individual-0001", "ACME")]
            half = r6(qty / 2)
            px = prices["ACME"][d]
            proceeds = r2(half * px)
            book.cost[(acct, "ACME")] *= 0.5
            book.shares[(acct, "ACME")] -= half
            book.cash[acct] += proceeds
            activity(d, acct, "sell", "YOU SOLD ACME ROCKETS INC (ACME)", proceeds, "ACME", -half, px)
            acme_sold = True
        if d.weekday() == 4 or d == days[-1]:
            snap_id += 1
            positions, accounts = [], {}
            for acct in ACCOUNTS:
                total = 0.0
                for sym in SYMBOLS:
                    qty = book.shares.get((acct, sym), 0.0)
                    if qty <= 1e-9:
                        continue
                    value = r2(qty * prices[sym][d])
                    total += value
                    pos_id += 1
                    positions.append(
                        {
                            "id": pos_id,
                            "snapshotId": snap_id,
                            "accountKey": acct,
                            "symbol": sym,
                            "description": SYMBOLS[sym]["name"],
                            "quantity": r6(qty),
                            "lastPrice": prices[sym][d],
                            "value": value,
                            "cost": r2(book.cost[(acct, sym)]),
                            "isCash": False,
                            "lots": [{"type": "Cash", "quantity": r6(qty), "value": value, "cost": r2(book.cost[(acct, sym)])}],
                        }
                    )
                cash = r2(max(book.cash[acct], 0))
                if cash > 0:
                    pos_id += 1
                    total += cash
                    positions.append(
                        {
                            "id": pos_id,
                            "snapshotId": snap_id,
                            "accountKey": acct,
                            "symbol": CASH,
                            "description": "Synthetic Money Market",
                            "quantity": cash,
                            "lastPrice": 1,
                            "value": cash,
                            "cost": None,
                            "isCash": True,
                            "lots": [],
                        }
                    )
                accounts[acct] = {"key": acct, **ACCOUNTS[acct], "value": r2(total)}
            as_of = f"{d.isoformat()}T16:00"
            for p in positions:
                add("positions", p["id"], p, d)
            add(
                "snapshots",
                snap_id,
                {
                    "id": snap_id,
                    "asOf": as_of,
                    "asOfSource": "sync",
                    "importedAt": stamp(d),
                    "fileName": None,
                    "accounts": list(accounts.values()),
                    "lotCount": len(positions),
                    "positionCount": len(positions),
                    "total": r2(sum(a["value"] for a in accounts.values())),
                },
                d,
            )

    # ---- Bank side: pay, spending ----
    pay = first_month
    while pay <= today:
        for day in (1, 15):
            pd = pay.replace(day=day)
            if pd > today or pd < days[0]:
                continue
            key = f"stub-{pd.isoformat()}"
            add(
                "paystubs",
                key,
                {
                    "key": key,
                    "payDate": pd.isoformat(),
                    "periodStart": (pd - timedelta(days=14)).isoformat(),
                    "periodEnd": (pd - timedelta(days=1)).isoformat(),
                    "employer": "Synthetic Space Co",
                    "totals": {"gross": 4000.0, "pretax": 480.0, "taxes": 820.0, "post": 50.0, "net": 2650.0},
                    "importedAt": stamp(pd),
                },
                pd,
            )
            txn_id += 1
            add(
                "transactions",
                txn_id,
                {
                    "id": txn_id,
                    "date": pd.isoformat(),
                    "month": pd.isoformat()[:7],
                    "account": "Checking",
                    "merchant": "Synthetic Space Co Payroll",
                    "category": "Paycheck",
                    "kind": "income",
                    "amount": 2650.0,
                },
                pd,
            )
        pay = (pay.replace(day=28) + timedelta(days=4)).replace(day=1)
    firsts = {(d.year, d.month): d for d in reversed(days)}
    chances = {"Groceries": 0.25, "Dining": 0.35, "Transportation": 0.15, "Subscriptions": 0.05, "Utilities": 0.05}
    for d in days:
        for merchant, category, lo, hi in MERCHANTS:
            if category == "Housing":
                chance = 1.0 if firsts[(d.year, d.month)] == d else 0.0
            else:
                chance = chances[category]
            if rng.random() >= chance:
                continue
            txn_id += 1
            add(
                "transactions",
                txn_id,
                {
                    "id": txn_id,
                    "date": d.isoformat(),
                    "month": d.isoformat()[:7],
                    "account": "Card",
                    "merchant": merchant,
                    "category": category,
                    "kind": "spend",
                    "amount": -r2(rng.uniform(lo, hi)),
                },
                d,
            )

    # ---- Plan and prices ----
    months = []
    m = today.replace(day=1)
    for _ in range(6):
        months.append({"month": m.isoformat()[:7], "contribution": 500, "buys": {s: r2(500 * w) for s, w in PLAN_MIX.items()}})
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    plan = {
        "version": 1,
        "funds": [{"ticker": s, "sleeve": "core" if s != "FTEC" else "tilt", "target_weight": w} for s, w in PLAN_MIX.items()],
        "monthly_plan": months,
        "one_time_actions": [],
    }
    plan_day = days[0]
    add("plans", 1, {"id": 1, "plan": plan, "fileName": "synthetic-plan.json", "loadedAt": stamp(plan_day)}, plan_day)

    last = days[-1]
    quotes = {
        s: {"price": prices[s][last], "prevClose": prices[s][days[-2]], "at": stamp(last, 20), "source": "demo", "fetchedAt": stamp(last)} for s in SYMBOLS
    }
    ranges = {s: {"from": days[0].isoformat(), "first": days[0].isoformat(), "to": last.isoformat(), "fetchedAt": stamp(last), "error": None} for s in SYMBOLS}
    final: dict[str, list[Row]] = defaultdict(list)
    final["prices"].append(Row(id="board", json=json.dumps({"quotes": quotes, "ranges": ranges, "triedAt": stamp(last)}), at=stamp(last)))
    for sym in SYMBOLS:
        for year in sorted({d.year for d in days}):
            rows = [[d.isoformat(), prices[sym][d], prices[sym][d]] for d in days if d.year == year]
            final["priceCloses"].append(Row(id=f"{sym}_{year}", json=json.dumps({"symbol": sym, "year": year, "rows": rows}), at=stamp(last)))
        profile = {"symbol": sym, "name": SYMBOLS[sym]["name"], "kind": "stock" if sym == "ACME" else "fund", "fetchedAt": stamp(last)}
        final["priceProfiles"].append(Row(id=sym, json=json.dumps(profile), at=stamp(last)))

    # ---- Replaying the pulls ----
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    store = MirrorStore(path)
    try:
        seen: dict[str, list[Row]] = defaultdict(list)
        for week in sorted(weeks):
            delta = weeks[week]
            for tbl, rows in delta.items():
                seen[tbl].extend(rows)
            store.apply({}, delta, stamp=datetime(week.year, week.month, week.day, 22, tzinfo=UTC).isoformat(timespec="seconds"))
        for tbl, rows in final.items():
            seen[tbl].extend(rows)
        store.apply(dict(seen), stamp=datetime.now(UTC).isoformat(timespec="seconds"))
        run = store.start_run()
        store.finish_run(run, ok=True, tables=len(seen), full_tables=len(seen), rows=sum(store.counts().values()), read=0, changed=0, skipped=0, seconds=0)
    finally:
        store.close()
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m desk.demo", description="Write a synthetic mirror.db: two years of made-up holdings, activity, pay and prices."
    )
    parser.add_argument("out", help="where to write mirror.db")
    parser.add_argument("--today", default=None, help="YYYY-MM-DD, default today")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else None
    path = build_demo_mirror(Path(args.out), today=today, seed=args.seed)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
