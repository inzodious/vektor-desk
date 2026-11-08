import hashlib
import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta

from desk.config import Config
from desk.decisions.store import has_mirror, now_iso, session

SAVINGS_DAYS = 180

# ---- Bands ----

BANDS: dict[int, dict] = {
    1: {"label": "Conservative", "equity_min_pct": 20, "equity_max_pct": 40, "speculative_max_pct": 0, "worst_year_loss_pct": 10, "single_stock_max_pct": 2},
    2: {
        "label": "Moderately conservative",
        "equity_min_pct": 40,
        "equity_max_pct": 60,
        "speculative_max_pct": 2,
        "worst_year_loss_pct": 18,
        "single_stock_max_pct": 3,
    },
    3: {"label": "Moderate", "equity_min_pct": 60, "equity_max_pct": 75, "speculative_max_pct": 5, "worst_year_loss_pct": 25, "single_stock_max_pct": 5},
    4: {
        "label": "Moderately aggressive",
        "equity_min_pct": 75,
        "equity_max_pct": 90,
        "speculative_max_pct": 10,
        "worst_year_loss_pct": 33,
        "single_stock_max_pct": 10,
    },
    5: {"label": "Aggressive", "equity_min_pct": 90, "equity_max_pct": 100, "speculative_max_pct": 20, "worst_year_loss_pct": 45, "single_stock_max_pct": 15},
}

# ---- Questions ----

QUESTIONS: list[dict] = [
    {
        "id": "max_drawdown",
        "part": "tolerance",
        "prompt": "In a bad year, how far could your portfolio fall before you'd lose sleep?",
        "options": [{"value": v, "label": f"{v}%", "drop_pct": v, "score": i + 1} for i, v in enumerate((10, 20, 30, 40, 50))],
    },
    {
        "id": "drop_reaction",
        "part": "tolerance",
        "prompt": "Markets fall 30% in three months. What do you do?",
        "options": [
            {"value": "sell_all", "label": "Sell everything", "score": 1},
            {"value": "sell_some", "label": "Sell some to stop the bleeding", "score": 2},
            {"value": "hold", "label": "Hold and wait", "score": 3},
            {"value": "buy_some", "label": "Buy a little more", "score": 4},
            {"value": "buy_lots", "label": "Buy a lot more", "score": 5},
        ],
    },
    {
        "id": "one_year_range",
        "part": "tolerance",
        "prompt": "Pick the one-year range you'd take.",
        "options": [
            {"value": "r1", "label": "Up 4% to down 2%", "score": 1},
            {"value": "r2", "label": "Up 8% to down 8%", "score": 2},
            {"value": "r3", "label": "Up 15% to down 15%", "score": 3},
            {"value": "r4", "label": "Up 22% to down 25%", "score": 4},
            {"value": "r5", "label": "Up 30% to down 35%", "score": 5},
        ],
    },
    {
        "id": "goal",
        "part": "tolerance",
        "prompt": "What matters more for this money?",
        "options": [
            {"value": "preserve", "label": "Not losing it", "score": 1},
            {"value": "income", "label": "Steady income", "score": 2},
            {"value": "balanced", "label": "A balance of growth and safety", "score": 3},
            {"value": "growth", "label": "Growth", "score": 4},
            {"value": "max_growth", "label": "As much growth as possible", "score": 5},
        ],
    },
    {
        "id": "experience",
        "part": "tolerance",
        "prompt": "How much investing have you done?",
        "options": [
            {"value": "none", "label": "None yet", "score": 1},
            {"value": "funds", "label": "Index funds and a 401(k)", "score": 2},
            {"value": "some_stocks", "label": "Some single stocks", "score": 3},
            {"value": "active", "label": "Active trading through a bear market", "score": 4},
            {"value": "advanced", "label": "Options, margin or short selling", "score": 5},
        ],
    },
    {
        "id": "horizon",
        "part": "capacity",
        "prompt": "When will you start drawing on this money?",
        "options": [
            {"value": "lt3", "label": "Within 3 years", "years": 2, "score": 1},
            {"value": "3to7", "label": "3 to 7 years", "years": 5, "score": 2},
            {"value": "7to12", "label": "7 to 12 years", "years": 10, "score": 3},
            {"value": "12to20", "label": "12 to 20 years", "years": 15, "score": 4},
            {"value": "20plus", "label": "20 years or more", "years": 25, "score": 5},
        ],
    },
    {
        "id": "income_stability",
        "part": "capacity",
        "prompt": "How steady is your income?",
        "options": [
            {"value": "none", "label": "No steady income", "score": 1},
            {"value": "variable", "label": "It swings a lot", "score": 2},
            {"value": "mostly", "label": "Mostly steady", "score": 3},
            {"value": "steady", "label": "Steady salary", "score": 4},
            {"value": "very", "label": "Very secure salary plus other income", "score": 5},
        ],
    },
    {
        "id": "emergency_months",
        "part": "capacity",
        "prompt": "How many months of expenses do you keep in cash, outside investments?",
        "options": [
            {"value": "0", "label": "None", "score": 1},
            {"value": "1to2", "label": "1 to 2 months", "score": 2},
            {"value": "3to5", "label": "3 to 5 months", "score": 3},
            {"value": "6to11", "label": "6 to 11 months", "score": 4},
            {"value": "12plus", "label": "A year or more", "score": 5},
        ],
    },
]

