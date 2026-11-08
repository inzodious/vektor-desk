import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.db import connect
from desk.decisions.plan import deposits_landed
from desk.decisions.profile import active_profile
from desk.engine.core import PROFILE_ERRORS
from desk.notify import publish

MOVE_BY_RISK = {1: 1.0, 2: 1.5, 3: 2.0, 4: 3.0, 5: 4.0}
HOLDING_MOVE_X = 2.5
MAX_GAP_DAYS = 5
DETECTED = {"margin_debit", "daily_move", "concentration", "rule_breach", "earnings", "deposit_landed"}
ALERTS = {
    "margin_debit": ("Margin debit on the desk", "high"),
    "daily_move": ("Big move today", "default"),
    "concentration": ("Concentration band crossed", "high"),
    "rule_breach": ("A plan rule is off", "high"),
    "deposit_landed": ("Deposit landed", "low"),
}


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _metric(conn: sqlite3.Connection, as_of: str, metric_id: str, scope: str = "portfolio", scope_id: str = "all", window: str = "now"):
    r = conn.execute(
        'SELECT value FROM metric_values WHERE as_of=? AND metric_id=? AND scope=? AND scope_id=? AND "window"=?', (as_of, metric_id, scope, scope_id, window)
    ).fetchone()
    return r["value"] if r else None


def _dials(cfg: Config) -> tuple[float, float | None]:
    try:
        p = active_profile(cfg)
        risk, cap = p.get("risk_level", default=3), p.get("opportunity", "satellite_cap_pct")
    except PROFILE_ERRORS:
        risk, cap = 3, None
    move = MOVE_BY_RISK.get(int(risk) if isinstance(risk, int | float) else 3, 2.0)
    return move, float(cap) if isinstance(cap, int | float) else None


# ---- Detection ----


def market_close(conn: sqlite3.Connection, symbol: str, day: str) -> tuple[str, float] | None:
    best = None
    for tbl in ("price_bars", "prices_daily"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tbl,)).fetchone():
            r = conn.execute(f"SELECT date, close FROM {tbl} WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1", (symbol, day)).fetchone()
            if r and r["close"] and (best is None or r["date"] > best[0]):
                best = (r["date"], r["close"])
    return best


def detect(cfg: Config, conn: sqlite3.Connection, as_of: str, *, now: datetime | None = None) -> list[tuple[str, str, str, dict]]:
    found: list[tuple[str, str, str, dict]] = []
    move, cap = _dials(cfg)
    debit = _metric(conn, as_of, "margin.debit")
    if debit and debit > 0:
        found.append((as_of, "margin_debit", "portfolio", {"debit": debit, "cost_month": _metric(conn, as_of, "margin.cost_month")}))
    day = _metric(conn, as_of, "ret.twr", window="1D")
    if day is not None and abs(day) >= move:
        found.append((as_of, "daily_move", "portfolio", {"ret_pct": day, "dial_pct": move}))
    days = [r[0] for r in conn.execute("SELECT DISTINCT date FROM holdings_daily WHERE date <= ? ORDER BY date DESC LIMIT 2", (as_of,))]
    if len(days) == 2:
        held = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM holdings_daily WHERE date=? AND is_cash=0", (days[0],))]
        for sym in sorted(held):
            now_close, before = market_close(conn, sym, days[0]), market_close(conn, sym, days[1])
            fresh = before and (date.fromisoformat(days[0]) - date.fromisoformat(before[0])).days <= MAX_GAP_DAYS
            if now_close and fresh and now_close[0] == days[0] and before[0] < days[0] and before[1]:
                pct = (now_close[1] / before[1] - 1) * 100
                if abs(pct) >= move * HOLDING_MOVE_X:
                    found.append((as_of, "daily_move", sym, {"ret_pct": round(pct, 2), "dial_pct": move * HOLDING_MOVE_X}))
    picks = "SELECT metric_id, scope_id, value FROM metric_values WHERE as_of=? AND scope IN ('holding', 'rule') "
    for r in conn.execute(picks + "AND metric_id IN ('plan.single_stock', 'plan.rules')", (as_of,)):
        if r["metric_id"] == "plan.single_stock" and cap is not None and r["value"] is not None and r["value"] > cap:
            found.append((as_of, "concentration", r["scope_id"], {"weight_pct": r["value"], "band_pct": cap}))
        if r["metric_id"] == "plan.rules" and r["value"] == 0:
            found.append((as_of, "rule_breach", r["scope_id"], {}))
    for r in conn.execute("SELECT scope_id FROM metric_values WHERE as_of=? AND metric_id='sig.earnings_reported' AND value=1", (as_of,)):
        found.append((as_of, "earnings", r["scope_id"], {"surprise_pct": _metric(conn, as_of, "sig.eps_surprise", "holding", r["scope_id"])}))
    total = _metric(conn, as_of, "plan.single_stock")
    if cap is not None and total is not None and total > cap:
        found.append((as_of, "concentration", "satellite", {"weight_pct": total, "band_pct": cap}))
    try:
        since = (date.fromisoformat(as_of) - timedelta(days=3)).isoformat()
        for d in deposits_landed(cfg, since, now=now):
            detail = {"date": d["landed"]["date"], "account": d.get("account") or d["landed"].get("accountKey"), "expected": d["date"]}
            found.append((as_of, "deposit_landed", str(d["id"]), detail | {"scheduled": d.get("scheduled", True)}))
    except PROFILE_ERRORS:
        pass
    return found


