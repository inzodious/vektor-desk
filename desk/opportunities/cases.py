import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine.discounts import CASE_MAX, RISKS_MAX, VERDICTS
from desk.runlock import run_dir

CAP = 6
NIGHT_HOURS = 18
FRESH_DAYS = 7
KEEP_DAYS = 45
HIT_NUMBERS = ("price", "day_move_pct", "drop_from_high_pct", "high_52w", "ret_1y_pct", "sigma_month_pct", "vs_sma_200_pct", "swings_under_high")
VALUATION_NUMBERS = ("valuation_value", "valuation_pctile")


# ---- The file ----


def _path(cfg: Config):
    return run_dir(cfg) / "opportunities" / "cases.json"


def load(cfg: Config) -> dict[str, dict]:
    try:
        found = json.loads(_path(cfg).read_text())
    except (OSError, ValueError):
        return {}
    cases = found.get("cases") if isinstance(found, dict) else None
    return {str(k).upper(): v for k, v in cases.items() if isinstance(v, dict)} if isinstance(cases, dict) else {}


def _save(cfg: Config, cases: dict[str, dict]) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cases": cases}, indent=1, sort_keys=True))
    tmp.replace(path)


def fresh(cfg: Config, today: str) -> dict[str, dict]:
    cut = (date.fromisoformat(today) - timedelta(days=FRESH_DAYS)).isoformat()
    return {s: c for s, c in load(cfg).items() if str(c.get("as_of") or "") >= cut}


# ---- Tonight's count ----


def parse(text: object) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def written_tonight(cfg: Config, now: datetime) -> int:
    cut = now - timedelta(hours=NIGHT_HOURS)
    n = sum(1 for c in load(cfg).values() if (t := parse(c.get("written_at"))) is not None and t >= cut)
    if not cfg.desk_db.exists():
        return n
    conn = connect(cfg.desk_db, readonly=True)
    try:
        stamps = [r[0] for r in conn.execute("SELECT written_at FROM discount_cases")]
    except sqlite3.Error:
        stamps = []
    finally:
        conn.close()
    return n + sum(1 for s in stamps if (t := parse(s)) is not None and t >= cut)


# ---- Rows that need a case ----


def hit_for(row: dict) -> dict:
    figures = row.get("numbers") or {}
    numbers = {k: figures[k] for k in (*HIT_NUMBERS, *VALUATION_NUMBERS) if figures.get(k) is not None}
    return {
        "signal_id": f"list-{row['price_as_of']}-{row['symbol']}",
        "symbol": row["symbol"],
        "name": row.get("name"),
        "as_of": row["price_as_of"],
        "list": "held" if row.get("held") else "on sale, not held",
        "reason": "on_sale_by_the_numbers",
        "price": figures.get("price"),
        "drop_from_high_pct": figures.get("drop_from_high_pct"),
        "move_z": None,
        "valuation": {"metric": figures.get("valuation_metric"), "value": figures.get("valuation_value"), "pctile_own": figures.get("valuation_pctile")},
        "numbers": numbers,
    }


def wanted(listing: dict) -> list[dict]:
    return [hit_for(r) for r in listing.get("rows") or () if r.get("stance") == "screen" and (r.get("numbers") or {}).get("price")]


# ---- The source the Discount cases desk reads and writes ----


def problems(case: dict, numbers: dict) -> list[str]:
    errors = []
    if case.get("verdict") not in VERDICTS:
        errors.append("verdict must be buy, wait or avoid")
    for key, cap in (("case", CASE_MAX), ("risks", RISKS_MAX)):
        if not isinstance(case.get(key), str) or not case[key].strip() or len(case[key]) > cap:
            errors.append(f"{key} must be text of at most {cap} characters")
    conf = case.get("confidence")
    if not isinstance(conf, int | float) or isinstance(conf, bool) or not 0 <= conf <= 1:
        errors.append("confidence must be between 0 and 1")
    days = case.get("horizon_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        errors.append("horizon_days must be a whole number of at least 1")
    cited = case.get("numbers_cited")
    if not isinstance(cited, list) or any(c not in numbers for c in cited):
        errors.append("numbers_cited must list keys from the hit's numbers")
    for key in ("model", "written_at"):
        if not isinstance(case.get(key), str) or not case[key]:
            errors.append(f"{key} is required")
    return errors


class ListSource:
    def __init__(self, hits: list[dict]):
        self.hits = {h["signal_id"]: h for h in hits}

    def pending(self, cfg: Config, limit: int) -> list[dict]:
        return list(self.hits.values())[: max(0, int(limit))]

    def record(self, cfg: Config, signal_id: str, case: dict) -> bool:
        hit = self.hits.get(signal_id)
        if hit is None:
            raise ValueError(f"no row {signal_id}")
        errors = problems(case or {}, hit["numbers"])
        if errors:
            raise ValueError("; ".join(errors))
        cases = load(cfg)
        cut = (date.fromisoformat(hit["as_of"]) - timedelta(days=KEEP_DAYS)).isoformat()
        cases = {s: c for s, c in cases.items() if str(c.get("as_of") or "") >= cut}
        cases[hit["symbol"]] = {
            "signal_id": signal_id,
            "symbol": hit["symbol"],
            "as_of": hit["as_of"],
            "verdict": case["verdict"],
            "case": case["case"].strip(),
            "risks": case["risks"].strip(),
            "confidence": float(case["confidence"]),
            "horizon_days": case["horizon_days"],
            "numbers_cited": list(case["numbers_cited"]),
            "model": case["model"],
            "written_at": case["written_at"],
            "run_id": case.get("run_id"),
        }
        _save(cfg, cases)
        return True
