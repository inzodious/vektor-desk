import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from desk.api.deps import get_cfg
from desk.config import Config
from desk.db import connect
from desk.engine import asof, discounts, lab, lane, leaderboard, paper_exec, planfacts, review, schema, watchlist
from desk.engine.compare import CompareError, compare
from desk.engine.live import live_view
from desk.engine.lots import current_lots
from desk.engine.preflight import PreflightError, check_trade

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
        rows = [r for r in current_lots(conn) if (not symbol or r["symbol"] == symbol.upper()) and (not account or r["account"] == account)]
        has = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name IN ('lot_files', 'broker_files')")}
        files = (
            [dict(r) for r in conn.execute("SELECT id, name, kind, as_of, imported_at, rows, warnings FROM lot_files ORDER BY id DESC LIMIT 20")]
            if "lot_files" in has
            else []
        )
        history = (
            [
                dict(r)
                for r in conn.execute(
                    "SELECT id, name, imported_at, window_start, window_end, rows, added, cancelled FROM broker_files ORDER BY id DESC LIMIT 20"
                )
            ]
            if "broker_files" in has
            else []
        )
    finally:
        conn.close()
    return _json({"lots": rows, "files": files, "history": history})


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


@router.get("/api/asof")
def as_of(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    try:
        return _json(asof.view(conn))
    finally:
        if conn is not None:
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


@router.post("/api/preflight")
def post_preflight(request: Request, trade: Annotated[dict, Body()]) -> JSONResponse:
    cfg = get_cfg(request)
    if not cfg.desk_db.exists():
        return JSONResponse({"error": "No holdings yet; the engine has not run"}, status_code=409)
    try:
        return _json(check_trade(cfg, trade))
    except PreflightError as e:
        return JSONResponse({"error": str(e)}, status_code=400 if "No holdings" not in str(e) else 409)


@router.get("/api/engine/preflight")
def get_preflight(request: Request, ticket_id: str) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "preflight"):
        return _json({"ticket_id": ticket_id, "rows": []})
    try:
        rows = [dict(r) for r in conn.execute("SELECT metric_id, before, after, flag, at FROM preflight WHERE ticket_id=? ORDER BY metric_id", (ticket_id,))]
    finally:
        conn.close()
    return _json({"ticket_id": ticket_id, "rows": rows})


@router.get("/api/engine/wash")
def wash(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "wash_windows"):
        return _json({"as_of": None, "windows": []})
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM wash_windows ORDER BY clears, symbol")]
    finally:
        conn.close()
    return _json({"as_of": rows[0]["as_of"] if rows else None, "windows": rows})


@router.get("/api/engine/research")
def research(request: Request, symbol: str) -> JSONResponse:
    sym = symbol.upper()
    empty = {"symbol": sym, "filings": [], "fundamentals": {}, "earnings": [], "insiders": [], "signals": [], "filing_signals": []}
    conn = _open(get_cfg(request))
    if conn is None:
        return _json(empty)
    if not _has(conn, "filings"):
        try:
            return _json(empty | {"filing_signals": filing_signals(conn, sym)})
        finally:
            conn.close()
    try:
        filings = [
            dict(r) for r in conn.execute("SELECT form, filed, report_date, description, url FROM filings WHERE symbol=? ORDER BY filed DESC LIMIT 40", (sym,))
        ]
        facts: dict[str, list[dict]] = {}
        for r in conn.execute(
            "SELECT concept, start, period_end, fp, form, value, unit FROM fundamentals WHERE symbol=? ORDER BY concept, period_end DESC", (sym,)
        ):
            rows = facts.setdefault(r["concept"], [])
            if len(rows) < 12:
                rows.append({k: r[k] for k in ("start", "period_end", "fp", "form", "value", "unit")})
        earnings = [dict(r) for r in conn.execute("SELECT * FROM earnings WHERE symbol=? ORDER BY date DESC LIMIT 12", (sym,))]
        insiders = [
            dict(r)
            for r in conn.execute(
                "SELECT name, filing_date, txn_date, code, change, shares_after, price FROM insider_trades WHERE symbol=? ORDER BY txn_date DESC LIMIT 50",
                (sym,),
            )
        ]
        day = conn.execute("SELECT max(as_of) FROM metric_values").fetchone()[0] if _has(conn, "metric_values") else None
        sigs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM metric_values WHERE as_of=? AND scope='holding' AND scope_id=? AND (metric_id LIKE 'sig.%' OR metric_id LIKE 'fund.%')",
                (day, sym),
            )
        ]
        scored = filing_signals(conn, sym)
    finally:
        conn.close()
    return _json(
        {"symbol": sym, "filings": filings, "fundamentals": facts, "earnings": earnings, "insiders": insiders, "signals": sigs, "filing_signals": scored}
    )


