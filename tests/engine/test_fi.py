import random
import sqlite3

import pytest

from desk.db import connect
from desk.engine import fi
from desk.engine.core import Out
from desk.engine.lab.factors import FACTORS
from desk.engine.shadows import TotalReturn
from tests.engine.test_core import computed
from tests.engine.test_preflight import seed
from tests.engine.test_scoring import weekdays

PREFS = {
    "key": "fi",
    "value": {"birthDate": "1990-07-12", "fiTargetAge": 50, "fiYearlySpend": 40000, "fiMultiple": 25, "inflation": 0.03, "inflationAdjusted": True},
}
PLAN = {
    "funds": [{"ticker": "FXAIX", "target_weight": 0.8}, {"ticker": "FXNAX", "target_weight": 0.2, "sleeve": "bonds"}],
    "monthly_plan": [{"month": "2026-12", "contribution": 1000}, {"month": "2027-01", "contribution": 2000}],
}


def monthly(desk, months=600, seed_=2):
    rng = random.Random(seed_)
    rows = []
    for i in range(months):
        d = f"{1950 + i // 12}-{i % 12 + 1:02d}-01"
        rows += [("mkt_rf_m", d, rng.gauss(0.6, 4.5)), ("rf_m", d, 0.3)]
    with desk:
        desk.executemany("INSERT OR REPLACE INTO factors_daily VALUES (?, ?, ?)", rows)


# ---- Inputs ----


def test_prefs_deposits_and_bond_share(monkeypatch):
    p = fi.fi_prefs([{"key": "taxEngine", "value": {}}, PREFS])
    assert p == {"fi_number": 1_000_000.0, "target_date": "2040-07-12", "inflation": 0.03, "real": True}
    assert fi.fi_prefs([{"key": "fi", "value": {"fiYearlySpend": None}}]) is None and fi.fi_prefs([]) is None
    year = [(f"2026-{m:02d}-03", 1000.0) for m in range(1, 12)] + [("2025-10-03", 9999.0), ("2026-11-03", -500.0)]
    assert fi.monthly_deposit(year, "2026-11-07") == (pytest.approx(10500 / 12), "activity", 12)
    assert fi.monthly_deposit([("2026-09-15", 600.0), ("2026-10-15", -900.0)], "2026-11-07") == (0.0, "activity", 2)
    assert fi.monthly_deposit([("2026-10-15", -900.0)], "2026-11-07") == (None, "none", 0)
    assert fi.monthly_deposit([("2026-09-15", 600.0), ("2026-10-15", 600.0)], "2026-11-07") == (pytest.approx(600.0), "activity", 2)
    assert fi.monthly_deposit([], "2026-11-07") == (None, "none", 0)
    targets = {"FXAIX": 0.8, "FXNAX": 0.2}
    assert fi.bond_share(PLAN, targets) == 0.2
    monkeypatch.setenv("DESK_BOND_FUNDS", "fxaix")
    assert fi.bond_share(PLAN, targets) == 1.0


def test_required_return_and_month_math():
    assert fi.required_return(0.0, 1000.0, 12, 12000.0) == pytest.approx(0.0, abs=1e-6)
    r = fi.required_return(10000.0, 0.0, 120, 20000.0)
    assert r == pytest.approx(2 ** (1 / 10) - 1, abs=1e-6)
    assert fi.required_return(0.0, 1.0, 12, 1e12) is None
    assert fi.months_between("2026-11-07", "2040-07-12") == 164 and fi.add_months("2026-11-30", 3) == "2027-02-28"


def test_constant_history_hits_on_the_closed_form_month():
    hist = [("1950-01-01", 0.01, 0.0)] * 240
    hit, years, at_year = fi.simulate(hist, start=1000.0, deposit=0.0, equity=1.0, fee_pct=0.0, months=120, goal=2000.0, inflation=0.0, real=False, paths=50)
    assert set(hit) == {70} and years[0] == 12 and at_year[0][0] == pytest.approx(1000 * 1.01**12)
    again = fi.simulate(
        [("a", 0.02, 0.0), ("b", -0.01, 0.0)] * 60, start=1.0, deposit=1.0, equity=1.0, fee_pct=0.0, months=24, goal=1e9, inflation=0.0, real=False, paths=20
    )
    assert again == fi.simulate(
        [("a", 0.02, 0.0), ("b", -0.01, 0.0)] * 60, start=1.0, deposit=1.0, equity=1.0, fee_pct=0.0, months=24, goal=1e9, inflation=0.0, real=False, paths=20
    )


def test_run_writes_percentiles_and_lines(desk_db, monkeypatch):
    monkeypatch.setenv("DESK_MC_PATHS", "400")
    monthly(desk_db)
    out = Out(as_of="2026-11-07")
    deposits = [("2026-09-01", 1500.0), ("2026-10-01", 1500.0), ("2026-11-01", 1500.0)]
    view = fi.run(out, PLAN, {"FXAIX": 0.8, "FXNAX": 0.2}, {"FXAIX": 0.015, "FXNAX": 0.025}, fi.fi_prefs([PREFS]), desk_db, 100_000.0, deposits)
    assert (
        view["deposit_source"] == "activity"
        and view["deposit_note"] == "from your last 3 months of deposits, net of withdrawals"
        and view["monthly_deposit"] == 1500.0
    )
    assert view["status"] == "ok" and view["paths"] == 400 and view["mix"] == {"equity": 0.8, "bonds_as_bills": 0.2}
    assert view["fee_pct"] == pytest.approx(0.017) and view["history"]["months"] == 600
    known = [x for x in view["fi_date"].values() if x]
    assert known and known == sorted(known) and 0 < view["reached_share"] <= 1
    assert all(r["p10"] <= r["p50"] <= r["p90"] for r in view["lines"]) and view["lines"][0]["year"] == 1
    m = {(r[0], r[3]): r for r in out.metrics}
    assert m[("fi.progress", "now")][5] == 10.0 and m[("fi.number", "now")][5] == 1_000_000.0
    assert ("fi.date_pctl", "p50") in m and ("fi.on_time", "now") in m and m[("fi.required_return", "now")][5] > 0


