import json
import math
import sqlite3
from datetime import date, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine.lab.data import ledger_path
from desk.engine.lab.paper import PAPER_DAYS
from desk.engine.lane import BENCHMARK

EMPTY_NOTE = "No strategies are paper trading yet. The filings lane starts the morning after the first filing is scored."
STATUS_RANK = {"eligible": 0, "paper": 1, "retired": 2}
MIN_DAYS = 20
CALMAR_DAYS = 63
RATIO_KEYS = ("ann_return_pct", "sharpe", "sortino", "max_drawdown_pct", "calmar", "hit_rate")


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _counts(conn: sqlite3.Connection, table: str) -> dict[tuple[str, int], int]:
    if not _has(conn, table):
        return {}
    return {(r[0], r[1]): r[2] for r in conn.execute(f"SELECT strategy_id, version, count(*) FROM {table} GROUP BY strategy_id, version")}


# ---- Reward to risk ----


def ratios(days: list[str], values: list[float]) -> dict | None:
    pairs = [(d, v) for d, v in zip(days, values, strict=True) if v]
    if len(pairs) < MIN_DAYS + 1:
        return None
    vals = [v for _, v in pairs]
    rets = [b / a - 1 for a, b in zip(vals, vals[1:], strict=False)]
    n = len(rets)
    mean = sum(rets) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
    down = math.sqrt(sum(min(0.0, r) ** 2 for r in rets) / n)
    span = (date.fromisoformat(pairs[-1][0]) - date.fromisoformat(pairs[0][0])).days
    ann = (vals[-1] / vals[0]) ** (365.25 / span) - 1 if span >= CALMAR_DAYS else None
    peak, mdd = 0.0, 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {
        "days": len(pairs),
        "ann_return_pct": _r(ann * 100) if ann is not None else None,
        "sharpe": _r(mean / sd * math.sqrt(252)) if sd else None,
        "sortino": _r(mean / down * math.sqrt(252)) if down else None,
        "max_drawdown_pct": _r(mdd * 100),
        "calmar": _r(ann / -mdd) if ann is not None and mdd < 0 else None,
        "hit_rate": _r(sum(1 for r in rets if r > 0) / n),
    }


def _ledgers(conn: sqlite3.Connection) -> dict[tuple[str, int], tuple[list[str], list[float]]]:
    if not _has(conn, "paper_ledger_daily"):
        return {}
    out: dict[tuple[str, int], tuple[list[str], list[float]]] = {}
    for r in conn.execute("SELECT strategy_id, version, date, value FROM paper_ledger_daily ORDER BY date"):
        days, vals = out.setdefault((r[0], r[1]), ([], []))
        days.append(r[2])
        vals.append(r[3])
    return out


def _from_summary(summary: dict) -> dict | None:
    picked = {
        "ann_return_pct": summary.get("ann_return_pct"),
        "sharpe": summary.get("sharpe"),
        "sortino": summary.get("sortino"),
        "max_drawdown_pct": summary.get("mdd_pct"),
        "calmar": summary.get("calmar"),
        "hit_rate": summary.get("hit_rate"),
    }
    if picked["calmar"] is None and picked["ann_return_pct"] is not None and (picked["max_drawdown_pct"] or 0) < 0:
        picked["calmar"] = _r(picked["ann_return_pct"] / -picked["max_drawdown_pct"])
    return picked if any(v is not None for v in picked.values()) else None


def backtests(cfg: Config) -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = ledger_path(cfg)
    if path.exists():
        led = connect(path, readonly=True)
        try:
            for r in led.execute("SELECT strategy_id, version, body FROM lab_results WHERE kind='finalize' ORDER BY version, result_at"):
                hold = json.loads(r["body"]).get("holdout") or {}
                picked = _from_summary(hold)
                if picked:
                    out[f"{r['strategy_id']}@{r['version']}"] = {"source": "lab_holdout", "start": hold.get("start"), "end": hold.get("end")} | picked
        finally:
            led.close()
    if cfg.desk_db.exists():
        conn = connect(cfg.desk_db, readonly=True)
        try:
            row = conn.execute("SELECT body FROM engine_views WHERE name='bands'").fetchone() if _has(conn, "engine_views") else None
        finally:
            conn.close()
        for b in (json.loads(row[0]).get("rows") or []) if row else []:
            bt = b.get("backtest") or {}
            if bt.get("sharpe") is not None:
                pick = {k: bt.get(k) for k in RATIO_KEYS if k != "ann_return_pct"} | {"ann_return_pct": bt.get("cagr_pct")}
                out[b["id"]] = {"source": "bands", "start": bt.get("start"), "end": bt.get("end")} | pick
    return out