FILING_SIGNALS = 3


def filing_signals(conn: sqlite3.Connection, sym: str, limit: int = FILING_SIGNALS) -> list[dict]:
    if not _has(conn, "filing_signals"):
        return []
    cols = "accession, form, filed_at, scored_at, direction, confidence, event_type, horizon_days, rationale"
    rows = [dict(r) for r in conn.execute(f"SELECT {cols} FROM filing_signals WHERE symbol=? ORDER BY filed_at DESC, accession LIMIT ?", (sym, limit))]
    lanes = {v.id for v in lane.variants(conn)}
    bought: set[str] = set()
    held = False
    if _has(conn, "paper_trades"):
        bought = {r[0] for r in conn.execute("SELECT date, strategy_id FROM paper_trades WHERE symbol=? AND side='buy'", (sym,)) if r[1] in lanes}
    if _has(conn, "paper_positions"):
        held = any(r[0] in lanes for r in conn.execute("SELECT strategy_id FROM paper_positions WHERE symbol=? AND shares > 0", (sym,)))
    for r in rows:
        r["in_lane"] = lane.entry_session(lane._stamp(r["scored_at"])).isoformat() in bought
        r["lane_open"] = r["in_lane"] and held
    return rows


@router.get("/api/engine/macro")
def macro_series(request: Request, start: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "macro_daily"):
        return _json({"series": {}})
    try:
        out: dict[str, list[dict]] = {}
        for r in conn.execute("SELECT series, date, value FROM macro_daily WHERE date >= ? ORDER BY series, date", (start or "0000",)):
            out.setdefault(r["series"], []).append({"date": r["date"], "value": r["value"]})
    finally:
        conn.close()
    return _json({"series": out})


@router.get("/api/compare")
def compare_view(request: Request, ids: str, window: str = "1Y") -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None:
        return JSONResponse({"detail": "The engine has not run yet."}, status_code=400)
    try:
        return _json(compare(conn, ids.split(","), window))
    except CompareError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    finally:
        conn.close()


@router.get("/api/engine/lookthrough")
def lookthrough_view(request: Request, fund: str | None = None, limit: int = 50) -> JSONResponse:
    empty = {"as_of": None, "rows": [], "sectors": [], "funds": [], "holdings": []}
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "lookthrough"):
        return _json(empty)
    try:
        rows = [
            {**dict(r), "via": json.loads(r["via"])} for r in conn.execute("SELECT * FROM lookthrough ORDER BY weight DESC LIMIT ?", (max(1, min(limit, 500)),))
        ]
        day = conn.execute("SELECT max(as_of) FROM metric_values").fetchone()[0]
        sectors = [
            {"sector": r["scope_id"], "weight": r["value"], "quality": r["quality"]}
            for r in conn.execute("SELECT * FROM metric_values WHERE as_of=? AND metric_id='risk.sector' ORDER BY value DESC", (day,))
        ]
        funds = [dict(r) for r in conn.execute("SELECT fund, max(as_of) AS as_of, count(*) AS holdings FROM fund_holdings GROUP BY fund ORDER BY fund")]
        holdings = []
        if fund:
            holdings = [
                dict(r)
                for r in conn.execute(
                    "SELECT holding, name, weight, asset_cat, country FROM fund_holdings WHERE fund=? ORDER BY weight DESC LIMIT ?",
                    (fund.upper(), max(1, min(limit, 500))),
                )
            ]
    finally:
        conn.close()
    return _json({"as_of": rows[0]["as_of"] if rows else day, "rows": rows, "sectors": sectors, "funds": funds, "holdings": holdings})


@router.get("/api/lab/strategies")
def lab_strategies(request: Request) -> JSONResponse:
    cfg = get_cfg(request)
    return _json({"strategies": lab.strategies(cfg), "rules": lab.rules(cfg), "features": lab.features(cfg), "grammar": lab.grammar()})


@router.get("/api/engine/lab/leaderboard")
def lab_leaderboard(request: Request) -> JSONResponse:
    cfg = get_cfg(request)
    conn = connect(cfg.desk_db, readonly=True) if cfg.desk_db.exists() else None
    try:
        return _json(leaderboard.build(conn, paper_exec.budget(), leaderboard.backtests(cfg)))
    finally:
        if conn is not None:
            conn.close()


@router.get("/api/lab/strategies/{strategy_id}")
def lab_strategy(request: Request, strategy_id: str) -> JSONResponse:
    cfg = get_cfg(request)
    try:
        view = lab.desk_view(cfg, strategy_id)
    except lab.NotReady as e:
        return JSONResponse({"detail": str(e)}, status_code=404)
    if view.get("status") is None:
        return JSONResponse({"detail": view.get("note")}, status_code=404)
    trades = []
    if cfg.desk_db.exists():
        conn = connect(cfg.desk_db, readonly=True)
        try:
            if _has(conn, "paper_trades"):
                trades = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT date, symbol, side, shares, price, cost FROM paper_trades WHERE strategy_id=? AND version=? ORDER BY date DESC LIMIT 200",
                        (strategy_id, view["version"]),
                    )
                ]
        finally:
            conn.close()
    return _json(view | {"paper_trades": trades})


