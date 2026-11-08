from datetime import UTC, datetime

import pytest
import yaml

from desk.decisions import calendar_events
from desk.decisions.profile import ProfileError, active_profile, main, parse
from desk.decisions.rules import describe
from desk.decisions.targets import TargetsError, add_action, plan_for, planned_actions, profile_plan, set_plan

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
START = """# my notes stay
risk_level: 2
rules:
- id: cash-floor
  kind: cash_floor_pct
  params: {pct: 2}
- id: old-drift
  kind: drift_max_pts
  params: {pts: 9}
agents:
  enabled: true
"""


@pytest.fixture
def desk_yaml(cfg):
    path = cfg.data_dir / "desk.yaml"
    path.write_text(START)
    return path


# ---- Preset ----


def test_set_plan_v3_writes_targets_and_rules_once(cfg, desk_yaml):
    changed, message = set_plan(desk_yaml, "v3")
    assert changed and "8 funds" in message and (cfg.data_dir / "desk.yaml.bak").read_text() == START
    text = desk_yaml.read_text()
    data, warnings = parse(text)
    assert warnings == [] and text.startswith("# my notes stay") and data["risk_level"] == 2 and data["agents"]["enabled"] is True
    assert [r["id"] for r in data["rules"]] == ["no-margin-buys", "no-new-single-stocks", "single-stock-band", "drift-max", "cash-floor"]
    band = next(r for r in data["rules"] if r["id"] == "single-stock-band")
    assert band["params"] == {"min_pct": 0, "max_pct": 15, "trim_to_pct": 10}
    assert describe(band) == "Single stocks up to 15%, trim back to 10% when over"
    assert set_plan(desk_yaml, "v3") == (False, f"{desk_yaml} already has the v3 plan. Nothing changed.")
    assert (cfg.data_dir / "desk.yaml.bak").read_text() == START
    with pytest.raises(TargetsError, match="Unknown preset"):
        set_plan(desk_yaml, "v9")


def test_profile_plan_is_engine_shaped_and_beats_the_mirror_plan(cfg, desk_yaml):
    assert plan_for(cfg, {"funds": [{"ticker": "AAAA", "target_weight": 1}]}) == {"funds": [{"ticker": "AAAA", "target_weight": 1}]}
    set_plan(desk_yaml, "v3")
    plan = profile_plan(active_profile(cfg))
    weights = {f["ticker"]: f["target_weight"] for f in plan["funds"]}
    assert weights["FXAIX"] == 0.4 and weights["UFO"] == 0.05 and round(sum(weights.values()), 6) == 1
    assert plan["hold"] == ["SPY"] and plan["guardrails"] == {"drift_alert_pct_points": 5} and plan["new_money"] == "underweight_first"
    assert plan["outside"] == [{"account": "401k", "proxy": {"SPY": 80, "ISTNX": 20}, "note": "Managed in the 401(k); the desk doesn't steer it"}]
    assert plan_for(cfg, {"funds": []})["source"] == "profile"


@pytest.mark.parametrize(
    "block, message",
    [
        ("targets:\n  funds: [{ticker: AAAA, weight_pct: 60}, {ticker: BBBB, weight_pct: 30}]\n", "add to 90"),
        ("targets:\n  funds: [{ticker: AAAA, weight_pct: 100}]\n  hold: [AAAA]\n", "can't repeat"),
        ("targets:\n  funds: [{ticker: aaaa, weight_pct: 100}]\n", "needs a ticker"),
        ("rules:\n  - {id: b, kind: single_stock_band, params: {min_pct: 0, max_pct: 10, trim_to_pct: 12}}\n", "trim_to_pct is above"),
        ("actions:\n  - {id: a, side: sell, symbols: [ABCD, QRST], shares: 5, from: 2026-12-01, to: 2026-12-02}\n", "single symbol"),
        ("actions:\n  - {id: a, side: hold, symbol: ABCD, from: 2026-12-03, to: 2026-12-02}\n", "sell or buy"),
    ],
)
def test_validation(block, message):
    with pytest.raises(ProfileError, match=message):
        parse(block)


# ---- One-off actions ----


