import json
import math
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.decisions.profile import DESKS, sync
from desk.decisions.profile import profile_path as _profile_path
from desk.decisions.store import dumps, has_mirror, loads, log_event, new_id, now_iso, session
from desk.engine.broker import decision_rows

TRADE_KINDS = ("buy", "sell", "trim", "rebalance", "harvest", "deposit_route")
ADVICE_KINDS = ("hold_off", "alert", "memo")
KINDS = TRADE_KINDS + ADVICE_KINDS
FUNDING = ("cash", "deposit", "sale_proceeds", "margin")
ORIGINS = ("you", *DESKS)
SELL_KINDS = ("sell", "trim", "harvest")
BUY_KINDS = ("buy", "deposit_route")
NOTE_KINDS = ("memo", "alert")
OPEN = ("proposed", "snoozed")
DRIFT_PCT = 10.0
PRICE_GAP_DAYS = 5
CASH_QUALITY = ("ok", "modelled")
NOTE_DAYS = 7
SUBJECT_MAX = 80
REPLACED = "A newer proposal on the same subject replaced this one on {day}."
NOTE_REASON = "A heads-up that needs no decision, so it is kept in the journal."
EXPIRY_TRADING_DAYS = 5
FILL_WINDOW_DAYS = 10
UNMATCHED_DAYS = 90
JSON_FIELDS = ("numbers_used", "sources", "order_ticket", "skeptic", "preflight", "tax_impact", "fill", "valid")


class DecisionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- Time ----


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def trading_days_after(start: date, n: int) -> date:
    day = start
    while n > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


def close_on(day: date, tz: str) -> datetime:
    return datetime.combine(day, time(16, 0), ZoneInfo(tz)).astimezone(UTC)


def expiry(raw, now: datetime, tz: str) -> str:
    if raw in (None, ""):
        local = now.astimezone(ZoneInfo(tz)).date()
        return now_iso(close_on(trading_days_after(local, EXPIRY_TRADING_DAYS), tz))
    text = str(raw)
    try:
        if len(text) == 10:
            return now_iso(close_on(date.fromisoformat(text), tz))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise DecisionError(f"expires must be a date or a date and time, got {text!r}") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz))
    return now_iso(parsed)


def local_day(stamp: str | None, tz: str) -> str | None:
    if not stamp:
        return None
    if len(stamp) == 10:
        return stamp
    return datetime.fromisoformat(stamp).astimezone(ZoneInfo(tz)).date().isoformat()


def day_words(stamp: str | None, tz: str) -> str:
    day = local_day(stamp, tz)
    if not day:
        return "an earlier day"
    d = date.fromisoformat(day)
    return f"{d:%b} {d.day}"


# ---- Shape ----


def _float(value, where: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise DecisionError(f"{where} must be a number")
    try:
        out = float(value)
    except (TypeError, ValueError) as e:
        raise DecisionError(f"{where} must be a number") from e
    if not math.isfinite(out):
        raise DecisionError(f"{where} must be a number")
    return out


def _text(value) -> str | None:
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _slug(value, words: int = 6) -> str:
    return "-".join(re.sub(r"[^a-z ]+", " ", str(value or "").lower()).split()[:words])


def _subject(value) -> str | None:
    text = " ".join(str(value or "").lower().split())
    return text[:SUBJECT_MAX] or None


def subject_of(d: dict) -> str:
    given = _subject(d.get("subject"))
    if given:
        return given
    kind, symbol = d["kind"], d.get("symbol")
    head = "buy" if kind in BUY_KINDS else "sell" if kind in SELL_KINDS else "note" if kind in NOTE_KINDS else kind
    if symbol:
        return f"{head}:{str(symbol).upper()}"
    if head != "note":
        return f"{head}:general"
    return f"note:{_slug(d.get('rule_served')) or _slug(d.get('title')) or 'general'}"[:SUBJECT_MAX]


def _as_of(raw) -> str | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise DecisionError(f"as_of must be a date or a date and time, got {text!r}") from e
    return now_iso(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))


def _valid(p: dict) -> dict | None:
    out = {}
    for key in ("price_min", "price_max", "needs_cash_usd"):
        value = _float(p.get(key), key)
        if value is not None:
            if value < 0:
                raise DecisionError(f"{key} can't be negative")
            out[key] = value
    if "price_min" in out and "price_max" in out and out["price_min"] > out["price_max"]:
        raise DecisionError("price_min can't be above price_max")
    return out or None


