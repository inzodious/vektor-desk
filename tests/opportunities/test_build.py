import json
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from desk.agents import store
from desk.db import apply_schemas, connect
from desk.opportunities import build as ob
from desk.opportunities import ready, sizing

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=UTC)
AS_OF = "2026-11-06"


def sessions(n, end=date(2026, 11, 6)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def slide(n, last, drop, noise=0.012, seed=7):
    rng = random.Random(seed)
    top = last / (1 - drop)
    out = [top * (1 + rng.gauss(0, noise)) for _ in range(n - 60)]
    out += [(top - (top - last) * (i + 1) / 60) * (1 + rng.gauss(0, noise) * (59 - i) / 60) for i in range(60)]
    out[0] = top * 1.02
    return out


def seed(cfg, *, cash=600.0):
    apply_schemas(cfg)
    conn = connect(cfg.desk_db)
    days = sessions(320)
    names = (("ACME", 24.0, 0.30), ("IVV", 107.0, 0.02), ("QUAL", 180.0, 0.14), ("MSFT", 400.0, 0.03), ("WTCH", 10.0, 0.25))
    with conn:
        for sym, last, drop in names:
            rows = [(sym, d, p, p) for d, p in zip(days, slide(320, last, drop), strict=True)]
            conn.executemany("INSERT INTO price_bars (symbol, date, close, adj_close) VALUES (?, ?, ?, ?)", rows)
        hold = f"INSERT INTO holdings_daily VALUES ('{AS_OF}', ?, ?, ?, ?, ?, ?, NULL, ?, 's', 'a', 'ok')"
        conn.execute(hold, ("individual", "ACME", 20, 24.0, 480.0, 600.0, 0))
        conn.execute(hold, ("individual", "IVV", 80, 107.0, 8560.0, 7000.0, 0))
        conn.execute(hold, ("individual", "SPAXX", abs(cash), 1.0, cash, cash, 1))
        conn.execute("INSERT INTO sec_tickers VALUES ('ACME', 1, 'Acme Corp', '2026-11-01')")
        conn.execute("INSERT INTO sec_tickers VALUES ('MSFT', 2, 'Microsoft Corp', '2026-11-01')")
        conn.execute("INSERT INTO sec_tickers VALUES ('WTCH', 3, 'Watch Co', '2026-11-01')")
        conn.execute("INSERT INTO sec_tickers VALUES ('QUAL', 4, 'Quality Factor ETF', '2026-11-01')")
        conn.execute("INSERT INTO market_symbols (symbol, role, priority, added_at) VALUES ('WTCH', 'watch', 5, '2026-11-01')")
    return conn


def signal(conn, symbol, *, day=AS_OF, reason="crossed_10", case=None):
    numbers = {"price": 180.0, "day_move_pct": -2.4, "drop_from_high_pct": -14.0, "move_z": -2.2}
    sid = f"{day}-{symbol}"
    with conn:
        conn.execute(
            "INSERT INTO discount_signals VALUES (?, ?, ?, ?, 'quality', ?, 180, -14.0, -2.2, '{}', ?, ?)",
            (sid, day, symbol, f"{symbol} name", reason, json.dumps(numbers), day),
        )
        conn.execute("INSERT OR REPLACE INTO discount_scans VALUES (?, ?, 20, 1, '[]')", (day, day))
        if case:
            conn.execute(
                "INSERT INTO discount_cases VALUES (?, ?, ?, ?, ?, 90, '[]', 'opus', '2026-11-07T02:00:00+00:00', '1')",
                (sid, case, f"{symbol} fell with the market, not on its own news.", "The sell-off may be the start of something longer", 0.62),
            )
    return sid


def row(listing, symbol):
    return next((r for r in listing["rows"] if r["symbol"] == symbol), None)


RULES = [
    {"id": "c1", "kind": "conviction_hold", "symbols": ["ACME"], "params": {"band_min_pct": 0, "band_max_pct": 12}},
    {"id": "m1", "kind": "no_margin_buys", "params": {}},
]


@pytest.fixture
def rules(monkeypatch):
    monkeypatch.setattr("desk.engine.preflight.rules_in_force", lambda cfg, plan: (RULES, "profile"))


def scout_idea(cfg, symbol="MSFT", *, flag=False):
    from desk import decisions

    idea = {
        "kind": "buy",
        "title": f"Start a position in {symbol}",
        "symbol": symbol,
        "amount_usd": 100,
        "thesis": "Backlog doubled while the price slipped on one customer's delay.",
        "bear_case": "One customer is a large share of sales.",
        "invalidation": "A second guidance cut.",
        "horizon": "12 months",
        "rule_served": "satellite",
        "confidence": 0.6,
        "sources": [{"url": "https://example.com/a", "title": "A"}, {"url": "https://example.com/b", "title": "B"}],
    }
    record = decisions.create_proposal(cfg, idea, "scout", run_id="9")
    if flag:
        decisions.attach_skeptic(cfg, record["id"], "flag", "The delay may repeat next quarter.")
    return record


# ---- Empty states ----


def test_no_engine_run_gives_an_empty_list_with_its_reason(cfg):
    out = ob.build(cfg, now=NOW)
    assert out["rows"] == [] and out["as_of"] is None
    assert out["note"] == ob.NO_ENGINE and out["headline"] == ob.NO_ENGINE
    assert out["counts"]["total"] == 0 and out["advice_only"] is True
    assert out["profile"]["source"] == "default_moderate" and "Moderate" in out["profile"]["note"]
    assert ready(cfg) is None


def test_nothing_on_sale_says_so(cfg):
    apply_schemas(cfg)
    conn = connect(cfg.desk_db)
    days = sessions(320)
    with conn:
        conn.executemany(
            "INSERT INTO price_bars (symbol, date, close, adj_close) VALUES ('IVV', ?, ?, ?)", [(d, 100 + i * 0.01, 100 + i * 0.01) for i, d in enumerate(days)]
        )
        conn.execute(f"INSERT INTO holdings_daily VALUES ('{AS_OF}', 'individual', 'IVV', 10, 103.19, 1031.9, 900, NULL, 0, 's', 'a', 'ok')")
    out = ob.build(cfg, now=NOW)
    assert out["rows"] == [] and out["note"] == ob.NOTHING and out["as_of"] == AS_OF


# ---- Sources and stance ----


def test_a_written_buy_case_leads_the_list_with_zone_size_and_what_would_make_it_wrong(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    out = ob.build(cfg, now=NOW)
    top = out["rows"][0]
    assert top["symbol"] == "QUAL" and top["rank"] == 1 and top["stance"] == "buy" and top["held"] is False
    assert top["sources"] == ["scanner", "case"] and top["source_label"] == "Discount scanner + written case"
    assert top["why_now"].startswith("QUAL fell with the market")
    assert "First close 10% under its 52-week high on Nov 6" in top["facts"]
    assert top["entry"]["high"] == 180.0 and top["entry"]["low"] < 180.0 and top["entry"]["in_zone"] is True
    assert top["size"]["funding"] == "cash" and top["size"]["blocked"] is None
    assert top["size"]["usd"] == pytest.approx(0.025 * 9640, abs=0.5) and top["size"]["pct_points"] == 2.5
    assert top["wrong_if"].startswith("The sell-off may be the start of something longer.") and "Off below $" in top["wrong_if"]
    assert top["invalid_below"] < top["entry"]["low"]
    assert top["case"] == {"verdict": "buy", "confidence": 0.62, "horizon_days": 90, "written_at": "2026-11-07T02:00:00+00:00"}
    assert out["headline"].startswith("1 worth buying now") and "Top: QUAL" in out["headline"]
    assert out["counts"]["buy"] == 1 and out["counts"]["with_case"] == 1
    assert ready(cfg).endswith("1 rated a buy") and "$" not in ready(cfg)


def test_a_wait_case_is_a_watch_and_an_avoid_case_is_passed_on(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="wait")
    signal(conn, "MSFT", case="avoid")
    out = ob.build(cfg, now=NOW)
    assert row(out, "QUAL")["stance"] == "watch" and row(out, "QUAL")["stance_label"] == "Watch: the written case says wait"
    assert row(out, "MSFT") is None
    assert out["passed"] == [{"symbol": "MSFT", "name": "Microsoft Corp", "reason": "Written case says avoid: MSFT fell with the market, not on its own news."}]


def test_a_hit_without_a_case_stands_on_its_numbers_and_says_the_case_is_missing(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", reason="big_down_day")
    out = ob.build(cfg, now=NOW)
    r = row(out, "QUAL")
    assert r["stance"] == "screen" and r["case"] is None and r["sources"] == ["scanner"]
    assert r["why_now"].startswith("Fell 2.4% on Nov 6, a 2.2-sigma day for it.")
    assert r["wrong_if"].startswith("No written case yet")
    assert "no written case yet" in out["freshness"]["note"]
    assert out["headline"].startswith("Nothing rated a buy yet.")


def test_names_on_sale_by_the_numbers_are_listed_without_a_scanner_hit(cfg, rules):
    seed(cfg)
    out = ob.build(cfg, now=NOW)
    r = row(out, "QUAL")
    assert r["sources"] == ["standing"] and r["stance"] == "screen" and r["source_label"] == "On sale by the numbers"
    assert "under its 52-week high" in r["why_now"]
    assert row(out, "IVV") is None


def test_scout_ideas_join_the_list_and_a_skeptic_flag_makes_them_a_watch(cfg, rules):
    seed(cfg)
    record = scout_idea(cfg, "MSFT")
    out = ob.build(cfg, now=NOW)
    r = row(out, "MSFT")
    assert r["sources"] == ["scout"] and r["stance"] == "buy" and r["decision_id"] == record["id"]
    assert r["why_now"].startswith("Scout: Backlog doubled") and r["wrong_if"].startswith("One customer is a large share of sales.")
    assert "Scout confidence 60%" in r["facts"]
    flagged = scout_idea(cfg, "WTCH", flag=True)
    out = ob.build(cfg, now=NOW)
    r = row(out, "WTCH")
    assert r["decision_id"] == flagged["id"] and r["stance"] == "watch" and r["stance_label"] == "Watch: Skeptic disagreed"
    assert r["wrong_if"].startswith("Skeptic: The delay may repeat next quarter.")


def test_a_research_note_that_says_trim_keeps_a_holding_off_the_buy_tier(cfg, rules):
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    run_id = store.start_run(cfg, "research", trigger="schedule", model="opus", effort="xhigh", status="ok")
    store.save_dossier(cfg, "ACME", run_id, json.dumps({"symbol": "ACME", "verdict": "Trim"}))
    r = row(ob.build(cfg, now=NOW), "ACME")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: your research note says trim" and r["research_verdict"] == "trim"


# ---- Sizes respect the caps ----


def test_a_conviction_hold_is_sized_inside_its_own_band_not_the_single_stock_cap(cfg, rules):
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    r = row(ob.build(cfg, now=NOW), "ACME")
    assert r["held"] is True and r["weight_pct"] == pytest.approx(4.98, abs=0.01)
    assert r["stance"] == "buy" and r["size"]["blocked"] is None
    assert r["size"]["usd"] == pytest.approx(96.4, abs=0.1) and r["size"]["room_usd"] == pytest.approx(676.8, abs=0.5)


def test_a_single_stock_past_its_band_gets_no_size_and_a_plain_reason(cfg, monkeypatch):
    monkeypatch.setattr("desk.engine.preflight.rules_in_force", lambda cfg, plan: ([RULES[1]], "profile"))
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    r = row(ob.build(cfg, now=NOW), "ACME")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: no room under your cap"
    assert r["size"]["usd"] == 0 and "no room left under the 5% single-stock band" in r["size"]["blocked"]


def test_plan_rules_block_a_new_single_stock_in_the_checker_s_own_words(cfg, monkeypatch):
    rule = {"id": "no-new", "kind": "no_new_single_stocks", "params": {}}
    monkeypatch.setattr("desk.engine.preflight.rules_in_force", lambda cfg, plan: ([RULES[0], rule], "profile"))
    conn = seed(cfg)
    signal(conn, "MSFT", case="buy")
    r = row(ob.build(cfg, now=NOW), "MSFT")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: your rules block it"
    assert r["size"]["usd"] == 0 and "new single stock" in r["size"]["blocked"]


def test_nothing_is_ever_sized_on_margin(cfg, rules, monkeypatch):
    conn = seed(cfg, cash=-900.0)
    signal(conn, "QUAL", case="buy")
    out = ob.build(cfg, now=NOW)
    r = row(out, "QUAL")
    assert r["size"]["usd"] == 0 and r["size"]["funding"] == "wait" and r["size"]["blocked"] is None
    assert "the margin debit comes first" in r["size"]["note"] and "Never on margin" in r["size"]["note"]
    assert r["stance"] == "buy" and r["stance_label"] == "Worth buying once cash is free"
    assert out["headline"].startswith("1 worth buying once cash is free")
    assert out["cash"]["free_usd"] == 0 and out["cash"]["margin_debit_usd"] == 900.0
    monkeypatch.setattr("desk.engine.preflight.next_deposit", lambda cfg, plan, day, now=None: (1000.0, "2026-11-18"))
    r = row(ob.build(cfg, now=NOW), "QUAL")
    assert r["size"]["funding"] == "deposit" and r["size"]["usd"] == pytest.approx(100.0)
    assert "Waits for the Nov 18 deposit after it clears the margin debit" in r["size"]["note"]
    assert r["stance_label"] == "Worth buying with the next deposit"


def test_a_planned_loss_sale_window_blocks_buys_of_that_name(cfg, rules, monkeypatch):
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    monkeypatch.setattr(sizing, "_no_buy", lambda cfg, now: {"ACME": {"from": "2026-11-01", "until": "2027-01-15"}})
    r = row(ob.build(cfg, now=NOW), "ACME")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: inside a no-buy window"
    assert r["size"]["blocked"] == "ACME is inside a planned loss-sale window: no buys until Jan 15."


def test_sizes_never_exceed_free_cash(cfg, rules):
    conn = seed(cfg, cash=60.0)
    signal(conn, "QUAL", case="buy")
    r = row(ob.build(cfg, now=NOW), "QUAL")
    assert r["size"]["usd"] == 60.0 and r["size"]["limited_by"] == "free cash"


# ---- Order ----


def test_buys_rank_above_watches_and_ranks_count_from_one(cfg, rules):
    conn = seed(cfg)
    signal(conn, "MSFT", case="buy")
    out = ob.build(cfg, now=NOW)
    assert [r["rank"] for r in out["rows"]] == list(range(1, len(out["rows"]) + 1))
    assert out["rows"][0]["symbol"] == "MSFT"
    stances = [r["stance"] for r in out["rows"]]
    assert stances == sorted(stances, key=lambda s: s != "buy")
    assert len(out["rows"]) <= ob.MAX_ROWS


def test_the_endpoint_returns_the_list(cfg, rules, app_client):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    conn.close()
    res = app_client().get("/api/opportunities")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["rows"][0]["symbol"] == "QUAL" and body["counts"]["total"] == len(body["rows"])
    assert set(body) == {"as_of", "built_at", "advice_only", "freshness", "headline", "counts", "note", "profile", "cash", "method", "rows", "passed"}


def test_a_fault_while_building_gives_an_empty_list_that_says_so(cfg, rules, monkeypatch):
    seed(cfg)
    monkeypatch.setattr(ob, "_universe", lambda conn: 1 / 0)
    out = ob.build(cfg, now=NOW)
    assert out["rows"] == [] and out["note"].startswith("The list could not be built this time (ZeroDivisionError")
