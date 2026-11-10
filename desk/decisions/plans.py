import re
import sqlite3
from datetime import date, datetime, timedelta

from desk.config import Config
from desk.decisions.profile import LOT_METHODS, digest
from desk.decisions.store import dumps, loads, now_iso, session

ROLES = ("core", "conviction", "satellite", "exit")
STEP_KINDS = ("add", "trim", "hold", "review", "harvest", "sell", "repay", "other")
BUYS = ("add",)
SELLS = ("trim", "harvest", "sell")
AUTHORS = ("you", "desk")
LIVE = ("draft", "approved")
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]{0,47}$")
SLACK_DAYS = 3
HARVEST_NO_BUY_DAYS = 31
MAX_STEPS = 15
PLAN_KEYS = ("role", "thesis", "weight_band", "add_rule", "trim_rule", "exit_conditions", "tax_notes", "catalysts", "next_review", "steps")
STEP_KEYS = ("id", "kind", "text", "due", "until", "when", "shares", "amount_usd", "account", "lots", "no_buy_days", "note")
PLAN_VIEW_KEYS = {
    "symbol",
    "version",
    "status",
    "author",
    "run_id",
    "model",
    "summary",
    "created_at",
    "approved_at",
    "next_step",
    "weight_pct",
    "weight_as_of",
    "band_status",
    "band_source",
    "conviction",
    "warnings",
    "review_due",
    "approved",
    "versions",
}
STEP_VIEW_KEYS = {"symbol", "by", "status", "done_on", "done_by", "filled_shares", "activity_ids", "no_buy_from", "rebuy_on", "no_buy_now", "line"}
LOT_TEXT = {
    "highest_cost": "Specific Shares, highest-cost lots",
    "lowest_cost": "Specific Shares, lowest-cost lots",
    "tax_efficient": "Specific Shares, tax-efficient lots",
    "fifo": "first in, first out",
    "lifo": "last in, first out",
}
STEP_TEMPLATES = {
    "harvest": {"kind": "harvest", "lots": "highest_cost", "no_buy_days": HARVEST_NO_BUY_DAYS, "note": "Tax-loss harvest. Pick Specific Shares at the broker."},
    "repay": {"kind": "repay", "note": "The deposit pays off the margin debit."},
}


class PlanError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ---- Cleaning ----


def clean_symbol(symbol) -> str:
    out = str(symbol or "").strip().upper()
    if not TICKER.match(out):
        raise PlanError(f"{symbol!r} doesn't look like a ticker")
    return out


def _text(errors, where, value, limit, required=False) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.append(f"{where} is required")
        return None
    if not isinstance(value, str):
        errors.append(f"{where} must be text")
        return None
    out = value.strip()
    if len(out) > limit:
        errors.append(f"{where} is {len(out)} characters; keep it to {limit}")
    return out


def _number(errors, where, value, low, high):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        errors.append(f"{where} must be a number from {low:g} to {high:g}")
        return None
    return int(value) if float(value).is_integer() else round(float(value), 6)


def _day(errors, where, value) -> str | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        errors.append(f"{where} must be a date like 2026-12-07")
        return None


def _mapping(errors, where, value, keys) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{where} must be a mapping")
        return None
    unknown = sorted(set(value) - set(keys))
    if unknown:
        errors.append(f"{where}: unknown field {', '.join(unknown)}")
    return value


def _pair(errors, where, low, high, low_name, high_name) -> None:
    if low is not None and high is not None and low > high:
        errors.append(f"{where}: {low_name} is above {high_name}")


def _band(errors, value) -> dict | None:
    raw = _mapping(errors, "weight_band", value, ("min_pct", "max_pct"))
    if raw is None:
        return None
    if raw.get("max_pct") is None:
        errors.append("weight_band.max_pct is required")
    low = raw.get("min_pct")
    out = {
        "min_pct": _number(errors, "weight_band.min_pct", 0 if low is None else low, 0, 100),
        "max_pct": _number(errors, "weight_band.max_pct", raw.get("max_pct"), 0, 100),
    }
    _pair(errors, "weight_band", out["min_pct"], out["max_pct"], "min_pct", "max_pct")
    return out


