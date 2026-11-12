import json
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from desk.agents import store
from desk.db import apply_schemas, connect
from desk.opportunities import build as ob
from desk.opportunities import cases as own_cases
from desk.opportunities import ready, sizing

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=UTC)
AS_OF = "2026-11-06"
LATER = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
NEXT = "2026-11-09"
DEBIT = "A margin debit of $900 is open, so ready cash goes there first and no buy is proposed."


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


def scout_idea(cfg, symbol="MSFT", *, flag=False, rejected=None):
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
    if rejected:
        return decisions.reject_proposal(cfg, idea, "scout", rejected, run_id="9")
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
    assert out["asof"]["day"] is None and out["prices"] == {"day": None, "words": None, "older": []}
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


def note(cfg, symbol, verdict, **more):
    run_id = store.start_run(cfg, "research", trigger="schedule", model="opus", effort="xhigh", status="ok")
    body = {
        "symbol": symbol,
        "verdict": verdict,
        "verdict_line": f"{verdict.capitalize()}: the story is intact but the price is fair.",
        "bear_case": "Margins may slip.",
    }
    store.save_dossier(cfg, symbol, run_id, json.dumps(body | more), "2026-11-06T07:10:00+00:00")


def test_a_held_row_on_sale_carries_its_research_note_and_hold_is_not_a_buy(cfg, rules):
    seed(cfg)
    note(cfg, "ACME", "hold")
    out = ob.build(cfg, now=NOW)
    r = row(out, "ACME")
    assert r["stance"] == "watch" and r["stance_label"] == "You already hold this; the analysis says hold, not add"
    assert r["why_now"] == "Research: Hold: the story is intact but the price is fair." and r["wrong_if"].startswith("Research: Margins may slip.")
    assert "research" in r["sources"] and r["source_label"] == "research note + On sale by the numbers"
    assert r["research"] == {"verdict": "hold", "written_at": "2026-11-06T07:10:00+00:00"} and r["analysis_as_of"] == AS_OF
    assert "Your research note is from the same day." in r["as_of_words"]
    assert out["counts"]["written"] == 1 and out["counts"]["with_case"] == 0


def test_a_research_note_that_says_add_is_a_buy_even_when_the_name_is_not_on_sale(cfg, rules):
    seed(cfg)
    assert row(ob.build(cfg, now=NOW), "IVV") is None
    note(cfg, "IVV", "add")
    r = row(ob.build(cfg, now=NOW), "IVV")
    assert r["stance"] == "buy" and r["stance_label"] == "Worth buying now" and r["size"]["usd"] > 0 and r["not_queued"] is None


def test_a_held_name_that_says_hold_and_is_not_on_sale_stays_off_the_list(cfg, rules):
    seed(cfg)
    note(cfg, "IVV", "hold")
    note(cfg, "ACME", "watch", what_it_is="Unclear.", identified=False)
    out = ob.build(cfg, now=NOW)
    assert row(out, "IVV") is None
    assert row(out, "ACME")["research"] is None and row(out, "ACME")["stance"] == "screen"


def test_a_buy_case_on_a_holding_the_research_note_says_hold_is_a_watch(cfg, rules):
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    note(cfg, "ACME", "hold")
    r = row(ob.build(cfg, now=NOW), "ACME")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: the case says buy, but your research note says hold"
    assert r["why_now"] == "ACME fell with the market, not on its own news."


# ---- The page leads with rows that could become a buy ----


def test_rows_are_grouped_buy_then_could_then_not_now_and_the_headline_counts_them(cfg, rules):
    conn = seed(cfg)
    note(cfg, "ACME", "hold")
    out = ob.build(cfg, now=NOW)
    assert [(r["symbol"], r["group"]) for r in out["rows"]] == [("QUAL", "could"), ("WTCH", "could"), ("ACME", "not_now")]
    assert row(out, "ACME")["group_label"] == "Not now" and row(out, "QUAL")["group_label"] == "Could become a buy"
    assert out["counts"]["could"] == 2 and out["counts"]["not_now"] == 1
    assert out["headline"] == "Nothing rated a buy yet. 2 could become one, 1 not for now. Top: QUAL, 16.7% under its high."
    signal(conn, "WTCH", case="buy")
    out = ob.build(cfg, now=NOW)
    assert [(r["symbol"], r["group"]) for r in out["rows"]] == [("WTCH", "buy"), ("QUAL", "could"), ("ACME", "not_now")]
    assert out["headline"].startswith("1 worth buying now, 1 to watch, 1 not for now. Top: WTCH, 27.4% under its high.")
    assert ready(cfg, now=NOW).startswith("2 buying opportunities, 1 rated a buy")


