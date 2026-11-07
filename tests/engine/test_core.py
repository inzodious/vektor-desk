from datetime import UTC, date, datetime

import pytest

from desk.db import connect
from desk.engine import core
from desk.engine.__main__ import run_core, run_daily, run_holdings
from desk.engine.flows import classify
from desk.engine.returns import annualize, base_index, drawdowns, period_mwr, twr_index, volatility, xirr
from desk.engine.shadows import TotalReturn, shadow
from desk.engine.source import open_mirror
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"
HSA = "hsa-2222"
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04"]
FRESH = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)


# ---- Returns ----


def test_twr_without_flows_is_the_simple_return():
    values = [100.0, 104.0, 98.0, 110.0]
    index = twr_index(values, [0.0] * 4)
    assert index[-1] == pytest.approx(1.10)


def test_twr_ignores_a_deposit_and_a_withdrawal():
    values = [100.0, 100.0, 1100.0, 600.0]
    flows = [0.0, 0.0, 1000.0, -500.0]
    assert twr_index(values, flows) == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_xirr_identities():
    t0 = date(2025, 1, 1)
    assert xirr([(t0, -100.0), (date(2026, 1, 1), 110.0)]) == pytest.approx(0.10, abs=1e-6)
    assert xirr([(t0, -100.0), (date(2026, 1, 1), 100.0)]) == pytest.approx(0.0, abs=1e-6)
    assert xirr([(t0, -100.0)]) is None
    assert xirr([(t0, 100.0), (date(2026, 1, 1), 100.0)]) is None


def test_period_mwr_is_not_annualized_under_a_year():
    dates = ["2026-01-01", "2026-07-02"]
    assert period_mwr(dates, [100.0, 105.0], [0.0, 0.0], 0) == pytest.approx(0.05, abs=1e-6)
    assert annualize(0.05, 182) is None
    assert annualize(0.21, 730) == pytest.approx(0.1, abs=1e-3)


def test_drawdowns_and_volatility():
    worst, current, longest = drawdowns([1.0, 1.2, 0.9, 1.0, 1.3, 1.17])
    assert worst == pytest.approx(-0.25) and current == pytest.approx(-0.1) and longest == 2
    assert volatility([0.01, 0.01, 0.01]) == pytest.approx(0.0)
    assert volatility([0.01]) is None


