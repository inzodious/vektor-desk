import json
from datetime import UTC, datetime

import pytest

from desk.db import apply_schemas, connect
from desk.engine import catalog, review

NOW = datetime(2026, 11, 6, 22, 40, tzinfo=UTC)
MONDAY = datetime(2026, 11, 9, 13, 35, tzinfo=UTC)
DAYS = ["2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"]
DAYS += ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
ACME = [20.0, 20.5, 21.0, 21.5, 22.0, 22.5, 22.5, 22.0, 21.0, 21.5, 23.0, 24.0]
IVV = [100.0, 101.0, 102.0, 101.0, 103.0, 104.0, 104.0, 104.0, 105.0, 103.0, 106.0, 107.0]
SHARES = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 8, 8]
CASH = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 600.0, 600.0, 646.0, 646.0]
FLOWS = {"2026-11-03": 500.0}
VALUES = [s * a + 5 * i + c for s, a, i, c in zip(SHARES, ACME, IVV, CASH, strict=True)]
PACK_KEYS = {
    "version",
    "kind",
    "start",
    "end",
    "as_of",
    "label",
    "quality",
    "coverage",
    "value",
    "vs",
    "movers",
    "accounts",
    "income",
    "flows",
    "trades",
    "trade_count",
    "realized",
    "risk",
    "decisions",
    "paper",
    "fi",
    "events",
    "numbers",
}
ACTIVITY = [
    {"date": "2026-10-28", "accountKey": "ind", "kind": "interest", "amount": 0.4},
    {"date": "2026-11-03", "accountKey": "ind", "kind": "deposit", "amount": 500.0},
    {"date": "2026-11-03", "accountKey": "ind", "kind": "buy", "symbol": "SPAXX", "quantity": 500, "price": 1, "amount": -500.0, "core": True},
    {"date": "2026-11-04", "accountKey": "ind", "kind": "dividend", "symbol": "IVV", "amount": 3.0},
    {"date": "2026-11-05", "accountKey": "ind", "kind": "sell", "symbol": "ACME", "quantity": -2, "price": 23.0, "amount": 46.0},
    {"date": "2026-11-05", "accountKey": "ind", "kind": "margin_interest", "amount": -1.25},
]
RULES = [{"id": "c1", "kind": "conviction_hold", "symbols": ["ACME"], "params": {"band_min_pct": 5, "band_max_pct": 12}}]
DEBRIEF = {
    "headline": "A quiet week that ended up.",
    "what_happened": "The book rose after a deposit.",
    "why": "ACME and the index fund both gained.",
    "against_decisions": "The trim on ACME matured ahead.",
    "watch": ["ACME is over its band."],
    "next_steps": [{"text": "Review the ACME band.", "symbol": "ACME"}, {"text": "Nothing else.", "symbol": None}],
    "numbers_cited": ["change_usd", "vs.spy.pts", "contrib.ACME.usd"],
    "model": "test-model",
    "written_at": "2026-11-06T23:30:00Z",
    "run_id": 7,
}


def index_series():
    out, ix = [100.0], 100.0
    for i in range(1, len(DAYS)):
        ix *= (VALUES[i] - FLOWS.get(DAYS[i], 0.0)) / VALUES[i - 1]
        out.append(ix)
    return out