BY_ID = {q["id"]: q for q in QUESTIONS}


class RiskError(ValueError):
    pass


# ---- Capacity inputs ----


def _mirror_rows(conn: sqlite3.Connection, tbl: str) -> list[dict]:
    if not has_mirror(conn):
        return []
    out = []
    for r in conn.execute("SELECT json FROM mirror.rows WHERE tbl=?", (tbl,)):
        try:
            v = json.loads(r["json"])
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def fi_years(conn: sqlite3.Connection, today: date) -> float | None:
    for p in _mirror_rows(conn, "prefs"):
        v = p.get("value") if p.get("key") == "fi" else None
        if isinstance(v, dict) and isinstance(v.get("birthDate"), str) and isinstance(v.get("fiTargetAge"), int | float):
            try:
                birth = date.fromisoformat(v["birthDate"])
            except ValueError:
                return None
            return round(birth.year + float(v["fiTargetAge"]) - (today.year + (today.timetuple().tm_yday - 1) / 365), 1)
    return None


def savings_rate(conn: sqlite3.Connection, today: date) -> float | None:
    since = (today - timedelta(days=SAVINGS_DAYS)).isoformat()
    income = spend = 0.0
    for t in _mirror_rows(conn, "transactions"):
        amount = t.get("amount")
        if str(t.get("date", "")) < since or isinstance(amount, bool) or not isinstance(amount, int | float):
            continue
        if t.get("kind") == "income" and amount > 0:
            income += amount
        elif t.get("kind") == "spend":
            spend += -amount
    return round((income - spend) / income * 100, 1) if income > 0 else None