def test_window_bases():
    dates = ["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]
    assert base_index(dates, "1D") == 2
    assert base_index(dates, "YTD") == 1
    assert base_index(dates, "1Y") is None
    assert base_index(dates, "ITD") == 0


# ---- Shadows and flows ----


def test_shadow_buys_with_the_actual_flows():
    tr = TotalReturn({"AAA": {"2026-11-02": (1.0, None), "2026-11-03": (2.0, None), "2026-11-04": (2.0, 2.0)}})
    values, quality, mix = shadow(DAYS, 100.0, [0.0, 100.0, -150.0], {"AAA": 1.0}, tr)
    assert values == [100.0, 300.0, 150.0] and quality == "ok" and mix == {"AAA": 1.0}


def test_plan_shadow_deposits_steer_drift_and_never_sell():
    tr = TotalReturn(
        {
            "AAA": {"2026-11-02": (1.0, None), "2026-11-03": (2.0, None), "2026-11-04": (2.0, None)},
            "BBB": {"2026-11-02": (1.0, None), "2026-11-03": (1.0, None), "2026-11-04": (2.0, None)},
        }
    )
    values, _, _ = shadow(DAYS, 100.0, [0.0, 50.0, 0.0], {"AAA": 0.5, "BBB": 0.5}, tr)
    assert values == [100.0, 200.0, 300.0]


def test_shadow_is_pro_forma_when_a_fund_has_no_history():
    tr = TotalReturn({"AAA": {"2026-11-02": (1.0, 1.0)}, "BBB": {"2026-11-04": (1.0, 1.0)}})
    values, quality, mix = shadow(DAYS, 100.0, [0.0, 0.0, 0.0], {"AAA": 0.5, "BBB": 0.5}, tr)
    assert quality == "pro_forma" and mix == {"AAA": 1.0} and values[-1] == 100.0


def test_transfers_between_accounts_are_internal():
    activity = [
        {"date": "2026-11-02", "accountKey": IND, "kind": "deposit", "amount": 500.0},
        {"date": "2026-11-03", "accountKey": IND, "kind": "withdrawal", "amount": -200.0},
        {"date": "2026-11-04", "accountKey": HSA, "kind": "deposit", "amount": 200.0},
        {"date": "2026-11-04", "accountKey": IND, "kind": "deposit", "amount": 50.0, "core": True},
    ]
    flows = {(f["account"], f["amount"]): f for f in classify(activity)}
    assert len(flows) == 3
    assert flows[(IND, 500.0)]["external_portfolio"] == 1
    assert flows[(IND, -200.0)]["external_portfolio"] == 0 and flows[(HSA, 200.0)]["external_portfolio"] == 0
    assert flows[(HSA, 200.0)]["external_account"] == 1


def test_deposit_split_closes_drift_without_selling():
    targets = {"AAA": 0.5, "BBB": 0.5}
    assert core.deposit_split(targets, {"AAA": 60.0, "BBB": 40.0}, 1000.0, 200.0) == {"BBB": 200.0}
    assert core.deposit_split(targets, {"AAA": 60.0, "BBB": 40.0}, 1000.0, 100.0) == {"BBB": 100.0}
    assert core.deposit_split(targets, {"AAA": 50.0, "BBB": 50.0}, 1000.0, 100.0) == {"AAA": 50.0, "BBB": 50.0}
    assert core.deposit_split(targets, {"AAA": 55.0, "BBB": 45.0}, 1000.0, 300.0) == {"AAA": 100.0, "BBB": 200.0}
    assert core.deposit_split(targets, {}, 1000.0, 0.0) == {}


# ---- The run ----


def seed(m, *, debit=False):
    plan = {"funds": [{"ticker": "FXAIX", "target_weight": 0.8, "expense_ratio_pct": 0.015}, {"ticker": "VXUS", "target_weight": 0.2}]}
    m.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": plan})
    m.put("snapshots", 1, snapshot(1, "2026-11-02T08:00", 1500.0 if not debit else 1700.0, 3))
    m.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0, 900.0))
    m.put("positions", 2, position(2, 1, IND, "ACME", 10, 1000.0 if debit else 200.0, 250.0))
    if debit:
        m.put("positions", 3, position(3, 1, IND, "SPAXX", -300, -300.0, cash=True))
    else:
        m.put("positions", 3, position(3, 1, IND, "SPAXX", 300, 300.0, cash=True))
    m.put("priceProfiles", "ACME", {"symbol": "ACME", "kind": "stock"})
    m.put("priceProfiles", "FXAIX", {"symbol": "FXAIX", "kind": "mutual_fund"})
    m.put("priceCloses", "FXAIX_2026", closes_doc("FXAIX", 2026, [["2026-11-02", 200.0, 200.0], ["2026-11-03", 210.0, 210.0], ["2026-11-04", 220.0, 220.0]]))
    acme = 100.0 if debit else 20.0
    m.put("priceCloses", "ACME_2026", closes_doc("ACME", 2026, [["2026-11-02", acme, acme], ["2026-11-03", acme, acme], ["2026-11-04", acme, acme]]))
    m.pull("2026-11-04T21:00:00+00:00")


def computed(cfg, now=FRESH):
    run_holdings(cfg)
    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=now)
        result = core.store(desk, out)
        metrics = {(r["metric_id"], r["scope"], r["scope_id"], r["window"]): dict(r) for r in desk.execute("SELECT * FROM metric_values")}
    finally:
        desk.close()
        mirror.close()
    return result, metrics


def test_core_metrics_on_a_small_portfolio(cfg, mirror):
    seed(mirror)
    result, m = computed(cfg)
    assert result["as_of"] == "2026-11-04" and result["checks"]["freshness"] == "ok" and result["checks"]["value"] == "ok"
    assert m[("value.market", "portfolio", "all", "now")]["value"] == 1600.0
    assert m[("value.day_change", "portfolio", "all", "now")]["value"] == 50.0
    assert m[("ret.twr", "portfolio", "all", "ITD")]["value"] == pytest.approx(6.6667, abs=1e-4)
    assert m[("ret.twr", "portfolio", "all", "ITD")]["quality"] == "pro_forma"
    assert m[("cash.share", "portfolio", "all", "now")]["value"] == 18.75
    assert m[("plan.weight", "holding", "FXAIX", "now")]["value"] == 68.75
    assert m[("plan.drift", "holding", "VXUS", "now")]["value"] == -20.0
    assert m[("plan.drift_max", "portfolio", "all", "now")]["value"] == 20.0
    assert m[("plan.single_stock", "portfolio", "all", "now")]["value"] == 12.5
    assert m[("plan.rules", "rule", "drift-max", "now")]["value"] == 0
    assert m[("plan.rules", "rule", "no-margin-buys", "now")]["value"] == 1
    assert m[("risk.top1", "portfolio", "all", "now")]["value"] == 68.75
    assert m[("margin.debit", "portfolio", "all", "now")]["value"] == 0.0
    assert ("bm.plan_shadow", "shadow", "plan_shadow", "now") in m
    assert m[("bm.sp500_shadow", "shadow", "sp500_shadow", "now")]["value"] == pytest.approx(1650.0)
    assert m[("bm.sp500_shadow", "shadow", "sp500_shadow", "now")]["quality"] == "ok"
    assert ("ret.twr_ann", "portfolio", "all", "ITD") not in m
    assert all(r["engine_version"] for r in m.values())


