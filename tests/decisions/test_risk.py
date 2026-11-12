import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from desk.db import apply_schemas
from desk.decisions import active_profile, risk
from desk.decisions.risk import RiskError, check_answers, score
from desk.mirror.store import SCHEMA as MIRROR_SCHEMA

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
MIDDLE = {
    "max_drawdown": 30,
    "drop_reaction": "hold",
    "one_year_range": "r3",
    "goal": "balanced",
    "experience": "some_stocks",
    "horizon": "7to12",
    "income_stability": "mostly",
    "emergency_months": "3to5",
}
BOLD = MIDDLE | {"max_drawdown": 50, "drop_reaction": "buy_lots", "one_year_range": "r5", "goal": "max_growth", "experience": "advanced"}


def _mirror(cfg, rows):
    conn = sqlite3.connect(cfg.mirror_db)
    conn.executescript(MIRROR_SCHEMA)
    for i, (tbl, row) in enumerate(rows):
        conn.execute("INSERT INTO rows (tbl, id, json, at) VALUES (?, ?, ?, '2026-11-08T00:00:00Z')", (tbl, f"{tbl}-{i}", json.dumps(row)))
    conn.commit()
    conn.close()


# ---- Scoring ----


def test_middle_answers_give_a_moderate_band():
    r = score(MIDDLE)
    assert r["band"] == 3 and r["label"] == "Moderate" and (r["equity_min_pct"], r["equity_max_pct"]) == (60, 75) and r["limited_by"] == "both"
    assert r["tolerance"]["score"] == 3 and r["capacity"]["parts"] == {"horizon": 3, "income_stability": 3, "emergency_months": 3}


def test_the_lower_of_tolerance_and_capacity_wins():
    thin = score(BOLD | {"emergency_months": "0", "income_stability": "variable", "horizon": "3to7"})
    assert thin["tolerance"]["band"] == 5 and thin["capacity"]["band"] == 2 and thin["band"] == 2 and thin["limited_by"] == "capacity"
    roomy = score(BOLD | {"emergency_months": "12plus", "income_stability": "very", "horizon": "20plus"}, fi_horizon=27.5, savings_pct=40)
    assert roomy["band"] == 5 and roomy["single_stock_max_pct"] == 15 and roomy["worst_year_loss_pct"] == 45
    assert roomy["capacity"]["horizon_years"] == 27.5 and roomy["capacity"]["horizon_source"] == "fi_goal" and roomy["capacity"]["parts"]["savings_rate"] == 5
    timid = score(MIDDLE | {"max_drawdown": 10, "drop_reaction": "sell_all", "one_year_range": "r1", "goal": "preserve", "experience": "none"})
    assert timid["band"] == 1 and timid["limited_by"] == "tolerance"


@pytest.mark.parametrize(
    "answers, message",
    [
        ({k: v for k, v in MIDDLE.items() if k != "goal"}, "goal is not answered"),
        (MIDDLE | {"goal": "yolo"}, "goal has no choice"),
        (MIDDLE | {"shoe_size": 11}, "unknown questions: shoe_size"),
        ("all of them", "must map"),
    ],
)
def test_bad_answers(answers, message):
    with pytest.raises(RiskError, match=message):
        check_answers(answers)


# ---- Inputs from the mirror ----


def test_capacity_reads_the_fi_goal_and_savings_rate(cfg):
    _mirror(
        cfg,
        [
            ("prefs", {"key": "fi", "value": {"birthDate": "1990-01-01", "fiTargetAge": 50, "fiYearlySpend": 40000}}),
            ("transactions", {"date": "2026-10-01", "kind": "income", "amount": 5000}),
            ("transactions", {"date": "2026-10-02", "kind": "spend", "amount": -3500}),
            ("transactions", {"date": "2025-01-02", "kind": "spend", "amount": -9000}),
        ],
    )
    facts = risk.inputs(cfg, date(2026, 11, 8))
    assert facts["fi_horizon_years"] == 13.1 and facts["savings_rate_pct"] == 30.0 and facts["portfolio_value"] is None


def test_drawdown_choices_show_dollars_on_the_portfolio(cfg):
    apply_schemas(cfg, only=["engine"])
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(
        "INSERT INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, quality, engine_version) "
        "VALUES ('value.market', 'portfolio', 'all', 'now', '2026-11-07', 40000, 'usd', 'ok', 'x')"
    )
    conn.commit()
    conn.close()
    first = risk.questions(cfg)[0]
    assert first["options"][2] == {"value": 30, "label": "30% (about $12,000 today)", "drop_pct": 30, "dollars": 12000.0}
    assert "score" not in first["options"][0]


# ---- Versions and the profile ----


def test_saving_versions_and_overlaying_the_profile(cfg):
    assert risk.current(cfg) is None and active_profile(cfg).get("risk_level") == 3
    saved, changed = risk.save(cfg, BOLD | {"emergency_months": "12plus", "income_stability": "very", "horizon": "20plus"}, now=NOW)
    assert changed and saved["version"] == 1 and saved["band"] == 5
    assert risk.save(cfg, BOLD | {"emergency_months": "12plus", "income_stability": "very", "horizon": "20plus"}, now=NOW)[1] is False
    saved, changed = risk.save(cfg, MIDDLE, now=NOW)
    assert changed and saved["version"] == 2 and [v["version"] for v in risk.history(cfg)] == [2, 1]
    assert risk.current(cfg) == {
        "version": 2,
        "band": 3,
        "label": "Moderate",
        "equity_min_pct": 60,
        "equity_max_pct": 75,
        "speculative_max_pct": 5,
        "worst_year_loss_pct": 25,
        "single_stock_max_pct": 5,
        "tolerance_band": 3,
        "capacity_band": 3,
        "limited_by": "both",
        "answered_at": "2026-11-08T15:00:00+00:00",
        "taken_at": "2026-11-08T15:00:00+00:00",
    }
    p = active_profile(cfg)
    assert p.get("risk_level") == 3 and p.get("risk", "source") == "questionnaire" and p.get("risk", "version") == 2


# ---- API ----


def test_risk_endpoints_and_profile_init(cfg, demo_cfg, app_client):
    client = app_client(packages=["decisions"])
    body = client.get("/api/decisions/risk").json()
    assert (
        [q["id"] for q in body["questions"]][:2] == ["max_drawdown", "drop_reaction"]
        and body["current"] is None
        and set(body["bands"]) == {"1", "2", "3", "4", "5"}
    )
    assert client.put("/api/decisions/risk", json={"answers": {"goal": "growth"}}).status_code == 422
    put = client.put("/api/decisions/risk", json={"answers": MIDDLE}).json()
    assert put["changed"] is True and put["current"]["band"] == 3
    assert client.put("/api/decisions/risk", json={"answers": MIDDLE}).json()["changed"] is False
    assert len(client.get("/api/decisions/risk/versions").json()["versions"]) == 1
    assert client.get("/api/decisions/profile").json()["profile"]["risk"]["band"] == 3
    made = client.post("/api/decisions/profile/init")
    assert made.status_code == 200 and made.json()["changed"] is True and made.json()["status"]["exists"] is True
    assert made.json()["message"] == "Your profile is set up from your data."
    again = client.post("/api/decisions/profile/init")
    assert again.status_code == 409 and again.json()["detail"] == "You already have a profile. Open Settings to change it."
