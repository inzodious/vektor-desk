import random
from datetime import UTC, date, datetime, timedelta

import pytest

from desk.db import connect
from desk.engine import discounts, schema

NOW = datetime(2026, 11, 6, 22, 40, tzinfo=UTC)


def sessions(n, end=date(2026, 11, 6)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def path(n=400, last=None, seed=1, drift=0.0004, noise=0.006):
    rng = random.Random(seed)
    px, out = 100.0, []
    for _ in range(n):
        px *= 1 + drift + rng.gauss(0, noise)
        out.append(px)
    if last is not None:
        out[-1] = out[-2] * (1 + last)
    return out


def desk(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


def bars(conn, symbol, closes, days=None):
    days = days or sessions(len(closes))
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(symbol, d, p, p, p, p, p) for d, p in zip(days, closes, strict=True)],
        )


# ---- Measures ----


def test_a_big_down_day_and_a_first_close_under_the_high_are_hits():
    days = sessions(400)
    calm = list(zip(days, path(), strict=True))
    m = discounts.measures(calm)
    assert discounts.reason(m) is None and m["as_of"] == "2026-11-06"
    crash = list(zip(days, path(last=-0.04), strict=True))
    m = discounts.measures(crash)
    assert discounts.reason(m) == "big_down_day" and m["move_z"] < -2 and m["day_move_pct"] == pytest.approx(-4.0)
    slide = [100.0] * 300 + [100 - 0.1 * i for i in range(1, 99)] + [90.05, 89.9]
    m = discounts.measures(list(zip(days, slide, strict=True)))
    assert discounts.reason(m) == "crossed_10" and m["drop_from_high_pct"] == pytest.approx(-10.1)
    assert discounts.measures(calm[:30]) is None


def test_valuation_uses_annual_eps_or_the_five_year_average(cfg):
    conn = desk(cfg)
    days = sessions(1300)
    px = list(zip(days, [50 + i * 0.05 for i in range(1300)], strict=True))
    v = discounts.valuation(conn, "ETFX", px)
    assert v["metric"] == "price_vs_5y_avg" and v["pctile_own"] == 1.0 and v["value"] > 0
    with conn:
        conn.executemany(
            "INSERT INTO fundamentals VALUES ('CORP', 'eps_diluted', ?, ?, ?, 'FY', '10-K', ?, ?, 'USD/shares')",
            [(f"{y}-01-01", f"{y}-12-31", y, f"{y + 1}-02-15", 2.0 + (y - 2020) * 0.5) for y in range(2020, 2026)],
        )
        conn.execute("INSERT INTO fundamentals VALUES ('CORP', 'eps_diluted', '2026-01-01', '2026-03-31', 2026, 'Q1', '10-Q', '2026-05-01', 9.0, 'USD/shares')")
    v = discounts.valuation(conn, "CORP", px)
    assert v["metric"] == "pe_annual" and v["value"] == pytest.approx(px[-1][1] / 4.5, abs=1e-3) and 0 <= v["pctile_own"] <= 1
    conn.close()


# ---- Scan and the agents seam ----


def seeded(cfg):
    conn = desk(cfg)
    days = sessions(400)
    with conn:
        conn.execute("INSERT INTO holdings_daily VALUES ('2026-11-06', 'ind', 'HELD', 10, 1, 10, 9, NULL, 0, 's', 'a', 'ok')")
        conn.execute("INSERT INTO holdings_daily VALUES ('2026-11-06', 'ind', 'SPAXX', 5, 1, 5, 5, NULL, 1, 's', 'a', 'ok')")
        conn.execute("INSERT INTO market_symbols (symbol, role, priority, added_at) VALUES ('WTCH', 'watch', 2, '2026-11-01')")
        conn.execute("INSERT INTO sec_tickers VALUES ('HELD', 1, 'Held Corp', '2026-11-01')")
    bars(conn, "HELD", path(last=-0.05, seed=2)[:-1], days[:-1])
    with conn:
        conn.execute("INSERT INTO prices_daily VALUES ('HELD', '2026-11-06', ?, NULL, 'finnhub')", (path(last=-0.05, seed=2)[-1],))
    bars(conn, "WTCH", path(last=-0.03, seed=3))
    bars(conn, "VOO", path(seed=4))
    bars(conn, "QQQ", path(last=-0.035, seed=5))
    return conn


