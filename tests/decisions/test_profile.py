from pathlib import Path

import pytest

from desk.decisions import active_profile, active_rules
from desk.decisions.profile import DEFAULTS, ProfileError, parse, profile_path
from desk.decisions.store import session

EXAMPLE = Path(__file__).resolve().parents[2] / "desk.example.yaml"


@pytest.fixture
def yaml_path(cfg, monkeypatch):
    path = cfg.data_dir / "desk.yaml"
    monkeypatch.setenv("DESK_PROFILE", str(path))
    return path


def test_example_file_is_valid():
    data, warnings = parse(EXAMPLE.read_text())
    assert warnings == []
    assert data["agents"]["enabled"] is False
    assert {r["kind"] for r in data["rules"]} >= {"no_margin_buys", "no_new_single_stocks"}


def test_missing_file_uses_safe_defaults(cfg, yaml_path):
    p = active_profile(cfg)
    assert p.source == "defaults"
    assert p.version == 1
    assert p.desk_enabled("plan_keeper") is False
    assert p.data["rules"] == DEFAULTS["rules"]


def test_profile_path_default_and_env(cfg):
    assert profile_path(cfg, {}) == cfg.data_dir / "desk.yaml"
    assert profile_path(cfg, {"DESK_PROFILE": "/x/desk.yaml"}) == Path("/x/desk.yaml")


def test_versions_only_move_when_content_changes(cfg, yaml_path):
    yaml_path.write_text(EXAMPLE.read_text())
    first = active_profile(cfg)
    assert active_profile(cfg).version == first.version
    yaml_path.write_text(EXAMPLE.read_text().replace("risk_level: 3", "risk_level: 2"))
    second = active_profile(cfg)
    assert second.version == first.version + 1
    assert second.data["risk_level"] == 2
    assert second.rules_version == first.rules_version


def test_partial_file_merges_over_defaults(cfg, yaml_path):
    yaml_path.write_text("risk_level: 4\ntax:\n  harvest_threshold_usd: 500\n")
    p = active_profile(cfg)
    assert p.data["risk_level"] == 4
    assert p.data["tax"]["harvest_threshold_usd"] == 500
    assert p.data["tax"]["lot_method"] == "highest_cost"
    assert p.data["rules"] == DEFAULTS["rules"]


def test_bad_file_keeps_last_good_version(cfg, yaml_path):
    yaml_path.write_text("risk_level: 2\n")
    good = active_profile(cfg)
    yaml_path.write_text("risk_level: 9\nagents:\n  enabled: maybe\n")
    p = active_profile(cfg)
    assert p.version == good.version
    assert p.data["risk_level"] == 2
    assert "risk_level must be between 1 and 5" in p.error
    assert "agents.enabled must be true or false" in p.error
    yaml_path.write_text("risk_level: 2\n")
    assert active_profile(cfg).error is None


def test_bad_yaml_on_first_load_still_gives_defaults(cfg, yaml_path):
    yaml_path.write_text("risk_level: [unclosed\n")
    p = active_profile(cfg)
    assert p.source == "defaults"
    assert "not valid YAML" in p.error


@pytest.mark.parametrize(
    "text, message",
    [
        ("- just a list\n", "mapping at the top level"),
        ("opportunity:\n  min_confidence: 2\n", "opportunity.min_confidence"),
        ("tax:\n  lot_method: random\n", "tax.lot_method must be one of"),
        ("tax:\n  year_end_start: December\n", "MM-DD"),
        ("growth:\n  tilt: yolo\n", "growth.tilt"),
        ("usage:\n  weekly_runs:\n    tax: 2.5\n", "usage.weekly_runs.tax"),
        ("rules:\n  - kind: no_margin_buys\n", "needs an id"),
        ("rules:\n  - {id: a, kind: no_margin_buys}\n  - {id: a, kind: no_new_single_stocks}\n", "used twice"),
        ("rules:\n  - {id: d, kind: drift_max_pts}\n", "params.pts is required"),
        ("rules:\n  - {id: b, kind: single_stock_band, params: {min_pct: 20, max_pct: 10}}\n", "min_pct is above max_pct"),
    ],
)
def test_validation_errors(text, message):
    with pytest.raises(ProfileError, match=message):
        parse(text)


