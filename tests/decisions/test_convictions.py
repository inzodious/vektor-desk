import sqlite3
from datetime import UTC, datetime

import pytest
import yaml

from desk.db import apply_schemas
from desk.decisions import active_profile, risk
from desk.decisions import alerts as alerting
from desk.decisions.rules import conviction_symbols, describe, validate_rules
from desk.decisions.yamlfile import EditError, edit_profile, replace_section

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
STARTER = """# My desk
risk_level: 3

# Alerts
alerts:
  min_priority: default

rules:
  - id: no-margin-buys
    kind: no_margin_buys
  - id: single-stock-band
    kind: single_stock_band
    params: {min_pct: 0, max_pct: 10}

# Tail comment stays
deposits: auto
"""


@pytest.fixture
def yaml_file(cfg):
    path = cfg.data_dir / "desk.yaml"
    path.write_text(STARTER)
    return path


def _weight(cfg, symbol, value, as_of="2026-11-07"):
    apply_schemas(cfg, only=["engine"])
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(
        "INSERT INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, quality, engine_version) "
        "VALUES ('plan.single_stock', 'holding', ?, 'now', ?, ?, 'pct', 'ok', 'x')",
        (symbol, as_of, value),
    )
    conn.commit()
    conn.close()


# ---- Rule kind ----


def test_conviction_rule_validates():
    good = [{"id": "c", "kind": "conviction_hold", "symbols": ["ABCD"], "params": {"band_min_pct": 0, "band_max_pct": 20}}]
    assert validate_rules(good) == ([], [])
    assert describe(good[0]) == "ABCD conviction hold 0 to 20%"
    assert conviction_symbols(good) == {"ABCD"}
    assert conviction_symbols([{**good[0], "enabled": False}]) == set()
    errors, _ = validate_rules([{**good[0], "symbols": ["A", "B"]}])
    assert errors == ["rules[0]: conviction_hold needs exactly one ticker in symbols"]
    errors, _ = validate_rules([{**good[0], "params": {"band_min_pct": 30, "band_max_pct": 20}}])
    assert errors == ["rules[0]: band_min_pct is above band_max_pct"]
    errors, _ = validate_rules([good[0], {**good[0], "id": "d", "symbols": ["abcd"]}])
    assert errors == ["rules[1]: ABCD already has a conviction hold"]
    errors, _ = validate_rules([{**good[0], "params": {"band_min_pct": 0}}])
    assert errors == ["rules[0].params.band_max_pct is required for conviction_hold"]


# ---- Profile edits ----


def test_replace_section_keeps_other_text():
    out = replace_section(STARTER, "alerts", "alerts:\n  min_priority: high\n")
    assert "# My desk\nrisk_level: 3\n\n# Alerts\nalerts:\n  min_priority: high\n\nrules:" in out
    assert out.endswith("# Tail comment stays\ndeposits: auto\n")
    assert replace_section("a: 1\n", "b", "b: 2").endswith("a: 1\n\nb: 2\n")


def test_edit_profile_merges_writes_backup_and_versions(cfg, yaml_file):
    before = active_profile(cfg).version
    result = edit_profile(cfg, {"alerts": {"min_priority": "high"}, "agents": {"enabled": True, "desks": {"tax": True}}})
    assert result["changed"] is True and result["sections"] == ["agents", "alerts"]
    assert result["version"] > before
    assert (cfg.data_dir / "desk.yaml.bak").read_text() == STARTER
    text = yaml_file.read_text()
    assert text.startswith("# My desk\nrisk_level: 3\n") and "# Tail comment stays" in text
    data = active_profile(cfg).data
    assert data["alerts"]["min_priority"] == "high" and data["agents"]["enabled"] is True and data["agents"]["desks"]["tax"] is True
    assert data["agents"]["desks"]["risk"] is False
    again = edit_profile(cfg, {"alerts": {"min_priority": "high"}})
    assert again["changed"] is False and again["backup"] is None


def test_edit_profile_refuses_bad_changes(cfg, yaml_file):
    with pytest.raises(EditError, match="risk questions"):
        edit_profile(cfg, {"risk_level": 5})
    with pytest.raises(EditError, match="unknown section nope"):
        edit_profile(cfg, {"nope": 1})
    with pytest.raises(EditError, match="doesn't validate"):
        edit_profile(cfg, {"alerts": {"min_priority": "shout"}})
    assert yaml_file.read_text() == STARTER
    assert not (cfg.data_dir / "desk.yaml.bak").exists()
    yaml_file.unlink()
    with pytest.raises(EditError, match="no desk.yaml") as e:
        edit_profile(cfg, {"alerts": {"min_priority": "high"}})
    assert e.value.status == 409


# ---- Convictions ----


