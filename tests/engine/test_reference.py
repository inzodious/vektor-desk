from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.engine import catalog, core
from desk.engine.__main__ import run_holdings
from desk.engine.source import open_mirror
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
PRICED = ("IVV", "VXUS", "FTEC", "SCHD", "NLR", "GRID", "ICLN", "UFO", "FXAIX", "ROKT", "SPY")


def seed(mirror, plan=None):
    mirror.put("snapshots", 1, snapshot(1, f"{DAYS[0]}T21:00", 1000.0, 4))
    mirror.put("positions", 1, position(1, 1, IND, "FXAIX", 3.0, 300.0, 280.0))
    mirror.put("positions", 2, position(2, 1, IND, "FTEC", 2.0, 200.0, 150.0))
    mirror.put("positions", 3, position(3, 1, IND, "ROKT", 10.0, 400.0, 500.0))
    mirror.put("positions", 4, position(4, 1, IND, "SPAXX", 100.0, 100.0, cash=True))
    mirror.put("activity", "a1", {"date": DAYS[2], "accountKey": IND, "kind": "buy", "symbol": "ROKT", "quantity": 1, "amount": -40.0, "core": False})
    mirror.put("activity", "a2", {"date": DAYS[3], "accountKey": IND, "kind": "buy", "symbol": "FTEC", "quantity": 0.1, "amount": -10.0, "core": False})
    mirror.put("priceProfiles", "ROKT", {"symbol": "ROKT", "kind": "stock"})
    base = {"FXAIX": 100.0, "FTEC": 100.0, "ROKT": 40.0}
    for i, sym in enumerate(PRICED):
        px = base.get(sym, 50.0 + i)
        mirror.put("priceCloses", f"{sym}_2026", closes_doc(sym, 2026, [[d, px * (1 + 0.01 * n), px * (1 + 0.01 * n)] for n, d in enumerate(DAYS)]))
    if plan:
        mirror.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {"funds": [{"ticker": t, "target_weight": w} for t, w in plan.items()]}})
    mirror.pull(f"{DAYS[-1]}T22:00:00+00:00")


def computed(cfg):
    run_holdings(cfg)
    mirror, desk = open_mirror(cfg), connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=NOW)
        core.store(desk, out)
    finally:
        desk.close()
        mirror.close()
    return out


def rows(out, metric_id, scope=None):
    return {(m[2], m[3]): m for m in out.metrics if m[0] == metric_id and (scope is None or m[1] == scope)}


def test_reference_mix_falls_back_to_the_built_in_safe_mix():
    assert core.reference_mix({}) == (catalog.SAFE_MIX, "safe_mix")
    plan = {"funds": [{"ticker": "fxaix", "target_weight": 3}, {"ticker": "FTEC", "target_weight": 1}]}
    assert core.reference_mix(plan) == ({"FXAIX": 0.75, "FTEC": 0.25}, "plan")
    assert core.reference_mix({"funds": [{"ticker": "FXAIX", "target_weight": 0}]})[1] == "safe_mix"


def test_without_a_plan_the_safe_mix_is_a_yardstick_not_a_target(cfg, mirror, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/reference").json() == {"as_of": None, "source": None, "name": None, "weights": {}, "judged": False, "note": None}
    seed(mirror)
    out = computed(cfg)
    ref = client.get("/api/engine/reference").json()
    assert ref["source"] == "safe_mix" and ref["name"] == "Safe mix" and ref["judged"] is False and ref["note"] == core.REFERENCE_NOTE
    assert ref["weights"] == {s: w * 100 for s, w in sorted(catalog.SAFE_MIX.items())} and ref["as_of"] == DAYS[-1]
    bench = rows(out, "bm.plan_shadow")[("plan_shadow", "now")]
    assert bench[5] is not None and bench[8] in ("ok", "stale")
    conn = connect(cfg.desk_db, readonly=True)
    shadow_days = conn.execute("SELECT count(*) FROM series_daily WHERE series_id='value' AND scope='shadow' AND scope_id='plan_shadow'").fetchone()[0]
    conn.close()
    assert shadow_days == len(DAYS) and ("plan_shadow", "ITD") in rows(out, "bm.excess")
    targets = rows(out, "plan.target", "holding")
    assert {k[0]: m[5] for k, m in targets.items()} == pytest.approx({s: w * 100 for s, w in catalog.SAFE_MIX.items()})
    assert {m[8] for m in targets.values()} == {"modelled"} and {m[8] for m in rows(out, "plan.drift", "holding").values()} == {"modelled"}
    drift_max, in_mix = rows(out, "plan.drift_max")[("all", "now")], rows(out, "plan.in_mix")[("all", "now")]
    assert drift_max[8] == "modelled" and drift_max[5] > 5 and in_mix[8] == "modelled" and in_mix[5] > 0
    assert {m[8] for m in rows(out, "plan.weight", "holding").values()} != {"modelled"}
    judged = {k[0] for k in rows(out, "plan.rules", "rule")}
    assert judged and "drift-max" not in judged
    adherence = rows(out, "plan.adherence")[("all", "ITD")]
    assert adherence[5] == pytest.approx(20.0) and adherence[8] == "modelled"
    assert rows(out, "bm.active_share")[("all", "now")][5] is not None
    assert rows(out, "plan.single_stock", "holding").keys() == {("ROKT", "now")}


def test_an_escape_vektor_plan_still_wins_and_is_judged(cfg, mirror, app_client):
    seed(mirror, plan={"FXAIX": 0.6, "FTEC": 0.4})
    out = computed(cfg)
    ref = app_client(packages=["engine"]).get("/api/engine/reference").json()
    assert ref["source"] == "plan" and ref["name"] == "Your plan" and ref["judged"] is True and ref["note"] is None
    assert ref["weights"] == {"FTEC": 40.0, "FXAIX": 60.0}
    assert {m[8] for m in rows(out, "plan.target", "holding").values()} != {"modelled"}
    assert "drift-max" in {k[0] for k in rows(out, "plan.rules", "rule")}
    assert rows(out, "plan.drift_max")[("all", "now")][8] != "modelled"
