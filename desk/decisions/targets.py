import copy
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from desk.config import Config
from desk.decisions.profile import LOT_METHODS, ProfileError, active_profile, parse
from desk.decisions.yamlfile import replace_section, write_with_backup

TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
SIDES = ("sell", "buy")
NEW_MONEY = ("underweight_first", "pro_rata")
PRESETS: dict[str, dict] = {
    "v3": {
        "targets": {
            "preset": "v3",
            "funds": [
                {"ticker": "FXAIX", "weight_pct": 40, "sleeve": "US core"},
                {"ticker": "SCHD", "weight_pct": 20, "sleeve": "Dividend"},
                {"ticker": "FTIHX", "weight_pct": 10, "sleeve": "International"},
                {"ticker": "FTEC", "weight_pct": 10, "sleeve": "Tech"},
                {"ticker": "NLR", "weight_pct": 5, "sleeve": "Nuclear"},
                {"ticker": "GRID", "weight_pct": 5, "sleeve": "Grid"},
                {"ticker": "ICLN", "weight_pct": 5, "sleeve": "Clean energy"},
                {"ticker": "UFO", "weight_pct": 5, "sleeve": "Space"},
            ],
            "hold": ["SPY"],
            "steer_drift_pts": 5,
            "new_money": "underweight_first",
            "outside": [{"account": "401k", "proxy": {"SPY": 80, "ISTNX": 20}, "note": "Managed in the 401(k); the desk doesn't steer it"}],
        },
        "rules": [
            {"id": "no-margin-buys", "kind": "no_margin_buys"},
            {"id": "no-new-single-stocks", "kind": "no_new_single_stocks"},
            {"id": "single-stock-band", "kind": "single_stock_band", "params": {"min_pct": 0, "max_pct": 15, "trim_to_pct": 10}},
            {"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": 5}},
        ],
    }
}


class TargetsError(Exception):
    pass


# ---- Validation ----


def symbols_of(a: dict) -> list[str]:
    raw = a.get("symbols") if a.get("symbols") is not None else [a.get("symbol")] if a.get("symbol") else []
    return [str(x).upper() for x in raw] if isinstance(raw, list) else []


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def validate_targets(t) -> list[str]:
    if t in (None, {}):
        return []
    if not isinstance(t, dict):
        return ["targets must be a mapping"]
    errors: list[str] = []
    funds = t.get("funds")
    if not isinstance(funds, list) or not funds:
        return ["targets.funds must list at least one fund"]
    seen: set[str] = set()
    for i, f in enumerate(funds):
        where = f"targets.funds[{i}]"
        if not isinstance(f, dict) or not TICKER.match(str(f.get("ticker") or "")):
            errors.append(f"{where} needs a ticker like FXAIX")
            continue
        if f["ticker"] in seen:
            errors.append(f"{where}: {f['ticker']} is listed twice")
        seen.add(f["ticker"])
        w = f.get("weight_pct")
        if isinstance(w, bool) or not isinstance(w, int | float) or not 0 < w <= 100:
            errors.append(f"{where}.weight_pct must be a number above 0 and up to 100")
    total = sum(f.get("weight_pct") or 0 for f in funds if isinstance(f, dict) and isinstance(f.get("weight_pct"), int | float))
    if not errors and abs(total - 100) > 0.01:
        errors.append(f"targets.funds weights add to {total:g}, not 100")
    hold = t.get("hold", [])
    if not isinstance(hold, list) or not all(isinstance(h, str) and TICKER.match(h) for h in hold):
        errors.append("targets.hold must list tickers")
    elif set(hold) & seen:
        errors.append("targets.hold can't repeat a target fund")
    pts = t.get("steer_drift_pts", 5)
    if isinstance(pts, bool) or not isinstance(pts, int | float) or not 0 < pts <= 50:
        errors.append("targets.steer_drift_pts must be between 0 and 50")
    if t.get("new_money", "underweight_first") not in NEW_MONEY:
        errors.append(f"targets.new_money must be one of {', '.join(NEW_MONEY)}")
    outside = t.get("outside", [])
    if not isinstance(outside, list):
        errors.append("targets.outside must be a list")
    for i, o in enumerate(outside if isinstance(outside, list) else []):
        proxy = o.get("proxy", {}) if isinstance(o, dict) else None
        if not isinstance(o, dict) or not isinstance(o.get("account"), str) or not o["account"].strip():
            errors.append(f"targets.outside[{i}] needs an account")
        elif not isinstance(proxy, dict) or not all(TICKER.match(str(k)) and isinstance(v, int | float) and v > 0 for k, v in proxy.items()):
            errors.append(f"targets.outside[{i}].proxy must map tickers to percents")
    return errors