def seeded(cfg, monkeypatch):
    apply_schemas(cfg)
    conn = connect(cfg.desk_db)
    ix = index_series()
    with conn:
        for scope, scope_id in (("portfolio", "all"), ("account", "ind")):
            conn.executemany(
                "INSERT INTO series_daily VALUES ('value', ?, ?, ?, ?, 'ok')", [(scope, scope_id, d, v) for d, v in zip(DAYS, VALUES, strict=True)]
            )
            conn.executemany(
                "INSERT INTO series_daily VALUES ('twr_index', ?, ?, ?, ?, 'ok')", [(scope, scope_id, d, x) for d, x in zip(DAYS, ix, strict=True)]
            )
        for d, s, a, i, c in zip(DAYS, SHARES, ACME, IVV, CASH, strict=True):
            conn.execute("INSERT INTO holdings_daily VALUES (?, 'ind', 'ACME', ?, ?, ?, NULL, NULL, 0, 's', 'a', 'ok')", (d, s, a, s * a))
            conn.execute("INSERT INTO holdings_daily VALUES (?, 'ind', 'IVV', 5, ?, ?, NULL, NULL, 0, 's', 'a', 'ok')", (d, i, 5 * i))
            conn.execute("INSERT INTO holdings_daily VALUES (?, 'ind', 'SPAXX', ?, 1, ?, NULL, NULL, 1, 's', 'a', 'ok')", (d, c, c))
            if d != "2026-10-31":
                bars = [("ACME", d, a), ("IVV", d, i), ("SPY", d, 5 * i), ("VXUS", d, 60.0)]
                conn.executemany("INSERT INTO price_bars (symbol, date, close, adj_close) VALUES (?, ?, ?, ?)", [(s, day, p, p) for s, day, p in bars])
        conn.execute(
            "INSERT INTO cash_flows (date, account, amount, kind, external_account, external_portfolio) VALUES ('2026-11-03', 'ind', 500, 'deposit', 1, 1)"
        )
        conn.execute("INSERT INTO sec_tickers VALUES ('ACME', 1, 'Acme Corp', '2026-11-01')")
        realized = (
            "INSERT INTO broker_realized (account, symbol, acquired, sold, shares, proceeds, cost, gain, term, method) "
            "VALUES ('ind', 'ACME', ?, ?, ?, ?, ?, ?, ?, 'fifo')"
        )
        conn.execute(realized, ("2025-01-10", "2026-11-05", 2, 46.0, 30.0, 16.0, "long"))
        conn.execute(realized, ("2026-09-01", "2026-10-28", 1, 20.0, 24.0, -4.0, "short"))
        conn.execute(
            "INSERT INTO decisions (id, created_at, updated_at, origin, kind, title, symbol, status) "
            "VALUES ('d1', '2026-11-04T15:00:00Z', '2026-11-04T15:00:00Z', 'user', 'trim', 'Trim ACME', 'ACME', 'logged')"
        )
        scored = {
            "decisions": [
                {
                    "id": "d0",
                    "origin": "user",
                    "kind": "trim",
                    "symbol": "ACME",
                    "scores": {"30D": {"end": "2026-11-05", "usd": 12.5}, "90D": {"end": "2027-01-04", "usd": None}},
                }
            ]
        }
        conn.execute("INSERT INTO engine_views VALUES ('scorecard', '2026-11-06', ?)", (json.dumps(scored),))
        conn.execute("INSERT INTO engine_views VALUES ('fi', '2026-11-06', ?)", (json.dumps({"fi_number": 100000.0}),))
        bands = {"rows": [{"id": "as-held", "status": "ok", "fit": "fits", "worst_year_p10_pct": -15.0}]}
        conn.execute("INSERT INTO engine_views VALUES ('bands', '2026-11-06', ?)", (json.dumps(bands),))
        conn.execute(
            "INSERT INTO paper_portfolios VALUES ('safe-mix', 1, 'Safe mix', '2026-10-01', '2026-11-06', 26, 1010, 1.0, 0.1, 'paper', ?)",
            (json.dumps({"kind": "mix"}),),
        )
        conn.executemany("INSERT INTO paper_ledger_daily VALUES ('safe-mix', 1, ?, 0, ?, ?)", [("2026-10-30", 1000.0, 1000.0), ("2026-11-06", 1010.0, 1010.0)])
        conn.execute(
            "INSERT INTO discount_signals VALUES "
            "('2026-11-05-ACME', '2026-11-05', 'ACME', 'Acme Corp', 'held', 'big_down_day', 23, -12.3, -2.4, '{}', '{}', '2026-11-05')"
        )
        signal = "INSERT INTO filing_signals VALUES (?, ?, '2026-11-04T21:10:00Z', '8-K', '2.02', '2026-11-04', 'm', 1, 0.6, 'results', 20, NULL, '[]', NULL)"
        conn.execute(signal, ("a1", "ACME"))
        conn.execute(signal, ("a2", "OTHER"))
        conn.execute("INSERT INTO earnings (symbol, date, eps_estimate, eps_actual) VALUES ('ACME', '2026-11-03', 1.0, 1.2)")
    catalog.sync(conn, catalog.mixes({}, 0.0, safe={"IVV": 0.8, "VXUS": 0.2}), now=NOW)
    monkeypatch.setattr(review.broker, "history", lambda mirror, desk: (list(ACTIVITY), None))
    monkeypatch.setattr(review, "rules_in_force", lambda cfg, plan: (RULES, "profile"))
    monkeypatch.setattr("desk.decisions.risk.current", lambda cfg: {"band": 3, "label": "Balanced", "worst_year_loss_pct": 20})
    return conn


