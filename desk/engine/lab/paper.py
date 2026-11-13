import json
import sqlite3
from datetime import UTC, date, datetime

from desk.config import Config
from desk.db import connect
from desk.engine import gate
from desk.engine.gate import PAPER_DAYS
from desk.engine.lab import stats
from desk.engine.lab.data import data_path, ledger_path, load
from desk.engine.lab.sim import _benchmark, simulate
from desk.engine.lab.spec import SpecError, parse, resolve

__all__ = ["PAPER_DAYS", "run"]
PLAN_BENCHMARK = "Plan mix"


def _family_sizes(rows) -> dict[str, int]:
    parents = {r["id"]: r["parent_id"] for r in rows}

    def root(sid):
        seen = set()
        while parents.get(sid) and sid not in seen:
            seen.add(sid)
            sid = parents[sid]
        return gate.family(sid) or sid

    keys = {r["id"]: root(r["id"]) for r in rows}
    return {sid: sum(1 for r in rows if keys[r["id"]] == key) for sid, key in keys.items()}


def _buys(trades: list[tuple], cut: str) -> int:
    return sum(1 for t in trades if t[2] == "buy" and t[0] <= cut)


def run(cfg: Config, desk: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if not ledger_path(cfg).exists() or not data_path(cfg).exists():
        return {"ok": True, "paper": []}
    led = connect(ledger_path(cfg), readonly=True)
    try:
        rows = led.execute("SELECT * FROM strategies WHERE status='paper'").fetchall()
        finals = {
            (r["strategy_id"], r["version"]): json.loads(r["body"])
            for r in led.execute("SELECT strategy_id, version, body FROM lab_results WHERE kind='finalize' ORDER BY result_at")
        }
    finally:
        led.close()
    data = load(data_path(cfg))
    sizes = _family_sizes(rows)
    done = []
    for row in rows:
        fin = finals.get((row["id"], row["version"]))
        if not fin or not fin.get("paper_start"):
            continue
        try:
            spec = parse(json.loads(row["spec"]), data, model=row["model"] or "")
        except SpecError:
            continue
        start, end = fin["paper_start"], data.end_for(spec.universe.get("kind"))
        res = simulate(data, spec, resolve(spec, fin["params"]), start, end, enter=False)
        summary = stats.summary(res)
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        bench_ret = (res.bench[-1] - 1) * 100 if res.bench and res.bench[-1] else None
        own_ret = (res.values[-1] / res.values[0] - 1) * 100 if res.values else None
        excess = own_ret - bench_ret if own_ret is not None and bench_ret is not None else None
        settled = gate.settle(
            desk,
            spec.id,
            spec.version,
            start,
            res.days,
            res.values,
            res.bench,
            events=lambda cut, trades=res.trades: _buys(trades, cut),
            bars=fin.get("verdict") == "pass",
            family_size=sizes.get(row["id"], 1),
            now=now,
        )
        status = settled["status"]
        mix = _benchmark(data, spec)
        summary |= {"benchmark": next(iter(mix)) if len(mix) == 1 else (PLAN_BENCHMARK if mix else None), "gate": settled["gate"]}
        holdings = {s: n for s, n in res.holdings.items()}
        with desk:
            desk.execute("DELETE FROM paper_trades WHERE strategy_id=? AND version=?", (spec.id, spec.version))
            desk.executemany("INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(spec.id, spec.version, *t) for t in res.trades])
            desk.execute("DELETE FROM paper_positions WHERE strategy_id=? AND version=?", (spec.id, spec.version))
            desk.executemany(
                "INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?)",
                [(spec.id, spec.version, end, s, n, round(n * data.series[s].adj[-1], 2)) for s, n in holdings.items()],
            )
            desk.execute(
                "INSERT OR REPLACE INTO paper_portfolios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    spec.id,
                    spec.version,
                    spec.title,
                    start,
                    end,
                    days,
                    round(res.values[-1], 2) if res.values else None,
                    round(own_ret, 4) if own_ret is not None else None,
                    round(excess, 4) if excess is not None else None,
                    status,
                    json.dumps(summary),
                ),
            )
        done.append({"strategy_id": spec.id, "version": spec.version, "days": days, "status": status})
    return {"ok": True, "paper": done}