def test_a_row_the_caps_block_is_not_for_now_and_nothing_close_says_so(cfg, monkeypatch):
    monkeypatch.setattr("desk.engine.preflight.rules_in_force", lambda cfg, plan: ([RULES[1]], "profile"))
    conn = seed(cfg)
    signal(conn, "ACME", case="buy")
    with conn:
        conn.execute("DELETE FROM price_bars WHERE symbol IN ('QUAL', 'WTCH')")
        conn.execute("DELETE FROM market_symbols")
    out = ob.build(cfg, now=NOW)
    assert row(out, "ACME")["group"] == "not_now" and row(out, "IVV")["stance_label"] == "Watch: not on sale yet"
    assert {r["group"] for r in out["rows"]} == {"not_now"} and out["rows"][0]["symbol"] == "ACME"
    assert out["headline"] == "Nothing rated a buy yet, and nothing is close: 3 not for now. Top: ACME, 32.2% under its high."
    assert ready(cfg, now=NOW) == "No buying opportunities today: 3 looked at, none for now; 1 case written overnight"


def test_the_drop_is_one_figure_and_says_so_when_the_case_was_written_at_another_price(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="wait")
    with conn:
        conn.execute("INSERT INTO closes_provisional VALUES ('QUAL', ?, 171.0, 180.0, '2026-11-09T21:00:00+00:00', '2026-11-09T21:02:00+00:00')", (NEXT,))
    out = ob.build(cfg, now=LATER)
    r = row(out, "QUAL")
    assert r["facts"][0] == "20.9% under its 52-week high at the latest price (14.0% when the case was written)"
    assert r["numbers"]["drop_from_high_pct"] == pytest.approx(-20.9, abs=0.05)
    assert "Top: QUAL, 20.9% under its high." in out["headline"]


# ---- Cases for rows the scanner did not flag ----


def test_only_rows_with_no_written_analysis_ask_for_a_case_and_the_hit_is_in_the_scanner_s_shape(cfg, rules):
    seed(cfg)
    note(cfg, "ACME", "hold")
    hits = own_cases.wanted(ob.build(cfg, now=NOW))
    assert [h["symbol"] for h in hits] == ["QUAL", "WTCH"]
    h = hits[1]
    assert h["signal_id"] == f"list-{AS_OF}-WTCH" and h["as_of"] == AS_OF and h["list"] == "on sale, not held" and h["name"] == "Watch Co"
    assert h["price"] == 10.0 and h["drop_from_high_pct"] == h["numbers"]["drop_from_high_pct"] < -20
    assert {"price", "drop_from_high_pct", "high_52w", "sigma_month_pct", "swings_under_high"} <= set(h["numbers"])


def test_a_case_written_for_the_list_rates_the_row_and_a_bad_one_is_refused(cfg, rules):
    seed(cfg)
    hits = [h for h in own_cases.wanted(ob.build(cfg, now=NOW)) if h["symbol"] == "WTCH"]
    source = own_cases.ListSource(hits)
    assert source.pending(cfg, 6) == hits and source.pending(cfg, 0) == []
    good = {"verdict": "avoid", "case": "The product line is being shut.", "risks": "A buyer may appear.", "confidence": 0.7, "horizon_days": 120}
    good |= {"numbers_cited": ["price"], "model": "opus", "written_at": "2026-11-07T06:00:00+00:00", "run_id": 4}
    with pytest.raises(ValueError, match="verdict must be buy, wait or avoid"):
        source.record(cfg, hits[0]["signal_id"], good | {"verdict": "strong buy"})
    with pytest.raises(ValueError, match="numbers_cited"):
        source.record(cfg, hits[0]["signal_id"], good | {"numbers_cited": ["made_up"]})
    with pytest.raises(ValueError, match="no row"):
        source.record(cfg, "list-2026-11-06-NOPE", good)
    assert own_cases.load(cfg) == {}
    assert source.record(cfg, hits[0]["signal_id"], good) is True
    out = ob.build(cfg, now=NOW)
    assert row(out, "WTCH") is None and out["passed"] == [
        {"symbol": "WTCH", "name": "Watch Co", "reason": "Written case says avoid: The product line is being shut."}
    ]
    assert own_cases.fresh(cfg, "2026-11-20") == {}


