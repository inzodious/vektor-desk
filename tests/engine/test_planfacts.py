import math
import sys
import types
from datetime import date, timedelta

import pytest

from desk.db import apply_schemas, connect
from desk.engine import planfacts

AS_OF = "2026-11-06"
ROW_KEYS = {
    "symbol",
    "name",
    "kind",
    "as_of",
    "price_as_of",
    "held",
    "accounts",
    "numbers",
    "lots",
    "wash_windows",
    "zones",
    "discount",
    "next_earnings",
    "filing_signals",
    "valuation",
    "band",
}
RULES = [
    {"id": "c1", "kind": "conviction_hold", "symbols": ["ACME"], "params": {"band_min_pct": 5, "band_max_pct": 12}},
    {"id": "s1", "kind": "single_stock_band", "params": {"min_pct": 0, "max_pct": 5}},
]


def sessions(n, end=date(2026, 11, 6)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def path(n, last, swing):
    return [last * (1 + swing * math.sin(i / 7) * (n - 1 - i) / n) for i in range(n)]


def seeded(cfg, monkeypatch):
    apply_schemas(cfg)
    conn = connect(cfg.desk_db)
    days = sessions(300)
    with conn:
        for sym, last, swing in (("ACME", 24.0, 0.3), ("IVV", 107.0, 0.05), ("SOLO", 50.0, 0.1), ("WTCH", 10.0, 0.2)):
            rows = [(sym, d, p, p) for d, p in zip(days, path(300, last, swing), strict=True)]
            conn.executemany("INSERT INTO price_bars (symbol, date, close, adj_close) VALUES (?, ?, ?, ?)", rows)
        hold = "INSERT INTO holdings_daily VALUES ('2026-11-06', ?, ?, ?, ?, ?, ?, NULL, ?, 's', 'a', 'ok')"
        conn.execute(hold, ("ind", "ACME", 10, 24.0, 240.0, 200.0, 0))
        conn.execute(hold, ("ind", "IVV", 5, 107.0, 535.0, 450.0, 0))
        conn.execute(hold, ("hsa", "SOLO", 1, 50.0, 50.0, None, 0))
        conn.execute(hold, ("ind", "SPAXX", 175, 1.0, 175.0, 175.0, 1))
        fid = conn.execute(
            "INSERT INTO lot_files (sha256, name, kind, as_of, imported_at, rows) VALUES ('a', 'lots.csv', 'lots', ?, ?, 2)", (AS_OF, AS_OF)
        ).lastrowid
        lot = "INSERT INTO lots (file_id, as_of, account, symbol, acquired, shares, cost, cost_per_share) VALUES (?, ?, 'ind', 'ACME', ?, ?, ?, ?)"
        conn.execute(lot, (fid, AS_OF, "2025-01-10", 6, 90.0, 15.0))
        conn.execute(lot, (fid, AS_OF, "2026-06-01", 4, 110.0, 27.5))
        conn.execute("INSERT INTO wash_windows VALUES (?, 'ACME', 'recent_buy', '2026-10-20', '2026-11-20', 'ind', 55.0)", (AS_OF,))
        conn.execute("INSERT INTO sec_tickers VALUES ('ACME', 1, 'Acme Corp', '2026-11-01')")
        conn.execute("INSERT INTO sec_tickers VALUES ('SOLO', 2, 'Solo Inc', '2026-11-01')")
        conn.execute(
            "INSERT INTO discount_signals VALUES "
            "('2026-11-05-ACME', '2026-11-05', 'ACME', 'Acme Corp', 'held', 'crossed_10', 23, -12.3, -2.4, '{}', '{}', '2026-11-05')"
        )
        conn.execute("INSERT INTO earnings (symbol, date, hour, eps_estimate) VALUES ('ACME', '2026-11-20', 'amc', 1.1)")
        conn.execute("INSERT INTO earnings (symbol, date, hour, eps_estimate) VALUES ('ACME', '2026-08-20', 'amc', 0.9)")
        signal = "INSERT INTO filing_signals VALUES (?, 'ACME', ?, '8-K', '2.02', '2026-11-04', 'm', 1, 0.6, 'results', 20, 'Beat.', '[]', NULL)"
        conn.execute(signal, ("a1", "2026-11-04T21:10:00Z"))
    monkeypatch.setattr(planfacts, "rules_in_force", lambda cfg, plan: (RULES, "profile"))
    monkeypatch.setattr("desk.decisions.risk.current", lambda cfg: {"band": 3, "label": "Moderate", "single_stock_max_pct": 5})
    return conn


def test_plan_facts_row_shape_and_numbers(cfg, monkeypatch):
    with pytest.raises(planfacts.NotReady):
        planfacts.facts(cfg)
    seeded(cfg, monkeypatch).close()
    rows = {r["symbol"]: r for r in planfacts.facts(cfg)}
    assert list(rows) == ["ACME", "IVV", "SOLO"] and all(set(r) == ROW_KEYS for r in rows.values())
    acme = rows["ACME"]
    n = acme["numbers"]
    assert (acme["name"], acme["kind"], acme["as_of"], acme["price_as_of"], acme["held"], acme["accounts"]) == (
        "Acme Corp",
        "stock",
        AS_OF,
        AS_OF,
        True,
        ["ind"],
    )
    assert (n["price"], n["shares"], n["value"], n["weight_pct"], n["cost_basis"], n["cost_per_share"]) == (24.0, 10.0, 240.0, 24.0, 200.0, 20.0)
    assert (n["unrealized_usd"], n["unrealized_pct"], n["long_term_shares"], n["short_term_shares"]) == (40.0, 20.0, 6.0, 4.0)
    assert (n["long_term_gain"], n["short_term_gain"]) == (54.0, -14.0)
    closes = path(300, 24.0, 0.3)
    assert n["high_52w"] == pytest.approx(max(closes[-252:]), abs=1e-3) and n["low_52w"] == pytest.approx(min(closes[-252:]), abs=1e-3)
    assert n["drop_from_high_pct"] == pytest.approx((24 / max(closes[-252:]) - 1) * 100, abs=1e-3) and n["above_low_pct"] >= 0
    assert n["sma_50"] == pytest.approx(sum(closes[-50:]) / 50, abs=1e-3) and n["sma_200"] == pytest.approx(sum(closes[-200:]) / 200, abs=1e-3)
    assert n["vs_sma_50_pct"] == pytest.approx((24 / n["sma_50"] - 1) * 100, abs=1e-2) and n["vol_annual_pct"] > 0 and "ret_1y_pct" in n
    assert all(isinstance(v, int | float) for v in n.values())
    assert sum(r["numbers"]["risk_share_pct"] for r in rows.values()) == pytest.approx(100.0, abs=0.01) and n["risk_share_pct"] > n["weight_pct"]
    assert acme["lots"] == [
        {
            "account": "ind",
            "acquired": "2025-01-10",
            "shares": 6.0,
            "cost": 90.0,
            "cost_per_share": 15.0,
            "value": 144.0,
            "gain": 54.0,
            "term": "long",
            "long_term_on": "2026-01-11",
            "days_to_long_term": 0,
            "quality": "ok",
        },
        {
            "account": "ind",
            "acquired": "2026-06-01",
            "shares": 4.0,
            "cost": 110.0,
            "cost_per_share": 27.5,
            "value": 96.0,
            "gain": -14.0,
            "term": "short",
            "long_term_on": "2027-06-02",
            "days_to_long_term": 208,
            "quality": "ok",
        },
    ]
    assert acme["wash_windows"] == [{"kind": "recent_buy", "date": "2026-10-20", "clears": "2026-11-20", "account": "ind", "amount": 55.0}]
    assert acme["discount"] == {"active": True, "signal_id": "2026-11-05-ACME", "reason": "crossed_10", "as_of": "2026-11-05"}
    assert acme["next_earnings"] == {"date": "2026-11-20", "hour": "amc", "eps_estimate": 1.1, "days": 14}
    assert [s["accession"] for s in acme["filing_signals"]] == ["a1"] and acme["filing_signals"][0]["direction"] == 1
    assert set(acme["valuation"]) == {"metric", "value", "pctile_own"} and n["valuation_pctile"] == acme["valuation"]["pctile_own"]


def test_zones_come_from_volatility_and_every_level_is_a_number(cfg, monkeypatch):
    seeded(cfg, monkeypatch).close()
    acme = planfacts.facts(cfg, "acme")[0]
    z, n = acme["zones"], acme["numbers"]
    sigma = z["sigma_month_pct"] / 100
    assert set(z) == {"method", "sigma_month_pct", "add", "trim", "levels"} and 0 < sigma <= planfacts.SIGMA_CAP
    assert z["add"] == {"low": pytest.approx(24 * (1 - 2 * sigma), abs=1e-3), "high": pytest.approx(24 * (1 - sigma), abs=1e-3)}
    assert z["trim"] == {"low": pytest.approx(24 * (1 + sigma), abs=1e-3), "high": pytest.approx(24 * (1 + 2 * sigma), abs=1e-3)}
    assert z["add"]["low"] < z["add"]["high"] < 24 < z["trim"]["low"] < z["trim"]["high"]
    assert set(z["levels"]) == {
        "price",
        "high_52w",
        "low_52w",
        "sma_50",
        "sma_200",
        "cost_per_share",
        "down_10_from_high",
        "down_20_from_high",
        "down_30_from_high",
    }
    assert z["levels"]["down_20_from_high"] == pytest.approx(n["high_52w"] * 0.8, abs=1e-3) and z["levels"]["cost_per_share"] == 20.0
    assert (n["add_low"], n["add_high"], n["trim_low"], n["trim_high"]) == (z["add"]["low"], z["add"]["high"], z["trim"]["low"], z["trim"]["high"])


def test_band_status_by_plan_conviction_single_stock_and_fund(cfg, monkeypatch):
    seeded(cfg, monkeypatch).close()
    rows = {r["symbol"]: r for r in planfacts.facts(cfg)}
    risk = {"band": 3, "label": "Moderate", "single_stock_max_pct": 5}
    acme = {"source": "conviction", "min_pct": 5.0, "max_pct": 12.0, "weight_pct": 24.0, "status": "over", "room_pct": -12.0, "risk_band": risk}
    solo = {"source": "single_stock_band", "min_pct": 0.0, "max_pct": 5.0, "weight_pct": 5.0, "status": "inside", "room_pct": 0.0, "risk_band": risk}
    assert rows["ACME"]["band"] == acme and rows["SOLO"]["band"] == solo
    assert rows["IVV"]["kind"] == "fund" and rows["IVV"]["band"]["source"] == "none" and rows["IVV"]["band"]["status"] == "inside"
    assert rows["SOLO"]["numbers"].get("cost_basis") is None and rows["SOLO"]["lots"] == [] and rows["SOLO"]["discount"]["active"] is False
    plans = types.SimpleNamespace(approved_plans=lambda cfg: [{"symbol": "acme", "weight_band": {"min_pct": 26, "max_pct": 30}}])
    monkeypatch.setitem(sys.modules, "desk.decisions.plans", plans)
    band = planfacts.facts(cfg, "ACME")[0]["band"]
    assert (band["source"], band["min_pct"], band["max_pct"], band["status"], band["room_pct"]) == ("plan", 26.0, 30.0, "under", 6.0)
    monkeypatch.setattr(planfacts, "rules_in_force", lambda cfg, plan: ([], "profile"))
    monkeypatch.setitem(sys.modules, "desk.decisions.plans", types.SimpleNamespace(approved_plans=lambda cfg: {}))
    solo = planfacts.facts(cfg, "SOLO")[0]["band"]
    assert (solo["source"], solo["max_pct"], solo["status"]) == ("risk_band", 5.0, "inside")


def test_a_symbol_you_do_not_hold_still_gets_price_facts(cfg, monkeypatch):
    seeded(cfg, monkeypatch).close()
    row = planfacts.facts(cfg, "wtch")[0]
    assert set(row) == ROW_KEYS and row["held"] is False and row["lots"] == [] and row["accounts"] == []
    assert row["numbers"]["price"] == 10.0 and row["numbers"]["shares"] == 0.0 and row["numbers"]["weight_pct"] == 0.0 and row["zones"]["add"]["high"] < 10.0
    assert "risk_share_pct" not in row["numbers"] and row["band"]["status"] == "inside"
    bare = planfacts.facts(cfg, "NOPE")[0]
    assert bare["numbers"] == {"shares": 0.0, "value": 0.0, "weight_pct": 0.0} and bare["zones"] is None and bare["valuation"] is None


def test_planfacts_api(cfg, monkeypatch, app_client):
    api = app_client(packages=["engine"])
    assert api.get("/api/engine/planfacts").json() == {"as_of": None, "rows": [], "note": planfacts.EMPTY_NOTE}
    seeded(cfg, monkeypatch).close()
    body = api.get("/api/engine/planfacts").json()
    assert body["as_of"] == AS_OF and body["note"] is None and [r["symbol"] for r in body["rows"]] == ["ACME", "IVV", "SOLO"]
    one = api.get("/api/engine/planfacts?symbol=acme").json()
    assert [r["symbol"] for r in one["rows"]] == ["ACME"] and one["rows"][0] == body["rows"][0]


def test_plan_facts_on_the_engine_output(cfg, mirror):
    from tests.engine.test_core import computed
    from tests.engine.test_preflight import seed

    seed(mirror)
    computed(cfg)
    rows = {r["symbol"]: r for r in planfacts.facts(cfg)}
    assert set(rows) == {"FXAIX", "ACME"} and all(set(r) == ROW_KEYS for r in rows.values())
    assert rows["FXAIX"]["kind"] == "fund" and rows["FXAIX"]["numbers"]["price"] == 200.0 and rows["ACME"]["numbers"]["unrealized_usd"] == -50.0