def validate_actions(actions) -> list[str]:
    if actions in (None, []):
        return []
    if not isinstance(actions, list):
        return ["actions must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for i, a in enumerate(actions):
        where = f"actions[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{where} must be a mapping")
            continue
        if not isinstance(a.get("id"), str) or not a["id"].strip():
            errors.append(f"{where} needs an id")
        elif a["id"] in seen:
            errors.append(f"{where}: id {a['id']!r} is used twice")
        else:
            seen.add(a["id"])
        if a.get("side") not in SIDES:
            errors.append(f"{where}.side must be sell or buy")
        if not symbols_of(a) or not all(TICKER.match(x) for x in symbols_of(a)):
            errors.append(f"{where} needs a symbol (or symbols) as tickers")
        shares = a.get("shares", "all")
        if shares != "all" and (isinstance(shares, bool) or not isinstance(shares, int | float) or shares <= 0):
            errors.append(f"{where}.shares must be a positive number or all")
        elif shares != "all" and len(symbols_of(a)) > 1:
            errors.append(f"{where}: a share count needs a single symbol")
        if "account" in a and (not isinstance(a["account"], str) or not a["account"].strip()):
            errors.append(f"{where}.account must be a name")
        start, end = _day(a.get("from")), _day(a.get("to"))
        if start is None or end is None:
            errors.append(f"{where}.from and .to must be dates like 2026-12-07")
        elif end < start:
            errors.append(f"{where}.to is before .from")
        if "lots" in a and a["lots"] not in LOT_METHODS:
            errors.append(f"{where}.lots must be one of {', '.join(LOT_METHODS)}")
        days = a.get("no_buy_days", 0)
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 400:
            errors.append(f"{where}.no_buy_days must be a whole number of days")
    return errors


# ---- The plan the engine reads ----


def profile_plan(profile) -> dict | None:
    t = profile.get("targets", default={}) or {}
    if not t.get("funds"):
        return None
    pts = t.get("steer_drift_pts", 5)
    return {
        "source": "profile",
        "preset": t.get("preset"),
        "funds": [{"ticker": f["ticker"], "sleeve": f.get("sleeve") or f["ticker"], "target_weight": f["weight_pct"] / 100} for f in t["funds"]],
        "hold": list(t.get("hold") or []),
        "outside": copy.deepcopy(t.get("outside") or []),
        "new_money": t.get("new_money", "underweight_first"),
        "guardrails": {"drift_alert_pct_points": pts},
    }


def plan_for(cfg: Config, mirror_plan: dict | None = None) -> dict:
    try:
        mine = profile_plan(active_profile(cfg))
    except Exception:  # noqa: BLE001
        mine = None
    return mine or (mirror_plan or {})


# ---- Writing desk.yaml ----


def _merged_rules(current: list[dict], preset: list[dict]) -> list[dict]:
    kinds = {r["kind"] for r in preset}
    kept = [r for r in current if r.get("kind") not in kinds and r.get("id") not in {p["id"] for p in preset}]
    return [*copy.deepcopy(preset), *kept]


def _dump(key: str, value) -> str:
    return yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False)


def set_plan(path: Path, preset: str) -> tuple[bool, str]:
    if preset not in PRESETS:
        raise TargetsError(f"Unknown preset {preset!r}. Known: {', '.join(sorted(PRESETS))}.")
    if not path.exists():
        raise TargetsError(f"{path} doesn't exist. Run `profile init` first.")
    text = path.read_text()
    parse(text)
    raw = yaml.safe_load(text) or {}
    want = PRESETS[preset]
    rules = _merged_rules(raw.get("rules") or [], want["rules"])
    if raw.get("targets") == want["targets"] and (raw.get("rules") or []) == rules:
        return False, f"{path} already has the {preset} plan. Nothing changed."
    out = replace_section(replace_section(text, "targets", _dump("targets", want["targets"])), "rules", _dump("rules", rules))
    try:
        parse(out)
    except ProfileError as e:
        raise TargetsError(f"The {preset} plan didn't validate ({e}); nothing changed.") from e
    backup = write_with_backup(path, out)
    return True, f"{path} now has the {preset} plan ({len(want['targets']['funds'])} funds). The old file is at {backup}."


