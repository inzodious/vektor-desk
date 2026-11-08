import json
import sqlite3

from desk.config import Config
from desk.decisions.store import dumps, log_event, new_id, now_iso, session

KINDS: dict[str, dict[str, tuple[float, float]]] = {
    "no_margin_buys": {},
    "no_new_single_stocks": {},
    "single_stock_band": {"min_pct": (0, 100), "max_pct": (0, 100)},
    "drift_max_pts": {"pts": (0, 100)},
    "cash_floor_pct": {"pct": (0, 100)},
    "conviction_hold": {"band_min_pct": (0, 100), "band_max_pct": (0, 100)},
}

LABELS = {
    "no_margin_buys": "No buying on margin",
    "no_new_single_stocks": "No new single stocks",
    "single_stock_band": "Single-stock band",
    "drift_max_pts": "Drift limit",
    "cash_floor_pct": "Cash floor",
    "conviction_hold": "Conviction hold",
}


def validate_rules(rules) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(rules, list):
        return ["rules must be a list"], warnings
    seen: set[str] = set()
    held: set[str] = set()
    for i, rule in enumerate(rules):
        where = f"rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{where} must be a mapping with id and kind")
            continue
        rid, kind = rule.get("id"), rule.get("kind")
        if not isinstance(rid, str) or not rid.strip():
            errors.append(f"{where} needs an id")
        elif rid in seen:
            errors.append(f"{where}: id {rid!r} is used twice")
        else:
            seen.add(rid)
        if kind not in KINDS:
            warnings.append(f"{where}: kind {kind!r} is not one the engine checks yet")
            continue
        params = rule.get("params") or {}
        if not isinstance(params, dict):
            errors.append(f"{where}.params must be a mapping")
            continue
        for name, (low, high) in KINDS[kind].items():
            value = params.get(name)
            if value is None:
                errors.append(f"{where}.params.{name} is required for {kind}")
            elif isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
                errors.append(f"{where}.params.{name} must be a number from {low} to {high}")
        if kind == "single_stock_band" and not errors and params["min_pct"] > params["max_pct"]:
            errors.append(f"{where}: min_pct is above max_pct")
        if kind == "conviction_hold":
            errors += _conviction_errors(where, rule, params, held)
        if "enabled" in rule and not isinstance(rule["enabled"], bool):
            errors.append(f"{where}.enabled must be true or false")
        if "symbols" in rule and (not isinstance(rule["symbols"], list) or not all(isinstance(s, str) for s in rule["symbols"])):
            errors.append(f"{where}.symbols must be a list of tickers")
    return errors, warnings


def _conviction_errors(where: str, rule: dict, params: dict, held: set[str]) -> list[str]:
    out = []
    symbols = rule.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 1 or not isinstance(symbols[0], str) or not symbols[0].strip():
        return [f"{where}: conviction_hold needs exactly one ticker in symbols"]
    symbol = symbols[0].strip().upper()
    if symbol in held:
        out.append(f"{where}: {symbol} already has a conviction hold")
    held.add(symbol)
    low, high = params.get("band_min_pct"), params.get("band_max_pct")
    if all(isinstance(v, int | float) and not isinstance(v, bool) for v in (low, high)) and low > high:
        out.append(f"{where}: band_min_pct is above band_max_pct")
    return out


def conviction_symbols(rules: list[dict]) -> set[str]:
    return {r["symbols"][0].upper() for r in rules if r.get("kind") == "conviction_hold" and r.get("symbols") and r.get("enabled", True)}


def normalize(rules: list[dict]) -> list[dict]:
    out = []
    for rule in rules:
        item = {"id": rule["id"], "kind": rule["kind"], "params": dict(rule.get("params") or {}), "enabled": rule.get("enabled", True)}
        if rule.get("symbols"):
            item["symbols"] = [s.upper() for s in rule["symbols"]]
        if rule.get("note"):
            item["note"] = str(rule["note"])
        out.append(item)
    return out


def describe(rule: dict) -> str:
    p = rule.get("params", {})
    label = LABELS.get(rule["kind"], rule["kind"])
    if rule["kind"] == "single_stock_band":
        return f"{label} {p['min_pct']:g} to {p['max_pct']:g}%"
    if rule["kind"] == "drift_max_pts":
        return f"{label} {p['pts']:g} points"
    if rule["kind"] == "conviction_hold":
        return f"{rule['symbols'][0].upper()} {label.lower()} {p['band_min_pct']:g} to {p['band_max_pct']:g}%"
    if rule["kind"] == "cash_floor_pct":
        return f"{label} {p['pct']:g}%"
    return label


def diff(before: list[dict], after: list[dict]) -> dict:
    old = {r["id"]: r for r in before}
    new = {r["id"]: r for r in after}
    return {
        "added": [new[k] for k in new if k not in old],
        "removed": [old[k] for k in old if k not in new],
        "changed": [{"id": k, "before": old[k], "after": new[k]} for k in new if k in old and old[k] != new[k]],
    }


def summarize(change: dict, first: bool) -> str:
    if first:
        return "Rules set: " + ", ".join(describe(r) for r in change["added"]) if change["added"] else "Rules set: none"
    parts = []
    for r in change["added"]:
        parts.append(f"added {describe(r)}")
    for r in change["removed"]:
        parts.append(f"removed {describe(r)}")
    for c in change["changed"]:
        b, a = c["before"], c["after"]
        if b["enabled"] != a["enabled"]:
            parts.append(f"{'turned on' if a['enabled'] else 'turned off'} {describe(a)}")
        else:
            parts.append(f"{describe(b)} → {describe(a)}")
    return "Rules changed: " + "; ".join(parts)


def record_rules(conn: sqlite3.Connection, rules: list[dict]) -> int:
    from desk.decisions.profile import digest

    body = normalize(rules)
    sha = digest(body)
    current = conn.execute("SELECT * FROM rules_versions ORDER BY version DESC LIMIT 1").fetchone()
    if current is not None and current["hash"] == sha:
        return current["version"]
    before = json.loads(current["body"]) if current else []
    change = diff(before, body)
    at = now_iso()
    did = new_id()
    title = summarize(change, current is None)
    conn.execute(
        "INSERT INTO decisions (id, created_at, updated_at, origin, kind, title, thesis, rule_served, status, decided_at) "
        "VALUES (?, ?, ?, 'you', 'rule_change', ?, ?, ?, 'logged', ?)",
        (did, at, at, title, title, ",".join(sorted({r["id"] for r in change["added"] + change["removed"]} | {c["id"] for c in change["changed"]})), at),
    )
    log_event(conn, did, "logged", detail=change, at=at)
    cur = conn.execute("INSERT INTO rules_versions (hash, body, created_at, decision_id) VALUES (?, ?, ?, ?)", (sha, dumps(body), at, did))
    version = cur.lastrowid
    conn.execute("UPDATE decisions SET rules_version=? WHERE id=?", (version, did))
    return version


def active_rules(cfg: Config | None = None) -> tuple[int, list[dict]]:
    from desk.decisions.profile import active_profile

    cfg = cfg or Config.from_env()
    profile = active_profile(cfg)
    with session(cfg) as conn:
        row = conn.execute("SELECT version, body FROM rules_versions WHERE version=?", (profile.rules_version,)).fetchone()
    rules = [r for r in json.loads(row["body"]) if r["enabled"]]
    return row["version"], rules


def versions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT version, created_at, decision_id, body FROM rules_versions ORDER BY version DESC LIMIT ?", (limit,))
    return [{"version": r["version"], "created_at": r["created_at"], "decision_id": r["decision_id"], "rules": json.loads(r["body"])} for r in rows]