def test_margin_call_drop(cfg, mirror, monkeypatch):
    monkeypatch.setenv("DESK_MARGIN_RATE_PCT", "12")
    seed(mirror, debit=True)
    _, m = computed(cfg)
    assert m[("margin.debit", "portfolio", "all", "now")]["value"] == 300.0
    assert m[("margin.cost_month", "portfolio", "all", "now")]["value"] == 3.0
    gross = 5 * 220.0 + 1000.0
    assert m[("margin.call_drop", "account", IND, "now")]["value"] == pytest.approx((1 - 300 / (0.7 * gross)) * 100, abs=1e-4)
    assert m[("plan.rules", "rule", "no-margin-buys", "now")]["value"] == 1


def test_a_failed_check_marks_metrics_stale(cfg, mirror):
    seed(mirror)
    result, m = computed(cfg, now=datetime(2026, 11, 9, 12, 0, tzinfo=UTC))
    assert result["checks"]["freshness"] == "fail" and result["health"] == "fail"
    assert m[("margin.debit", "portfolio", "all", "now")]["quality"] == "stale"
    assert m[("ret.twr", "portfolio", "all", "ITD")]["quality"] == "pro_forma"


def test_core_without_holdings(cfg, mirror):
    mirror.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {}})
    mirror.pull("2026-11-04T21:00:00+00:00")
    result = run_core(cfg)
    assert result["ok"] and result["metrics"] == 0 and result["health"] == "fail"


def test_api_metrics_series_health_prices(cfg, mirror, app_client):
    seed(mirror)
    computed(cfg)
    client = app_client(packages=["engine"])
    body = client.get("/api/engine/metrics", params={"ids": "ret.*,value.market", "scope": "portfolio"}).json()
    ids = {r["metric_id"] for r in body["metrics"]}
    assert body["as_of"] == "2026-11-04" and ids == {"ret.twr", "ret.mwr", "value.market"}
    one = client.get("/api/engine/metrics", params={"ids": "ret.twr", "window": "1D"}).json()["metrics"]
    assert len(one) == 2 and {r["scope"] for r in one} == {"portfolio", "account"}
    series = client.get("/api/engine/series", params={"id": "value", "start": "2026-11-03"}).json()
    assert [r["date"] for r in series["rows"]] == DAYS[1:] and series["rows"][-1]["value"] == 1600.0
    shadow_series = client.get("/api/engine/series", params={"id": "value", "scope": "shadow", "scope_id": "sp500_shadow"}).json()
    assert len(shadow_series["rows"]) == 3
    health = client.get("/api/engine/health").json()
    assert health["as_of"] == "2026-11-04" and {c["check_name"] for c in health["checks"]} >= {"freshness", "value", "shares"}
    prices = client.get("/api/engine/prices", params={"symbol": "fxaix", "start": "2026-11-03"}).json()
    assert prices == {"symbol": "FXAIX", "rows": [{"date": "2026-11-03", "close": 210.0}, {"date": "2026-11-04", "close": 220.0}]}
    acme = client.get("/api/engine/value", params={"symbol": "acme"}).json()["series"]
    assert [r["value"] for r in acme] == [200.0, 200.0, 200.0]


def test_api_intraday(cfg, mirror, app_client):
    seed(mirror)
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        desk.executemany(
            "INSERT INTO quotes_live VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("FXAIX", "2026-11-04T10:00:00-05:00", 221.0, 220.0, "finnhub", "2026-11-04T15:00:00+00:00"),
                ("FXAIX", "2026-11-04T10:05:00-05:00", 222.0, 220.0, "finnhub", "2026-11-04T15:05:00+00:00"),
                ("ACME", "2026-11-03T16:00:00-05:00", 20.0, 20.0, "close", "2026-11-04T15:05:00+00:00"),
            ],
        )
    desk.close()
    body = app_client(packages=["engine"]).get("/api/live/intraday").json()
    assert body["day"] == "2026-11-04" and list(body["symbols"]) == ["FXAIX"]
    assert [p["price"] for p in body["symbols"]["FXAIX"]] == [221.0, 222.0]


def test_empty_endpoints(cfg, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/metrics").json()["metrics"] == []
    assert client.get("/api/engine/series", params={"id": "value"}).json()["rows"] == []
    assert client.get("/api/engine/health").json()["status"] == "fail"
    assert client.get("/api/engine/prices", params={"symbol": "SPY"}).json()["rows"] == []
    assert client.get("/api/live/intraday").json()["symbols"] == {}


def test_demo_daily_run(demo_cfg):
    result = run_daily(demo_cfg)
    assert result["ok"] and result["core"]["ok"] and result["core"]["metrics"] > 100
    assert result["core"]["checks"]["value"] == "ok"
