import json
import sqlite3
from datetime import date, timedelta

import pytest

from desk.decisions import active_profile, starter
from desk.decisions.profile import main, parse
from desk.decisions.starter import StarterError, cadence, init, rules_from_plan, status
from desk.mirror.store import SCHEMA as MIRROR_SCHEMA

TODAY = date(2026, 11, 20)


def _mirror(cfg, rows):
    conn = sqlite3.connect(cfg.mirror_db)
    conn.executescript(MIRROR_SCHEMA)
    for i, (tbl, row) in enumerate(rows):
        conn.execute("INSERT INTO rows (tbl, id, json, at) VALUES (?, ?, ?, '2026-11-20T00:00:00Z')", (tbl, f"{tbl}-{i}", json.dumps(row)))
    conn.commit()
    conn.close()


def _every(start: date, step: int, n: int) -> list[date]:
    return [start + timedelta(days=step * i) for i in range(n)]


def test_cadence_patterns():
    assert cadence(_every(date(2026, 9, 4), 7, 6)) == {"cadence": "weekly", "anchor": "2026-10-09"}
    assert cadence(_every(date(2026, 7, 3), 14, 8)) == {"cadence": "biweekly", "anchor": "2026-10-09"}
    semi = [date(2026, 8, 14), date(2026, 8, 31), date(2026, 9, 15), date(2026, 9, 30), date(2026, 10, 15), date(2026, 10, 30)]
    assert cadence(semi) == {"cadence": "semimonthly", "days": [15, 30], "weekend": "before"}
    monthly = [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 3), date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 2)]
    assert cadence(monthly) == {"cadence": "monthly", "days": [1], "weekend": "after"}
    assert cadence([date(2026, 1, 1), date(2026, 1, 3), date(2026, 3, 9), date(2026, 8, 20)]) is None
    assert cadence([date(2026, 1, 1), date(2026, 1, 15)]) is None


def test_rules_from_plan_guardrails():
    rules = rules_from_plan({"guardrails": {"max_single_stock_weight": 0.12, "drift_alert_pct_points": 4}})
    assert {"id": "single-stock-band", "kind": "single_stock_band", "params": {"min_pct": 0, "max_pct": 12.0}} in rules
    assert {"id": "drift-max", "kind": "drift_max_pts", "params": {"pts": 4}} in rules
    assert [r["kind"] for r in rules_from_plan({})] == ["no_margin_buys", "no_new_single_stocks", "drift_max_pts"]


def test_init_from_demo_mirror_writes_a_valid_draft_once(demo_cfg):
    path, text = init(demo_cfg, today=TODAY)
    assert path == demo_cfg.data_dir / "desk.yaml" and path.read_text() == text
    data, warnings = parse(text)
    assert warnings == []
    assert {d["account"] for d in data["deposits"]} == {"individual-0001", "hsa-0002"}
    assert all(d["cadence"] == "monthly" and d["days"] == [1] for d in data["deposits"])
    assert sorted(d["amount_usd"] for d in data["deposits"]) == [100, 500]
    assert data["tax"]["wash_sale_accounts"] == ["hsa-0002", "individual-0001"]
    assert data["tax"]["lot_method"] == "highest_cost"
    assert data["agents"]["enabled"] is False and data["agents"]["desks"]["plan_keeper"] is True
    assert "# risk_level: 3" in text
    with pytest.raises(StarterError, match="already exists"):
        init(demo_cfg, today=TODAY)
    assert path.read_text() == text
    assert active_profile(demo_cfg).source == str(path)


def test_status_lists_what_is_still_default(demo_cfg):
    before = status(demo_cfg)
    assert before["exists"] is False and before["source"] == "defaults" and "profile init" in before["starter"]
    assert "deposits" in before["defaults"] and "risk_level" in before["defaults"]
    init(demo_cfg, today=TODAY)
    after = status(demo_cfg)
    assert after["exists"] is True and after["starter"] is None and after["error"] is None
    assert {"deposits", "tax.wash_sale_accounts", "industry_focus.themes", "agents.desks"} <= set(after["set"])
    assert {"risk_level", "agents.enabled", "tax.harvest_threshold_usd", "opportunity.satellite_cap_pct"} <= set(after["defaults"])
    assert after["agents_enabled"] is False and after["desks_on"] == [] and after["deposits"] == 2


def test_falls_back_to_pay_dates_and_plan_amount(cfg):
    stubs = [("paystubs", {"payDate": d.isoformat()}) for d in _every(date(2026, 7, 3), 14, 10)]
    plan = {"funds": [{"ticker": "AAAA", "sleeve": "core", "target_weight": 1}], "monthly_plan": [{"month": "2026-12", "contribution": 1000}]}
    snap = {"id": 9, "asOf": "2026-11-19T16:00", "accounts": [{"key": "hsa-1", "kind": "hsa"}, {"key": "brokerage-2", "kind": "individual"}]}
    _mirror(cfg, [*stubs, ("plans", {"id": 1, "plan": plan, "loadedAt": "2026-10-01"}), ("snapshots", snap)])
    _, text = init(cfg, dry_run=True, today=TODAY)
    data, _ = parse(text)
    assert data["deposits"] == [{"id": "payday", "account": "brokerage-2", "cadence": "biweekly", "anchor": "2026-11-06", "amount_usd": 462}]
    assert "pay dates from paystubs, amount from the plan" in text
    assert not (cfg.data_dir / "desk.yaml").exists()


def test_payroll_transactions_when_no_paystubs(cfg):
    pay = [("transactions", {"date": d.isoformat(), "kind": "income", "category": "Paycheck", "amount": 1}) for d in _every(date(2026, 8, 7), 7, 8)]
    _mirror(cfg, [*pay, ("snapshots", {"id": 1, "asOf": "2026-11-19", "accounts": [{"key": "joint-3", "kind": "joint"}]})])
    data, _ = parse(init(cfg, dry_run=True, today=TODAY)[1])
    assert data["deposits"][0]["cadence"] == "weekly" and "amount_usd" not in data["deposits"][0]


def test_empty_mirror_still_drafts_and_no_mirror_refuses(cfg):
    with pytest.raises(StarterError, match="No mirror"):
        init(cfg, today=TODAY)
    _mirror(cfg, [])
    _, text = init(cfg, dry_run=True, today=TODAY)
    assert "add deposits by hand" in text and "rules stay at the defaults" in text
    parse(text)


def test_cli_init_print_status(demo_cfg, monkeypatch, capsys):
    monkeypatch.setattr("desk.decisions.profile.Config.from_env", lambda: demo_cfg)
    assert main(["init", "--print"]) == 0
    assert "deposits:" in capsys.readouterr().out
    assert main(["init"]) == 0 and "Wrote" in capsys.readouterr().out
    assert main(["init"]) == 1 and "already exists" in capsys.readouterr().err
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["exists"] is True


def test_status_endpoint(demo_cfg, app_client):
    client = app_client(packages=["decisions"], config=demo_cfg)
    body = client.get("/api/decisions/profile/status").json()
    assert body["source"] == "defaults" and "deposits" in body["defaults"]


def test_bad_draft_is_never_written(demo_cfg, monkeypatch):
    monkeypatch.setattr(starter, "render", lambda data, notes, today: "risk_level: 9\n")
    with pytest.raises(StarterError, match="didn't validate"):
        init(demo_cfg, today=TODAY)
    assert not (demo_cfg.data_dir / "desk.yaml").exists()
