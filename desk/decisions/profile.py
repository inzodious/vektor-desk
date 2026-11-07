import copy
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from desk.config import Config
from desk.decisions.store import dumps, now_iso, session

DESKS = ("plan_keeper", "tax", "risk", "research", "skeptic", "scout", "strategy")
LOT_METHODS = ("highest_cost", "lowest_cost", "fifo", "lifo", "tax_efficient")
TILTS = ("growth", "balanced", "income")

DEFAULTS: dict = {
    "risk_level": 3,
    "industry_focus": {"themes": [], "exclude": []},
    "opportunity": {"satellite_cap_pct": 10, "ideas_per_month": 2, "min_confidence": 0.55},
    "tax": {"harvest_threshold_usd": 250, "lot_method": "highest_cost", "year_end_start": "12-01", "wash_sale_accounts": []},
    "growth": {"horizon_years": 10, "tilt": "growth", "fi_target_from_plan": True},
    "usage": {"overnight_window": "01:00-05:00", "weekly_runs": {}},
    "agents": {"enabled": False, "desks": {d: False for d in DESKS}},
    "deposits": [],
    "alerts": {"min_priority": "default"},
    "rules": [
        {"id": "no-margin-buys", "kind": "no_margin_buys"},
        {"id": "no-new-single-stocks", "kind": "no_new_single_stocks"},
        {"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": 5}},
    ],
}


class ProfileError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Profile:
    version: int
    data: dict
    source: str
    loaded_at: str
    rules_version: int
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def get(self, *path, default=None):
        node = self.data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def desk_enabled(self, desk: str) -> bool:
        return bool(self.get("agents", "enabled")) and bool(self.get("agents", "desks", desk, default=False))

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "rules_version": self.rules_version,
            "source": self.source,
            "loaded_at": self.loaded_at,
            "warnings": self.warnings,
            "error": self.error,
            "profile": self.data,
        }


