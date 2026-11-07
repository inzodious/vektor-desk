import copy
import json
import sqlite3
import statistics
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from desk.config import Config
from desk.db import connect
from desk.decisions.plan import cash_in
from desk.decisions.profile import DEFAULTS, ProfileError, active_profile, parse, profile_path

WINDOW_DAYS = 180
SERIES_TOLERANCE = 0.05
MIN_SERIES = 3
STALE_DAYS = 45
PAYS_PER_MONTH = {"weekly": 52 / 12, "biweekly": 26 / 12, "semimonthly": 2, "monthly": 1}
STARTER_DESKS = ("plan_keeper", "tax", "risk", "skeptic")
BROKERAGE_KINDS = ("individual", "brokerage", "joint")
STARTER_RUNS = {"plan_keeper": 10}


class StarterError(Exception):
    pass


# ---- Reading the mirror ----


def _rows(conn: sqlite3.Connection, tbl: str) -> list[dict]:
    out = []
    try:
        cursor = conn.execute("SELECT json FROM rows WHERE tbl=?", (tbl,))
    except sqlite3.Error:
        return out
    for r in cursor:
        try:
            out.append(json.loads(r["json"]))
        except (TypeError, ValueError):
            continue
    return out


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def latest_plan(conn: sqlite3.Connection) -> dict:
    plans = _rows(conn, "plans")
    if not plans:
        return {}
    best = max(plans, key=lambda p: (str(p.get("loadedAt") or ""), str(p.get("id") or "")))
    return best.get("plan") or {}


def accounts(conn: sqlite3.Connection) -> list[dict]:
    snaps = _rows(conn, "snapshots")
    found: dict[str, dict] = {}
    if snaps:
        snap = max(snaps, key=lambda s: str(s.get("asOf", "")))
        for a in snap.get("accounts") or []:
            if a.get("key"):
                found[a["key"]] = {"key": a["key"], "kind": str(a.get("kind") or "").lower()}
        for p in _rows(conn, "positions"):
            key = p.get("accountKey")
            if key and p.get("snapshotId") == snap.get("id") and key not in found:
                found[key] = {"key": key, "kind": ""}
    return sorted(found.values(), key=lambda a: a["key"])


# ---- Cadence ----


def cadence(days: list[date]) -> dict | None:
    days = sorted(set(days))
    if len(days) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    med = statistics.median(gaps)
    weekend = "after" if sum(d.weekday() == 0 for d in days) > sum(d.weekday() == 4 for d in days) else "before"
    if 5 <= med <= 9:
        return {"cadence": "weekly", "anchor": days[-1].isoformat()}
    if 12 <= med <= 16:
        steady = sum(13 <= g <= 15 for g in gaps) / len(gaps)
        weekday_share = Counter(d.weekday() for d in days).most_common(1)[0][1] / len(days)
        if steady >= 0.7 and weekday_share >= 0.7:
            return {"cadence": "biweekly", "anchor": days[-1].isoformat()}
        low = [d.day for d in days if d.day <= 15]
        high = [d.day for d in days if d.day > 15]
        if low and high:
            pick = [Counter(low).most_common(1)[0][0], Counter(high).most_common(1)[0][0]]
            return {"cadence": "semimonthly", "days": pick, "weekend": weekend}
        return None
    if 26 <= med <= 35:
        return {"cadence": "monthly", "days": [Counter(d.day for d in days).most_common(1)[0][0]], "weekend": weekend}
    return None


def _activity(conn: sqlite3.Connection, since: date) -> list[tuple[str, dict]]:
    try:
        cursor = conn.execute("SELECT id, json FROM rows WHERE tbl='activity'")
    except sqlite3.Error:
        return []
    out = []
    for r in cursor:
        try:
            a = json.loads(r["json"])
        except (TypeError, ValueError):
            continue
        if isinstance(a, dict) and (d := _day(a.get("date"))) is not None and d >= since:
            out.append((r["id"], a))
    return out