def lot_export(cfg: Config, conn: sqlite3.Connection, imported: list[dict], *, now: datetime | None = None) -> list[tuple[str, str, str, dict]]:
    today = _now(now).astimezone(ZoneInfo(cfg.timezone)).date().isoformat()
    return [(today, "lot_export", str(f.get("kind") or "lots"), {"file": f.get("file"), "kind": f.get("kind"), "rows": f.get("rows")}) for f in imported]


# ---- Storing and alerting ----


def record(cfg: Config, conn: sqlite3.Connection, found: list[tuple[str, str, str, dict]], *, now: datetime | None = None) -> list[dict]:
    at = _now(now).isoformat(timespec="seconds")
    new = []
    with conn:
        for as_of, kind, scope_id, detail in found:
            cur = conn.execute(
                "INSERT OR IGNORE INTO triggers (as_of, kind, scope_id, detail, fired_at) VALUES (?, ?, ?, ?, ?)",
                (as_of, kind, scope_id, json.dumps(detail), at),
            )
            if cur.rowcount:
                prev = conn.execute("SELECT max(as_of) FROM metric_values WHERE as_of < ?", (as_of,)).fetchone()[0]
                held = prev is not None and conn.execute("SELECT 1 FROM triggers WHERE kind=? AND scope_id=? AND as_of=?", (kind, scope_id, prev)).fetchone()
                new.append({"as_of": as_of, "kind": kind, "scope_id": scope_id, "detail": detail, "crossed": not held})
    for t in new:
        if t["kind"] in ALERTS and t["crossed"]:
            title, priority = ALERTS[t["kind"]]
            tags = ["rotating_light"] if priority == "high" else []
            publish("alerts", title, _words(t), priority, tags=tags, click="/", key=f"trigger-{t['kind']}-{t['scope_id']}-{t['as_of']}", cfg=cfg)
    return new


def _words(t: dict) -> str:
    d, s = t["detail"], t["scope_id"]
    if t["kind"] == "margin_debit":
        return "There is a margin debit, so interest is running. The Bridge shows the monthly cost."
    if t["kind"] == "daily_move":
        who = "The portfolio" if s == "portfolio" else s
        return f"{who} moved {d['ret_pct']:+.1f}% today, past the {d['dial_pct']:g}% dial."
    if t["kind"] == "concentration":
        who = "Single stocks together" if s == "satellite" else s
        return f"{who} at {d['weight_pct']:.1f}% of the portfolio, past the {d['band_pct']:g}% band."
    if t["kind"] == "rule_breach":
        return f"Rule {s} doesn't hold today. Plan shows why."
    if t["kind"] == "deposit_landed":
        if d.get("scheduled", True):
            return f"The deposit expected {d['expected']} landed on {d['date']}."
        return f"Money landed in {d.get('account') or 'your account'} on {d['date']}."
    return ""


def refresh(conn: sqlite3.Connection, as_of: str, found: list[tuple[str, str, str, dict]]) -> int:
    keep = {(kind, scope_id): detail for _, kind, scope_id, detail in found}
    gone = 0
    with conn:
        rows = conn.execute("SELECT kind, scope_id FROM triggers WHERE as_of=?", (as_of,)).fetchall()
        for r in rows:
            if r["kind"] not in DETECTED:
                continue
            key = (r["kind"], r["scope_id"])
            if key in keep:
                conn.execute("UPDATE triggers SET detail=? WHERE as_of=? AND kind=? AND scope_id=?", (json.dumps(keep[key]), as_of, *key))
            else:
                conn.execute("DELETE FROM triggers WHERE as_of=? AND kind=? AND scope_id=?", (as_of, *key))
                gone += 1
    return gone


def run(cfg: Config, conn: sqlite3.Connection, as_of: str, *, now: datetime | None = None) -> dict:
    found = detect(cfg, conn, as_of, now=now)
    gone = refresh(conn, as_of, found)
    new = record(cfg, conn, found, now=now)
    return {"new": len(new), "kinds": sorted({t["kind"] for t in new}), "withdrawn": gone}


def today(cfg: Config) -> list[dict]:
    if not cfg.desk_db.exists():
        return []
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='triggers'").fetchone() is None:
            return []
        latest = conn.execute("SELECT max(as_of) FROM triggers").fetchone()[0]
        if not latest:
            return []
        cut = (date.fromisoformat(latest) - timedelta(days=1)).isoformat()
        rows = conn.execute("SELECT as_of, kind, scope_id, detail FROM triggers WHERE as_of >= ? ORDER BY as_of, kind, scope_id", (cut,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