def profile_path(cfg: Config, env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("DESK_PROFILE", "").strip()
    return Path(raw) if raw else cfg.data_dir / "desk.yaml"


# ---- Validation ----


def _num(errors, where, value, low=None, high=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, int | float) or (integer and not isinstance(value, int)):
        errors.append(f"{where} must be {'a whole number' if integer else 'a number'}, got {value!r}")
        return
    if low is not None and value < low or high is not None and value > high:
        errors.append(f"{where} must be between {low} and {high}, got {value!r}")


def _choice(errors, where, value, options):
    if value not in options:
        errors.append(f"{where} must be one of {', '.join(options)}, got {value!r}")


def _section(errors, data, name) -> dict:
    value = data.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append(f"{name} must be a mapping")
        return {}
    return value


def _str_list(errors, where, value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{where} must be a list of text")


def validate(data) -> list[str]:
    from desk.decisions.rules import validate_rules

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ProfileError(["desk.yaml must be a mapping at the top level"])
    errors: list[str] = []
    warnings = [f"unknown section {k!r} is kept but nothing reads it" for k in data if k not in DEFAULTS]
    if "risk_level" in data:
        _num(errors, "risk_level", data["risk_level"], 1, 5, integer=True)
    focus = _section(errors, data, "industry_focus")
    for i, theme in enumerate(focus.get("themes", []) or []):
        if not isinstance(theme, dict) or not isinstance(theme.get("name"), str):
            errors.append(f"industry_focus.themes[{i}] needs a name")
        elif "weight" in theme:
            _num(errors, f"industry_focus.themes[{i}].weight", theme["weight"], 0, 100)
    if "exclude" in focus:
        _str_list(errors, "industry_focus.exclude", focus["exclude"])
    opp = _section(errors, data, "opportunity")
    if "satellite_cap_pct" in opp:
        _num(errors, "opportunity.satellite_cap_pct", opp["satellite_cap_pct"], 0, 100)
    if "ideas_per_month" in opp:
        _num(errors, "opportunity.ideas_per_month", opp["ideas_per_month"], 0, 50, integer=True)
    if "min_confidence" in opp:
        _num(errors, "opportunity.min_confidence", opp["min_confidence"], 0, 1)
    tax = _section(errors, data, "tax")
    if "harvest_threshold_usd" in tax:
        _num(errors, "tax.harvest_threshold_usd", tax["harvest_threshold_usd"], 0)
    if "lot_method" in tax:
        _choice(errors, "tax.lot_method", tax["lot_method"], LOT_METHODS)
    if "year_end_start" in tax:
        start = str(tax["year_end_start"])
        if len(start) != 5 or start[2] != "-" or not start.replace("-", "").isdigit():
            errors.append(f"tax.year_end_start must look like MM-DD, got {start!r}")
    if "wash_sale_accounts" in tax:
        _str_list(errors, "tax.wash_sale_accounts", tax["wash_sale_accounts"])
    growth = _section(errors, data, "growth")
    if "horizon_years" in growth:
        _num(errors, "growth.horizon_years", growth["horizon_years"], 0, 80)
    if "tilt" in growth:
        _choice(errors, "growth.tilt", growth["tilt"], TILTS)
    usage = _section(errors, data, "usage")
    runs = usage.get("weekly_runs", {}) or {}
    if not isinstance(runs, dict):
        errors.append("usage.weekly_runs must be a mapping of desk to runs a week")
    else:
        for desk, n in runs.items():
            if desk not in DESKS:
                warnings.append(f"usage.weekly_runs.{desk} is not a known desk")
            _num(errors, f"usage.weekly_runs.{desk}", n, 0, 100, integer=True)
    agents = _section(errors, data, "agents")
    if "enabled" in agents and not isinstance(agents["enabled"], bool):
        errors.append("agents.enabled must be true or false")
    desks = agents.get("desks", {}) or {}
    if not isinstance(desks, dict):
        errors.append("agents.desks must be a mapping of desk to true or false")
    else:
        for desk, on in desks.items():
            if desk not in DESKS:
                warnings.append(f"agents.desks.{desk} is not a known desk")
            if not isinstance(on, bool):
                errors.append(f"agents.desks.{desk} must be true or false")
    alerts = _section(errors, data, "alerts")
    if "min_priority" in alerts:
        _choice(errors, "alerts.min_priority", alerts["min_priority"], ("min", "low", "default", "high", "urgent"))
    if "deposits" in data:
        from desk.decisions.plan import validate_deposits

        dep_errors, dep_warnings = validate_deposits(data["deposits"])
        errors += dep_errors
        warnings += dep_warnings
    if "rules" in data:
        rule_errors, rule_warnings = validate_rules(data["rules"])
        errors += rule_errors
        warnings += rule_warnings
    if errors:
        raise ProfileError(errors)
    return warnings


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key == "rules" or not isinstance(value, dict) or not isinstance(out.get(key), dict):
            out[key] = copy.deepcopy(value)
        else:
            out[key] = merge(out[key], value)
    return out


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse(text: str) -> tuple[dict, list[str]]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ProfileError([f"desk.yaml is not valid YAML: {e}"]) from e
    warnings = validate(data)
    return merge(DEFAULTS, data or {}), warnings


# ---- Versions ----


def _row_to_profile(row: sqlite3.Row, error: str | None = None) -> Profile:
    return Profile(
        version=row["version"],
        data=json.loads(row["body"]),
        source=row["source"],
        loaded_at=row["loaded_at"],
        rules_version=row["rules_version"],
        warnings=json.loads(row["warnings"]),
        error=error,
    )


def latest(conn: sqlite3.Connection) -> Profile | None:
    row = conn.execute("SELECT * FROM profile_versions ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        return None
    state = conn.execute("SELECT error FROM profile_state WHERE id=1").fetchone()
    return _row_to_profile(row, state["error"] if state else None)


def _set_state(conn: sqlite3.Connection, source: str, error: str | None) -> None:
    conn.execute(
        "INSERT INTO profile_state (id, checked_at, source, error) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at, source=excluded.source, error=excluded.error",
        (now_iso(), source, error),
    )


def sync(conn: sqlite3.Connection, path: Path) -> Profile:
    from desk.decisions.rules import record_rules

    if path.exists():
        source = str(path)
        try:
            data, warnings = parse(path.read_text())
        except (ProfileError, OSError) as e:
            with conn:
                _set_state(conn, source, str(e))
            current = latest(conn)
            if current is not None:
                return current
            data, warnings, source = copy.deepcopy(DEFAULTS), [], "defaults"
            error = str(e)
        else:
            error = None
    else:
        data, warnings, source, error = copy.deepcopy(DEFAULTS), [], "defaults", None
    body = dumps(data)
    current = conn.execute("SELECT * FROM profile_versions ORDER BY version DESC LIMIT 1").fetchone()
    with conn:
        _set_state(conn, source, error)
        if current is not None and current["hash"] == digest(data) and current["source"] == source:
            return _row_to_profile(current, error)
        rules_version = record_rules(conn, data.get("rules", []))
        conn.execute(
            "INSERT INTO profile_versions (hash, source, body, warnings, rules_version, loaded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (digest(data), source, body, json.dumps(warnings), rules_version, now_iso()),
        )
    return latest(conn)


def active_profile(cfg: Config | None = None) -> Profile:
    cfg = cfg or Config.from_env()
    with session(cfg) as conn:
        return sync(conn, profile_path(cfg))


def versions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT version, source, rules_version, loaded_at, warnings FROM profile_versions ORDER BY version DESC LIMIT ?", (limit,))
    return [{**dict(r), "warnings": json.loads(r["warnings"])} for r in rows]


def get_version(conn: sqlite3.Connection, version: int) -> Profile | None:
    row = conn.execute("SELECT * FROM profile_versions WHERE version=?", (version,)).fetchone()
    return None if row is None else _row_to_profile(row)


# ---- Command line ----


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from desk.decisions import starter

    parser = argparse.ArgumentParser(prog="python -m desk.decisions.profile", description="Draft or check the desk profile (desk.yaml).")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="write a draft desk.yaml from the mirror; never overwrites")
    init.add_argument("--path", type=Path, help="where to write (default $DESK_PROFILE or /data/desk.yaml)")
    init.add_argument("--print", dest="dry_run", action="store_true", help="print the draft instead of writing it")
    init.add_argument("--deposits", action="store_true", help="print only the detected deposits block, to paste into an existing desk.yaml")
    sub.add_parser("status", help="show the active version and which settings are still defaults")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.command == "status":
        print(json.dumps(starter.status(cfg), indent=2))
        return 0
    try:
        if args.deposits:
            print(starter.deposits_block(cfg))
            return 0
        path, text = starter.init(cfg, args.path, dry_run=args.dry_run)
    except starter.StarterError as e:
        print(e, file=sys.stderr)
        return 1
    if args.dry_run:
        print(text)
    else:
        print(f"Wrote {path}. Check it, then the next sync (or any page load) picks it up as a new profile version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