def _accounts(conn: sqlite3.Connection, sleeve: float) -> dict[tuple[str, int], dict]:
    if not _has(conn, "paper_ledger_daily"):
        return {}
    out = {}
    for r in conn.execute("SELECT * FROM paper_ledger_daily ORDER BY date"):
        out[(r["strategy_id"], r["version"])] = {
            "as_of": r["date"],
            "sleeve": sleeve,
            "cash": r["cash"],
            "value": r["value"],
            "return_pct": round((r["value"] / sleeve - 1) * 100, 4) if sleeve else None,
        }
    return out


def _r(v):
    return round(v, 4) if v is not None else None


def _reward_risk(ledger: tuple[list[str], list[float]] | None, summary: dict) -> dict:
    got = ratios(*ledger) if ledger else None
    if got:
        return {"source": "sub_ledger"} | got
    record = _from_summary(summary)
    if record:
        return {"source": "forward_record", "days": summary.get("days")} | record
    return {"source": None, "days": len(ledger[0]) if ledger else 0} | dict.fromkeys(RATIO_KEYS)


def build(conn: sqlite3.Connection | None, sleeve: float, tested: dict[str, dict] | None = None) -> dict:
    base = {"as_of": None, "benchmark": BENCHMARK, "gate_days": PAPER_DAYS, "rows": [], "note": EMPTY_NOTE}
    if conn is None or not _has(conn, "paper_portfolios"):
        return base
    trades, opens, accounts = _counts(conn, "paper_trades"), _counts(conn, "paper_positions"), _accounts(conn, sleeve)
    ledgers, tested = _ledgers(conn), tested or {}
    rows = []
    for r in conn.execute("SELECT * FROM paper_portfolios"):
        key = (r["strategy_id"], r["version"])
        summary = json.loads(r["summary"] or "{}")
        excess, own = r["excess_pts"], r["return_pct"]
        bench = summary.get("benchmark_return_pct")
        if bench is None and own is not None and excess is not None:
            bench = own - excess
        days = r["days"]
        waiting = "time" if days < PAPER_DAYS else ("benchmark" if excess is None else None)
        rows.append(
            {
                "id": r["strategy_id"],
                "version": r["version"],
                "name": r["title"],
                "kind": summary.get("kind") if summary.get("kind") in ("lane", "mix") else "strategy",
                "benchmark": summary.get("benchmark") or BENCHMARK,
                "status": r["status"],
                "started": r["started"],
                "as_of": r["as_of"],
                "days_live": days,
                "days_to_eligible": max(0, PAPER_DAYS - days),
                "eligible_on": (date.fromisoformat(r["started"]) + timedelta(days=PAPER_DAYS)).isoformat(),
                "waiting_on": waiting if r["status"] == "paper" else None,
                "return_pct": _r(own),
                "bench_return_pct": _r(bench),
                "excess_pts": _r(excess),
                "max_drawdown_pct": _r(summary.get("mdd_pct")),
                "trades": trades.get(key, 0),
                "open_positions": opens.get(key, 0),
                "account": accounts.get(key),
                "reward_risk": _reward_risk(ledgers.get(key), summary),
                "backtest": tested.get(f"{r['strategy_id']}@{r['version']}") or tested.get(r["strategy_id"]),
            }
        )
    rows.sort(key=lambda x: (STATUS_RANK.get(x["status"], 3), x["excess_pts"] is None, -(x["excess_pts"] or 0), -x["days_live"], x["id"]))
    as_of = max((x["as_of"] for x in rows), default=None)
    return base | {"as_of": as_of, "rows": rows, "note": None if rows else EMPTY_NOTE}