def test_the_real_cases_desk_writes_into_the_list_through_its_own_source_parameter(cfg, rules):
    from desk.agents.adapter import FakeAdapter
    from desk.agents.discounts import run_discount_desk
    from tests.agents.agent_fakes import FakeDecisions
    from tests.agents.test_advisor import FakeAdvisor

    seed(cfg)
    store.set_guard(cfg, False)
    hits = own_cases.wanted(ob.build(cfg, now=NOW))[:2]
    answer = {"verdict": "buy", "case": "It fell with its sector on no news of its own.", "risks": "The sector may keep sliding.", "confidence": 0.58}
    answer |= {"horizon_days": 120, "numbers_cited": ["drop_from_high_pct", "made_up"]}
    fake = FakeAdapter({"discounts": answer})
    profile = {"agents": {"enabled": True, "desks": {"discounts": True}}}
    report = run_discount_desk(
        cfg,
        discounts=own_cases.ListSource(hits),
        decisions=FakeDecisions(profile_data=profile),
        adapter=fake,
        advice=FakeAdvisor(),
        trigger="schedule",
        limit=2,
    )
    assert report.status == "ok" and report.written == [h["signal_id"] for h in hits] and report.dropped_numbers == 2
    sent = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["hit"]
    assert sent["symbol"] == "QUAL" and sent["list"] == "on sale, not held" and sent["numbers"]["drop_from_high_pct"] < -10
    saved = own_cases.load(cfg)["QUAL"]
    assert saved["numbers_cited"] == ["drop_from_high_pct"] and saved["as_of"] == AS_OF and saved["run_id"]
    out = ob.build(cfg, now=NOW)
    r = row(out, "QUAL")
    assert r["stance"] == "buy" and r["stance_label"] == "Worth buying now" and r["case"]["confidence"] == 0.58
    assert r["wrong_if"].startswith("The sector may keep sliding.") and out["counts"]["with_case"] == 2
    assert own_cases.written_tonight(cfg, datetime.now(UTC)) == 2 and [h["symbol"] for h in own_cases.wanted(out)] == ["WTCH"]


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
    assert out["headline"].startswith("1 worth buying once the margin debit is paid")
    assert out["cash"]["free_usd"] == 0 and out["cash"]["margin_debit_usd"] == 900.0
    assert r["queued"] is False and r["not_queued"] == "Pay the margin debit first: $900 is open, so no buy goes to the queue."
    monkeypatch.setattr("desk.engine.preflight.next_deposit", lambda cfg, plan, day, now=None: (1000.0, "2026-11-18"))
    r = row(ob.build(cfg, now=NOW), "QUAL")
    assert r["size"]["funding"] == "deposit" and r["size"]["usd"] == pytest.approx(100.0)
    assert "Waits for the Nov 18 deposit after it clears the margin debit" in r["size"]["note"]
    assert r["stance_label"] == "Worth buying with the next deposit"
    assert r["not_queued"].endswith("The Nov 18 deposit clears it and covers this.")


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
    assert r["stance_label"] == "Worth buying now" and r["not_queued"] is None


def test_a_buy_with_no_ready_cash_still_shows_and_says_why_it_is_not_queued(cfg, rules):
    conn = seed(cfg, cash=10.0)
    signal(conn, "QUAL", case="buy")
    out = ob.build(cfg, now=NOW)
    r = row(out, "QUAL")
    assert r["stance"] == "buy" and r["size"]["usd"] == 0 and r["stance_label"] == "Worth buying once cash is free"
    assert r["not_queued"] == "Needs more ready cash than there is: $10 is ready today."
    assert out["headline"].startswith("1 worth buying once cash is free")