def _groups(items: list[tuple[date, float]]) -> list[list[tuple[date, float]]]:
    groups: list[list[tuple[date, float]]] = []
    for d, amount in sorted(items, key=lambda x: (x[1], x[0])):
        if groups and amount <= groups[-1][0][1] * (1 + SERIES_TOLERANCE):
            groups[-1].append((d, amount))
        else:
            groups.append([(d, amount)])
    return groups


def series(items: list[tuple[date, float]], today: date) -> tuple[list[dict], int, int]:
    found, used, stale = [], 0, 0
    for g in sorted(_groups(items), key=len, reverse=True):
        if len(g) < MIN_SERIES:
            continue
        hit = cadence([d for d, _ in g])
        if hit is None:
            continue
        if (today - max(d for d, _ in g)).days > STALE_DAYS:
            stale += 1
            continue
        found.append({**hit, "amount_usd": round(statistics.median(a for _, a in g)), "_n": len(g)})
        used += len(g)
    if not found and not stale:
        hit = cadence([d for d, _ in items])
        if hit is not None:
            found.append({**hit, "amount_usd": round(statistics.median(a for _, a in items)), "_n": len(items)})
            used = len(items)
    return sorted(found, key=lambda x: -x["amount_usd"]), len(items) - used, stale


def _inbound_hint(rows: list[tuple[str, dict]], key: str) -> str:
    seen = Counter(
        f'{a.get("kind") or "?"} "{" ".join(str(a.get("action") or "").split()[:4])}"'
        for _, a in rows
        if a.get("accountKey") == key and isinstance(a.get("amount"), int | float) and a["amount"] > 0 and not a.get("symbol")
    )
    return ", ".join(f"{label} x{n}" for label, n in seen.most_common(3)) or "none"


def deposit_schedule(conn: sqlite3.Connection, plan: dict, accts: list[dict], today: date) -> tuple[list[dict], list[str]]:
    since = today - timedelta(days=WINDOW_DAYS)
    rows = _activity(conn, since)
    by_account: dict[str, list[tuple[date, float]]] = {}
    for x in cash_in(rows):
        by_account.setdefault(x["accountKey"], []).append((date.fromisoformat(x["date"]), x["amount"]))
    out: list[dict] = []
    notes: list[str] = []
    for key in sorted(by_account):
        items = by_account[key]
        found, loose, stale = series(items, today)
        for hit in found:
            n = hit.pop("_n")
            out.append({"id": _slug(key, out), "account": key, **hit})
            notes.append(f"{key}: {hit['cadence']} from {n} deposits since {since.isoformat()}")
        if loose:
            notes.append(f"{key}: {loose} one-off deposits left out")
        if stale:
            notes.append(f"{key}: {stale} schedule(s) with no deposit in {STALE_DAYS} days left out")
        if not found and not stale:
            notes.append(f"{key}: {len(items)} deposits since {since.isoformat()}, no steady pattern, so it is left out")
    for a in accts:
        if a["key"] not in by_account and a["kind"] in BROKERAGE_KINDS:
            notes.append(f"{a['key']}: no deposits seen since {since.isoformat()}; money-in rows there: {_inbound_hint(rows, a['key'])}")
    brokerage = {a["key"] for a in accts if a["kind"] in BROKERAGE_KINDS}
    if out and (not brokerage or any(d["account"] in brokerage for d in out)):
        return out, notes
    pay = [d for d in (_day(s.get("payDate")) for s in _rows(conn, "paystubs")) if d and d >= since]
    source = "paystubs"
    if len(pay) < 3:
        pay = [
            d
            for d in (_day(t.get("date")) for t in _rows(conn, "transactions") if t.get("kind") == "income" and "pay" in str(t.get("category", "")).lower())
            if d and d >= since
        ]
        source = "payroll transactions"
    found = cadence(pay)
    target = min(brokerage) if brokerage else (accts[0]["key"] if accts else None)
    if found is None or target is None:
        notes.append("No deposit pattern in the mirror yet; add deposits by hand")
        return out, notes
    item = {"id": "payday", "account": target, **found}
    monthly, _ = _plan_monthly(plan)
    if monthly:
        item["amount_usd"] = round(monthly / PAYS_PER_MONTH[found["cadence"]])
    out.append(item)
    how = ", amount from the plan's monthly contribution" if monthly else ", amount left blank"
    notes.append(f"{target}: {found['cadence']} pay dates from {source}{how}")
    return out, notes