def test_run_without_goal_or_history(desk_db):
    out = Out(as_of="2026-11-07")
    assert fi.run(out, PLAN, {}, {}, None, desk_db, 1000.0)["status"] == "not_ready" and out.metrics == []
    view = fi.run(out, PLAN, {}, {}, fi.fi_prefs([PREFS]), desk_db, 1000.0)
    assert view["status"] == "not_ready" and "french" in view["note"] and view["required_return_pct"] is not None


# ---- Factor exposure ----


def test_exposure_recovers_holding_loadings(desk_db):
    rng = random.Random(8)
    days = weekdays("2022-01-03", 800)
    rows, px, p = [], {}, 100.0
    for d in days:
        f = {k: rng.gauss(0, 1.0) for k in FACTORS} | {"rf": 0.01}
        rows += [(k, d, v) for k, v in f.items()]
        p *= 1 + (f["rf"] + 1.2 * f["mkt_rf"] + 0.5 * f["smb"] + rng.gauss(0, 0.2)) / 100
        px[d] = (p, p)
    with desk_db:
        desk_db.executemany("INSERT INTO factors_daily VALUES (?, ?, ?)", rows)
    tr = TotalReturn({"TILT": px, "NEW": {d: (1.0, 1.0) for d in days[-50:]}})
    out = Out(as_of=days[-1])
    view = fi.exposure(out, tr, desk_db, {"TILT": 0.5, "NEW": 0.5})
    assert set(view["holdings"]) == {"TILT"} and view["coverage_pct"] == 50.0
    assert view["portfolio"]["mkt_rf"] == pytest.approx(1.2, abs=0.03) and view["portfolio"]["smb"] == pytest.approx(0.5, abs=0.03)
    rows_ = {(r[0], r[2]): r[5] for r in out.metrics}
    assert rows_[("risk.factor", "hml")] == pytest.approx(0.0, abs=0.03) and rows_[("risk.factor_coverage", "all")] == 50.0
    assert fi.exposure(Out(as_of="x"), tr, sqlite3.connect(":memory:"), {"TILT": 1.0})["note"]


# ---- Engine ----


def test_core_writes_fi_and_factor_views(cfg, mirror, monkeypatch, app_client):
    monkeypatch.setenv("DESK_MC_PATHS", "200")
    seed(mirror)
    mirror.put("prefs", "fi", PREFS)
    mirror.pull("2026-11-04T21:30:00+00:00")
    _, m = computed(cfg)
    assert m[("fi.number", "portfolio", "all", "now")]["value"] == 1_000_000.0
    value = m[("value.market", "portfolio", "all", "now")]["value"]
    assert m[("fi.progress", "portfolio", "all", "now")]["value"] == pytest.approx(value / 1_000_000 * 100, abs=1e-4)
    desk = connect(cfg.desk_db)
    names = {r[0] for r in desk.execute("SELECT name FROM engine_views")}
    desk.close()
    assert {"fi", "factors"} <= names
    client = app_client(packages=["engine"])
    body = client.get("/api/engine/fi").json()
    assert body["fi_number"] == 1_000_000.0 and body["status"] == "not_ready"
    assert client.get("/api/engine/factors").json()["note"]


def test_fi_endpoints_before_a_run(cfg, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/fi").json()["status"] == "not_ready"
    assert client.get("/api/engine/factors").json()["holdings"] == {}


# ---- Goal fallback ----


def test_the_goal_falls_back_to_the_desk_profile(cfg, mirror, monkeypatch):
    from desk.decisions import profile
    from desk.engine import core
    from desk.engine.source import open_mirror

    mirror.put("prefs", "theme", {"key": "theme", "value": "dark"})
    mirror.pull("2026-11-04T21:00:00+00:00")
    conn = open_mirror(cfg)
    assert core.fi_goal(cfg, conn) is None
    monkeypatch.setattr(core, "active_profile", lambda cfg: profile.Profile(1, {"fi": {}}, "test", "2026-11-10", 1))
    monkeypatch.setattr(profile, "fi_goal", lambda data: {"fi_number": 900000.0, "target_date": "2040-01-01", "source": "profile"}, raising=False)
    assert core.fi_goal(cfg, conn) == {"fi_number": 900000.0, "target_date": "2040-01-01", "inflation": 0.0, "real": False, "source": "profile"}
    monkeypatch.setattr(profile, "fi_goal", lambda data: {"fi_number": 0}, raising=False)
    assert core.fi_goal(cfg, conn) is None
    monkeypatch.setattr(profile, "fi_goal", lambda data: None, raising=False)
    assert core.fi_goal(cfg, conn) is None
    conn.close()
    mirror.put("prefs", "fi", PREFS)
    mirror.pull("2026-11-04T21:30:00+00:00")
    conn = open_mirror(cfg)
    assert core.fi_goal(cfg, conn)["fi_number"] == 1_000_000.0
    conn.close()
