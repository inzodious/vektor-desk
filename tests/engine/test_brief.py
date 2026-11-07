import json
from datetime import UTC, datetime

import pytest

from desk.agents.sources import NotReady as AgentNotReady
from desk.agents.sources import RealEngine, RealTriggers
from desk.db import connect
from desk.engine import brief, core, triggers
from desk.engine.__main__ import run_holdings
from desk.engine.preflight import check_trade
from desk.engine.source import open_mirror
from tests.engine.helpers import closes_doc, position, snapshot
from tests.engine.test_preflight import IND, add_lots, seed

NOW = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)
TAX_ENGINE = {
    "key": "taxEngine",
    "value": {"res": {"ok": True, "federal": {"tax": 10000.0}, "stateTax": 3000.0, "raise": {"federal": 10220.0, "state": 3045.0}}},
}


def run_core(cfg, now=NOW):
    mirror, desk = open_mirror(cfg), connect(cfg.desk_db)
    try:
        stored = core.store(desk, core.compute(cfg, mirror, desk, now=now))
        fired = triggers.run(cfg, desk, stored["as_of"], now=now)
        metrics = {
            (r["metric_id"], r["scope_id"], r["window"]): r["value"] for r in desk.execute("SELECT * FROM metric_values WHERE as_of=?", (stored["as_of"],))
        }
    finally:
        desk.close()
        mirror.close()
    return stored, fired, metrics


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        triggers, "publish", lambda topic, title, body="", priority="default", **kw: calls.append((topic, title, body, priority, kw["key"])) or True
    )
    return calls


# ---- Brief slices ----


def test_slice_needs_an_engine_run(cfg):
    with pytest.raises(brief.NotReady):
        brief.desk_slice(cfg, "plan_keeper")
    with pytest.raises(AgentNotReady):
        RealEngine().desk_slice(cfg, "tax")
    assert RealTriggers().today(cfg) == []


def test_slices_carry_metrics_lots_wash_and_triggers(cfg, mirror, sent):
    seed(mirror)
    mirror.put("prefs", "taxEngine", TAX_ENGINE)
    mirror.put("activity", "a1", {"date": "2026-10-20", "accountKey": IND, "kind": "buy", "symbol": "FXAIX", "quantity": 1, "amount": -200.0})
    mirror.pull("2026-11-04T21:30:00+00:00")
    add_lots(cfg, [(IND, "ACME", "2025-01-10", 10, 600.0), (IND, "FXAIX", "2026-06-01", 5, 900.0)])
    stored, _, _ = run_core(cfg)
    keeper = RealEngine().desk_slice(cfg, "plan_keeper")
    assert keeper["data_as_of"] == stored["as_of"] and {h["check"] for h in keeper["data_health"]} >= {"freshness", "value"}
    keys = {f"{i['metric_id']}:{i['scope_id']}:{i['window']}" for i in keeper["sections"]["drift"]}
    assert {"plan.drift:FXAIX:now", "plan.drift_max:all:now", "plan.next_deposit:VXUS:now"} <= keys
    assert "lots" not in keeper["sections"] and all(i["metric_id"].startswith("cash.") for i in keeper["sections"]["cash"])
    tax = brief.desk_slice(cfg, "tax")
    lots = {lot["symbol"]: lot for lot in tax["sections"]["lots"]}
    assert lots["ACME"]["gain"] == -400.0 and lots["ACME"]["term"] == "long" and lots["FXAIX"]["term"] == "short"
    assert [w["symbol"] for w in tax["sections"]["wash_windows"]] == ["FXAIX"]
    ids = {i["metric_id"] for i in tax["sections"]["tax"]}
    assert {"tax.marginal_rate", "tax.harvest_value", "tax.harvestable", "tax.unrealized_lt", "tax.wash_window"} <= ids
    kinds = {t["kind"] for t in keeper["sections"]["triggers"]}
    assert {"concentration", "rule_breach"} <= kinds
    with pytest.raises(ValueError):
        brief.desk_slice(cfg, "nobody")