def stored(conn, kind, end):
    row = conn.execute('SELECT * FROM period_reviews WHERE kind=? AND "end"=?', (kind, end)).fetchone()
    return dict(row) | {"pack": json.loads(row["pack"])}


# ---- Periods ----


def test_periods_run_on_trading_days_and_carry_plain_labels():
    assert review.periods("day", "2026-11-25", "2026-11-30") == [("2026-11-25",) * 2, ("2026-11-27",) * 2, ("2026-11-30",) * 2]
    assert review.periods("week", "2026-11-20", "2026-12-01") == [("2026-11-16", "2026-11-20"), ("2026-11-23", "2026-11-27"), ("2026-11-30", "2026-12-04")]
    assert review.periods("month", "2026-10-23", "2026-11-06") == [("2026-10-01", "2026-10-30"), ("2026-11-02", "2026-11-30")]
    assert review.periods("year", "2026-10-23", "2026-11-06") == [("2026-01-02", "2026-12-31")]
    assert review.periods("day", "2026-10-31", "2026-11-02") == [("2026-11-02", "2026-11-02")]
    assert review.label("day", "2026-11-06", "2026-11-06") == "Fri Nov 6, 2026"
    assert review.label("week", "2026-11-02", "2026-11-06") == "Week of Nov 2, 2026"
    assert review.label("month", "2026-11-02", "2026-11-30") == "November 2026" and review.label("year", "2026-01-02", "2026-12-31") == "2026"


# ---- Pack ----