@router.get("/api/engine/watchlist")
def watchlist_view(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request)) or sqlite3.connect(":memory:")
    try:
        return _json({"symbols": watchlist.rows(conn)})
    finally:
        conn.close()


def _write(cfg: Config) -> sqlite3.Connection:
    cfg.desk_db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


@router.post("/api/engine/watchlist")
def watchlist_add(request: Request, body: Annotated[dict, Body()]) -> JSONResponse:
    conn = _write(get_cfg(request))
    try:
        sym = watchlist.add(conn, str(body.get("symbol") or ""))
        return _json({"added": sym, "symbols": watchlist.rows(conn)})
    except watchlist.WatchError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    finally:
        conn.close()


@router.delete("/api/engine/watchlist/{symbol}")
def watchlist_remove(request: Request, symbol: str) -> JSONResponse:
    conn = _write(get_cfg(request))
    try:
        sym = watchlist.remove(conn, symbol)
        return _json({"removed": sym, "symbols": watchlist.rows(conn)})
    except watchlist.WatchError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    finally:
        conn.close()


def _view(request: Request, name: str, empty: dict) -> JSONResponse:
    conn = _open(get_cfg(request))
    if conn is None or not _has(conn, "engine_views"):
        if conn is not None:
            conn.close()
        return _json(empty)
    try:
        row = conn.execute("SELECT as_of, body FROM engine_views WHERE name=?", (name,)).fetchone()
    finally:
        conn.close()
    return _json(json.loads(row["body"]) if row else empty)


@router.get("/api/engine/scorecard")
def scorecard_view(request: Request, origin: str | None = None) -> JSONResponse:
    empty = {"as_of": None, "groups": [], "desks": [], "saves": {"n": 0, "usd": 0.0}, "offplan_gap": {"n": 0}, "decisions": []}
    resp = _view(request, "scorecard", empty)
    if origin is None:
        return resp
    body = json.loads(resp.body)
    body["decisions"] = [d for d in body["decisions"] if d["origin"] == origin]
    body["desks"] = [d for d in body["desks"] if d["desk"] == origin]
    body["groups"] = [g for g in body["groups"] if g["by"] != "origin" or g["group"] == origin]
    return _json(body)


@router.get("/api/engine/patterns")
def patterns_view(request: Request) -> JSONResponse:
    empty = {"as_of": None, "market": [], "holdings": {}, "drawdowns": [], "seasonality": {}, "corr_shifts": [], "behavior": {}}
    return _view(request, "patterns", empty)


@router.get("/api/engine/replay")
def replay_view(request: Request) -> JSONResponse:
    return _view(request, "replay", {"as_of": None, "status": "not_ready", "quality": "insufficient_history", "variants": []})


@router.get("/api/engine/fi")
def fi_view(request: Request) -> JSONResponse:
    return _view(request, "fi", {"as_of": None, "status": "not_ready", "lines": [], "fi_date": {}})


@router.get("/api/engine/reference")
def reference_view(request: Request) -> JSONResponse:
    return _view(request, "reference", {"as_of": None, "source": None, "name": None, "weights": {}, "judged": False, "note": None})


@router.get("/api/engine/factors")
def factors_view(request: Request) -> JSONResponse:
    return _view(request, "factors", {"as_of": None, "holdings": {}, "portfolio": {}, "coverage_pct": 0.0})


@router.get("/api/engine/bands")
def bands_view(request: Request) -> JSONResponse:
    return _view(request, "bands", {"as_of": None, "status": "not_ready", "rows": [], "book": "as-held"})


@router.get("/api/engine/reviews/index")
def reviews_index(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    try:
        return _json(review.index_view(conn))
    finally:
        if conn is not None:
            conn.close()


@router.get("/api/engine/reviews")
def reviews_view(request: Request, kind: str = "day", end: str | None = None) -> JSONResponse:
    conn = _open(get_cfg(request))
    try:
        return _json(review.review_view(conn, kind, end))
    finally:
        if conn is not None:
            conn.close()


@router.get("/api/engine/planfacts")
def planfacts_view(request: Request, symbol: str | None = None) -> JSONResponse:
    return _json(planfacts.view(get_cfg(request), symbol))


@router.get("/api/engine/discounts")
def discounts_view(request: Request) -> JSONResponse:
    conn = _open(get_cfg(request))
    try:
        return _json(discounts.view(conn))
    finally:
        if conn is not None:
            conn.close()
