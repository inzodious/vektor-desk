import json
import sqlite3
from datetime import UTC, date, datetime

from desk.engine import backfill, gate
from desk.engine.lane import drawdown_pct, entry_session

BENCHMARK = "IVV"
DIP_CASH = 0.20
DIP_STEPS = (0.05, 0.10, 0.20)
TECH_TILT = {"IVV": 0.50, "FTEC": 0.30, "SMH": 0.10, "VXUS": 0.10}
REVERSION_PTS = 0.5
FALLBACK = "IVV"
PROXIES = {
    "FXAIX": "IVV",
    "FUSEX": "IVV",
    "SWPPX": "IVV",
    "VFIAX": "VOO",
    "VFINX": "VOO",
    "FSKAX": "ITOT",
    "FZROX": "ITOT",
    "VTSAX": "VTI",
    "SWTSX": "SCHB",
    "FTIHX": "VXUS",
    "FZILX": "VXUS",
    "FSPSX": "IEFA",
    "VTIAX": "VXUS",
    "SWISX": "SCHF",
    "FXNAX": "AGG",
    "FUAMX": "IEF",
    "VBTLX": "BND",
    "VBMFX": "BND",
    "SWAGX": "SCHZ",
    "FSMDX": "IJH",
    "FSSNX": "IJR",
    "VIMAX": "VO",
    "VSMAX": "VB",
    "FSELX": "SOXX",
    "FSPTX": "VGT",
}
ENTRIES = (
    {
        "id": "safe-mix",
        "name": "Safe mix",
        "hypothesis": "The plan's fund weights, rebalanced when a fund drifts, is the steady way to compound deposits.",
    },
    {
        "id": "as-held",
        "name": "As held",
        "hypothesis": "Your book as it stands, ASTS kept, followed each day so the other mixes have a real yardstick.",
    },
    {
        "id": "tech-tilt",
        "name": "Aggressive tech tilt",
        "hypothesis": "Half S&P 500, 30% FTEC, 10% SMH and 10% VXUS earns more than the safe mix and swings harder.",
    },
    {
        "id": "dip-buy",
        "name": "Dip-buy",
        "hypothesis": "The safe mix holding 20% cash, a third deployed at each 5, 10 and 20% S&P 500 drop from its high, back to 20% cash at a new high.",
    },
)
NAMES = {e["id"]: e["name"] for e in ENTRIES}


# ---- Proxies ----


def proxy(symbol: str) -> str:
    return PROXIES.get(symbol.upper(), symbol.upper())


def _mutual_fund(symbol: str, kind: str | None) -> bool:
    return kind == "mutual_fund" or (len(symbol) == 5 and symbol.endswith("X"))


def proxied(weights: dict[str, float], kinds: dict[str, str] | None = None) -> tuple[dict[str, float], list[str]]:
    out: dict[str, float] = {}
    notes = []
    for sym, w in sorted(weights.items()):
        if w <= 0:
            continue
        p = proxy(sym)
        kind = (kinds or {}).get(sym)
        if p == sym and (kind == "unknown" or _mutual_fund(sym, kind)):
            p = FALLBACK
            notes.append(f"{sym} has no ETF twin, so it trades as {FALLBACK}")
        elif p != sym:
            notes.append(f"{sym} trades as {p}")
        out[p] = out.get(p, 0.0) + w
    total = sum(out.values())
    return ({s: round(w / total, 6) for s, w in out.items()} if total else {}), notes


# ---- Mixes ----