def test_actions_from_the_cli_show_on_the_calendar_and_finish_from_activity(cfg, desk_yaml, mirror, monkeypatch, capsys):
    monkeypatch.setattr("desk.decisions.profile.Config.from_env", lambda: cfg)
    trim = ["add-action", "--id", "trim", "--side", "sell", "--symbol", "ABCD", "--shares", "12", "--account", "Individual"]
    trim += ["--from", "2026-12-07", "--to", "2026-12-15", "--lots", "highest_cost", "--no-buy-days", "31", "--note", "Tax loss."]
    assert main(trim) == 0 and "now plans sell 12 ABCD" in capsys.readouterr().out
    assert main(trim) == 0 and "Nothing changed" in capsys.readouterr().out
    gains = ["add-action", "--id", "gains", "--side", "sell", "--symbol", "QRST,WXYZ", "--from", "2026-11-10", "--to", "2026-11-20"]
    assert main(gains) == 0
    raw = yaml.safe_load(desk_yaml.read_text())["actions"]
    assert raw[0] == {
        "id": "trim",
        "side": "sell",
        "symbol": "ABCD",
        "shares": 12,
        "from": "2026-12-07",
        "to": "2026-12-15",
        "account": "Individual",
        "lots": "highest_cost",
        "no_buy_days": 31,
        "note": "Tax loss.",
    }
    assert raw[1]["symbols"] == ["QRST", "WXYZ"] and raw[1]["shares"] == "all"
    mirror("q", date="2026-11-12", accountKey="individual-1", kind="sell", symbol="QRST", quantity=-3, amount=300)
    items = {a["id"]: a for a in planned_actions(cfg, now=NOW)}
    assert items["trim"]["status"] == "upcoming" and items["trim"]["title"] == "Sell 12 ABCD"
    assert items["gains"]["status"] == "open" and items["gains"]["done"] == ["QRST"] and items["gains"]["title"] == "Sell QRST and WXYZ"
    titles = [e["title"] for e in calendar_events(cfg, "2026-11-01", "2027-02-01", now=NOW) if e["kind"] == "trade"]
    assert titles == [
        "Sell QRST and WXYZ window opens",
        "Sell QRST and WXYZ window closes",
        "Sell 12 ABCD window opens, highest-cost lots",
        "Sell 12 ABCD window closes",
    ]
    mirror("w", date="2026-11-18", accountKey="individual-1", kind="sell", symbol="WXYZ", quantity=-1, amount=90)
    mirror("a", date="2026-12-08", accountKey="individual-1", kind="sell", symbol="ABCD", quantity=-12, amount=-400)
    later = datetime(2026, 12, 9, 15, 0, tzinfo=UTC)
    items = {a["id"]: a for a in planned_actions(cfg, now=later)}
    assert items["gains"]["status"] == "done" and items["gains"]["done_on"] == "2026-11-18"
    assert items["trim"]["status"] == "done" and items["trim"]["no_buy_until"] == "2027-01-08" and items["trim"]["no_buy_now"] is True
    assert "ABCD buys are fine again" in [e["title"] for e in calendar_events(cfg, "2027-01-01", "2027-01-31", now=later)]
    assert main(["actions"]) == 0
    out = capsys.readouterr().out
    assert "Sell 12 ABCD. From Individual. Done 2026-12-08. No ABCD buys until 2027-01-08." in out


def test_add_action_needs_a_file(cfg):
    with pytest.raises(TargetsError, match="doesn't exist"):
        add_action(cfg.data_dir / "desk.yaml", {"id": "a", "side": "sell", "symbol": "ABCD", "from": "2026-12-01", "to": "2026-12-02"})


# ---- API ----


def test_plan_endpoints(cfg, desk_yaml, app_client):
    client = app_client(packages=["decisions"])
    assert client.get("/api/decisions/plan").json()["plan"] is None
    first = client.put("/api/decisions/profile/plan", json={"preset": "v3"}).json()
    assert first["changed"] is True and first["profile"]["profile"]["targets"]["preset"] == "v3"
    assert client.put("/api/decisions/profile/plan", json={"preset": "v3"}).json()["changed"] is False
    assert client.put("/api/decisions/profile/plan", json={"preset": "nope"}).status_code == 422
    body = client.get("/api/decisions/plan").json()
    assert body["source"] == "profile" and body["presets"] == ["v3"] and len(body["plan"]["funds"]) == 8
    assert client.get("/api/decisions/actions").json() == {"actions": [], "lines": []}