def test_unknown_sections_and_desks_warn(cfg, yaml_path):
    yaml_path.write_text("mood: sunny\nagents:\n  desks:\n    oracle: true\nrules:\n  - {id: x, kind: moon_phase}\n")
    p = active_profile(cfg)
    assert p.error is None
    assert any("mood" in w for w in p.warnings)
    assert any("oracle" in w for w in p.warnings)
    assert any("moon_phase" in w for w in p.warnings)


def test_desk_needs_master_switch_and_its_own(cfg, yaml_path):
    yaml_path.write_text("agents:\n  enabled: true\n  desks:\n    tax: true\n")
    p = active_profile(cfg)
    assert p.desk_enabled("tax") is True
    assert p.desk_enabled("scout") is False


def test_rule_change_is_logged_as_a_decision(cfg, yaml_path):
    yaml_path.write_text(EXAMPLE.read_text())
    v1, rules = active_rules(cfg)
    assert {r["id"] for r in rules} == {"no-margin-buys", "no-new-single-stocks", "single-stock-band", "drift-max", "cash-floor"}
    floor = "  - id: cash-floor\n    kind: cash_floor_pct\n    params: {pct: 2}\n"
    yaml_path.write_text(EXAMPLE.read_text().replace("{pts: 5}", "{pts: 4}").replace(floor, ""))
    v2, rules = active_rules(cfg)
    assert v2 == v1 + 1
    with session(cfg) as conn:
        logged = conn.execute("SELECT * FROM decisions WHERE kind='rule_change' ORDER BY rowid").fetchall()
        events = conn.execute("SELECT event FROM decision_events").fetchall()
    titles = [r["title"] for r in logged]
    assert titles[0].startswith("Rules set: No buying on margin")
    assert any("Drift limit 5 points → Drift limit 4 points" in t and "removed Cash floor 2%" in t for t in titles)
    assert all(r["status"] == "logged" and r["origin"] == "you" for r in logged)
    assert logged[-1]["rules_version"] == v2
    assert len(events) == len(logged)


def test_disabled_rules_are_versioned_but_not_active(cfg, yaml_path):
    yaml_path.write_text("rules:\n  - {id: m, kind: no_margin_buys}\n  - {id: c, kind: cash_floor_pct, params: {pct: 3}, enabled: false}\n")
    _, rules = active_rules(cfg)
    assert [r["id"] for r in rules] == ["m"]
    with session(cfg) as conn:
        title = conn.execute("SELECT title FROM decisions WHERE kind='rule_change' ORDER BY rowid DESC").fetchone()["title"]
    assert "Cash floor 3%" in title


# ---- FI goal ----


def test_fi_goal_from_the_profile(cfg, yaml_path):
    from datetime import date

    from desk.decisions import risk
    from desk.decisions.profile import DEFAULTS, fi_goal
    from desk.decisions.yamlfile import edit_profile

    assert fi_goal(DEFAULTS) is None
    yaml_path.write_text("fi:\n  yearly_spend_usd: 40000\n  target_age: 40\n  birth_date: '1992-02-29'\n  inflation_pct: 3\n  inflation_adjusted: true\n")
    goal = fi_goal(active_profile(cfg).data)
    assert goal == {"fi_number": 1000000.0, "target_date": "2032-02-28", "inflation": 0.03, "real": True, "source": "profile"}
    assert risk.inputs(cfg, date(2026, 11, 10))["fi_horizon_years"] == 5.3
    out = edit_profile(cfg, {"fi": {"number_usd": 900000, "target_date": "2035-01-01"}})
    assert out["changed"] is True
    goal = fi_goal(active_profile(cfg).data)
    assert (goal["fi_number"], goal["target_date"]) == (900000.0, "2035-01-01")
    yaml_path.write_text("fi:\n  multiple: 0\n  birth_date: soon\n  inflation_adjusted: maybe\n")
    with pytest.raises(ProfileError) as e:
        parse(yaml_path.read_text())
    assert (
        "fi.multiple must be between 1 and 100" in str(e.value) and "fi.birth_date must be a date" in str(e.value) and "fi.inflation_adjusted" in str(e.value)
    )