def test_scan_stores_hits_and_feeds_the_case_writers(cfg, app_client):
    conn = seeded(cfg)
    with pytest.raises(discounts.NotReady):
        discounts.pending(cfg)
    out = discounts.scan(conn, now=NOW)
    assert out["hits"] == 3 and out["as_of"] == "2026-11-06" and out["short_history"] > 0
    assert conn.execute("SELECT role FROM market_symbols WHERE symbol='MSFT'").fetchone()[0] == "universe"
    assert discounts.scan(conn, now=NOW)["hits"] == 3 and conn.execute("SELECT count(*) FROM discount_signals").fetchone()[0] == 3
    conn.close()
    hits = discounts.pending(cfg, 10)
    assert [h["symbol"] for h in hits] == sorted((h["symbol"] for h in hits), key=lambda s: next(x["drop_from_high_pct"] for x in hits if x["symbol"] == s))
    held = next(h for h in hits if h["symbol"] == "HELD")
    assert held["list"] == "held" and held["name"] == "Held Corp" and held["signal_id"] == "2026-11-06-HELD" and held["reason"] == "crossed_10"
    assert set(held) >= {"signal_id", "symbol", "name", "as_of", "list", "price", "drop_from_high_pct", "move_z", "valuation", "numbers"}
    assert set(held["valuation"]) == {"metric", "value", "pctile_own"} and "day_move_pct" in held["numbers"]
    assert {h["list"] for h in hits} == {"held", "watchlist", "quality"} and len(discounts.pending(cfg, 1)) == 1
    case = {
        "verdict": "wait",
        "case": "A fund-level drop with no news; wait for the close to settle.",
        "risks": "Could keep falling.",
        "confidence": 0.6,
        "horizon_days": 20,
        "numbers_cited": ["day_move_pct", "drop_from_high_pct"],
        "model": "test-model",
        "written_at": "2026-11-06T23:00:00Z",
        "run_id": "r1",
    }
    for bad in ({"verdict": "sell"}, {"case": "x" * 401}, {"confidence": 2}, {"horizon_days": 0}, {"numbers_cited": ["made_up"]}):
        with pytest.raises(ValueError):
            discounts.record(cfg, held["signal_id"], case | bad)
    with pytest.raises(ValueError):
        discounts.record(cfg, "nope", case)
    assert discounts.record(cfg, held["signal_id"], case) is True
    assert discounts.record(cfg, held["signal_id"], case | {"verdict": "buy"}) is False
    assert "HELD" not in {h["symbol"] for h in discounts.pending(cfg)}
    body = app_client(packages=["engine"]).get("/api/engine/discounts").json()
    assert body["as_of"] == "2026-11-06" and body["scanned"] == 4 and len(body["rows"]) == 3 and body["rule"].startswith("After the close")
    row = next(r for r in body["rows"] if r["symbol"] == "HELD")
    assert (
        row["case"]["verdict"] == "wait"
        and row["case"]["case"].startswith("A fund-level")
        and row["case"]["numbers_cited"] == ["day_move_pct", "drop_from_high_pct"]
        and row["case"]["buy_if"] is None
    )


def test_a_case_keeps_its_buy_condition_as_the_desk_sent_it_and_an_older_table_gains_the_column(cfg, app_client):
    conn = seeded(cfg)
    discounts.scan(conn, now=NOW)
    with conn:
        conn.execute("ALTER TABLE discount_cases DROP COLUMN buy_if")
    schema.apply(conn)
    assert "buy_if" in {r[1] for r in conn.execute("PRAGMA table_info(discount_cases)")}
    conn.close()
    first, second, third = (h["signal_id"] for h in discounts.pending(cfg, 10))
    case = {"verdict": "wait", "case": "Wait for a better price.", "risks": "Could keep falling.", "confidence": 0.6, "horizon_days": 20}
    case |= {"numbers_cited": ["day_move_pct"], "model": "test-model", "written_at": "2026-11-06T23:00:00Z"}
    below = {"kind": "price_below", "value": 41.5, "date": None, "words": "Buy under $41.50."}
    odd = {"kind": "whenever", "value": "soon"}
    assert discounts.record(cfg, first, case | {"buy_if": below}) and discounts.record(cfg, second, case | {"buy_if": odd})
    assert discounts.record(cfg, third, case)
    rows = {r["signal_id"]: r["case"] for r in app_client(packages=["engine"]).get("/api/engine/discounts").json()["rows"]}
    assert (rows[first]["buy_if"], rows[second]["buy_if"], rows[third]["buy_if"]) == (below, odd, None)


def test_discounts_endpoint_before_a_scan_and_the_job(cfg, app_client):
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    body = app_client(packages=["engine"]).get("/api/engine/discounts").json()
    assert body["rows"] == [] and body["as_of"] is None
    assert "discounts" in engine_main.JOBS and ("40 17 * * 1-5", "python -m desk.engine discounts") in JOBS