def _add_rule(errors, value) -> dict | None:
    raw = _mapping(errors, "add_rule", value, ("zone_low", "zone_high", "max_per_month_usd", "deposits_only", "note"))
    if raw is None:
        return None
    only = raw.get("deposits_only", True)
    if not isinstance(only, bool):
        errors.append("add_rule.deposits_only must be true or false")
    out = {
        "zone_low": _number(errors, "add_rule.zone_low", raw.get("zone_low"), 0, 1e7),
        "zone_high": _number(errors, "add_rule.zone_high", raw.get("zone_high"), 0, 1e7),
        "max_per_month_usd": _number(errors, "add_rule.max_per_month_usd", raw.get("max_per_month_usd"), 0, 1e8),
        "deposits_only": only is True,
        "note": _text(errors, "add_rule.note", raw.get("note"), 600),
    }
    _pair(errors, "add_rule", out["zone_low"], out["zone_high"], "zone_low", "zone_high")
    return out


def _trim_rule(errors, value) -> dict | None:
    raw = _mapping(errors, "trim_rule", value, ("above_pct", "to_pct", "zone_low", "zone_high", "note"))
    if raw is None:
        return None
    out = {
        "above_pct": _number(errors, "trim_rule.above_pct", raw.get("above_pct"), 0, 100),
        "to_pct": _number(errors, "trim_rule.to_pct", raw.get("to_pct"), 0, 100),
        "zone_low": _number(errors, "trim_rule.zone_low", raw.get("zone_low"), 0, 1e7),
        "zone_high": _number(errors, "trim_rule.zone_high", raw.get("zone_high"), 0, 1e7),
        "note": _text(errors, "trim_rule.note", raw.get("note"), 600),
    }
    _pair(errors, "trim_rule", out["zone_low"], out["zone_high"], "zone_low", "zone_high")
    _pair(errors, "trim_rule", out["to_pct"], out["above_pct"], "to_pct", "above_pct")
    return out


def _texts(errors, where, value, count, limit) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{where} must be a list of text")
        return []
    if len(value) > count:
        errors.append(f"{where} has {len(value)} entries; keep it to {count}")
    return [t for i, v in enumerate(value) if (t := _text(errors, f"{where}[{i}]", v, limit, required=True))]