def clean(p: dict) -> dict:
    if not isinstance(p, dict):
        raise DecisionError("a proposal must be an object")
    kind = p.get("kind")
    if kind not in KINDS:
        raise DecisionError(f"kind must be one of {', '.join(KINDS)}")
    funding = _text(p.get("funding"))
    if funding is not None and funding not in FUNDING:
        raise DecisionError(f"funding must be one of {', '.join(FUNDING)}")
    amount = _float(p.get("amount_usd", p.get("amount")), "amount_usd")
    shares = _float(p.get("shares"), "shares")
    if amount is not None and amount < 0 or shares is not None and shares < 0:
        raise DecisionError("amount_usd and shares are positive; the kind says which way")
    confidence = _float(p.get("confidence"), "confidence")
    if confidence is not None and not 0 <= confidence <= 1:
        raise DecisionError("confidence is a probability from 0 to 1")
    symbol = _text(p.get("symbol"))
    if kind in TRADE_KINDS:
        if symbol is None:
            raise DecisionError(f"a {kind} needs a symbol")
        if amount is None and shares is None:
            raise DecisionError(f"a {kind} needs amount_usd or shares")
    for key in ("numbers_used", "sources"):
        if p.get(key) is not None and not isinstance(p[key], list):
            raise DecisionError(f"{key} must be a list")
    if p.get("expires") not in (None, ""):
        expiry(p["expires"], datetime.now(UTC), "UTC")
    ticket = p.get("order_ticket")
    if ticket is not None and not isinstance(ticket, dict):
        raise DecisionError("order_ticket must be an object")
    return {
        "kind": kind,
        "title": _text(p.get("title")),
        "symbol": symbol.upper() if symbol else None,
        "account": _text(p.get("account")),
        "amount_usd": amount,
        "shares": shares,
        "funding": funding,
        "thesis": _text(p.get("thesis")),
        "bear_case": _text(p.get("bear_case")),
        "invalidation": _text(p.get("invalidation")),
        "horizon": _text(p.get("horizon")),
        "rule_served": _text(p.get("rule_served")),
        "confidence": confidence,
        "numbers_used": p.get("numbers_used") or [],
        "sources": p.get("sources") or [],
        "order_ticket": ticket,
        "expires": p.get("expires"),
        "subject": _subject(p.get("subject")),
        "as_of": _as_of(p.get("as_of")),
        "valid": _valid(p),
    }


def rejection(c: dict) -> str | None:
    if c["kind"] in ("buy", "sell"):
        if not c["bear_case"]:
            return "A buy or sell needs a bear case."
        if len(c["sources"]) < 2:
            return "A buy or sell needs at least two sources."
    if c["kind"] in TRADE_KINDS and not c["thesis"]:
        return "A trade needs a thesis."
    return None


def default_title(c: dict) -> str:
    verb = {"deposit_route": "Route deposit to", "hold_off": "Hold off on", "harvest": "Harvest"}.get(c["kind"], c["kind"].capitalize())
    size = f"${c['amount_usd']:,.0f} " if c["amount_usd"] is not None else f"{c['shares']:g} shares " if c["shares"] is not None else ""
    return f"{verb} {size}{c['symbol'] or ''}".strip()


# ---- Rows ----


def to_dict(row: sqlite3.Row, events: list[dict] | None = None) -> dict:
    out = dict(row)
    for key in JSON_FIELDS:
        out[key] = loads(out[key])
    out["override"] = bool(out["override"])
    out["decision"] = label(out)
    out["as_of"] = out.get("as_of") or out["created_at"]
    if events is not None:
        out["events"] = events
    return out


def label(d: dict) -> str | None:
    if d["status"] in OPEN:
        return None
    if d["override"]:
        return "override"
    return {"approved": "approved", "placed": "approved", "filled": "approved", "done": "approved"}.get(d["status"], d["status"])


