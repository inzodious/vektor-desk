import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk.api.deps import get_cfg
from desk.config import Config
from desk.db import connect
from desk.engine.lots import current_lots

router = APIRouter(prefix="/api/engine", tags=["engine"])

QUALITY_ORDER = ("ok", "trimmed", "pro_forma", "modelled", "mismatch", "stale", "insufficient_history")


def worst(qualities) -> str:
    rank = {q: i for i, q in enumerate(QUALITY_ORDER)}
    return max(qualities, key=lambda q: rank.get(q, len(rank)), default="insufficient_history")


def _open(cfg: Config) -> sqlite3.Connection | None:
    if not cfg.desk_db.exists():
        return None
    conn = connect(cfg.desk_db, readonly=True)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='holdings_daily'").fetchone() is None:
        conn.close()
        return None
    return conn


def _json(body: dict) -> JSONResponse:
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/holdings")
def holdings(request: Request, date: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None:
        return _json({"date": None, "quality": "insufficient_history", "rows": []})
    try:
        day = date or (conn.execute("SELECT max(date) FROM holdings_daily").fetchone()[0])
        if date:
            day = conn.execute("SELECT max(date) FROM holdings_daily WHERE date <= ?", (date,)).fetchone()[0]
        rows = [dict(r) for r in conn.execute("SELECT * FROM holdings_daily WHERE date=? ORDER BY value DESC", (day,))] if day else []
    finally:
        conn.close()
    return _json(
        {
            "date": day,
            "quality": worst(r["quality"] for r in rows),
            "value": round(sum(r["value"] for r in rows), 2),
            "rows": rows,
        }
    )


@router.get("/value")
def value(request: Request, start: str | None = None, end: str | None = None, account: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None:
        return _json({"series": []})
    where, args = ["1=1"], []
    if start:
        where.append("date >= ?")
        args.append(start)
    if end:
        where.append("date <= ?")
        args.append(end)
    if account:
        where.append("account = ?")
        args.append(account)
    try:
        rows = conn.execute(
            "SELECT date, round(sum(value), 2) AS value, group_concat(DISTINCT quality) AS q, max(source) AS source "
            f"FROM holdings_daily WHERE {' AND '.join(where)} GROUP BY date ORDER BY date",
            args,
        ).fetchall()
    finally:
        conn.close()
    return _json({"series": [{"date": r["date"], "value": r["value"], "source": r["source"], "quality": worst((r["q"] or "").split(","))} for r in rows]})


@router.get("/lots")
def lots(request: Request, symbol: str | None = None, account: str | None = None) -> JSONResponse:
    cfg = get_cfg(request)
    if not cfg.desk_db.exists():
        return _json({"lots": [], "files": []})
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lot_files'").fetchone() is None:
            return _json({"lots": [], "files": []})
        rows = [r for r in current_lots(conn) if (not symbol or r["symbol"] == symbol.upper()) and (not account or r["account"] == account)]
        files = [dict(r) for r in conn.execute("SELECT id, name, kind, as_of, imported_at, rows, warnings FROM lot_files ORDER BY id DESC LIMIT 20")]
    finally:
        conn.close()
    return _json({"lots": rows, "files": files})