def _plan_monthly(plan: dict) -> tuple[float | None, str]:
    amounts = [float(m["contribution"]) for m in plan.get("monthly_plan") or [] if isinstance(m.get("contribution"), int | float)]
    if amounts:
        return statistics.median(amounts), "plan"
    acct = (plan.get("accounts") or {}).get("individual") or {}
    if isinstance(acct.get("monthly_contribution"), int | float):
        return float(acct["monthly_contribution"]), "plan"
    return None, "none"


def _slug(key: str, taken: list[dict]) -> str:
    base = key.split("-")[0].lower() or "deposit"
    used = {d["id"] for d in taken}
    name, n = base, 2
    while name in used:
        name, n = f"{base}-{n}", n + 1
    return name


# ---- Plan ----


def rules_from_plan(plan: dict) -> list[dict]:
    g = plan.get("guardrails") or {}
    rules = [{"id": "no-margin-buys", "kind": "no_margin_buys"}, {"id": "no-new-single-stocks", "kind": "no_new_single_stocks"}]
    single = g.get("max_single_stock_weight")
    if isinstance(single, int | float) and single > 0:
        top = round(single * 100 if single <= 1 else single, 2)
        rules.append({"id": "single-stock-band", "kind": "single_stock_band", "params": {"min_pct": 0, "max_pct": top}})
    drift = g.get("drift_alert_pct_points")
    rules.append({"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": drift if isinstance(drift, int | float) and drift > 0 else 5}})
    return rules


def themes_from_plan(plan: dict) -> list[dict]:
    weights: Counter = Counter()
    for f in plan.get("funds") or []:
        w = f.get("target_weight")
        if isinstance(w, int | float) and w > 0:
            weights[str(f.get("sleeve") or f.get("ticker") or "core").lower()] += float(w)
    total = sum(weights.values())
    return [{"name": k, "weight": round(v / total * 100)} for k, v in weights.most_common()] if total else []


# ---- Draft ----


def draft(cfg: Config, *, today: date | None = None) -> tuple[dict, list[str]]:
    if not cfg.mirror_db.exists():
        raise StarterError(f"No mirror at {cfg.mirror_db}. Run the mirror first (deploy.sh mirror).")
    today = today or datetime.now(UTC).date()
    conn = connect(cfg.mirror_db, readonly=True)
    try:
        plan = latest_plan(conn)
        accts = accounts(conn)
        deposits, notes = deposit_schedule(conn, plan, accts, today)
    finally:
        conn.close()
    data: dict = {}
    if deposits:
        data["deposits"] = deposits
    if accts:
        data["tax"] = {"wash_sale_accounts": [a["key"] for a in accts]}
        notes.append(f"Wash-sale checks cover {len(accts)} accounts from the latest snapshot")
    themes = themes_from_plan(plan)
    if themes:
        data["industry_focus"] = {"themes": themes}
        notes.append(f"Industry focus from the plan's {len(themes)} sleeves")
    if plan:
        data["rules"] = rules_from_plan(plan)
        notes.append("Rules from the plan's guardrails plus no margin buys and no new single stocks")
    else:
        notes.append("No plan in the mirror; rules stay at the defaults")
    data["usage"] = {"weekly_runs": dict(STARTER_RUNS)}
    data["agents"] = {"enabled": False, "desks": {d: d in STARTER_DESKS for d in DEFAULTS["agents"]["desks"]}}
    notes.append("Agents stay off until you set agents.enabled: true")
    return data, notes


