from datetime import date, timedelta

import pytest

from desk.db import connect
from desk.engine import patterns, scoring
from desk.engine.core import Out
from desk.engine.shadows import TotalReturn
from tests.engine.test_core import computed
from tests.engine.test_preflight import seed

TZ = "America/New_York"


def weekdays(start: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DAYS = weekdays("2025-01-02", 400)


def book(**paths) -> TotalReturn:
    return TotalReturn({s: {d: (p, p) for d, p in zip(DAYS, ps, strict=True)} for s, ps in paths.items()})


def linear(start: float, step: float) -> list[float]:
    return [start + step * i for i in range(len(DAYS))]


TR = book(SPY=linear(100, 0.1), FXAIX=linear(100, 0.1), ACME=linear(50, 0.5))
CAL = DAYS


def decision(**over) -> dict:
    return {
        "id": "d1",
        "origin": "research",
        "kind": "buy",
        "symbol": "ACME",
        "account": "Z1",
        "amount_usd": 1000.0,
        "shares": None,
        "funding": "cash",
        "status": "approved",
        "override": False,
        "confidence": 0.7,
        "preflight_status": "clear",
        "tax_impact": None,
        "created_at": "2025-01-06T22:00:00+00:00",
        "decided_at": "2025-01-07T15:00:00+00:00",
        "filled_at": None,
        "fill": None,
    } | over


def score(d, **kw):
    return scoring.score(d, TR, CAL, {"FXAIX": 1.0}, tz=TZ, rate=kw.get("rate", 0.24), margin_rate=kw.get("margin_rate"), fallback="SPY")


def ratio(sym, a, b):
    return TR.price(sym, b) / TR.price(sym, a) - 1


# ---- One decision ----


def test_buy_starts_at_the_next_close_and_beats_the_plan_by_the_gap():
    s = score(decision())
    t0 = "2025-01-07"
    assert s["start"] == t0
    t1 = scoring.end_day(CAL, t0, 30)
    assert t1 == "2025-02-06"
    want = 1000 * (ratio("ACME", t0, t1) - ratio("FXAIX", t0, t1))
    assert s["scores"][30]["usd"] == pytest.approx(want, abs=0.01) and s["scores"][30]["quality"] == "ok"
    assert 365 in s["scores"] and set(s["scores"]) == {30, 90, 365}


def test_sell_is_the_mirror_and_margin_costs_interest():
    buy, sell = score(decision()), score(decision(kind="sell"))
    assert sell["scores"][90]["usd"] == pytest.approx(-buy["scores"][90]["usd"], abs=0.02)
    margin = score(decision(funding="margin"), margin_rate=12.0)
    assert margin["scores"][30]["usd"] == pytest.approx(buy["scores"][30]["usd"] - 10.0, abs=0.02) and margin["scores"][30]["interest"] == 10.0


def test_harvest_and_hold_off_are_scored_by_what_they_save():
    h = score(decision(kind="harvest", tax_impact={"realized": -500.0}))
    assert h["scores"][30]["usd"] == 120.0
    held = score(decision(kind="hold_off", symbol=None, amount_usd=2000.0, funding="margin"), margin_rate=9.0)
    assert held["scores"][90]["usd"] == 45.0 and held["scores"][90]["interest_avoided"] == 45.0
    memo = score(decision(kind="memo"))
    assert memo["scores"] == {} and memo["note"] == "not scored"


def test_own_trade_anchors_on_its_fill_and_young_ones_wait():
    s = score(decision(origin="you", status="logged", created_at="2025-06-01T12:00:00+00:00", filled_at="2025-01-10"))
    assert s["start"] == "2025-01-13"
    late = score(decision(created_at=DAYS[-40] + "T22:00:00+00:00"))
    assert set(late["scores"]) == {30} or late["scores"] == {}
    assert score(decision(created_at=DAYS[-1] + "T22:00:00+00:00"))["note"] == "waiting for the next close"


def test_missing_plan_prices_fall_back_to_the_market_and_say_so():
    s = scoring.score(decision(), TR, CAL, {"NOPE": 1.0}, tz=TZ, rate=None, margin_rate=None, fallback="SPY")
    assert s["scores"][30]["quality"] == "modelled"


# ---- Summaries ----


def test_bootstrap_is_seeded_and_covers_the_mean():
    xs = [10.0, -5.0, 3.0, 8.0, -2.0, 4.0, 6.0, -1.0]
    a, b = scoring.bootstrap_mean(xs), scoring.bootstrap_mean(xs)
    assert a == b and a[0] < sum(xs) / len(xs) < a[1]
    summary = scoring.summarize(xs)
    assert summary["n"] == 8 and summary["hit_rate"] == 0.625 and summary["note"]
    assert scoring.bootstrap_mean([1.0]) == (None, None)


def test_calibration_bins_start_at_thirty():
    few = scoring.calibration([(0.8, 1), (0.6, 0)])
    assert few["brier"] == pytest.approx((0.04 + 0.36) / 2) and few["bins"] == []
    many = scoring.calibration([(0.9, 1)] * 20 + [(0.1, 0)] * 10)
    assert many["n"] == 30 and [b["n"] for b in many["bins"]] == [10, 20] and many["bins"][1]["happened"] == 1.0


def test_scorecard_groups_desks_saves_and_offplan():
    rows = [
        decision(id="a"),
        decision(id="b", status="dismissed", kind="buy", symbol="FXAIX"),
        decision(id="c", origin="you", status="logged", override=True, filled_at="2025-01-08", confidence=None),
        decision(id="d", origin="tax", kind="harvest", tax_impact={"realized": -100.0}, status="dismissed"),
    ]
    out = Out(as_of=DAYS[-1])
    card = scoring.metrics(out, type("C", (), {"timezone": TZ})(), TR, {"FXAIX": 1.0}, rate=0.24, cal=CAL, fallback="SPY", rows=rows)
    by = {(g["by"], g["group"], g["window"]) for g in card["groups"]}
    assert ("origin", "research", "30D") in by and ("path", "override", "90D") in by and ("taken", "not_taken", "90D") in by
    research = next(d for d in card["desks"] if d["desk"] == "research")
    assert research["chip"] == "too_early" and research["lag_days_median"] == pytest.approx(0.71, abs=0.01)
    assert research["calibration"]["n"] == 2 and research["calibration"]["brier"] == pytest.approx((0.09 + 0.49) / 2)
    assert card["offplan_gap"]["n"] == 1
    ids = {(m[0], m[2], m[3]) for m in out.metrics}
    assert ("dec.score_30", "a", "30D") in ids and ("dec.desk_record", "research", "90D") in ids and ("dec.brier", "tax", "90D") in ids
    assert ("dec.offplan_gap", "all", "90D") in ids and ("dec.lag", "all", "now") in ids and ("dec.saves", "all", "90D") in ids
    assert card["decisions"][0]["scores"]["30D"]["usd"] is not None


# ---- Patterns ----


def test_wilson_and_buckets():
    lo, hi = patterns.wilson(5, 10)
    assert lo == pytest.approx(0.2693, abs=1e-3) and hi == pytest.approx(0.7307, abs=1e-3)
    assert patterns.wilson(0, 0) == (None, None)
    assert patterns.bucket(-12.0, patterns.DD_BUCKETS) == 2 and patterns.bucket(0.0, patterns.DD_BUCKETS) == 4
    assert patterns.quintile(0.999) == 4 and patterns.quintile(0.0) == 0


def test_drawdown_table_counts_recoveries():
    rise = [100 + i for i in range(260)]
    top = rise[-1]
    path = rise + [top * 0.9, top * 0.8, top, top * 1.1, top * 1.1 * 0.95, top * 1.1 * 1.01, top * 1.1 * 0.7]
    days = weekdays("2024-01-01", len(path))
    tr = TotalReturn({"FUND": {d: (p, p) for d, p in zip(days, path, strict=True)}})
    t = patterns.drawdown_table(tr, "FUND", days[-1])
    assert t["drawdown_pct"] == pytest.approx(-30.693, abs=1e-2) and t["open"]
    assert t["episodes"] == 0
    t2 = patterns.drawdown_table(tr, "FUND", days[-2])
    assert t2["episodes"] == 2 and t2["median_days_to_recover"] == 2.5 and t2["deepest_pct"] == -20.0


def test_market_and_holding_patterns_carry_base_rates(desk_db):
    import random

    rng = random.Random(4)
    days = weekdays("2010-01-04", 3800)
    px, p = [], 100.0
    for _ in days:
        p *= 1 + 0.0003 + rng.gauss(0, 0.011)
        px.append(p)
    tr = TotalReturn({"SPY": {d: (x, x) for d, x in zip(days, px, strict=True)}})
    with desk_db:
        desk_db.executemany("INSERT INTO macro_daily (series, date, value) VALUES ('VIXCLS', ?, ?)", [(d, 15 + 10 * rng.random()) for d in days[::5]])
        desk_db.executemany("INSERT INTO macro_daily (series, date, value) VALUES ('DGS10', ?, 3.0)", [(d,) for d in days[::5]])
        desk_db.executemany(
            "INSERT INTO macro_daily (series, date, value) VALUES ('DGS3MO', ?, ?)", [(d, 2.0 + (i % 40) / 10) for i, d in enumerate(days[::5])]
        )
        desk_db.executemany("INSERT INTO earnings (symbol, date) VALUES ('SPY', ?)", [(days[-30],), (days[-90],)])
    found = {p["id"]: p for p in patterns.market(tr, desk_db, days[-1])}
    assert set(found) == {"pat.mkt_drawdown", "pat.vix_pctl", "pat.curve_10y3m"}
    dd = found["pat.mkt_drawdown"]
    assert dd["n"] >= patterns.MIN_SAMPLES and 0 <= dd["base_rate"] <= 1 and dd["ci_low"] <= dd["base_rate"] <= dd["ci_high"] and dd["what_it_is_not"]
    own = {p["id"]: p for p in patterns.holding(tr, desk_db, "SPY", days[-1])}
    assert set(own) == {"pat.range_52w", "pat.ma200_gap", "pat.vol_pctl", "pat.earnings_move"} and own["pat.earnings_move"]["n"] == 2
    season = patterns.seasonality(tr, "SPY", days[-1])
    assert [m["month"] for m in season] == list(range(1, 13)) and all(m["n"] >= 13 for m in season)


# ---- Engine and API ----


def test_core_writes_the_flight_record_and_patterns(cfg, mirror, app_client):
    seed(mirror)
    computed(cfg)
    desk = connect(cfg.desk_db)
    names = {r[0] for r in desk.execute("SELECT name FROM engine_views")}
    desk.close()
    assert names == {"scorecard", "patterns", "fi", "factors", "bands"}
    client = app_client(packages=["engine"])
    card = client.get("/api/engine/scorecard").json()
    assert card["as_of"] == "2026-11-04" and card["decisions"] == [] and card["method"]
    pats = client.get("/api/engine/patterns").json()
    assert pats["as_of"] == "2026-11-04" and pats["seasonality_note"] and "behavior" in pats
    assert client.get("/api/engine/scorecard", params={"origin": "tax"}).json()["desks"] == []


def test_empty_flight_record_endpoints(cfg, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/scorecard").json()["as_of"] is None
    assert client.get("/api/engine/patterns").json()["market"] == []