def test_pack_shape_is_pinned(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    review.run(cfg, None, conn, now=NOW)
    for kind, end in (("day", "2026-11-06"), ("week", "2026-11-06"), ("month", "2026-11-30"), ("year", "2026-12-31")):
        pack = stored(conn, kind, end)["pack"]
        assert set(pack) == PACK_KEYS and pack["version"] == review.PACK_VERSION and pack["kind"] == kind
        assert set(pack["coverage"]) == {"full", "base", "days", "note"}
        assert set(pack["value"]) == {"start", "end", "change_usd", "change_pct", "net_flows", "gain_usd"}
        assert all(set(r) == {"id", "name", "kind", "return_pct", "excess_pts", "value_end", "diff_usd"} for r in pack["vs"]) and pack["vs"]
        assert set(pack["movers"]) == {"up", "down", "other_usd", "count"}
        movers = pack["movers"]["up"] + pack["movers"]["down"]
        assert all(set(r) == {"symbol", "name", "contribution_usd", "contribution_pts", "return_pct", "weight_pct"} for r in movers) and movers
        assert all(set(r) == {"account", "start", "end", "change_usd", "change_pct", "net_flows"} for r in pack["accounts"]) and pack["accounts"]
        assert set(pack["income"]) == {"dividends", "interest", "margin_interest"}
        assert set(pack["realized"]) == {"short_term", "long_term", "total", "sales"}
        assert set(pack["risk"]) == {"max_drawdown_pct", "volatility_pct", "best_day", "worst_day", "band", "convictions"}
        assert set(pack["risk"]["band"]) == {"band", "label", "worst_year_loss_pct", "fit", "worst_year_p10_pct"}
        assert all(set(c) == {"symbol", "weight_pct", "band_min_pct", "band_max_pct", "status"} for c in pack["risk"]["convictions"])
        assert set(pack["decisions"]) == {"made", "matured"}
        assert set(pack["fi"]) == {"fi_number", "progress_start_pct", "progress_end_pct", "change_pts"}
        assert all(isinstance(v, int | float) for v in pack["numbers"].values())
    week = stored(conn, "week", "2026-11-06")["pack"]
    assert all(set(r) == {"date", "account", "amount", "kind"} for r in week["flows"]) and len(week["flows"]) == 1
    assert all(set(r) == {"date", "account", "symbol", "side", "shares", "price", "amount"} for r in week["trades"]) and len(week["trades"]) == 1
    assert (
        all(set(r) == {"id", "date", "origin", "kind", "symbol", "title", "status"} for r in week["decisions"]["made"]) and len(week["decisions"]["made"]) == 1
    )
    assert all(set(r) == {"id", "symbol", "kind", "origin", "horizon", "usd", "end"} for r in week["decisions"]["matured"])
    assert all(set(r) == {"id", "name", "kind", "status", "return_pct", "value_end"} for r in week["paper"]) and len(week["paper"]) == 1
    assert all(set(r) == {"date", "type", "symbol", "detail"} for r in week["events"])
    wanted = {
        "change_usd",
        "change_pct",
        "net_flows",
        "gain_usd",
        "start_value",
        "end_value",
        "vs.spy.pts",
        "vs.safe-mix.pts",
        "contrib.ACME.usd",
        "ret.ACME.pct",
    }
    wanted |= {
        "dividends",
        "interest",
        "margin_interest",
        "realized_st",
        "realized_lt",
        "max_drawdown_pct",
        "volatility_pct",
        "fi_progress_pct",
        "fi_change_pts",
    }
    assert wanted <= set(week["numbers"])
    conn.close()


def test_week_pack_numbers(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    review.run(cfg, None, conn, now=NOW)
    row = stored(conn, "week", "2026-11-06")
    pack = row["pack"]
    ix = index_series()
    assert (row["start"], row["as_of"], pack["label"], pack["quality"]) == ("2026-11-02", "2026-11-06", "Week of Nov 2, 2026", "ok")
    assert pack["coverage"] == {"full": True, "base": "2026-10-30", "days": 6, "note": None}
    assert pack["value"] == {
        "start": 845.0,
        "end": 1373.0,
        "change_usd": 528.0,
        "change_pct": pytest.approx((ix[-1] / ix[5] - 1) * 100, abs=1e-4),
        "net_flows": 500.0,
        "gain_usd": 28.0,
    }
    spy, safe, dip = pack["vs"]
    assert [r["id"] for r in pack["vs"]] == ["spy", "safe-mix", "dip-buy"] and spy["kind"] == "benchmark" and safe["kind"] == "mix"
    same_dollars = 845.0
    for a, b, d in zip(IVV[5:], IVV[6:], DAYS[6:], strict=False):
        same_dollars = same_dollars * b / a + FLOWS.get(d, 0.0)
    assert spy["return_pct"] == pytest.approx((107 / 104 - 1) * 100, abs=1e-4) and spy["value_end"] == pytest.approx(same_dollars, abs=0.01)
    assert spy["diff_usd"] == pytest.approx(1373.0 - same_dollars, abs=0.01) and spy["excess_pts"] == pytest.approx(
        pack["value"]["change_pct"] - spy["return_pct"], abs=1e-3
    )
    assert 0 < dip["return_pct"] < safe["return_pct"] < spy["return_pct"]
    up = {r["symbol"]: r for r in pack["movers"]["up"]}
    assert [r["symbol"] for r in pack["movers"]["up"]] == ["IVV", "ACME"] and pack["movers"]["down"] == [] and pack["movers"]["other_usd"] == 0.0
    assert up["IVV"]["contribution_usd"] == 15.0 and up["ACME"]["contribution_usd"] == 13.0 and up["ACME"]["name"] == "Acme Corp"
    assert up["ACME"]["return_pct"] == pytest.approx((24 / 22.5 - 1) * 100, abs=1e-4) and up["ACME"]["weight_pct"] == pytest.approx(192 / 1373 * 100, abs=1e-4)
    assert up["ACME"]["contribution_pts"] == pytest.approx(13 / 845 * 100, abs=1e-4)
    assert pack["accounts"] == [
        {"account": "ind", "start": 845.0, "end": 1373.0, "change_usd": 528.0, "change_pct": pack["value"]["change_pct"], "net_flows": 500.0}
    ]
    assert pack["income"] == {"dividends": 3.0, "interest": 0.0, "margin_interest": 1.25}
    assert pack["trades"] == [{"date": "2026-11-05", "account": "ind", "symbol": "ACME", "side": "sell", "shares": 2.0, "price": 23.0, "amount": 46.0}]
    assert pack["realized"] == {"short_term": 0.0, "long_term": 16.0, "total": 16.0, "sales": 1}
    risk = pack["risk"]
    assert risk["worst_day"] == {"date": "2026-11-03", "pct": pytest.approx((835 / 840 - 1) * 100, abs=1e-4)} and risk["best_day"]["date"] == "2026-11-05"
    assert risk["max_drawdown_pct"] == pytest.approx((840 / 845 * 835 / 840 * 1330 / 1335 - 1) * 100, abs=1e-4) and risk["volatility_pct"] > 0
    assert risk["band"] == {"band": 3, "label": "Balanced", "worst_year_loss_pct": 20.0, "fit": "fits", "worst_year_p10_pct": -15.0}
    assert risk["convictions"] == [
        {"symbol": "ACME", "weight_pct": pytest.approx(13.984, abs=1e-3), "band_min_pct": 5.0, "band_max_pct": 12.0, "status": "over"}
    ]
    assert [d["id"] for d in pack["decisions"]["made"]] == ["d1"]
    assert pack["decisions"]["matured"] == [
        {"id": "d0", "symbol": "ACME", "kind": "trim", "origin": "user", "horizon": "30D", "usd": 12.5, "end": "2026-11-05"}
    ]
    assert pack["paper"] == [{"id": "safe-mix", "name": "Safe mix", "kind": "mix", "status": "paper", "return_pct": 1.0, "value_end": 1010.0}]
    assert pack["fi"] == {"fi_number": 100000.0, "progress_start_pct": 0.845, "progress_end_pct": 1.373, "change_pts": 0.528}
    assert [(e["date"], e["type"], e["symbol"]) for e in pack["events"]] == [
        ("2026-11-03", "earnings", "ACME"),
        ("2026-11-04", "filing", "ACME"),
        ("2026-11-05", "discount", "ACME"),
    ]
    assert pack["events"][0]["detail"] == "EPS 1.2 against 1 expected" and pack["events"][2]["detail"] == "big down day, -12.3% from its high"
    n = pack["numbers"]
    assert n["change_usd"] == 528.0 and n["vs.spy.pts"] == spy["excess_pts"] and n["contrib.ACME.usd"] == 13.0 and n["score.d0.30D.usd"] == 12.5
    assert n["paper.safe-mix.pct"] == 1.0 and n["weight.ACME.pct"] == pytest.approx(13.984, abs=1e-3) and "volatility_pct" in n
    conn.close()


def test_partial_cover_weekend_days_and_old_periods(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    review.run(cfg, None, conn, now=NOW)
    october = stored(conn, "month", "2026-10-30")["pack"]
    assert october["coverage"]["full"] is False and october["coverage"]["base"] == "2026-10-23" and "starts 2026-10-23" in october["coverage"]["note"]
    assert october["value"]["start"] == 800.0 and october["value"]["end"] == 845.0 and october["realized"]["short_term"] == -4.0
    assert october["income"]["interest"] == 0.4 and october["risk"]["band"] is None and october["trades"] == []
    monday = stored(conn, "day", "2026-11-02")["pack"]
    assert monday["coverage"]["base"] == "2026-10-30" and monday["coverage"]["days"] == 2 and monday["value"]["change_usd"] == -5.0
    assert monday["risk"]["volatility_pct"] is None and "volatility_pct" not in monday["numbers"]
    assert monday["movers"]["down"][0]["symbol"] == "ACME" and monday["movers"]["up"] == []
    assert conn.execute("SELECT count(*) FROM period_reviews WHERE \"end\"='2026-10-23'").fetchone()[0] == 0
    conn.close()


def test_a_movers_return_agrees_with_its_contribution(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    with conn:
        conn.execute("UPDATE price_bars SET close=20.0, adj_close=20.0 WHERE symbol='ACME' AND date='2026-11-06'")
        conn.execute("UPDATE series_daily SET value = value - 0.01 WHERE date='2026-11-06' AND series_id='value' AND scope='account'")
    review.run(cfg, None, conn, now=NOW)
    day = stored(conn, "day", "2026-11-06")["pack"]
    acme = next(r for r in day["movers"]["up"] if r["symbol"] == "ACME")
    assert acme["contribution_usd"] == 8.0 and acme["return_pct"] == pytest.approx((24 / 23 - 1) * 100, abs=1e-4)
    assert day["accounts"][0]["net_flows"] == 0.0 and day["value"]["net_flows"] == 0.0
    conn.close()


# ---- Job ----


def test_run_backfills_then_freezes_final_packs(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    out = review.run(cfg, None, conn, now=NOW)
    assert out == {"ok": True, "as_of": "2026-11-06", "written": 15, "kept": 0, "kinds": {"day": 10, "week": 2, "month": 2, "year": 1}}
    flags = {(r["kind"], r["end"]): (r["closed"], r["final"]) for r in conn.execute('SELECT kind, "end", closed, final FROM period_reviews')}
    assert flags[("day", "2026-11-05")] == (1, 1) and flags[("day", "2026-11-06")] == (1, 0) and flags[("week", "2026-10-30")] == (1, 1)
    assert flags[("week", "2026-11-06")] == (1, 0) and flags[("month", "2026-10-30")] == (1, 1) and flags[("month", "2026-11-30")] == (0, 0)
    assert flags[("year", "2026-12-31")] == (0, 0)
    before = stored(conn, "day", "2026-11-05")
    with conn:
        conn.execute("UPDATE series_daily SET value = value + 10 WHERE date IN ('2026-11-05', '2026-11-06') AND series_id='value'")
    again = review.run(cfg, None, conn, now=MONDAY)
    assert again["kept"] == 11 and again["written"] == 4 and again["kinds"] == {"day": 1, "week": 1, "month": 1, "year": 1}
    assert stored(conn, "day", "2026-11-05")["digest"] == before["digest"] and stored(conn, "day", "2026-11-06")["pack"]["value"]["end"] == 1383.0
    assert review.run(cfg, None, conn, now=MONDAY, rebuild=True)["written"] == 15
    assert stored(conn, "day", "2026-11-05")["digest"] != before["digest"]
    conn.close()


def test_the_open_day_is_not_closed_before_the_bell(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    review.run(cfg, None, conn, now=datetime(2026, 11, 6, 15, 0, tzinfo=UTC))
    assert stored(conn, "day", "2026-11-06")["closed"] == 0 and stored(conn, "week", "2026-11-06")["closed"] == 0
    assert stored(conn, "day", "2026-11-05")["closed"] == 1
    conn.close()


def test_run_needs_two_days_and_the_job_is_scheduled(cfg):
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    apply_schemas(cfg)
    conn = connect(cfg.desk_db)
    assert review.run(cfg, None, conn, now=NOW)["written"] == 0
    conn.close()
    with pytest.raises(review.NotReady):
        review.pending(cfg)
    assert "review" in engine_main.JOBS and ("35,45 17 * * 1-5", "python -m desk.engine review") in JOBS
    assert ("35 8 * * 1-5", "python -m desk.engine review") in JOBS
    assert engine_main.run_review(cfg)["ok"] is True


def test_review_runs_on_the_engine_output(cfg, mirror):
    from desk.engine.source import open_mirror
    from tests.engine.test_core import computed
    from tests.engine.test_preflight import seed

    seed(mirror)
    computed(cfg)
    conn = connect(cfg.desk_db)
    m = open_mirror(cfg)
    try:
        out = review.run(cfg, m, conn, now=datetime(2026, 11, 4, 23, 0, tzinfo=UTC))
        pack = stored(conn, "day", "2026-11-04")["pack"]
    finally:
        m.close()
        conn.close()
    assert out["ok"] and out["as_of"] == "2026-11-04" and set(pack) == PACK_KEYS
    assert pack["value"]["end"] == pytest.approx(pack["value"]["start"] + pack["value"]["change_usd"], abs=0.01)


# ---- Seam for the debrief desk ----


def test_pending_and_record_contract(cfg, monkeypatch):
    conn = seeded(cfg, monkeypatch)
    with pytest.raises(review.NotReady):
        review.pending(cfg)
    review.run(cfg, None, conn, now=NOW)
    rows = review.pending(cfg)
    assert [(r["kind"], r["end"], r["closed"]) for r in rows] == [
        ("day", "2026-11-06", True),
        ("week", "2026-11-06", True),
        ("month", "2026-11-30", False),
        ("year", "2026-12-31", False),
    ]
    week = rows[1]
    assert set(week) == {"kind", "start", "end", "closed", "digest", "debrief_digest", "pack"} and week["debrief_digest"] is None
    assert week["digest"] == review.digest(week["pack"]) and set(week["pack"]) == PACK_KEYS
    good = DEBRIEF | {"pack_digest": week["digest"]}
    bad = (
        {"headline": "x" * 121},
        {"what_happened": ""},
        {"why": "x" * 701},
        {"against_decisions": None},
        {"watch": ["a"] * 5},
        {"watch": ["x" * 161]},
        {"next_steps": [{"text": "a", "symbol": None}] * 4},
        {"next_steps": [{"text": "x" * 201, "symbol": None}]},
        {"next_steps": [{"symbol": "ACME"}]},
        {"numbers_cited": ["made_up"]},
        {"pack_digest": "stale"},
        {"model": ""},
        {"written_at": None},
    )
    for change in bad:
        with pytest.raises(ValueError):
            review.record(cfg, "week", "2026-11-06", good | change)
    with pytest.raises(ValueError):
        review.record(cfg, "week", "2026-11-13", good)
    assert review.record(cfg, "week", "2026-11-06", good) is True
    assert [r["kind"] for r in review.pending(cfg)] == ["day", "month", "year"]
    assert review.record(cfg, "week", "2026-11-06", good | {"headline": "Rewritten."}) is True
    body = json.loads(conn.execute("SELECT body FROM period_debriefs WHERE kind='week'").fetchone()[0])
    assert body["headline"] == "Rewritten." and body["next_steps"][1] == {"text": "Nothing else.", "symbol": None}
    assert conn.execute("SELECT count(*), max(run_id) FROM period_debriefs").fetchone()[:] == (1, "7")
    with conn:
        conn.execute("UPDATE series_daily SET value = value + 10 WHERE date='2026-11-06' AND series_id='value'")
    review.run(cfg, None, conn, now=MONDAY)
    again = next(r for r in review.pending(cfg) if r["kind"] == "week")
    assert again["debrief_digest"] == week["digest"] and again["digest"] != week["digest"]
    conn.close()


# ---- API ----


def test_reviews_api(cfg, monkeypatch, app_client):
    api = app_client(packages=["engine"])
    empty = api.get("/api/engine/reviews/index").json()
    assert empty == {"as_of": None, "kinds": {"day": [], "week": [], "month": [], "year": []}, "note": review.EMPTY_NOTE}
    first = api.get("/api/engine/reviews?kind=day").json()
    assert first["pack"] is None and first["debrief"] is None and first["note"] == review.EMPTY_NOTE
    conn = seeded(cfg, monkeypatch)
    review.run(cfg, None, conn, now=NOW)
    week = review.pending(cfg)[1]
    review.record(cfg, "week", "2026-11-06", DEBRIEF | {"pack_digest": week["digest"]})
    index = api.get("/api/engine/reviews/index").json()
    assert index["as_of"] == "2026-11-06" and index["note"] is None and [len(index["kinds"][k]) for k in review.KINDS] == [10, 2, 2, 1]
    assert index["kinds"]["week"][0] == {
        "start": "2026-11-02",
        "end": "2026-11-06",
        "as_of": "2026-11-06",
        "label": "Week of Nov 2, 2026",
        "closed": True,
        "final": False,
        "change_usd": 528.0,
        "change_pct": week["pack"]["value"]["change_pct"],
        "has_debrief": True,
    }
    assert index["kinds"]["day"][0]["end"] == "2026-11-06" and index["kinds"]["day"][0]["has_debrief"] is False
    latest = api.get("/api/engine/reviews?kind=week").json()
    assert set(latest) == {"kind", "start", "end", "as_of", "closed", "final", "computed_at", "digest", "pack", "debrief"}
    assert latest["end"] == "2026-11-06" and latest["digest"] == week["digest"] and latest["pack"] == week["pack"]
    debrief = latest["debrief"]
    assert set(debrief) == {
        "headline",
        "what_happened",
        "why",
        "against_decisions",
        "watch",
        "next_steps",
        "numbers_cited",
        "model",
        "written_at",
        "pack_digest",
        "stale",
    }
    assert (
        debrief["stale"] is False
        and debrief["headline"] == DEBRIEF["headline"]
        and debrief["next_steps"][0] == {"text": "Review the ACME band.", "symbol": "ACME"}
    )
    old = api.get("/api/engine/reviews?kind=day&end=2026-10-27").json()
    assert old["final"] is True and old["debrief"] is None and old["pack"]["label"] == "Tue Oct 27, 2026"
    assert api.get("/api/engine/reviews?kind=day&end=2026-10-25").json()["note"] == "No day review ends 2026-10-25."
    assert api.get("/api/engine/reviews?kind=decade").json()["note"].startswith("kind must be one of")
    with conn:
        conn.execute("UPDATE series_daily SET value = value + 10 WHERE date='2026-11-06' AND series_id='value'")
    review.run(cfg, None, conn, now=MONDAY)
    assert api.get("/api/engine/reviews?kind=week").json()["debrief"]["stale"] is True
    conn.close()