def test_marginal_rate_and_harvest_value(cfg, mirror, sent):
    seed(mirror)
    mirror.put("prefs", "taxEngine", TAX_ENGINE)
    mirror.pull("2026-11-04T21:30:00+00:00")
    add_lots(cfg, [(IND, "ACME", "2025-01-10", 10, 600.0)])
    stored, _, m = run_core(cfg)
    assert m[("tax.marginal_rate", "all", "now")] == 26.5 and m[("tax.marginal_rate", "federal", "now")] == 22.0
    assert m[("tax.harvest_value", "all", "now")] == pytest.approx(106.0)
    assert stored["checks"]["marginal_rate"] == "ok"
    r = check_trade(cfg, {"kind": "harvest", "symbol": "ACME", "shares": 10}, now=NOW)
    assert r["tax"]["harvest_loss"] == 400.0 and r["tax"]["harvest_value"] == 106.0


def test_marginal_rate_falls_back_to_env_then_warns(cfg, mirror, monkeypatch, sent):
    seed(mirror)
    add_lots(cfg, [])
    stored, _, _ = run_core(cfg)
    assert stored["checks"]["marginal_rate"] == "warn"
    monkeypatch.setenv("DESK_MARGINAL_RATE_PCT", "24")
    _, _, m = run_core(cfg)
    assert m[("tax.marginal_rate", "all", "now")] == 24.0


# ---- Triggers ----


def test_triggers_fire_once_a_day_and_alert_only_on_crossing(cfg, mirror, sent, monkeypatch):
    monkeypatch.setenv("DESK_MARGIN_RATE_PCT", "12")
    seed(mirror, cash=-300.0)
    add_lots(cfg, [])
    _, fired, _ = run_core(cfg)
    assert {"margin_debit", "concentration", "rule_breach"} <= set(fired["kinds"])
    titles = {t[1] for t in sent}
    assert "Margin debit on the desk" in titles and "Concentration band crossed" in titles and "A plan rule is off" in titles
    assert all("$" not in t[2] or "$…" in t[2] for t in sent) and all(t[0] == "alerts" for t in sent)
    count = len(sent)
    _, again, _ = run_core(cfg)
    assert again["new"] == 0 and len(sent) == count
    rows = RealTriggers().today(cfg)
    margin = next(r for r in rows if r["kind"] == "margin_debit")
    assert margin["scope_id"] == "portfolio" and json.loads(margin["detail"])["debit"] == 300.0


def test_a_condition_that_holds_overnight_does_not_alert_again(cfg, mirror, sent):
    seed(mirror, cash=-300.0)
    add_lots(cfg, [])
    run_core(cfg)
    first = len(sent)
    mirror.put("snapshots", 2, snapshot(2, "2026-11-05T08:00", 1000.0 + 200.0 - 300.0, 3))
    mirror.put("positions", 21, position(21, 2, IND, "FXAIX", 5, 1000.0, 900.0))
    mirror.put("positions", 22, position(22, 2, IND, "ACME", 10, 200.0, 250.0))
    mirror.put("positions", 23, position(23, 2, IND, "SPAXX", -300, -300.0, cash=True))
    for sym, price in (("FXAIX", 200.0), ("ACME", 20.0), ("VXUS", 60.0), ("NEWCO", 10.0)):
        mirror.put("priceCloses", f"{sym}_2026", closes_doc(sym, 2026, [[d, price, price] for d in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05")]))
    mirror.pull("2026-11-05T21:00:00+00:00")
    run_holdings(cfg)
    stored, fired, _ = run_core(cfg, now=datetime(2026, 11, 5, 23, 0, tzinfo=UTC))
    assert stored["as_of"] == "2026-11-05" and "margin_debit" in fired["kinds"] and len(sent) == first


def test_big_holding_move_and_lot_export(cfg, mirror, sent):
    seed(mirror)
    mirror.put("priceCloses", "ACME_2026", closes_doc("ACME", 2026, [["2026-11-02", 20.0, 20.0], ["2026-11-03", 20.0, 20.0], ["2026-11-04", 18.5, 18.5]]))
    mirror.pull("2026-11-04T21:30:00+00:00")
    add_lots(cfg, [])
    _, fired, _ = run_core(cfg)
    assert "daily_move" in fired["kinds"]
    desk = connect(cfg.desk_db)
    try:
        new = triggers.record(cfg, desk, triggers.lot_export(cfg, desk, [{"file": "lots.csv", "kind": "lots", "rows": 3}], now=NOW), now=NOW)
    finally:
        desk.close()
    assert [(t["kind"], t["scope_id"]) for t in new] == [("lot_export", "lots")]
    moves = [t for t in RealTriggers().today(cfg) if t["kind"] == "daily_move"]
    assert [m["scope_id"] for m in moves] == ["ACME"] and any("ACME" in t[2] for t in sent)