def mixes(plan_targets: dict[str, float], held: dict[str, float], cash: float, kinds: dict[str, str] | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if plan_targets:
        w, notes = proxied(plan_targets, kinds)
        out["safe-mix"] = {"weights": w, "cash": 0.0, "notes": notes, "source": dict(plan_targets)}
        out["dip-buy"] = {"weights": w, "cash": DIP_CASH, "notes": notes, "source": dict(plan_targets), "steps": list(DIP_STEPS)}
    if held:
        w, notes = proxied(held, kinds)
        out["as-held"] = {"weights": w, "cash": round(max(0.0, min(1.0, cash)), 6), "notes": notes, "source": {s: round(v, 6) for s, v in held.items()}}
    out["tech-tilt"] = {"weights": dict(TECH_TILT), "cash": 0.0, "notes": [], "source": dict(TECH_TILT)}
    return {k: out[k] for k in NAMES if k in out}


def held_mix(rows: list[dict]) -> tuple[dict[str, float], float, list[str]]:
    gross = sum(h["value"] for h in rows if not h["is_cash"] and h["value"] > 0)
    cash = sum(h["value"] for h in rows if h["is_cash"])
    notes = []
    if cash < 0:
        notes.append("The margin debit is left out; the mix is your positions at full size")
        cash = 0.0
    total = gross + cash
    if not total:
        return {}, 0.0, notes
    w: dict[str, float] = {}
    for h in rows:
        if not h["is_cash"] and h["value"] > 0:
            w[h["symbol"]] = w.get(h["symbol"], 0.0) + h["value"] / gross
    return w, cash / total, notes


class Dip:
    def __init__(self, cash: float = DIP_CASH, steps: tuple[float, ...] = DIP_STEPS):
        self.base, self.steps = cash, steps
        self.peak = 0.0
        self.used = 0

    def step(self, level: float) -> float:
        if level >= self.peak:
            self.peak, self.used = level, 0
        else:
            dd = 1 - level / self.peak
            self.used = max(self.used, sum(1 for s in self.steps if dd >= s - 1e-9))
        return self.cash()

    def cash(self) -> float:
        return self.base * (1 - self.used / len(self.steps))


def dip_cash(closes: list[float]) -> float:
    d = Dip()
    for c in closes:
        if c:
            d.step(c)
    return d.cash()


# ---- Registry ----


def _differs(a: dict, b: dict) -> bool:
    keys = set(a["weights"]) | set(b["weights"])
    moved = any(abs(a["weights"].get(k, 0.0) - b["weights"].get(k, 0.0)) * 100 > REVERSION_PTS for k in keys)
    return moved or abs(a.get("cash", 0.0) - b.get("cash", 0.0)) * 100 > REVERSION_PTS


def latest(conn: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in conn.execute("SELECT * FROM catalog_strategies ORDER BY id, version"):
        out[r["id"]] = dict(r) | {"mix": json.loads(r["mix"])}
    return out


def sync(conn: sqlite3.Connection, wanted: dict[str, dict], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    stamp = now.isoformat(timespec="seconds")
    have = latest(conn)
    made = []
    with conn:
        for sid, mix in wanted.items():
            cur = have.get(sid)
            if cur and cur["retired_at"] is None and (sid == "as-held" or not _differs(cur["mix"], mix)):
                if sid == "as-held":
                    conn.execute("UPDATE catalog_strategies SET mix=? WHERE id=? AND version=?", (json.dumps(mix), sid, cur["version"]))
                continue
            version = cur["version"] + 1 if cur else 1
            if cur and cur["retired_at"] is None:
                conn.execute("UPDATE catalog_strategies SET retired_at=? WHERE id=? AND version=?", (stamp, sid, cur["version"]))
            conn.execute("INSERT INTO catalog_strategies VALUES (?, ?, ?, ?, ?, NULL)", (sid, version, NAMES[sid], json.dumps(mix), stamp))
            made.append(f"{sid}@{version}")
    symbols = sorted({s for m in wanted.values() for s in m["weights"]} | {BENCHMARK})
    backfill.add_symbols(conn, symbols, "plan", now=now)
    return {"registered": made, "symbols": symbols}


# ---- Paper record ----


def _closes(conn: sqlite3.Connection, symbol: str) -> list[tuple[str, float]]:
    rows = conn.execute("SELECT date, coalesce(adj_close, close) FROM price_bars WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
    if not rows:
        rows = conn.execute("SELECT date, close FROM alpaca_bars WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
    return [(r[0], float(r[1])) for r in rows if r[1]]


def _at(series: list[tuple[str, float]], day: str) -> float | None:
    hit = [p for d, p in series if d <= day]
    return hit[-1] if hit else None


def targets(conn: sqlite3.Connection, mix: dict) -> dict[str, float]:
    cash = mix.get("cash", 0.0)
    if mix.get("steps"):
        cash = dip_cash([p for _, p in _closes(conn, BENCHMARK)])
    return {s: round(w * (1 - cash), 6) for s, w in mix["weights"].items()}


def rebuild(conn: sqlite3.Connection, sleeve: float, px, *, now: datetime | None = None) -> list[dict]:
    if not conn.execute("SELECT 1 FROM catalog_strategies LIMIT 1").fetchone():
        return []
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    bench = _closes(conn, BENCHMARK)
    out = []
    for r in conn.execute("SELECT * FROM catalog_strategies ORDER BY id, version").fetchall():
        sid, ver = r["id"], r["version"]
        mix = json.loads(r["mix"])
        started = entry_session(datetime.fromisoformat(r["registered_at"])).isoformat()
        ledger = conn.execute("SELECT date, value FROM paper_ledger_daily WHERE strategy_id=? AND version=? ORDER BY date", (sid, ver)).fetchall()
        as_of = ledger[-1][0] if ledger else max(started, today)
        value = ledger[-1][1] if ledger else sleeve
        days = max(0, (date.fromisoformat(as_of) - date.fromisoformat(started)).days)
        own = (value / sleeve - 1) * 100 if sleeve else None
        b0, b1 = _at(bench, started), _at(bench, as_of)
        bench_ret = (b1 / b0 - 1) * 100 if b0 and b1 and as_of > started else None
        excess = own - bench_ret if own is not None and bench_ret is not None else None
        settled = None
        if not r["retired_at"]:
            track = [(started, float(sleeve))] + [(d, v) for d, v in ledger if d > started]
            settled = gate.settle(conn, sid, ver, started, [d for d, _ in track], [v for _, v in track], [_at(bench, d) for d, _ in track], now=now)
        status = settled["status"] if settled else "retired"
        want = targets(conn, mix) if status != "retired" else {}
        summary = {
            "kind": "mix",
            "hypothesis": next(e["hypothesis"] for e in ENTRIES if e["id"] == sid),
            "weights": mix["weights"],
            "cash_target": round(1 - sum(want.values()), 6) if want else None,
            "notes": mix.get("notes") or [],
            "benchmark": BENCHMARK,
            "benchmark_return_pct": round(bench_ret, 4) if bench_ret is not None else None,
            "mdd_pct": drawdown_pct([v for _, v in ledger]) if ledger else 0.0,
            "forward_only": True,
            "gate": settled["gate"] if settled else None,
        }
        with conn:
            conn.execute("DELETE FROM paper_positions WHERE strategy_id=? AND version=?", (sid, ver))
            rows = []
            for sym, w in sorted(want.items()):
                p = px(sym)
                if p:
                    rows.append((sid, ver, as_of, sym, round(value * w / p, 6), round(value * w, 2)))
            conn.executemany("INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?)", rows)
            conn.execute(
                "INSERT OR REPLACE INTO paper_portfolios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    ver,
                    NAMES[sid],
                    started,
                    as_of,
                    days,
                    round(value, 2),
                    round(own, 4) if own is not None else None,
                    round(excess, 4) if excess is not None else None,
                    status,
                    json.dumps(summary),
                ),
            )
        out.append({"strategy_id": sid, "version": ver, "status": status, "started": started, "targets": len(rows)})
    return out


def is_catalog(conn: sqlite3.Connection, strategy_id: str) -> bool:
    return strategy_id in NAMES and conn.execute("SELECT 1 FROM catalog_strategies WHERE id=? LIMIT 1", (strategy_id,)).fetchone() is not None