def test_conviction_band_comes_from_risk_result(cfg, yaml_file):
    with pytest.raises(risk.RiskError, match="risk questions first"):
        risk.set_conviction(cfg, "abcd")
    assert risk.suggested_band(cfg) is None
    risk.save(cfg, MIDDLE, now=NOW)
    assert risk.suggested_band(cfg) == {"band_min_pct": 0, "band_max_pct": 5, "from_band": 3, "label": "Moderate"}
    out = risk.set_conviction(cfg, "abcd", note="Held for the long run")
    assert out["changed"] is True
    assert out["item"] == {
        "rule_id": "conviction-abcd",
        "symbol": "ABCD",
        "band_min_pct": 0,
        "band_max_pct": 5,
        "note": "Held for the long run",
        "enabled": True,
        "weight_pct": None,
        "weight_as_of": None,
        "status": None,
    }
    rules = yaml.safe_load(yaml_file.read_text())["rules"]
    assert rules[-1] == {
        "id": "conviction-abcd",
        "kind": "conviction_hold",
        "symbols": ["ABCD"],
        "params": {"band_min_pct": 0, "band_max_pct": 5},
        "note": "Held for the long run",
    }
    assert [r["id"] for r in rules] == ["no-margin-buys", "single-stock-band", "conviction-abcd"]


def test_conviction_update_status_and_drop(cfg, yaml_file):
    risk.set_conviction(cfg, "ABCD", band_min_pct=5, band_max_pct=20)
    risk.set_conviction(cfg, "abcd", band_max_pct=25)
    _weight(cfg, "ABCD", 31.4)
    [item] = risk.convictions(cfg)
    assert (item["band_min_pct"], item["band_max_pct"], item["weight_pct"], item["status"]) == (5, 25, 31.4, "above")
    assert len([r for r in active_profile(cfg).data["rules"] if r["kind"] == "conviction_hold"]) == 1
    with pytest.raises(EditError, match="doesn't validate"):
        risk.set_conviction(cfg, "ABCD", band_min_pct=30)
    with pytest.raises(risk.RiskError, match="ticker"):
        risk.set_conviction(cfg, "AB CD", band_max_pct=10)
    assert risk.drop_conviction(cfg, "abcd")["changed"] is True
    assert risk.convictions(cfg) == []
    with pytest.raises(risk.RiskError, match="no conviction hold"):
        risk.drop_conviction(cfg, "ABCD")


def test_trim_alert_only_above_band(cfg, yaml_file, monkeypatch):
    sent = []
    monkeypatch.setattr(alerting, "publish", lambda topic, title, body="", priority="default", **kw: sent.append({"title": title, "body": body, **kw}) or True)
    risk.set_conviction(cfg, "ABCD", band_min_pct=0, band_max_pct=20)
    _weight(cfg, "ABCD", 18.0, "2026-11-06")
    assert not [s for s in alerting.send_alerts(cfg, now=NOW) if s.startswith("conviction")]
    _weight(cfg, "ABCD", 22.5, "2026-11-07")
    keys = [s for s in alerting.send_alerts(cfg, now=NOW) if s.startswith("conviction")]
    assert keys == ["conviction-ABCD-2026-W45"]
    msg = next(s for s in sent if s["key"] == keys[0])
    assert msg["title"] == "ABCD is above its band" and "22.5% of the portfolio, past your 20% ceiling" in msg["body"]


# ---- API ----


def test_conviction_and_profile_endpoints(cfg, yaml_file, app_client):
    client = app_client(packages=["decisions"])
    assert client.get("/api/decisions/convictions").json() == {"items": [], "suggested": None}
    assert client.put("/api/decisions/convictions/ABCD", json={}).status_code == 422
    client.put("/api/decisions/risk", json={"answers": MIDDLE})
    put = client.put("/api/decisions/convictions/abcd", json={"note": "Long run"}).json()
    assert put["changed"] is True and put["item"]["band_max_pct"] == 5 and put["suggested"]["from_band"] == 3
    assert client.put("/api/decisions/convictions/ABCD", json={"band_min_pct": 9}).status_code == 422
    listed = client.get("/api/decisions/convictions").json()["items"]
    assert [c["symbol"] for c in listed] == ["ABCD"]
    rules = client.get("/api/decisions/rules").json()["rules"]
    assert any(r["label"] == "ABCD conviction hold 0 to 5%" for r in rules)
    assert client.delete("/api/decisions/convictions/ABCD").json()["changed"] is True
    assert client.delete("/api/decisions/convictions/ABCD").status_code == 404
    profile = client.get("/api/decisions/profile").json()
    assert "risk_level" not in profile["editable"] and "alerts" in profile["editable"]
    patched = client.patch("/api/decisions/profile", json={"changes": {"alerts": {"min_priority": "high"}}}).json()
    assert patched["changed"] is True and patched["status"]
    assert client.get("/api/decisions/profile").json()["profile"]["alerts"]["min_priority"] == "high"
    assert client.patch("/api/decisions/profile", json={"changes": {"risk_level": 2}}).status_code == 422
    yaml_file.unlink()
    assert client.patch("/api/decisions/profile", json={"changes": {"alerts": {"min_priority": "low"}}}).status_code == 409