def render(data: dict, notes: list[str], today: date) -> str:
    data = copy.deepcopy(data)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(DEFAULTS.get(key), dict):
            data[key] = {**copy.deepcopy(DEFAULTS[key]), **value}
    rest = {k: copy.deepcopy(v) for k, v in DEFAULTS.items() if k not in data}
    lines = [
        "# Vektor Desk profile, drafted from the mirror by `python -m desk.decisions.profile init`.",
        f"# Drafted {today.isoformat()}. Check every value, then edit freely: each change becomes a new profile version.",
        "#",
        *[f"# - {n}" for n in notes],
        "",
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip(),
        "",
    ]
    if rest:
        lines += ["", "# ---- Still at the defaults: uncomment and change to set them ----", ""]
        lines += ["# " + line if line else "#" for line in yaml.safe_dump(rest, sort_keys=False, default_flow_style=False).rstrip().splitlines()]
        lines.append("")
    return "\n".join(lines)


def init(cfg: Config, path: Path | None = None, *, today: date | None = None, dry_run: bool = False) -> tuple[Path, str]:
    path = path or profile_path(cfg)
    if path.exists() and not dry_run:
        raise StarterError(f"{path} already exists. The starter never overwrites it; edit it, or move it aside and run init again.")
    today = today or datetime.now(UTC).date()
    data, notes = draft(cfg, today=today)
    text = render(data, notes, today)
    try:
        parse(text)
    except ProfileError as e:
        raise StarterError(f"The draft didn't validate ({e}); nothing was written.") from e
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x") as f:
            f.write(text)
    return path, text


def deposits_block(cfg: Config, *, today: date | None = None) -> str:
    if not cfg.mirror_db.exists():
        raise StarterError(f"No mirror at {cfg.mirror_db}. Run the mirror first (deploy.sh mirror).")
    today = today or datetime.now(UTC).date()
    conn = connect(cfg.mirror_db, readonly=True)
    try:
        deposits, notes = deposit_schedule(conn, latest_plan(conn), accounts(conn), today)
    finally:
        conn.close()
    current = active_profile(cfg)
    lines = [
        f"# Deposits detected from the mirror on {today.isoformat()} by `python -m desk.decisions.profile init --deposits`.",
        f"# Your desk.yaml ({current.source}) lists {len(current.get('deposits') or [])} now. To use these, replace its deposits: section.",
        "#",
        *[f"# - {n}" for n in notes],
        "",
    ]
    if not deposits:
        return "\n".join([*lines, "# No deposit pattern found, so there is no block to paste.", ""])
    block = yaml.safe_dump({"deposits": deposits}, sort_keys=False, default_flow_style=False).rstrip()
    try:
        parse(block)
    except ProfileError as e:
        raise StarterError(f"The detected deposits didn't validate ({e}).") from e
    return "\n".join([*lines, block, ""])


# ---- Status ----


def _leaves(node: dict, prefix: str = "", depth: int = 2) -> list[str]:
    out = []
    for key, value in node.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value and depth > 1 and key not in ("desks", "weekly_runs"):
            out += _leaves(value, name + ".", depth - 1)
        else:
            out.append(name)
    return out


_MISSING = object()


def _at(node, dotted: str):
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def status(cfg: Config) -> dict:
    path = profile_path(cfg)
    profile = active_profile(cfg)
    raw: dict = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text())
            raw = loaded if isinstance(loaded, dict) else {}
        except (yaml.YAMLError, OSError):
            raw = {}
    leaves = _leaves(DEFAULTS)
    defaults = [k for k in leaves if _at(raw, k) is _MISSING or _at(raw, k) == _at(DEFAULTS, k)]
    desks = profile.get("agents", "desks", default={}) or {}
    return {
        "path": str(path),
        "exists": path.exists(),
        "source": profile.source,
        "version": profile.version,
        "loaded_at": profile.loaded_at,
        "error": profile.error,
        "warnings": profile.warnings,
        "set": [k for k in leaves if k not in defaults],
        "defaults": defaults,
        "agents_enabled": bool(profile.get("agents", "enabled")),
        "desks_on": sorted(d for d, on in desks.items() if on) if profile.get("agents", "enabled") else [],
        "deposits": len(profile.get("deposits", default=[]) or []),
        "rules": len(profile.get("rules", default=[]) or []),
        "starter": None if path.exists() else "docker exec vektor-desk-cron python -m desk.decisions.profile init",
    }