def _catalysts(errors, value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("catalysts must be a list")
        return []
    if len(value) > 10:
        errors.append(f"catalysts has {len(value)} entries; keep it to 10")
    out = []
    for i, c in enumerate(value):
        raw = _mapping(errors, f"catalysts[{i}]", c if c is not None else "", ("text", "date"))
        if raw is not None:
            out.append(
                {
                    "text": _text(errors, f"catalysts[{i}].text", raw.get("text"), 300, required=True),
                    "date": _day(errors, f"catalysts[{i}].date", raw.get("date")),
                }
            )
    return out


def _step(errors, where, step, symbol: str | None = None) -> dict | None:
    if not isinstance(step, dict):
        errors.append(f"{where} must be a mapping")
        return None
    step = {k: v for k, v in step.items() if k not in STEP_VIEW_KEYS}
    unknown = sorted(set(step) - set(STEP_KEYS))
    if unknown:
        errors.append(f"{where}: unknown field {', '.join(unknown)}")
    kind = step.get("kind")
    if kind not in STEP_KINDS:
        errors.append(f"{where}.kind must be one of {', '.join(STEP_KINDS)}")
        return None
    sid = step.get("id")
    if sid is not None and (not isinstance(sid, str) or not SLUG.match(sid)):
        errors.append(f"{where}.id must be lowercase letters, digits and dashes")
        sid = None
    trade = kind in BUYS + SELLS
    out = {
        "id": sid,
        "kind": kind,
        "text": _text(errors, f"{where}.text", step.get("text"), 300, required=kind in ("hold", "other")),
        "due": _day(errors, f"{where}.due", step.get("due")),
        "until": _day(errors, f"{where}.until", step.get("until")),
        "when": _text(errors, f"{where}.when", step.get("when"), 300),
        "shares": None,
        "amount_usd": None,
        "account": _text(errors, f"{where}.account", step.get("account"), 80),
        "lots": None,
        "no_buy_days": None,
        "note": _text(errors, f"{where}.note", step.get("note"), 600),
    }
    if out["until"] and not out["due"]:
        errors.append(f"{where}.until needs a due date")
    _pair(errors, where, out["due"], out["until"], "due", "until")
    shares = step.get("shares")
    if shares is not None:
        if not trade:
            errors.append(f"{where}.shares is only for add, trim, harvest and sell")
        elif shares != "all":
            shares = _number(errors, f"{where}.shares", shares, 1e-6, 1e9)
        elif kind in BUYS:
            errors.append(f"{where}.shares can't be all for an add")
        out["shares"] = shares if trade else None
    if step.get("amount_usd") is not None:
        if not trade and kind != "repay":
            errors.append(f"{where}.amount_usd is only for trades and repay")
        else:
            out["amount_usd"] = _number(errors, f"{where}.amount_usd", step["amount_usd"], 0.01, 1e9)
    if step.get("lots") is not None:
        if kind not in SELLS or step["lots"] not in LOT_METHODS:
            errors.append(f"{where}.lots must be one of {', '.join(LOT_METHODS)}, on a trim, harvest or sell")
        else:
            out["lots"] = step["lots"]
    days = step.get("no_buy_days")
    if days is not None:
        if kind not in SELLS or isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 400:
            errors.append(f"{where}.no_buy_days must be a whole number from 0 to 400, on a trim, harvest or sell")
        else:
            out["no_buy_days"] = days
    elif kind == "harvest":
        out["no_buy_days"] = HARVEST_NO_BUY_DAYS
    if symbol and out["text"] and kind not in ("hold", "other") and out["text"] == _step_text(symbol, out):
        out["text"] = None
    return out


def _steps(errors, value, symbol: str | None = None) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("steps must be a list")
        return []
    if len(value) > MAX_STEPS:
        errors.append(f"steps has {len(value)} entries; keep it to {MAX_STEPS}")
    out = [s for i, v in enumerate(value) if (s := _step(errors, f"steps[{i}]", v, symbol)) is not None]
    seen: set[str] = set()
    for s in out:
        if s["id"] and s["id"] in seen:
            errors.append(f"steps: id {s['id']!r} is used twice")
        if s["id"]:
            seen.add(s["id"])
    return out


def clean(plan, symbol: str | None = None) -> dict:
    if not isinstance(plan, dict):
        raise PlanError("plan must be a mapping")
    plan = {k: v for k, v in plan.items() if k not in PLAN_VIEW_KEYS}
    errors: list[str] = []
    unknown = sorted(set(plan) - set(PLAN_KEYS))
    if unknown:
        errors.append(f"unknown field {', '.join(unknown)}")
    if plan.get("role") not in ROLES:
        errors.append(f"role must be one of {', '.join(ROLES)}")
    out = {
        "role": plan.get("role"),
        "thesis": _text(errors, "thesis", plan.get("thesis"), 2000, required=True),
        "weight_band": _band(errors, plan.get("weight_band")),
        "add_rule": _add_rule(errors, plan.get("add_rule")),
        "trim_rule": _trim_rule(errors, plan.get("trim_rule")),
        "exit_conditions": _texts(errors, "exit_conditions", plan.get("exit_conditions"), 8, 400),
        "tax_notes": _text(errors, "tax_notes", plan.get("tax_notes"), 1200),
        "catalysts": _catalysts(errors, plan.get("catalysts")),
        "next_review": _day(errors, "next_review", plan.get("next_review")),
        "steps": _steps(errors, plan.get("steps"), symbol),
    }
    if errors:
        raise PlanError("; ".join(errors))
    return out


def _name_steps(steps: list[dict], taken: set[str]) -> None:
    used = set(taken) | {s["id"] for s in steps if s["id"]}
    for s in steps:
        if s["id"]:
            continue
        base = f"{s['kind']}-{s['due']}" if s["due"] else s["kind"]
        sid, n = base, 2
        while sid in used:
            sid, n = f"{base}-{n}", n + 1
        s["id"] = sid
        used.add(sid)


def _merge_steps(base: list[dict], new: list[dict], author: str) -> list[dict]:
    old = {s["id"]: s for s in base}
    mine = {sid for sid, s in old.items() if s.get("by") == "you"}
    _name_steps(new, mine if author == "desk" else set())
    out = []
    for s in new:
        before = old.get(s["id"])
        if before is None:
            out.append({**s, "by": author})
        elif author == "desk" and before.get("by") == "you":
            out.append(before)
        else:
            same = all(before.get(k) == s[k] for k in STEP_KEYS)
            out.append({**s, "by": before.get("by", author) if same else author})
    if author == "desk":
        kept = {s["id"] for s in out}
        out += [old[sid] for sid in old if sid in mine and sid not in kept]
    return out


# ---- Where each step stands ----


def _step_text(symbol: str, s: dict) -> str:
    shares, amount = s["shares"], s["amount_usd"]
    count = f"all {symbol}" if shares == "all" else f"{shares:g} {symbol}" if shares else None
    if s["kind"] == "add":
        return f"Buy {count}" if count else f"Buy ${amount:,.0f} of {symbol}" if amount else f"Add to {symbol}"
    if s["kind"] == "trim":
        return f"Trim {count}" if count else f"Trim {symbol}"
    if s["kind"] == "harvest":
        return f"Sell {count or 'all ' + symbol} to harvest the loss"
    if s["kind"] == "sell":
        return f"Sell {count or 'all ' + symbol}"
    if s["kind"] == "repay":
        return f"Pay ${amount:,.0f} toward the margin debit" if amount else "Pay off the margin debit"
    return f"Review the {symbol} plan"


def _fills(symbol: str, s: dict, trades: list[dict]) -> tuple[list[dict], float]:
    side = "buy" if s["kind"] in BUYS else "sell"
    lo = (date.fromisoformat(s["due"]) - timedelta(days=SLACK_DAYS)).isoformat()
    hi = (date.fromisoformat(s["until"] or s["due"]) + timedelta(days=SLACK_DAYS)).isoformat()
    hits = sorted((t for t in trades if t["symbol"] == symbol and t.get("kind") == side and lo <= str(t["date"])[:10] <= hi), key=lambda t: str(t["date"]))
    return hits, sum(abs(t.get("quantity") or 0) for t in hits)


def _debit_cleared(conn: sqlite3.Connection, start: str) -> str | None:
    try:
        rows = conn.execute(
            "SELECT as_of, value FROM metric_values WHERE metric_id='margin.debit' AND scope='portfolio' AND as_of >= ? AND value IS NOT NULL ORDER BY as_of",
            (start,),
        ).fetchall()
    except sqlite3.Error:
        return None
    return next((str(r["as_of"])[:10] for r in rows if r["value"] <= 1), None)


def _step_view(conn: sqlite3.Connection, symbol: str, s: dict, ctx: dict) -> dict:
    today = ctx["today"]
    v = {**s, "symbol": symbol, "text": s["text"] or _step_text(symbol, s), "done_by": None, "filled_shares": None, "activity_ids": []}
    done_on = ctx["state"].get((symbol, s["id"]))
    if done_on:
        v["done_by"] = "you"
    due, until = s["due"], s["until"] or s["due"]
    if due and s["kind"] in BUYS + SELLS:
        hits, filled = _fills(symbol, s, ctx["trades"])
        v["activity_ids"] = [t["activity_id"] for t in hits]
        v["filled_shares"] = round(filled, 6) if hits else None
        enough = bool(hits) and (not isinstance(s["shares"], int | float) or filled >= s["shares"] - 0.01)
        if enough and not done_on:
            done_on, v["done_by"] = str(hits[-1]["date"])[:10], "broker"
    elif due and s["kind"] == "repay" and not done_on:
        done_on = _debit_cleared(conn, due)
        v["done_by"] = "desk" if done_on else None
    if done_on:
        status = "done"
    elif not due:
        status = "waiting" if s["when"] else "standing"
    elif v["filled_shares"]:
        status = "partial"
    else:
        status = "open" if due <= today <= until else "upcoming" if today < due else "passed"
    days = s["no_buy_days"] or 0
    hold_from = (date.fromisoformat(due) - timedelta(days=days)).isoformat() if days and due else None
    rebuy = (date.fromisoformat(done_on) + timedelta(days=days)).isoformat() if days and done_on else None
    if status == "done":
        hold = bool(rebuy and today < rebuy)
    else:
        hold = bool(hold_from and status != "passed" and today >= hold_from)
    return v | {"status": status, "done_on": done_on, "no_buy_from": hold_from, "rebuy_on": rebuy, "no_buy_now": hold}


ORDER = {"partial": 0, "open": 0, "upcoming": 1, "waiting": 2, "standing": 3}


def _next_step(steps: list[dict]) -> dict | None:
    todo = [s for s in steps if s["status"] in ORDER]
    return min(todo, key=lambda s: (ORDER[s["status"]], s["due"] or "9999", s["id"])) if todo else None


# ---- Views ----


def _weights(conn: sqlite3.Connection) -> tuple[dict[str, float], str | None]:
    try:
        row = conn.execute("SELECT MAX(as_of) AS a FROM metric_values WHERE metric_id='value.weight' AND scope='holding'").fetchone()
        if not row or not row["a"]:
            return {}, None
        rows = conn.execute("SELECT scope_id, value FROM metric_values WHERE metric_id='value.weight' AND scope='holding' AND as_of=?", (row["a"],)).fetchall()
    except sqlite3.Error:
        return {}, None
    return {r["scope_id"]: float(r["value"] or 0) for r in rows}, str(row["a"])[:10]


def _context(cfg: Config, conn: sqlite3.Connection, rows: list[sqlite3.Row], now: datetime | None) -> dict:
    from desk.decisions.plan import _today
    from desk.decisions.records import mirror_trades
    from desk.decisions.risk import convictions

    dues = [s["due"] for r in rows for s in loads(r["body"])["steps"] if s["due"] and s["kind"] in BUYS + SELLS]
    since = (date.fromisoformat(min(dues)) - timedelta(days=SLACK_DAYS)).isoformat() if dues else None
    weights, as_of = _weights(conn)
    try:
        holds = {c["symbol"]: c for c in convictions(cfg) if c["enabled"]}
    except Exception:  # noqa: BLE001
        holds = {}
    return {
        "today": _today(cfg, now).isoformat(),
        "trades": mirror_trades(conn, since) if since else [],
        "state": {(r["symbol"], r["step_id"]): r["done_on"] for r in conn.execute("SELECT symbol, step_id, done_on FROM plan_step_state")},
        "weights": weights,
        "weights_as_of": as_of,
        "convictions": holds,
    }


def _view(conn: sqlite3.Connection, row: sqlite3.Row, ctx: dict) -> dict:
    body, symbol = loads(row["body"]), row["symbol"]
    steps = [_step_view(conn, symbol, s, ctx) for s in body["steps"]]
    hold = ctx["convictions"].get(symbol)
    band, source = body["weight_band"], "plan" if body["weight_band"] else None
    warnings = []
    if hold and not band:
        band, source = {"min_pct": hold["band_min_pct"], "max_pct": hold["band_max_pct"]}, "conviction"
    elif hold and (band["min_pct"], band["max_pct"]) != (hold["band_min_pct"], hold["band_max_pct"]):
        warnings.append(
            f"The plan's band differs from the conviction hold ({hold['band_min_pct']:g} to {hold['band_max_pct']:g}%), and the hold is what the desk enforces."
        )
    if body["role"] == "conviction" and not hold:
        warnings.append(f"{symbol} has no conviction hold yet, so the single-stock cap still applies. Set one in Settings → Risk check.")
    weight = round(ctx["weights"].get(symbol, 0.0), 2) if ctx["weights_as_of"] else None
    where = None
    if band and weight is not None:
        where = "above" if weight > band["max_pct"] else "below" if weight < band["min_pct"] else "inside"
    return {
        "symbol": symbol,
        "version": row["version"],
        "status": row["status"],
        "author": row["author"],
        "run_id": row["run_id"],
        "model": row["model"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "approved_at": row["approved_at"],
        **body,
        "weight_band": band,
        "band_source": source,
        "steps": steps,
        "next_step": _next_step(steps),
        "weight_pct": weight,
        "weight_as_of": ctx["weights_as_of"],
        "band_status": where,
        "conviction": hold,
        "review_due": bool(body["next_review"] and body["next_review"] <= ctx["today"]),
        "warnings": warnings,
    }


def _rows(conn: sqlite3.Connection, symbol: str | None = None) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(LIVE))
    if symbol:
        return conn.execute(f"SELECT * FROM stock_plans WHERE symbol=? AND status IN ({marks}) ORDER BY version", (symbol, *LIVE)).fetchall()
    return conn.execute(f"SELECT * FROM stock_plans WHERE status IN ({marks}) ORDER BY symbol, version", LIVE).fetchall()


def _entries(cfg: Config, conn: sqlite3.Connection, symbol: str | None, now: datetime | None) -> list[dict]:
    by_symbol: dict[str, list[sqlite3.Row]] = {}
    for r in _rows(conn, symbol):
        by_symbol.setdefault(r["symbol"], []).append(r)
    picked = {s: (rows[-1], next((r for r in reversed(rows) if r["status"] == "approved"), None)) for s, rows in by_symbol.items()}
    ctx = _context(cfg, conn, [r for pair in picked.values() for r in pair if r is not None], now)
    out = []
    for s, (latest, live) in sorted(picked.items()):
        entry = _view(conn, latest, ctx)
        entry["approved"] = _view(conn, live, ctx) if live is not None and live["version"] != latest["version"] else None
        entry["versions"] = len(by_symbol[s])
        out.append(entry)
    return out


def list_plans(cfg: Config, *, now: datetime | None = None) -> list[dict]:
    with session(cfg) as conn:
        return _entries(cfg, conn, None, now)


def get_plan(cfg: Config, symbol: str, *, now: datetime | None = None) -> dict | None:
    with session(cfg) as conn:
        found = _entries(cfg, conn, clean_symbol(symbol), now)
    return found[0] if found else None


def history(cfg: Config, symbol: str) -> list[dict]:
    keys = ("version", "status", "author", "run_id", "model", "summary", "created_at", "approved_at")
    with session(cfg) as conn:
        rows = conn.execute(f"SELECT {', '.join(keys)} FROM stock_plans WHERE symbol=? ORDER BY version DESC", (clean_symbol(symbol),)).fetchall()
    return [dict(r) for r in rows]


def get_version(cfg: Config, symbol: str, version: int, *, now: datetime | None = None) -> dict | None:
    with session(cfg) as conn:
        row = conn.execute("SELECT * FROM stock_plans WHERE symbol=? AND version=?", (clean_symbol(symbol), version)).fetchone()
        return _view(conn, row, _context(cfg, conn, [row], now)) if row else None


# ---- Writes ----


def _save(cfg: Config, symbol: str, plan, author: str, *, run_id=None, model=None, summary=None, approve=False, now: datetime | None = None) -> dict:
    symbol = clean_symbol(symbol)
    body = clean(plan, symbol)
    note = _text([], "summary", summary, 400)
    at = now_iso(now)
    with session(cfg) as conn:
        rows = _rows(conn, symbol)
        latest = rows[-1] if rows else None
        skipped = None
        if author == "desk" and latest is not None and latest["status"] == "draft" and latest["author"] == "you":
            skipped = "your_draft"
        else:
            body["steps"] = _merge_steps(loads(latest["body"])["steps"] if latest is not None else [], body["steps"], author)
            sha = digest(body)
            if latest is not None and latest["hash"] == sha:
                skipped = "unchanged"
        with conn:
            if skipped is None:
                version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM stock_plans WHERE symbol=?", (symbol,)).fetchone()[0]
                conn.execute("UPDATE stock_plans SET status='superseded' WHERE symbol=? AND status='draft'", (symbol,))
                conn.execute(
                    "INSERT INTO stock_plans (symbol, version, status, author, run_id, model, summary, hash, body, created_at, approved_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (symbol, version, "approved" if approve else "draft", author, run_id, model, note, sha, dumps(body), at, at if approve else None),
                )
            elif approve and skipped == "unchanged" and latest["status"] == "draft":
                conn.execute("UPDATE stock_plans SET status='approved', approved_at=? WHERE symbol=? AND version=?", (at, symbol, latest["version"]))
        return {"changed": skipped is None, "skipped": skipped, "plan": _entries(cfg, conn, symbol, now)[0]}


def save_draft(
    cfg: Config, symbol: str, plan, *, run_id: str | None = None, model: str | None = None, summary: str | None = None, now: datetime | None = None
) -> dict:
    return _save(cfg, symbol, plan, "desk", run_id=run_id, model=model, summary=summary, now=now)


def save_plan(cfg: Config, symbol: str, plan, *, approve: bool = False, summary: str | None = None, now: datetime | None = None) -> dict:
    return _save(cfg, symbol, plan, "you", summary=summary, approve=approve, now=now)


def approve_plan(cfg: Config, symbol: str, version: int | None = None, *, now: datetime | None = None) -> dict:
    symbol = clean_symbol(symbol)
    with session(cfg) as conn:
        rows = _rows(conn, symbol)
        if not rows:
            raise PlanError(f"{symbol} has no plan yet", 404)
        target = rows[-1] if version is None else next((r for r in rows if r["version"] == version), None)
        if target is None:
            raise PlanError(f"{symbol} has no version {version} to approve", 404)
        changed = target["status"] == "draft"
        if changed:
            with conn:
                conn.execute("UPDATE stock_plans SET status='approved', approved_at=? WHERE symbol=? AND version=?", (now_iso(now), symbol, target["version"]))
        return {"changed": changed, "plan": _entries(cfg, conn, symbol, now)[0]}


def discard_draft(cfg: Config, symbol: str, *, now: datetime | None = None) -> dict:
    symbol = clean_symbol(symbol)
    with session(cfg) as conn:
        rows = _rows(conn, symbol)
        if not rows or rows[-1]["status"] != "draft":
            raise PlanError(f"{symbol} has no draft to discard", 404)
        with conn:
            conn.execute("UPDATE stock_plans SET status='discarded' WHERE symbol=? AND version=?", (symbol, rows[-1]["version"]))
        left = _entries(cfg, conn, symbol, now)
        return {"changed": True, "plan": left[0] if left else None}


def mark_step(cfg: Config, symbol: str, step_id: str, *, on: str | None = None, undo: bool = False, now: datetime | None = None) -> dict:
    from desk.decisions.plan import _today

    symbol = clean_symbol(symbol)
    errors: list[str] = []
    day = _day(errors, "on", on) or _today(cfg, now).isoformat()
    if errors:
        raise PlanError("; ".join(errors))
    with session(cfg) as conn:
        rows = _rows(conn, symbol)
        if not any(s["id"] == step_id for r in rows for s in loads(r["body"])["steps"]):
            raise PlanError(f"{symbol} has no step {step_id!r}", 404)
        with conn:
            if undo:
                conn.execute("DELETE FROM plan_step_state WHERE symbol=? AND step_id=?", (symbol, step_id))
            else:
                conn.execute(
                    "INSERT INTO plan_step_state (symbol, step_id, done_on, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(symbol, step_id) DO UPDATE SET done_on=excluded.done_on, updated_at=excluded.updated_at",
                    (symbol, step_id, day, now_iso(now)),
                )
        return {"changed": True, "plan": _entries(cfg, conn, symbol, now)[0]}


# ---- What the approved plans ask for ----


def approved_plans(cfg: Config, *, now: datetime | None = None) -> list[dict]:
    return [p for e in list_plans(cfg, now=now) if (p := e if e["status"] == "approved" else e["approved"])]


def _line(s: dict) -> str:
    parts = [f"{s['symbol']}: {s['text']}."]
    if s["status"] == "done":
        parts.append(f"Done {s['done_on']}.")
    elif s["due"]:
        window = s["due"] if (s["until"] or s["due"]) == s["due"] else f"{s['due']} to {s['until']}"
        parts.append(f"{'Window' if ' to ' in window else 'Due'} {window} ({s['status']}).")
    elif s["when"]:
        parts.append(f"When: {s['when']}.")
    if s["filled_shares"] and s["status"] != "done":
        parts.append(f"{s['filled_shares']:g} shares so far.")
    if s["account"]:
        parts.append(f"From {s['account']}.")
    if s["lots"]:
        parts.append(f"Lots: {LOT_TEXT[s['lots']]}.")
    if s["no_buy_now"]:
        until = f"until {s['rebuy_on']}" if s["rebuy_on"] else f"until {s['no_buy_days']} days after the sale"
        parts.append(f"No {s['symbol']} buys in any account {until}.")
    if s["note"]:
        parts.append(s["note"] if s["note"].endswith(".") else s["note"] + ".")
    return " ".join(parts)


def open_steps(cfg: Config, *, days: int = 0, now: datetime | None = None) -> list[dict]:
    from desk.decisions.plan import _today

    ahead = (_today(cfg, now) + timedelta(days=max(days, 0))).isoformat()
    out = []
    for p in approved_plans(cfg, now=now):
        for s in p["steps"]:
            if s["status"] in ("open", "partial") or s["no_buy_now"] or (s["status"] == "upcoming" and s["due"] <= ahead):
                out.append(s | {"line": _line(s)})
    return sorted(out, key=lambda s: (s["due"] or "9999", s["symbol"], s["id"]))


def steps_today(cfg: Config, *, now: datetime | None = None) -> list[str]:
    return [s["line"] for s in open_steps(cfg, now=now)]


def no_buy(cfg: Config, *, now: datetime | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in open_steps(cfg, now=now):
        if s["no_buy_now"] and s["symbol"] not in out:
            out[s["symbol"]] = {"from": s["no_buy_from"], "until": s["rebuy_on"], "step_id": s["id"], "reason": s["text"]}
    return out


def plan_events(cfg: Config, start: str, end: str, *, now: datetime | None = None) -> list[dict]:
    events = []
    for p in approved_plans(cfg, now=now):
        sym = p["symbol"]
        if p["next_review"]:
            events.append({"date": p["next_review"], "kind": "note", "title": f"Review the {sym} plan", "source": "plan", "symbol": sym})
        events += [{"date": c["date"], "kind": "note", "title": f"{sym}: {c['text']}", "source": "plan", "symbol": sym} for c in p["catalysts"] if c["date"]]
        for s in p["steps"]:
            base = {"kind": "trade", "source": "plan", "symbol": sym, "step_id": s["id"], "status": s["status"]}
            if s["due"]:
                windowed = bool(s["until"] and s["until"] != s["due"])
                lots = f" ({LOT_TEXT[s['lots']]})" if s["lots"] else ""
                events.append(base | {"date": s["due"], "title": f"{sym}: {s['text']}{': window opens' if windowed else ''}{lots}"})
                if windowed:
                    events.append(base | {"date": s["until"], "title": f"{sym}: {s['text']}: window closes"})
            if s["rebuy_on"]:
                events.append(base | {"date": s["rebuy_on"], "title": f"{sym} buys are fine again"})
    return [e for e in events if start <= e["date"] <= end]
