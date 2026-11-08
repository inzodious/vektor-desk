import json
import sqlite3
from datetime import date, timedelta

from desk.engine.lab.paper import PAPER_DAYS
from desk.engine.lane import BENCHMARK

EMPTY_NOTE = "No strategies are paper trading yet. The filings lane starts the morning after the first filing is scored."
STATUS_RANK = {"eligible": 0, "paper": 1, "retired": 2}


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _counts(conn: sqlite3.Connection, table: str) -> dict[tuple[str, int], int]:
    if not _has(conn, table):
        return {}
    return {(r[0], r[1]): r[2] for r in conn.execute(f"SELECT strategy_id, version, count(*) FROM {table} GROUP BY strategy_id, version")}


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


def build(conn: sqlite3.Connection | None, sleeve: float) -> dict:
    base = {"as_of": None, "benchmark": BENCHMARK, "gate_days": PAPER_DAYS, "rows": [], "note": EMPTY_NOTE}
    if conn is None or not _has(conn, "paper_portfolios"):
        return base
    trades, opens, accounts = _counts(conn, "paper_trades"), _counts(conn, "paper_positions"), _accounts(conn, sleeve)
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
            }
        )
    rows.sort(key=lambda x: (STATUS_RANK.get(x["status"], 3), x["excess_pts"] is None, -(x["excess_pts"] or 0), -x["days_live"], x["id"]))
    as_of = max((x["as_of"] for x in rows), default=None)
    return base | {"as_of": as_of, "rows": rows, "note": None if rows else EMPTY_NOTE}
