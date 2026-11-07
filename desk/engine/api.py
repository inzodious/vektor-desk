import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk.api.deps import get_cfg
from desk.config import Config
from desk.db import connect
from desk.engine.live import live_view
from desk.engine.lots import current_lots

router = APIRouter(tags=["engine"])

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


@router.get("/api/engine/holdings")
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


@router.get("/api/engine/value")
def value(request: Request, start: str | None = None, end: str | None = None, account: str | None = None, symbol: str | None = None) -> JSONResponse:
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
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.upper())
    try:
        rows = conn.execute(
            "SELECT date, round(sum(value), 2) AS value, group_concat(DISTINCT quality) AS q, max(source) AS source "
            f"FROM holdings_daily WHERE {' AND '.join(where)} GROUP BY date ORDER BY date",
            args,
        ).fetchall()
    finally:
        conn.close()
    return _json({"series": [{"date": r["date"], "value": r["value"], "source": r["source"], "quality": worst((r["q"] or "").split(","))} for r in rows]})


@router.get("/api/engine/lots")
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


@router.get("/api/live")
def live(request: Request) -> JSONResponse:
    cfg = get_cfg(request)
    conn = _open(cfg)
    if conn is None:
        return _json({"state": None, "quality": "insufficient_history", "rows": [], "value": 0.0, "day_change": 0.0})
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='quotes_live'").fetchone() is None:
            return _json({"state": None, "quality": "insufficient_history", "rows": [], "value": 0.0, "day_change": 0.0})
        return _json(live_view(conn))
    finally:
        conn.close()


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None


@router.get("/api/live/intraday")
def intraday(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "quotes_live"):
        return _json({"day": None, "symbols": {}})
    try:
        day = conn.execute("SELECT max(substr(at, 1, 10)) FROM quotes_live WHERE source='finnhub'").fetchone()[0]
        out: dict[str, list[dict]] = {}
        if day:
            for r in conn.execute(
                "SELECT symbol, at, price FROM quotes_live WHERE source='finnhub' AND substr(at, 1, 10)=? GROUP BY symbol, at ORDER BY symbol, at", (day,)
            ):
                out.setdefault(r["symbol"], []).append({"t": r["at"], "price": r["price"]})
    finally:
        conn.close()
    return _json({"day": day, "symbols": out})


@router.get("/api/engine/prices")
def prices(request: Request, symbol: str, start: str | None = None, end: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None:
        return _json({"symbol": symbol.upper(), "rows": []})
    union = "SELECT date, close, 0 AS pri FROM prices_daily WHERE symbol=:s UNION ALL SELECT date, close, 1 AS pri FROM price_bars WHERE symbol=:s"
    try:
        rows = conn.execute(
            f"SELECT date, close, min(pri) AS pri FROM ({union}) WHERE date >= :a AND date <= :b GROUP BY date ORDER BY date",
            {"s": symbol.upper(), "a": start or "0000", "b": end or "9999"},
        ).fetchall()
    finally:
        conn.close()
    return _json({"symbol": symbol.upper(), "rows": [{"date": r["date"], "close": r["close"]} for r in rows]})


@router.get("/api/engine/metrics")
def metrics(
    request: Request, ids: str | None = None, scope: str | None = None, scope_id: str | None = None, window: str | None = None, as_of: str | None = None
) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "metric_values"):
        return _json({"as_of": None, "engine_version": None, "metrics": []})
    try:
        day = as_of or conn.execute("SELECT max(as_of) FROM metric_values").fetchone()[0]
        where, args = ["as_of = ?"], [day]
        if ids:
            wanted = [i.strip() for i in ids.split(",") if i.strip()]
            prefixes = [i[:-1] for i in wanted if i.endswith("*")]
            exact = [i for i in wanted if not i.endswith("*")]
            parts = ([f"metric_id IN ({','.join('?' * len(exact))})"] if exact else []) + ["metric_id LIKE ?"] * len(prefixes)
            where.append("(" + " OR ".join(parts) + ")")
            args += exact + [p + "%" for p in prefixes]
        for col, val in (("scope", scope), ("scope_id", scope_id), ('"window"', window)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM metric_values WHERE {' AND '.join(where)} ORDER BY metric_id, scope, scope_id", args)]
    finally:
        conn.close()
    return _json({"as_of": day, "engine_version": rows[0]["engine_version"] if rows else None, "metrics": rows})


@router.get("/api/engine/series")
def series(request: Request, id: str, scope: str = "portfolio", scope_id: str = "all", start: str | None = None, end: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "series_daily"):
        return _json({"id": id, "scope": scope, "scope_id": scope_id, "quality": "insufficient_history", "rows": []})
    try:
        rows = conn.execute(
            "SELECT date, value, quality FROM series_daily WHERE series_id=? AND scope=? AND scope_id=? AND date >= ? AND date <= ? ORDER BY date",
            (id, scope, scope_id, start or "0000", end or "9999"),
        ).fetchall()
    finally:
        conn.close()
    return _json(
        {
            "id": id,
            "scope": scope,
            "scope_id": scope_id,
            "quality": worst(r["quality"] for r in rows),
            "rows": [{"date": r["date"], "value": r["value"]} for r in rows],
        }
    )


@router.get("/api/engine/health")
def health(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "data_health"):
        return _json({"as_of": None, "status": "fail", "checks": []})
    try:
        day = conn.execute("SELECT max(as_of) FROM data_health").fetchone()[0]
        checks = [dict(r) for r in conn.execute("SELECT check_name, status, detail FROM data_health WHERE as_of=? ORDER BY check_name", (day,))]
        last = None
        if _has(conn, "engine_runs"):
            last = conn.execute("SELECT job, started_at, finished_at, ok FROM engine_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    status = "fail" if any(c["status"] == "fail" for c in checks) else ("warn" if any(c["status"] == "warn" for c in checks) else "ok")
    return _json({"as_of": day, "status": status if checks else "fail", "checks": checks, "last_run": dict(last) if last else None})