def add_action(path: Path, action: dict) -> tuple[bool, str]:
    if not path.exists():
        raise TargetsError(f"{path} doesn't exist. Run `profile init` first.")
    errors = validate_actions([action])
    if errors:
        raise TargetsError("; ".join(errors))
    text = path.read_text()
    parse(text)
    raw = yaml.safe_load(text) or {}
    current = [a for a in raw.get("actions") or [] if isinstance(a, dict)]
    if action in current:
        return False, f"{path} already has action {action['id']}. Nothing changed."
    actions = [a for a in current if a.get("id") != action["id"]] + [action]
    out = replace_section(text, "actions", _dump("actions", actions))
    try:
        parse(out)
    except ProfileError as e:
        raise TargetsError(f"The action didn't validate ({e}); nothing changed.") from e
    backup = write_with_backup(path, out)
    what = _what(action.get("shares", "all"), symbols_of(action))
    return True, f"{path} now plans {action['side']} {what} ({action['id']}). The old file is at {backup}."


# ---- Planned actions ----


def _what(shares, symbols: list[str]) -> str:
    if shares != "all":
        return f"{shares:g} {symbols[0]}"
    return " and ".join(symbols) if len(symbols) > 1 else f"all {symbols[0]}"


def _done(a: dict, trades: list[dict]) -> dict[str, dict]:
    lo = date.fromisoformat(str(a["from"])) - timedelta(days=3)
    hi = date.fromisoformat(str(a["to"])) + timedelta(days=3)
    hits: dict[str, dict] = {}
    for t in sorted(trades, key=lambda t: str(t["date"])):
        day = _day(str(t["date"])[:10])
        if t["symbol"] in symbols_of(a) and t["symbol"] not in hits and t["kind"] == a["side"] and day and lo <= day <= hi:
            hits[t["symbol"]] = t
    return hits


def planned_actions(cfg: Config, *, now: datetime | None = None) -> list[dict]:
    from desk.decisions.plan import _today
    from desk.decisions.records import mirror_trades
    from desk.decisions.store import session

    today = _today(cfg, now)
    actions = active_profile(cfg).get("actions", default=[]) or []
    if not actions:
        return []
    earliest = min(str(a["from"]) for a in actions)
    with session(cfg) as conn:
        trades = mirror_trades(conn, (date.fromisoformat(earliest) - timedelta(days=3)).isoformat())
    out = []
    for a in actions:
        start, end = date.fromisoformat(str(a["from"])), date.fromisoformat(str(a["to"]))
        symbols = symbols_of(a)
        hits = _done(a, trades)
        done = len(hits) == len(symbols)
        status = "done" if done else "open" if start <= today <= end else "upcoming" if today < start else "passed"
        done_on = max(str(t["date"])[:10] for t in hits.values()) if done else None
        days = int(a.get("no_buy_days") or 0)
        free = (date.fromisoformat(done_on) + timedelta(days=days)).isoformat() if done_on and days else None
        shares = a.get("shares", "all")
        what = _what(shares, symbols)
        out.append(
            {
                **a,
                "symbols": symbols,
                "shares": shares,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "title": f"{a['side'].capitalize()} {what}",
                "status": status,
                "done_on": done_on,
                "done": sorted(hits),
                "activity_ids": [hits[s]["activity_id"] for s in sorted(hits)],
                "no_buy_until": free,
                "no_buy_now": bool(free and today.isoformat() < free),
            }
        )
    return sorted(out, key=lambda a: (a["from"], a["id"]))


def action_events(items: list[dict], start: str, end: str) -> list[dict]:
    events = []
    for a in items:
        lots = f", {a['lots'].replace('_', '-')} lots" if a.get("lots") else ""
        events.append({"date": a["from"], "kind": "trade", "title": f"{a['title']} window opens{lots}", "source": "plan", "status": a["status"]})
        events.append({"date": a["to"], "kind": "trade", "title": f"{a['title']} window closes", "source": "plan", "status": a["status"]})
        if a["no_buy_until"]:
            names = " and ".join(a["symbols"])
            events.append({"date": a["no_buy_until"], "kind": "trade", "title": f"{names} buys are fine again", "source": "plan", "status": a["status"]})
    return [e for e in events if start <= e["date"] <= end]


def describe(items: list[dict]) -> list[str]:
    lines = []
    for a in items:
        names = " and ".join(a["symbols"])
        if a["status"] == "done":
            tail = f" Done {a['done_on']}." + (f" No {names} buys until {a['no_buy_until']}." if a["no_buy_now"] else "")
        else:
            tail = f" Window {a['from']} to {a['to']} ({a['status']})."
            if a["done"]:
                tail += f" Done so far: {', '.join(a['done'])}."
            if a.get("no_buy_days"):
                tail += f" Then no {names} buys for {a['no_buy_days']} days."
        where = f" From {a['account']}." if a.get("account") else ""
        lots = f" Lots: {a['lots'].replace('_', ' ')}." if a.get("lots") else ""
        note = f" {a['note']}" if a.get("note") else ""
        lines.append(f"{a['title']}.{where}{tail}{lots}{note}")
    return lines