def portfolio_value(conn: sqlite3.Connection) -> float | None:
    try:
        row = conn.execute(
            "SELECT value FROM metric_values WHERE metric_id='value.market' AND scope='portfolio' AND value IS NOT NULL ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    return float(row["value"]) if row else None


def _ladder(value: float, steps: tuple[float, ...]) -> int:
    return 1 + sum(value >= s for s in steps)


# ---- Scoring ----


def check_answers(answers) -> dict:
    if not isinstance(answers, dict):
        raise RiskError("answers must map question ids to choices")
    clean, errors = {}, []
    for q in QUESTIONS:
        value = answers.get(q["id"])
        if value is None:
            errors.append(f"{q['id']} is not answered")
            continue
        option = next((o for o in q["options"] if o["value"] == value or str(o["value"]) == str(value)), None)
        if option is None:
            errors.append(f"{q['id']} has no choice {value!r}")
            continue
        clean[q["id"]] = option["value"]
    unknown = sorted(set(answers) - set(BY_ID))
    if unknown:
        errors.append(f"unknown questions: {', '.join(unknown)}")
    if errors:
        raise RiskError("; ".join(errors))
    return clean


def _score(qid: str, value) -> int:
    return next(o["score"] for o in BY_ID[qid]["options"] if o["value"] == value)


def score(answers: dict, *, fi_horizon: float | None = None, savings_pct: float | None = None) -> dict:
    answers = check_answers(answers)
    tolerance_parts = {q["id"]: _score(q["id"], answers[q["id"]]) for q in QUESTIONS if q["part"] == "tolerance"}
    tolerance = round(statistics.mean(tolerance_parts.values()), 2)
    horizon_answer = next(o["years"] for o in BY_ID["horizon"]["options"] if o["value"] == answers["horizon"])
    years = fi_horizon if fi_horizon is not None and fi_horizon > 0 else horizon_answer
    capacity_parts = {
        "horizon": _ladder(years, (3, 7, 12, 20)),
        "income_stability": _score("income_stability", answers["income_stability"]),
        "emergency_months": _score("emergency_months", answers["emergency_months"]),
    }
    if savings_pct is not None:
        capacity_parts["savings_rate"] = _ladder(savings_pct, (5, 10, 20, 35))
    capacity = round(statistics.mean(capacity_parts.values()), 2)
    t_band, c_band = _band(tolerance), _band(capacity)
    band = min(t_band, c_band)
    return {
        "band": band,
        **BANDS[band],
        "tolerance": {"score": tolerance, "band": t_band, "parts": tolerance_parts},
        "capacity": {
            "score": capacity,
            "band": c_band,
            "parts": capacity_parts,
            "horizon_years": years,
            "horizon_source": "fi_goal" if years == fi_horizon else "answer",
            "savings_rate_pct": savings_pct,
        },
        "limited_by": "capacity" if c_band < t_band else "tolerance" if t_band < c_band else "both",
    }


def _band(value: float) -> int:
    return max(1, min(5, int(value + 0.5)))


# ---- Stored versions ----


def _digest(answers: dict, result: dict) -> str:
    return hashlib.sha256(json.dumps({"a": answers, "r": result}, sort_keys=True).encode()).hexdigest()


def latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM risk_profiles ORDER BY version DESC LIMIT 1").fetchone()
    return None if row is None else _row(row)


def _row(row: sqlite3.Row) -> dict:
    return {"version": row["version"], "created_at": row["created_at"], "answers": json.loads(row["answers"]), **json.loads(row["result"])}


def history(cfg: Config, limit: int = 50) -> list[dict]:
    with session(cfg) as conn:
        rows = conn.execute("SELECT * FROM risk_profiles ORDER BY version DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def inputs(cfg: Config, today: date | None = None) -> dict:
    today = today or date.today()
    with session(cfg) as conn:
        return {"fi_horizon_years": fi_years(conn, today), "savings_rate_pct": savings_rate(conn, today), "portfolio_value": portfolio_value(conn)}


def save(cfg: Config, answers: dict, *, now: datetime | None = None) -> tuple[dict, bool]:
    clean = check_answers(answers)
    facts = inputs(cfg, (now.date() if now else None))
    result = score(clean, fi_horizon=facts["fi_horizon_years"], savings_pct=facts["savings_rate_pct"])
    digest = _digest(clean, result)
    with session(cfg) as conn, conn:
        prev = conn.execute("SELECT version, hash FROM risk_profiles ORDER BY version DESC LIMIT 1").fetchone()
        if prev and prev["hash"] == digest:
            return latest(conn), False
        version = (prev["version"] if prev else 0) + 1
        conn.execute(
            "INSERT INTO risk_profiles (version, hash, answers, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (version, digest, json.dumps(clean), json.dumps(result), now_iso(now)),
        )
        return latest(conn), True


def questions(cfg: Config) -> list[dict]:
    value = inputs(cfg)["portfolio_value"]
    out = []
    for q in QUESTIONS:
        options = []
        for o in q["options"]:
            item = {k: v for k, v in o.items() if k != "score"}
            if "drop_pct" in o and value:
                item["dollars"] = round(value * o["drop_pct"] / 100, -2)
                item["label"] = f"{o['drop_pct']}% (about ${item['dollars']:,.0f} today)"
            options.append(item)
        out.append({"id": q["id"], "part": q["part"], "prompt": q["prompt"], "options": options})
    return out


def overlay(conn: sqlite3.Connection, data: dict) -> dict:
    try:
        current = latest(conn)
    except sqlite3.Error:
        return data
    if current is None:
        return data
    risk = {k: current[k] for k in ("band", *BANDS[1], "version", "limited_by")}
    return {**data, "risk_level": current["band"], "risk": risk | {"source": "questionnaire"}}


def current(cfg: Config) -> dict | None:
    with session(cfg) as conn:
        row = latest(conn)
    if row is None:
        return None
    return {
        "version": row["version"],
        "band": row["band"],
        **{k: row[k] for k in BANDS[1]},
        "tolerance_band": row["tolerance"]["band"],
        "capacity_band": row["capacity"]["band"],
        "limited_by": row["limited_by"],
        "answered_at": row["created_at"],
        "taken_at": row["created_at"],
    }