def _get(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise DecisionError("No such decision", 404)
    return row


def _events(conn: sqlite3.Connection, decision_id: str) -> list[dict]:
    rows = conn.execute("SELECT at, event, reason, detail FROM decision_events WHERE decision_id=? ORDER BY seq", (decision_id,))
    return [{**dict(r), "detail": loads(r["detail"])} for r in rows]


def get(cfg: Config, decision_id: str) -> dict:
    with session(cfg) as conn:
        return to_dict(_get(conn, decision_id), _events(conn, decision_id))


def _update(conn: sqlite3.Connection, decision_id: str, at: str, **fields) -> None:
    fields["updated_at"] = at
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE decisions SET {sets} WHERE id=?", (*fields.values(), decision_id))


def _close(conn: sqlite3.Connection, decision_id: str, at: str, event: str, reason: str, detail: dict | None = None, **fields) -> bool:
    fields = {"status": "expired", "decided_at": at, "status_reason": reason, "updated_at": at, **fields}
    sets = ", ".join(f"{k}=?" for k in fields)
    done = conn.execute(f"UPDATE decisions SET {sets} WHERE id=? AND status IN ('proposed', 'snoozed')", (*fields.values(), decision_id)).rowcount == 1
    if done:
        log_event(conn, decision_id, event, reason=reason, detail=detail, at=at)
    return done


# ---- Preflight ----


def side_of(d: dict) -> str | None:
    if d["kind"] in SELL_KINDS:
        return "sell"
    if d["kind"] in ("buy", "deposit_route"):
        return "buy"
    if d["kind"] == "rebalance":
        action = str((d.get("order_ticket") or {}).get("action", "")).lower()
        return "sell" if action.startswith("sell") else "buy" if action.startswith("buy") else None
    return None


def trade_of(d: dict) -> dict:
    ticket = d.get("order_ticket") or {}
    return {
        "kind": d["kind"],
        "symbol": d["symbol"],
        "account": d["account"],
        "side": side_of(d),
        "amount_usd": d["amount_usd"],
        "shares": d["shares"],
        "funding": d["funding"],
        "lot_method": ticket.get("lot_method"),
        "order_type": ticket.get("order_type"),
        "limit": ticket.get("limit"),
    }


def _checker():
    try:
        from desk.engine.preflight import check_trade
    except ImportError:
        return None
    return check_trade


def status_of(result: dict) -> str:
    status = result.get("status")
    if status in ("clear", "flagged", "blocked"):
        return status
    lights = [str(light.get("status", "")).lower() for light in result.get("lights", []) if isinstance(light, dict)]
    if any(s in ("act", "block", "blocked") for s in lights):
        return "blocked"
    if any(s in ("watch", "flag", "flagged") for s in lights):
        return "flagged"
    return "clear"


def run_preflight(cfg: Config, conn: sqlite3.Connection, d: dict, at: str) -> dict:
    if d["kind"] not in TRADE_KINDS and d["kind"] != "hold_off":
        return {"preflight_status": "none"}
    check = _checker()
    if check is None:
        return {"preflight_status": "pending"}
    try:
        result = check(cfg, trade_of(d), ticket_id=d["id"])
    except Exception as e:  # noqa: BLE001
        return {"preflight_status": "error", "preflight": dumps({"error": f"{type(e).__name__}: {e}"}), "preflight_at": at}
    if not isinstance(result, dict):
        return {"preflight_status": "error", "preflight": dumps({"error": "Preflight returned no result"}), "preflight_at": at}
    return {"preflight_status": status_of(result), "preflight": dumps(result), "preflight_at": at, "tax_impact": dumps(result.get("tax"))}


# ---- Create ----


def _insert(cfg: Config, conn: sqlite3.Connection, c: dict, *, origin: str, run_id, status: str, reason: str | None, now: datetime, skeptic=None) -> dict:
    if origin not in ORIGINS:
        raise DecisionError(f"origin must be one of {', '.join(ORIGINS)}")
    profile = sync(conn, _profile_path(cfg))
    at = now_iso(now)
    did = new_id(now)
    expires = expiry(c["expires"], now, cfg.timezone) if status == "proposed" else None
    valid = dict(c["valid"] or {})
    if status == "proposed" and c["symbol"] and c["kind"] in TRADE_KINDS:
        seen = _Facts(conn).latest(c["symbol"])
        if seen:
            valid["price_at"] = seen[0]
    record = {
        "id": did,
        "created_at": at,
        "updated_at": at,
        "origin": origin,
        "run_id": None if run_id is None else str(run_id),
        "kind": c["kind"],
        "title": c["title"] or default_title(c),
        "symbol": c["symbol"],
        "account": c["account"],
        "amount_usd": c["amount_usd"],
        "shares": c["shares"],
        "funding": c["funding"],
        "thesis": c["thesis"],
        "bear_case": c["bear_case"],
        "invalidation": c["invalidation"],
        "horizon": c["horizon"],
        "rule_served": c["rule_served"],
        "confidence": c["confidence"],
        "numbers_used": dumps(c["numbers_used"]),
        "sources": dumps(c["sources"]),
        "order_ticket": dumps(c["order_ticket"]),
        "skeptic": dumps(skeptic),
        "expires_at": expires,
        "status": status,
        "status_reason": reason,
        "profile_version": profile.version,
        "rules_version": profile.rules_version,
        "decided_at": None if status == "proposed" else at,
        "subject": subject_of(c),
        "as_of": c["as_of"],
        "valid": dumps(valid or None),
    }
    with conn:
        conn.execute(f"INSERT INTO decisions ({', '.join(record)}) VALUES ({', '.join('?' * len(record))})", tuple(record.values()))
        log_event(conn, did, status, reason=reason, at=at)
        if status == "proposed" and origin != "you" and record["run_id"] is not None:
            _replace(conn, record, at, cfg.timezone)
    if status == "proposed":
        d = to_dict(_get(conn, did))
        checked = run_preflight(cfg, conn, d, at)
        with conn:
            _update(conn, did, at, **checked)
            if checked["preflight_status"] not in ("none", "pending"):
                log_event(conn, did, "preflight", detail={"status": checked["preflight_status"]}, at=at)
    return to_dict(_get(conn, did))


def _replace(conn: sqlite3.Connection, new: dict, at: str, tz: str) -> int:
    rows = conn.execute(
        "SELECT id, status, snoozed_until FROM decisions WHERE status IN ('proposed', 'snoozed') AND origin=? AND subject=? AND id != ? "
        "AND (run_id IS NULL OR run_id != ?)",
        (new["origin"], new["subject"], new["id"], new["run_id"]),
    ).fetchall()
    reason = REPLACED.format(day=day_words(new["created_at"], tz))
    held = None
    for r in rows:
        if not _close(conn, r["id"], at, "replaced", reason, {"by": new["id"]}, replaced_by=new["id"]):
            continue
        if r["status"] == "snoozed" and r["snoozed_until"] and r["snoozed_until"] > at:
            held = max(held or "", r["snoozed_until"])
    if held and new["status"] == "proposed":
        _update(conn, new["id"], at, status="snoozed", snoozed_until=held)
        log_event(conn, new["id"], "snoozed", reason="Carried over from the proposal this one replaces.", detail={"until": held}, at=at)
    return len(rows)


def create_proposal(cfg: Config, proposal: dict, desk: str, run_id=None, skeptic: dict | None = None, *, now: datetime | None = None) -> dict:
    if desk not in DESKS:
        raise DecisionError(f"desk must be one of {', '.join(DESKS)}")
    try:
        c = clean(proposal)
    except DecisionError as e:
        return reject_proposal(cfg, proposal, desk, f"Malformed proposal: {e}", run_id, now=now)
    reason = rejection(c)
    status = "rejected" if reason else "logged" if c["kind"] in NOTE_KINDS else "proposed"
    with session(cfg) as conn:
        return _insert(cfg, conn, c, origin=desk, run_id=run_id, status=status, reason=reason, now=_now(now), skeptic=skeptic)


def reject_proposal(cfg: Config, proposal: dict, desk: str, reason: str, run_id=None, *, now: datetime | None = None) -> dict:
    if desk not in DESKS:
        raise DecisionError(f"desk must be one of {', '.join(DESKS)}")
    try:
        c = clean(proposal)
    except DecisionError as e:
        c = clean({"kind": "memo", "title": f"Malformed proposal: {e}"})
        if isinstance(proposal, dict) and proposal.get("kind") in KINDS:
            c["kind"] = proposal["kind"]
            c["symbol"] = _text(proposal.get("symbol"))
    with session(cfg) as conn:
        return _insert(cfg, conn, c, origin=desk, run_id=run_id, status="rejected", reason=_text(reason) or "Rejected by the runner", now=_now(now))


def draft(cfg: Config, proposal: dict, *, now: datetime | None = None) -> dict:
    c = clean(proposal)
    if c["kind"] in ("buy", "sell") and not c["thesis"]:
        raise DecisionError("Say why in a sentence or two: a buy or sell needs a thesis.", 422)
    with session(cfg) as conn:
        return _insert(cfg, conn, c, origin="you", run_id=None, status="proposed", reason=None, now=_now(now))


def attach_skeptic(cfg: Config, decision_id: str, verdict: str, counter_case: str, *, now: datetime | None = None) -> dict:
    if verdict not in ("pass", "flag"):
        raise DecisionError("verdict must be pass or flag")
    at = now_iso(_now(now))
    with session(cfg) as conn:
        _get(conn, decision_id)
        with conn:
            _update(conn, decision_id, at, skeptic=dumps({"verdict": verdict, "counter_case": _text(counter_case), "at": at}))
            log_event(conn, decision_id, "skeptic", detail={"verdict": verdict}, at=at)
        return to_dict(_get(conn, decision_id))


# ---- Act ----


def _open(conn: sqlite3.Connection, decision_id: str, at: str) -> dict:
    d = to_dict(_get(conn, decision_id))
    if d["status"] == "proposed" or d["status"] == "snoozed":
        if d["expires_at"] and d["expires_at"] < at:
            reason = "Its window closed before a decision was made."
            with conn:
                _update(conn, decision_id, at, status="expired", decided_at=at, status_reason=reason)
                log_event(conn, decision_id, "expired", reason=reason, detail={"check": "window"}, at=at)
            raise DecisionError("This one expired, so it can't be approved. Draft a fresh one if it still makes sense.", 409)
        return d
    raise DecisionError(f"This decision is already {d['status']}.", 409)


def approve(cfg: Config, decision_id: str, reason: str | None = None, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    reason = _text(reason)
    with session(cfg) as conn:
        d = _open(conn, decision_id, at)
        override = d["preflight_status"] in ("flagged", "blocked")
        if override and not reason:
            raise DecisionError("Preflight lit up. Add a one-line reason to go ahead anyway.", 422)
        status = "approved" if d["kind"] in TRADE_KINDS else "done"
        with conn:
            _update(
                conn, decision_id, at, status=status, decided_at=at, status_reason=reason, override=int(override), override_reason=reason if override else None
            )
            event = "override" if override else "approved_unchecked" if d["preflight_status"] in ("pending", "error") else "approved"
            log_event(conn, decision_id, event, reason=reason, at=at)
        return to_dict(_get(conn, decision_id))


def dismiss(cfg: Config, decision_id: str, reason: str | None = None, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    with session(cfg) as conn:
        _open(conn, decision_id, at)
        with conn:
            _update(conn, decision_id, at, status="dismissed", decided_at=at, status_reason=_text(reason))
            log_event(conn, decision_id, "dismissed", reason=_text(reason), at=at)
        return to_dict(_get(conn, decision_id))


def snooze(cfg: Config, decision_id: str, days: float = 1, reason: str | None = None, *, now: datetime | None = None) -> dict:
    if not 0 < days <= 30:
        raise DecisionError("Snooze for between a few hours and 30 days.")
    moment = _now(now)
    at = now_iso(moment)
    until = now_iso(moment + timedelta(days=days))
    with session(cfg) as conn:
        _open(conn, decision_id, at)
        with conn:
            _update(conn, decision_id, at, status="snoozed", snoozed_until=until, status_reason=_text(reason))
            log_event(conn, decision_id, "snoozed", reason=_text(reason), detail={"until": until}, at=at)
        return to_dict(_get(conn, decision_id))


def pass_on(cfg: Config, decision_id: str, reason: str, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    reason = _text(reason)
    if not reason:
        raise DecisionError("A pass needs a one-line reason so it can be scored later.", 422)
    with session(cfg) as conn:
        d = to_dict(_get(conn, decision_id))
        if d["status"] != "approved":
            _open(conn, decision_id, at)
        with conn:
            _update(conn, decision_id, at, status="passed", decided_at=at, status_reason=reason)
            log_event(conn, decision_id, "passed", reason=reason, at=at)
        return to_dict(_get(conn, decision_id))


def mark_placed(cfg: Config, decision_id: str, shares: float | None = None, price: float | None = None, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    shares = _float(shares, "shares")
    price = _float(price, "price")
    with session(cfg) as conn:
        d = to_dict(_get(conn, decision_id))
        if d["status"] != "approved":
            raise DecisionError("Only an approved trade can be marked placed.", 409)
        detail = {k: v for k, v in (("shares", shares), ("price", price)) if v is not None}
        with conn:
            _update(conn, decision_id, at, status="placed", placed_at=at, fill=dumps({"placed": detail}) if detail else None)
            log_event(conn, decision_id, "placed", detail=detail or None, at=at)
        return to_dict(_get(conn, decision_id))


def add_note(cfg: Config, decision_id: str, text: str, *, now: datetime | None = None) -> dict:
    text = _text(text)
    if not text:
        raise DecisionError("A note needs some text.", 422)
    at = now_iso(_now(now))
    with session(cfg) as conn:
        _get(conn, decision_id)
        with conn:
            log_event(conn, decision_id, "note", reason=text[:2000], at=at)
            _update(conn, decision_id, at)
        return get(cfg, decision_id)


def rerun_preflight(cfg: Config, decision_id: str, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    with session(cfg) as conn:
        d = to_dict(_get(conn, decision_id))
        if d["status"] not in OPEN:
            raise DecisionError("Preflight only re-runs on a decision that is still open.", 409)
        checked = run_preflight(cfg, conn, d, at)
        with conn:
            _update(conn, decision_id, at, **checked)
            if checked["preflight_status"] not in ("none", "pending"):
                log_event(conn, decision_id, "preflight", detail={"status": checked["preflight_status"]}, at=at)
        return to_dict(_get(conn, decision_id))


# ---- Queue and journal ----


class _Facts:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        marks = ("quotes_live", "prices_daily", "metric_values")
        self.tables = {r[0] for r in conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({','.join('?' * len(marks))})", marks)}
        self._latest: dict[str, tuple[float, str] | None] = {}
        self._cash: tuple | None = None

    def latest(self, symbol: str) -> tuple[float, str] | None:
        if symbol not in self._latest:
            found = []
            if "quotes_live" in self.tables:
                q = self.conn.execute("SELECT price, at FROM quotes_live WHERE symbol=? ORDER BY fetched_at DESC LIMIT 1", (symbol,)).fetchone()
                if q and q["price"]:
                    found.append((str(q["at"])[:10], 1, float(q["price"])))
            if "prices_daily" in self.tables:
                c = self.conn.execute("SELECT close, date FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
                if c and c["close"]:
                    found.append((str(c["date"])[:10], 0, float(c["close"])))
            best = max(found) if found else None
            self._latest[symbol] = (best[2], best[0]) if best else None
        return self._latest[symbol]

    def close_on(self, symbol: str, day: str) -> float | None:
        if "prices_daily" not in self.tables:
            return None
        r = self.conn.execute("SELECT close, date FROM prices_daily WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1", (symbol, day)).fetchone()
        if not r or not r["close"] or (date.fromisoformat(day) - date.fromisoformat(str(r["date"])[:10])).days > PRICE_GAP_DAYS:
            return None
        return float(r["close"])

    def cash(self) -> tuple[float, str, str] | None:
        if self._cash is None:
            row = None
            if "metric_values" in self.tables:
                row = self.conn.execute(
                    "SELECT value, as_of, quality FROM metric_values WHERE metric_id='cash.ready' AND scope='portfolio' AND window='now' "
                    "ORDER BY as_of DESC LIMIT 1"
                ).fetchone()
            ok = row is not None and row["value"] is not None and row["quality"] in CASH_QUALITY
            self._cash = ((float(row["value"]), str(row["as_of"])[:10], row["quality"]),) if ok else (None,)
        return self._cash[0]


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _usd(value: float) -> str:
    return f"${value:,.0f}"


def _price_reason(d: dict, facts: _Facts, tz: str) -> str | None:
    symbol = d["symbol"]
    seen = facts.latest(symbol) if symbol else None
    if not seen:
        return None
    price, day = seen
    born = local_day(d["as_of"], tz)
    if day < born:
        return None
    v = d["valid"] or {}
    low, high = v.get("price_min"), v.get("price_max")
    if low is not None or high is not None:
        zone = (
            f"{_money(low)} to {_money(high)} zone"
            if low is not None and high is not None
            else f"{_money(low)} floor"
            if high is None
            else f"{_money(high)} ceiling"
        )
        if low is not None and price < low:
            return f"{symbol} is at {_money(price)}, below the {zone} this was written for."
        if high is not None and price > high:
            return f"{symbol} is at {_money(price)}, above the {zone} this was written for."
        return None
    if d["origin"] == "you" or d["kind"] not in TRADE_KINDS:
        return None
    base = v.get("price_at") or facts.close_on(symbol, born)
    if not base or (day == born and not v.get("price_at")):
        return None
    moved = (price / base - 1) * 100
    if abs(moved) <= DRIFT_PCT:
        return None
    way = "up" if moved > 0 else "down"
    return (
        f"{symbol} is {way} {abs(moved):.0f}% since this was written on {day_words(d['as_of'], tz)} "
        f"({_money(base)} then, {_money(price)} now), so its numbers no longer hold."
    )


def _cash_reason(d: dict, facts: _Facts, tz: str) -> str | None:
    needs = (d["valid"] or {}).get("needs_cash_usd")
    if needs is None and d["origin"] != "you" and d["kind"] in BUY_KINDS and d["funding"] == "cash":
        needs = d["amount_usd"]
    seen = facts.cash() if needs else None
    if not seen:
        return None
    ready, day, quality = seen
    if day <= local_day(d["as_of"], tz) or ready >= needs - 0.005:
        return None
    rough = " (estimated)" if quality != "ok" else ""
    return f"Ready cash is {_usd(max(ready, 0.0))} as of {day_words(day, tz)}{rough}, less than the {_usd(needs)} this needs."


def stale_reason(d: dict, facts: _Facts, at: str, tz: str) -> tuple[str, str] | None:
    if d["expires_at"] and d["expires_at"] < at:
        return "window", f"Its window closed on {day_words(d['expires_at'], tz)}."
    reason = _price_reason(d, facts, tz)
    if reason:
        return "price", reason
    reason = _cash_reason(d, facts, tz)
    return ("cash", reason) if reason else None


def tidy(cfg: Config, conn: sqlite3.Connection, at: str) -> dict:
    tz = cfg.timezone
    out = {"notes": 0, "replaced": 0, "expired": 0}
    rows = [to_dict(r) for r in conn.execute("SELECT * FROM decisions WHERE status IN ('proposed', 'snoozed') ORDER BY created_at, rowid")]
    if not rows:
        return out
    facts = _Facts(conn)
    newest: dict[tuple[str, str], dict] = {}
    with conn:
        for d in rows:
            if not d["subject"]:
                d["subject"] = subject_of(d)
                conn.execute("UPDATE decisions SET subject=? WHERE id=?", (d["subject"], d["id"]))
            if d["origin"] != "you" and d["kind"] in NOTE_KINDS:
                out["notes"] += _close(conn, d["id"], at, "logged", NOTE_REASON, status="logged", expires_at=None)
                d["status"] = "logged"
            elif d["origin"] != "you":
                newest[(d["origin"], d["subject"])] = d
        for d in rows:
            if d["status"] not in OPEN:
                continue
            top = newest.get((d["origin"], d["subject"]))
            if top and top["id"] != d["id"] and d["run_id"] != top["run_id"]:
                reason = REPLACED.format(day=day_words(top["created_at"], tz))
                out["replaced"] += _close(conn, d["id"], at, "replaced", reason, {"by": top["id"]}, replaced_by=top["id"])
                continue
            found = stale_reason(d, facts, at, tz)
            if found:
                out["expired"] += _close(conn, d["id"], at, "expired", found[1], {"check": found[0]})
    return out


def queue(cfg: Config, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    with session(cfg) as conn:
        tidy(cfg, conn, at)
        rows = conn.execute(
            "SELECT * FROM decisions WHERE status='proposed' OR (status='snoozed' AND snoozed_until <= ?) "
            "ORDER BY expires_at IS NULL, expires_at, created_at DESC",
            (at,),
        ).fetchall()
        snoozed = conn.execute("SELECT COUNT(*) FROM decisions WHERE status='snoozed' AND snoozed_until > ?", (at,)).fetchone()[0]
        waiting = conn.execute("SELECT COUNT(*) FROM decisions WHERE status='approved'").fetchone()[0]
    items = [to_dict(r) for r in rows]
    return {"count": len(items), "snoozed": snoozed, "to_place": waiting, "items": items}


def notes(cfg: Config, *, days: int = NOTE_DAYS, now: datetime | None = None) -> dict:
    moment = _now(now)
    since = now_iso(moment - timedelta(days=max(1, min(int(days), 90))))
    marks = ",".join("?" * len(NOTE_KINDS))
    with session(cfg) as conn:
        tidy(cfg, conn, now_iso(moment))
        rows = conn.execute(
            f"SELECT * FROM decisions WHERE status='logged' AND origin != 'you' AND kind IN ({marks}) AND created_at >= ? ORDER BY created_at DESC, rowid DESC",
            (*NOTE_KINDS, since),
        ).fetchall()
    seen: set[tuple[str, str]] = set()
    items = []
    for r in rows:
        d = to_dict(r)
        key = (d["origin"], d["subject"] or subject_of(d))
        if key in seen:
            continue
        seen.add(key)
        items.append(d)
    return {"count": len(items), "days": days, "items": items}


def tidy_now(cfg: Config, *, now: datetime | None = None) -> dict:
    at = now_iso(_now(now))
    with session(cfg) as conn:
        moved = tidy(cfg, conn, at)
        waiting = conn.execute("SELECT COUNT(*) FROM decisions WHERE status='proposed' OR (status='snoozed' AND snoozed_until <= ?)", (at,)).fetchone()[0]
    return {**moved, "waiting": waiting}


def _scores(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metric_values'").fetchone():
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT scope_id, window, value, as_of FROM metric_values "
        f"WHERE scope='decision' AND metric_id LIKE 'dec.score%' AND scope_id IN ({marks}) ORDER BY as_of",
        ids,
    )
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["scope_id"], {})[r["window"]] = r["value"]
    return out


def journal(
    cfg: Config,
    *,
    origin: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> dict:
    where = ["status NOT IN ('proposed', 'snoozed')"]
    args: list = []
    for column, value in (("origin", origin), ("kind", kind), ("status", status), ("symbol", symbol.upper() if symbol else None)):
        if value:
            where.append(f"{column}=?")
            args.append(value)
    stamp = "COALESCE(filled_at, decided_at, created_at)"
    if since:
        where.append(f"{stamp} >= ?")
        args.append(since)
    if until:
        where.append(f"{stamp} < ?")
        args.append(until)
    limit = max(1, min(int(limit), 500))
    with session(cfg) as conn:
        tidy(cfg, conn, now_iso(_now(now)))
        rows = conn.execute(f"SELECT * FROM decisions WHERE {' AND '.join(where)} ORDER BY {stamp} DESC, rowid DESC LIMIT ?", (*args, limit)).fetchall()
        items = [to_dict(r) for r in rows]
        scores = _scores(conn, [d["id"] for d in items])
    days: list[dict] = []
    for d in items:
        d["day"] = local_day(d["filled_at"] or d["decided_at"] or d["created_at"], cfg.timezone)
        d["scores"] = scores.get(d["id"], {})
        if not days or days[-1]["day"] != d["day"]:
            days.append({"day": d["day"], "items": []})
        days[-1]["items"].append(d)
    return {"days": days, "count": len(items)}


def desk_history(cfg: Config, desk: str, limit: int = 20, *, now: datetime | None = None) -> list[dict]:
    with session(cfg) as conn:
        tidy(cfg, conn, now_iso(_now(now)))
        rows = conn.execute("SELECT * FROM decisions WHERE origin=? ORDER BY created_at DESC, rowid DESC LIMIT ?", (desk, limit)).fetchall()
    out = []
    for r in rows:
        d = to_dict(r)
        out.append(
            {
                "id": d["id"],
                "created_at": d["created_at"],
                "kind": d["kind"],
                "title": d["title"],
                "symbol": d["symbol"],
                "amount_usd": d["amount_usd"],
                "confidence": d["confidence"],
                "preflight_status": d["preflight_status"],
                "decision": d["decision"] or "open",
                "reason": d["override_reason"] or d["status_reason"],
            }
        )
    return out


def scoring_rows(cfg: Config, since: str | None = None) -> list[dict]:
    cols = (
        "id, origin, run_id, kind, symbol, account, amount_usd, shares, funding, status, override, confidence, horizon, "
        "preflight_status, tax_impact, profile_version, rules_version, created_at, decided_at, placed_at, filled_at, fill"
    )
    with session(cfg) as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM decisions WHERE kind != 'rule_change' AND status NOT IN ('proposed', 'snoozed') AND created_at >= ? ORDER BY created_at",
            (since or "",),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["override"] = bool(d["override"])
        d["tax_impact"] = loads(d["tax_impact"])
        d["fill"] = loads(d["fill"])
        out.append(d)
    return out


# ---- Fills from the mirror ----


def mirror_trades(conn: sqlite3.Connection, since: str) -> list[dict]:
    try:
        rows = decision_rows(conn, since or None)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for rid, a in rows:
        if a.get("kind") not in ("buy", "sell") or a.get("core") or not a.get("symbol") or str(a.get("date", "")) < since:
            continue
        out.append({"activity_id": rid, **a, "symbol": str(a["symbol"]).upper()})
    return out


def _taken(conn: sqlite3.Connection, trades: list[dict]) -> set[str]:
    linked = {r[0] for r in conn.execute("SELECT activity_id FROM decisions WHERE activity_id IS NOT NULL")}
    missing = linked - {a["activity_id"] for a in trades}
    if not missing or not has_mirror(conn):
        return linked
    taken = set(linked)
    for rid in sorted(missing):
        row = conn.execute("SELECT json FROM mirror.rows WHERE tbl='activity' AND id=?", (rid,)).fetchone()
        try:
            m = json.loads(row["json"]) if row else None
        except (TypeError, ValueError):
            m = None
        if not isinstance(m, dict) or not m.get("date"):
            continue
        day, amount = date.fromisoformat(str(m["date"])[:10]), abs(m.get("amount") or 0)
        twin = next(
            (
                a
                for a in trades
                if a["activity_id"] not in taken
                and a.get("source") == "broker"
                and a["symbol"] == str(m.get("symbol") or "").upper()
                and a["kind"] == m.get("kind")
                and a.get("accountKey") == m.get("accountKey")
                and abs((date.fromisoformat(str(a["date"])[:10]) - day).days) <= 3
                and abs(abs(a.get("amount") or 0) - amount) <= max(0.02, 0.005 * amount)
            ),
            None,
        )
        if twin:
            taken.add(twin["activity_id"])
    return taken


def _account_ok(want: str | None, key: str | None) -> bool:
    if not want or not key:
        return True
    w, k = want.lower().replace(" ", ""), key.lower().replace(" ", "")
    return w in k or k in w


def _size_ok(d: dict, a: dict) -> bool:
    qty = abs(a.get("quantity") or 0)
    amt = abs(a.get("amount") or 0)
    if d["shares"]:
        return qty > 0 and abs(qty - d["shares"]) <= max(0.001, d["shares"] * 0.01)
    if d["amount_usd"]:
        return amt > 0 and abs(amt - d["amount_usd"]) <= max(5.0, d["amount_usd"] * 0.05)
    return True


def match_fill(d: dict, trades: list[dict], taken: set[str], tz: str) -> dict | None:
    side = side_of(d)
    start = date.fromisoformat(local_day(d["placed_at"] or d["decided_at"], tz)) - timedelta(days=1)
    end = start + timedelta(days=FILL_WINDOW_DAYS + 1)
    hits = [
        a
        for a in trades
        if a["activity_id"] not in taken
        and a["symbol"] == d["symbol"]
        and a["kind"] == side
        and start.isoformat() <= str(a["date"]) <= end.isoformat()
        and _account_ok(d["account"], a.get("accountKey"))
        and _size_ok(d, a)
    ]
    return min(hits, key=lambda a: abs((date.fromisoformat(str(a["date"])) - start).days)) if hits else None


def confirm_fills(cfg: Config, *, now: datetime | None = None) -> list[str]:
    at = now_iso(_now(now))
    filled = []
    with session(cfg) as conn:
        pending = [to_dict(r) for r in conn.execute("SELECT * FROM decisions WHERE status='placed' ORDER BY placed_at")]
        if not pending:
            return []
        earliest = min(local_day(d["placed_at"], cfg.timezone) for d in pending)
        trades = mirror_trades(conn, (date.fromisoformat(earliest) - timedelta(days=1)).isoformat())
        taken = _taken(conn, trades)
        for d in pending:
            hit = match_fill(d, trades, taken, cfg.timezone)
            if hit is None:
                continue
            taken.add(hit["activity_id"])
            fill = {
                **(d["fill"] or {}),
                "activity_id": hit["activity_id"],
                "date": hit["date"],
                "shares": abs(hit.get("quantity") or 0) or None,
                "price": hit.get("price"),
                "amount": abs(hit.get("amount") or 0),
            }
            with conn:
                _update(conn, d["id"], at, status="filled", filled_at=str(hit["date"]), activity_id=hit["activity_id"], fill=dumps(fill))
                log_event(conn, d["id"], "filled", detail={"activity_id": hit["activity_id"], "date": hit["date"]}, at=at)
            filled.append(d["id"])
    return filled


def unmatched(cfg: Config, *, days: int = UNMATCHED_DAYS, now: datetime | None = None) -> list[dict]:
    since = (_now(now).astimezone(ZoneInfo(cfg.timezone)).date() - timedelta(days=days)).isoformat()
    with session(cfg) as conn:
        trades = mirror_trades(conn, since)
        taken = _taken(conn, trades)
    keep = ("activity_id", "date", "accountKey", "kind", "symbol", "quantity", "price", "amount")
    return sorted(({k: a.get(k) for k in keep} for a in trades if a["activity_id"] not in taken), key=lambda a: str(a["date"]), reverse=True)


def log_trade(cfg: Config, activity_id: str, thesis: str | None = None, reason: str | None = None, *, now: datetime | None = None) -> dict:
    moment = _now(now)
    at = now_iso(moment)
    with session(cfg) as conn:
        hit = next((a for a in mirror_trades(conn, "") if a["activity_id"] == activity_id), None)
        if hit is None:
            raise DecisionError("That trade isn't in the mirror.", 404)
        if conn.execute("SELECT 1 FROM decisions WHERE activity_id=?", (activity_id,)).fetchone():
            raise DecisionError("That trade already has a decision record.", 409)
        profile = sync(conn, _profile_path(cfg))
        did = new_id(moment)
        c = clean(
            {
                "kind": hit["kind"],
                "symbol": hit["symbol"],
                "account": hit.get("accountKey"),
                "amount_usd": abs(hit.get("amount") or 0) or None,
                "shares": abs(hit.get("quantity") or 0) or None,
                "thesis": thesis,
            }
        )
        fill = {"activity_id": activity_id, "date": hit["date"], "shares": c["shares"], "price": hit.get("price"), "amount": c["amount_usd"]}
        record = {
            "id": did,
            "created_at": at,
            "updated_at": at,
            "origin": "you",
            "kind": c["kind"],
            "title": default_title(c),
            "symbol": c["symbol"],
            "account": c["account"],
            "amount_usd": c["amount_usd"],
            "shares": c["shares"],
            "thesis": c["thesis"],
            "status": "filled",
            "status_reason": _text(reason),
            "preflight_status": "none",
            "profile_version": profile.version,
            "rules_version": profile.rules_version,
            "decided_at": str(hit["date"]),
            "filled_at": str(hit["date"]),
            "fill": dumps(fill),
            "activity_id": activity_id,
        }
        with conn:
            conn.execute(f"INSERT INTO decisions ({', '.join(record)}) VALUES ({', '.join('?' * len(record))})", tuple(record.values()))
            log_event(conn, did, "logged_after", reason=_text(reason), detail={"activity_id": activity_id}, at=at)
        return to_dict(_get(conn, did))


# ---- Summary ----


def summary(cfg: Config, *, now: datetime | None = None) -> dict:
    moment = _now(now)
    at = now_iso(moment)
    today = moment.astimezone(ZoneInfo(cfg.timezone)).date()
    since = (today - timedelta(days=UNMATCHED_DAYS)).isoformat()
    loose = unmatched(cfg, now=moment)
    with session(cfg) as conn:
        tidy(cfg, conn, at)
        waiting = conn.execute("SELECT COUNT(*) FROM decisions WHERE status='proposed' OR (status='snoozed' AND snoozed_until <= ?)", (at,)).fetchone()[0]
        approved = conn.execute(
            "SELECT override, COUNT(*) n FROM decisions WHERE status IN ('approved', 'placed', 'filled', 'done') GROUP BY override"
        ).fetchall()
        linked = conn.execute("SELECT COUNT(*) FROM decisions WHERE activity_id IS NOT NULL AND filled_at >= ?", (since,)).fetchone()[0]
        late = conn.execute(
            "SELECT COUNT(*) FROM decisions d WHERE activity_id IS NOT NULL AND filled_at >= ? "
            "AND EXISTS (SELECT 1 FROM decision_events e WHERE e.decision_id = d.id AND e.event = 'logged_after')",
            (since,),
        ).fetchone()[0]
        after = conn.execute("SELECT MAX(filled_at) FROM decisions d JOIN decision_events e ON e.decision_id = d.id WHERE e.event = 'logged_after'").fetchone()[
            0
        ]
        first = conn.execute("SELECT MIN(created_at) FROM decisions").fetchone()[0]
    counts = {bool(r["override"]): r["n"] for r in approved}
    breaks = [d for d in (after, *(a["date"] for a in loose)) if d]
    start = max(breaks) if breaks else local_day(first, cfg.timezone)
    streak = (today - date.fromisoformat(start)).days if start else 0
    total = linked + len(loose)
    return {
        "waiting": waiting,
        "clean": counts.get(False, 0),
        "overrides": counts.get(True, 0),
        "unmatched": len(loose),
        "logged_after": late,
        "coverage": None if total == 0 else round((linked - late) / total, 4),
        "coverage_window_days": UNMATCHED_DAYS,
        "streak_days": max(streak, 0),
    }