def test_cash_and_the_margin_debit_come_from_the_desk_s_own_numbers(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    with conn:
        for metric, value in (("cash.ready", 50.0), ("margin.debit", 1200.0)):
            conn.execute("INSERT INTO metric_values VALUES (?, 'portfolio', 'all', 'now', ?, ?, 'usd', 1, 'ok', '1')", (metric, AS_OF, value))
    out = ob.build(cfg, now=NOW)
    assert out["cash"]["free_usd"] == 50.0 and out["cash"]["margin_debit_usd"] == 1200.0
    r = row(out, "QUAL")
    assert r["stance"] == "buy" and r["size"]["usd"] == 0 and r["size"]["funding"] == "wait"
    assert r["not_queued"].startswith("Pay the margin debit first: $1,200 is open")


def test_cash_ready_elsewhere_never_sizes_a_buy_the_buying_account_cannot_pay_for(cfg, rules):
    conn = seed(cfg, cash=10.0)
    signal(conn, "QUAL", case="buy")
    with conn:
        conn.execute("INSERT INTO metric_values VALUES ('cash.ready', 'portfolio', 'all', 'now', ?, 600.0, 'usd', 1, 'ok', '1')", (AS_OF,))
    r = row(ob.build(cfg, now=NOW), "QUAL")
    assert r["stance"] == "buy" and r["size"]["usd"] == 0 and r["size"]["funding"] == "wait" and r["size"]["blocked"] is None
    assert r["size"]["note"] == "It needs more settled cash than the buying account holds today. Never on margin."
    assert r["not_queued"] == "Needs more ready cash than the buying account holds today."


# ---- The newest price ----


def test_a_provisional_close_moves_the_price_the_drop_and_the_zone(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    before = row(ob.build(cfg, now=NOW), "QUAL")
    assert before["price_as_of"] == AS_OF and before["price_source"] == "close" and before["entry"]["high"] == 180.0
    assert before["as_of_words"] == "Priced at the Fri Nov 6 close. The written case is from the same day."
    with conn:
        conn.execute("INSERT INTO closes_provisional VALUES ('QUAL', ?, 171.0, 180.0, '2026-11-09T21:00:00+00:00', '2026-11-09T21:02:00+00:00')", (NEXT,))
    out = ob.build(cfg, now=LATER)
    r = row(out, "QUAL")
    assert r["price_as_of"] == NEXT and r["as_of"] == NEXT and r["price_source"] == "provisional" and r["price_behind"] is False
    assert r["entry"]["high"] == 171.0 and r["entry"]["low"] < before["entry"]["low"] and r["invalid_below"] < before["invalid_below"]
    assert r["analysis_as_of"] == AS_OF and r["since_analysis_pct"] == pytest.approx(-5.0)
    assert r["as_of_words"].startswith("Priced at the Mon Nov 9 close, provisional until the official close lands.")
    assert "The written case is from Fri Nov 6; the price is 5.0% lower since." in r["as_of_words"]
    assert any(f.startswith("20.9% under its 52-week high") for f in r["facts"])
    assert out["as_of"] == AS_OF and out["asof"]["day"] == AS_OF and out["prices"]["day"] == NEXT


def test_a_name_with_no_newer_price_says_so_on_its_row(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", case="buy")
    with conn:
        conn.execute("INSERT INTO closes_provisional VALUES ('QUAL', ?, 171.0, 180.0, '2026-11-09T21:00:00+00:00', '2026-11-09T21:02:00+00:00')", (NEXT,))
    out = ob.build(cfg, now=LATER)
    r = row(out, "WTCH")
    assert r["price_as_of"] == AS_OF and r["price_behind"] is True
    later = "live quotes cover what you hold, and other closes arrive the same evening, mutual funds later."
    assert r["as_of_words"].endswith(f"The desk has no newer price for it than Fri Nov 6: {later}")
    assert {"symbol": "WTCH", "price_as_of": AS_OF, "held": False} in out["prices"]["older"]
    assert out["prices"]["words"].startswith("Prices run to Mon Nov 9.") and "WTCH" in out["prices"]["words"] and out["prices"]["words"].endswith(later)
    assert "overnight" not in out["prices"]["words"] + r["as_of_words"]


def test_a_live_quote_marks_a_held_name_and_an_old_quote_changes_nothing(cfg, rules):
    conn = seed(cfg)
    quote = "INSERT INTO quotes_live VALUES (?, ?, ?, ?, ?, ?)"
    with conn:
        conn.execute(quote, ("ACME", "2026-11-09T15:30:00-05:00", 22.0, 24.0, "finnhub", "2026-11-09T20:30:05+00:00"))
        conn.execute(quote, ("ACME", "2026-11-09T10:00:00-05:00", 23.5, 24.0, "finnhub", "2026-11-09T15:00:05+00:00"))
        conn.execute(quote, ("WTCH", "2026-11-06T15:59:00-05:00", 9.0, 10.2, "finnhub", "2026-11-06T21:00:05+00:00"))
        conn.execute(quote, ("IVV", "2026-11-09T16:00:00-05:00", 90.0, 107.0, "close", "2026-11-09T20:30:05+00:00"))
    out = ob.build(cfg, now=datetime(2026, 11, 9, 20, 40, tzinfo=UTC))
    r = row(out, "ACME")
    assert r["price_source"] == "quote" and r["price_as_of"] == NEXT and r["price_at"] == "2026-11-09T15:30:00-05:00"
    assert r["entry"]["high"] == 22.0 and r["as_of_words"].startswith("Priced at Mon Nov 9, 3:30 PM ET.")
    w = row(out, "WTCH")
    assert w["price_source"] == "close" and w["price_as_of"] == AS_OF and w["entry"]["high"] == 10.0
    assert all(x["symbol"] != "IVV" for x in out["rows"])


def test_the_scanner_hit_s_day_is_the_analysis_day_when_no_case_is_written(cfg, rules):
    conn = seed(cfg)
    signal(conn, "QUAL", day="2026-11-04")
    r = row(ob.build(cfg, now=NOW), "QUAL")
    assert r["analysis_as_of"] == "2026-11-04" and r["price_as_of"] == AS_OF
    assert "The scanner hit is from Wed Nov 4; the price is" in r["as_of_words"]
    a = row(ob.build(cfg, now=NOW), "ACME")
    assert a["analysis_as_of"] == AS_OF and a["as_of_words"] == "Priced at the Fri Nov 6 close. The numbers here are worked out from that price."


# ---- Ideas that cannot be bought yet ----


def test_a_scout_buy_turned_back_for_the_margin_debit_still_shows_as_a_buy(cfg, rules):
    seed(cfg, cash=-900.0)
    record = scout_idea(cfg, "MSFT", rejected=DEBIT)
    out = ob.build(cfg, now=NOW)
    r = row(out, "MSFT")
    assert r["stance"] == "buy" and r["stance_label"] == "Worth buying once cash is free" and "scout" in r["sources"]
    assert r["decision_id"] == record["id"] and r["queued"] is False
    assert r["not_queued"] == "Pay the margin debit first: $900 is open, so no buy goes to the queue."
    assert r["why_now"].startswith("Scout: Backlog doubled") and "One customer is a large share of sales." in r["wrong_if"]
    assert out["counts"]["buy"] == 1 and out["headline"].startswith("1 worth buying once the margin debit is paid")


def test_an_open_scout_idea_wins_over_an_older_turned_back_one(cfg, rules):
    seed(cfg)
    scout_idea(cfg, "MSFT", rejected="It needs $100 of ready cash and there is $40.")
    r = row(ob.build(cfg, now=NOW), "MSFT")
    assert r["stance"] == "buy" and r["stance_label"] == "Worth buying now" and r["queued"] is False
    assert r["not_queued"].startswith("Scout's idea was turned back on ") and "It needs $100 of ready cash and there is $40." in r["not_queued"]
    record = scout_idea(cfg, "MSFT")
    r = row(ob.build(cfg, now=NOW), "MSFT")
    assert r["decision_id"] == record["id"] and r["queued"] is True and r["not_queued"] is None


def test_a_hold_off_note_makes_it_a_watch_and_other_rejections_stay_out(cfg, rules):
    seed(cfg)
    held = "A standing note says to hold off: No new buys until the margin is cleared."
    scout_idea(cfg, "MSFT", rejected=held)
    scout_idea(cfg, "WTCH", rejected="WTCH is inside a planned wash-sale window: no buys until 2027-01-15.")
    scout_idea(cfg, "QUAL", rejected="Numbers don't match the brief: price")
    out = ob.build(cfg, now=NOW)
    r = row(out, "MSFT")
    assert r["stance"] == "watch" and r["stance_label"] == "Watch: a standing note says hold off" and r["not_queued"] == held
    w = row(out, "WTCH")
    assert w["stance"] == "watch" and w["stance_label"] == "Watch: inside a no-buy window" and "wash-sale window" in w["not_queued"]
    assert "scout" not in (row(out, "QUAL") or {"sources": []})["sources"]


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
    top = {"as_of", "asof", "prices", "built_at", "advice_only", "freshness", "headline", "counts", "note", "profile", "cash", "method", "rows", "passed"}
    assert set(body) == top
    assert {"research", "numbers"} <= set(body["rows"][0]) and "written" in body["counts"]
    timing = {"price_as_of", "price_source", "price_at", "price_behind", "analysis_as_of", "since_analysis_pct", "as_of_words", "queued", "not_queued"}
    assert timing <= set(body["rows"][0])
    assert set(body["asof"]) == {"day", "words", "status", "provisional", "expected_day", "behind"}


def test_a_fault_while_building_gives_an_empty_list_that_says_so(cfg, rules, monkeypatch):
    seed(cfg)
    monkeypatch.setattr(ob, "_universe", lambda conn: 1 / 0)
    out = ob.build(cfg, now=NOW)
    assert out["rows"] == [] and out["note"].startswith("The list could not be built this time (ZeroDivisionError")
