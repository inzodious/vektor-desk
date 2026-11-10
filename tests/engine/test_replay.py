from datetime import date, timedelta

import pytest

from desk.db import connect
from desk.engine import __main__ as engine_main
from desk.engine import backfill, broker, replay, schema
from desk.engine.__main__ import run_holdings
from tests.engine.helpers import closes_doc
from tests.engine.test_broker import IND_NUM, computed, drop, export, run_rows, seed, txn

IND, HSA = "individual-0003", "hsa-0002"
COVER = {IND: ("2024-01-01", "2025-12-31")}


# ---- Synthetic market and history ----


def weekdays(start: str, end: str) -> list[str]:
    d, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= stop:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def path(days: list[str], steps: list[tuple[str, float]]) -> dict[str, tuple[float, float]]:
    out, px = {}, steps[0][1]
    moves = dict(steps)
    for d in days:
        px = moves.get(d, px)
        out[d] = (px, px)
    return out


def flat_index(days: list[str], px: float = 100.0) -> dict:
    return {d: (px, px) for d in days}


def row(day, kind, amount=0.0, sym=None, qty=None, price=None, acct=IND):
    key = f"{day}-{kind}-{sym}-{amount}"
    return {"date": day, "accountKey": acct, "kind": kind, "symbol": sym, "quantity": qty, "price": price, "amount": amount, "key": key}


def variants(view: dict) -> dict[str, dict]:
    return {v["id"]: v for v in view["variants"]}


DAYS_2025 = weekdays("2024-12-30", "2025-06-30")


def capped_world():
    series = {"SPY": flat_index(DAYS_2025), "ROKT": path(DAYS_2025, [("2024-12-30", 100.0), ("2025-04-01", 80.0), ("2025-05-01", 50.0)])}
    activity = [
        row("2025-01-02", "deposit", 10000),
        row("2025-01-03", "buy", -3000, "ROKT", 30, 100),
        row("2025-06-02", "sell", 750, "ROKT", -15, 50),
    ]
    return activity, series


# ---- Size caps ----


def test_baseline_replays_to_the_account_value():
    activity, series = capped_world()
    view = replay.run("2025-06-30", activity, COVER, series, held_value=8500.0)
    assert view["status"] == "ok" and view["quality"] == "ok" and view["index"] == "SPY"
    assert view["you"]["end_value"] == 8500.0 and view["you"]["gap_usd"] == 0.0
    assert view["index_only"]["end_value"] == 10000.0
    assert view["dates"][-1] == "2025-06-30" and len(view["dates"]) == len(view["you"]["values"]) == len(view["index_only"]["values"])
    assert all(len(v["values"]) == len(view["dates"]) for v in view["variants"])
    assert view["headline"] == "house" and view["variants"][0]["id"] == "house"


def test_buy_cap_sends_the_rest_to_the_index_and_scales_later_sales():
    activity, series = capped_world()
    v = variants(replay.run("2025-06-30", activity, COVER, series))
    cap = v["buy-cap-10"]
    assert cap["end_value"] == 9500.0 and cap["change_usd"] == 1000.0
    assert cap["by_symbol"] == [{"symbol": "ROKT", "usd": 1000.0}]
    assert cap["actions"] == 1 and cap["moved_usd"] == 2000.0 and cap["events"][0]["what"] == "cap"
    assert v["buy-cap-20"]["change_usd"] == 500.0
    assert [v[f"buy-cap-{p}"]["change_usd"] for p in (5, 10, 15, 20)] == [1250.0, 1000.0, 750.0, 500.0]


def test_position_cap_counts_what_is_already_held():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2024-12-30", 100.0), ("2025-05-01", 50.0)])}
    activity = [row("2025-01-02", "deposit", 10000), row("2025-01-03", "buy", -800, "ROKT", 8, 100), row("2025-02-03", "buy", -800, "ROKT", 8, 100)]
    v = variants(replay.run("2025-06-30", activity, COVER, series))
    assert v["buy-cap-10"]["change_usd"] == 0.0
    assert v["position-cap-10"]["change_usd"] == 300.0
    assert v["position-cap-10"]["events"] == [{"date": "2025-02-03", "symbol": "ROKT", "what": "cap", "usd": 600.0}]


def test_funds_and_the_index_are_never_capped():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "FXAIX": flat_index(days, 200.0), "XLK": path(days, [("2024-12-30", 100.0), ("2025-05-01", 50.0)])}
    activity = [row("2025-01-02", "deposit", 10000), row("2025-01-03", "buy", -5000, "XLK", 50, 100), row("2025-01-06", "buy", -4000, "FXAIX", 20, 200)]
    view = replay.run("2025-06-30", activity, COVER, series, broad={"XLK"})
    assert all(v["change_usd"] == 0.0 for v in view["variants"])
    assert view["sizing"]["buys"] == 0


def test_the_index_sleeve_grows_with_the_index():
    days = DAYS_2025
    series = {"SPY": path(days, [("2024-12-30", 100.0), ("2025-03-03", 150.0)]), "ROKT": flat_index(days)}
    activity = [row("2025-01-02", "deposit", 10000), row("2025-01-03", "buy", -3000, "ROKT", 30, 100)]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert variants(view)["buy-cap-10"]["change_usd"] == 1000.0
    assert view["index_only"]["end_value"] == 15000.0


# ---- Exits ----


def test_fixed_stop_sells_at_the_first_close_under_the_line():
    activity, series = capped_world()
    v = variants(replay.run("2025-06-30", activity[:2], COVER, series))
    assert v["stop-15"]["change_usd"] == 900.0 and v["stop-20"]["change_usd"] == 900.0
    assert v["stop-25"]["change_usd"] == 0.0 and v["stop-30"]["change_usd"] == 0.0
    assert v["stop-15"]["events"] == [{"date": "2025-04-01", "symbol": "ROKT", "what": "stop", "usd": 2400.0}]
    assert v["stop-25"]["events"][0]["date"] == "2025-05-01"


def test_a_stop_also_cuts_the_winner_that_came_back():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2024-12-30", 100.0), ("2025-02-03", 80.0), ("2025-04-01", 200.0)])}
    activity = [row("2025-01-02", "deposit", 10000), row("2025-01-03", "buy", -1000, "ROKT", 10, 100)]
    stop = variants(replay.run("2025-06-30", activity, COVER, series))["stop-15"]
    assert stop["change_usd"] == -1200.0 and stop["hurt_usd"] == -1200.0 and stop["helped_usd"] == 0.0


def test_trend_rule_exits_under_the_200_day_average_and_skips_buys_below_it():
    days = weekdays("2024-01-01", "2025-06-30")
    rokt = {}
    for i, d in enumerate(days):
        px = 50.0 + i * 0.25 if d < "2025-03-03" else 60.0
        rokt[d] = (px, px)
    series = {"SPY": flat_index(days), "ROKT": rokt}
    activity = [
        row("2024-12-02", "deposit", 20000),
        row("2024-12-03", "buy", -rokt["2024-12-03"][0] * 10, "ROKT", 10, rokt["2024-12-03"][0]),
        row("2025-04-01", "buy", -600, "ROKT", 10, 60),
    ]
    cover = {IND: ("2024-01-01", "2025-12-31")}
    trend = variants(replay.run("2025-06-30", activity, cover, series))["trend-200"]
    whats = [(e["date"], e["what"]) for e in sorted(trend["events"], key=lambda e: e["date"])]
    assert whats == [("2025-03-03", "trend"), ("2025-04-01", "trend")]
    assert trend["change_usd"] == 0.0
    assert trend["moved_usd"] == 1200.0


def test_trend_rule_needs_200_closes():
    activity, series = capped_world()
    assert variants(replay.run("2025-06-30", activity, COVER, series))["trend-200"]["actions"] == 0


# ---- Margin ----


def test_no_margin_skips_the_borrowed_part_and_its_interest():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2024-12-30", 100.0), ("2025-05-01", 50.0)])}
    activity = [
        row("2025-01-02", "deposit", 1000),
        row("2025-01-03", "buy", -3000, "ROKT", 30, 100),
        row("2025-02-03", "margin_interest", -20),
        row("2025-03-03", "deposit", 2020),
    ]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 1500.0
    assert view["margin"]["peak_usd"] == 2020.0 and view["margin"]["interest_usd"] == 20.0 and view["margin"]["days"] > 30
    assert view["sizing"]["on_margin"] == 1
    free = variants(view)["no-margin"]
    assert free["change_usd"] == 1020.0
    assert {e["symbol"]: e["usd"] for e in free["by_symbol"]} == {"ROKT": 1000.0, "Margin interest": 20.0}
    assert variants(view)["buy-cap-10"]["events"][0]["what"] == "cap"


def test_a_same_day_swap_is_not_margin():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": flat_index(days), "NOVA": flat_index(days, 50.0)}
    activity = [
        row("2025-01-02", "deposit", 1000),
        row("2025-01-03", "buy", -1000, "ROKT", 10, 100),
        row("2025-02-03", "buy", -1000, "NOVA", 20, 50),
        row("2025-02-03", "sell", 1000, "ROKT", -10, 100),
    ]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert variants(view)["no-margin"]["actions"] == 0 and view["margin"]["days"] == 0


# ---- Holding period ----


def test_long_term_rule_waits_a_year_and_a_day():
    days = weekdays("2024-01-01", "2025-06-30")
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2024-01-01", 100.0), ("2024-06-03", 150.0), ("2025-01-02", 200.0)])}
    activity = [row("2024-01-02", "deposit", 10000), row("2024-01-03", "buy", -1000, "ROKT", 10, 100), row("2024-06-03", "sell", 1500, "ROKT", -10, 150)]
    view = replay.run("2025-06-30", activity, COVER, series, short_rate=30.0, state_rate=5.0)
    assert view["you"]["end_value"] == 10500.0 and view["you"]["realized"] == {"short": 500.0, "long": 0.0} and view["you"]["tax_usd"] == 150.0
    held = variants(view)["long-term"]
    assert held["change_usd"] == 500.0 and held["realized"] == {"short": 0.0, "long": 1000.0}
    assert held["tax_usd"] == 200.0 and held["tax_change_usd"] == 50.0
    assert held["events"] == [{"date": "2024-06-03", "symbol": "ROKT", "what": "wait", "usd": 1500.0}]
    assert view["tax_rates"] == {"short_pct": 30.0, "long_pct": 20.0}
    assert replay.long_from("2024-01-03") == "2025-01-04" and replay.long_from("2024-02-29") == "2025-03-01"


def test_a_sale_still_waiting_at_the_end_is_valued_at_the_last_close():
    days = weekdays("2025-01-01", "2025-06-30")
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2025-01-01", 100.0), ("2025-03-03", 150.0), ("2025-05-01", 90.0)])}
    activity = [row("2025-01-02", "deposit", 10000), row("2025-01-03", "buy", -1000, "ROKT", 10, 100), row("2025-03-03", "sell", 1500, "ROKT", -10, 150)]
    held = variants(replay.run("2025-06-30", activity, COVER, series))["long-term"]
    assert held["change_usd"] == -600.0 and held["realized"] == {"short": 0.0, "long": 0.0}


def test_sheltered_accounts_stay_out_of_the_tax_lines():
    days = weekdays("2025-01-01", "2025-06-30")
    series = {"SPY": flat_index(days), "ROKT": path(days, [("2025-01-01", 100.0), ("2025-03-03", 150.0)])}
    activity = [
        row("2025-01-02", "deposit", 10000, acct=HSA),
        row("2025-01-03", "buy", -1000, "ROKT", 10, 100, acct=HSA),
        row("2025-03-03", "sell", 1500, "ROKT", -10, 150, acct=HSA),
    ]
    view = replay.run("2025-06-30", activity, {HSA: ("2025-01-01", "2025-12-31")}, series, sheltered=lambda a: a.startswith("hsa"), short_rate=30.0)
    assert view["you"]["realized"] == {"short": 0.0, "long": 0.0} and view["you"]["tax_usd"] == 0.0


# ---- Corporate actions, dividends, old positions ----


def test_reverse_split_keeps_the_capped_share():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "TRDR": path(days, [("2024-12-30", 5.0), ("2025-03-03", 50.0), ("2025-05-01", 20.0)])}
    activity = [
        row("2025-01-02", "deposit", 2000),
        row("2025-01-03", "buy", -500, "TRDR", 100, 5),
        row("2025-03-03", "split", 0, "TRDR", -100),
        row("2025-03-03", "split", 0, "TRDR", 10),
        row("2025-06-02", "sell", 200, "TRDR", -10, 20),
    ]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 1700.0
    assert variants(view)["buy-cap-10"]["change_usd"] == 180.0


def test_distribution_of_a_held_name_scales_both_sides():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "GMEX": path(days, [("2024-12-30", 100.0), ("2025-03-03", 25.0)])}
    activity = [row("2025-01-02", "deposit", 1000), row("2025-01-03", "buy", -400, "GMEX", 4, 100), row("2025-03-03", "distribution", 0, "GMEX", 12)]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 1000.0 and variants(view)["buy-cap-10"]["change_usd"] == 0.0


def test_dividends_follow_the_shares_the_rule_kept():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": flat_index(days)}
    activity = [
        row("2025-01-02", "deposit", 10000),
        row("2025-01-03", "buy", -3000, "ROKT", 30, 100),
        row("2025-03-03", "dividend", 30, "ROKT"),
        row("2025-03-03", "reinvest", -30, "ROKT", 0.3, 100),
    ]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 10030.0
    cap = variants(view)["buy-cap-10"]
    assert cap["end_value"] == 10010.0 and cap["change_usd"] == -20.0


def test_shares_held_before_the_history_are_seeded_not_shorted():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "OLDY": flat_index(days, 20.0)}
    activity = [row("2025-01-02", "deposit", 500), row("2025-02-03", "sell", 100, "OLDY", -5, 20)]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 600.0 and view["you"]["values"][0] == 600.0
    assert view["quality"] == "modelled" and "OLDY was held before the history starts" in view["notes"][0]
    assert view["index_only"]["end_value"] == 600.0


def test_a_day_trade_is_not_an_old_position():
    days = DAYS_2025
    series = {"SPY": flat_index(days), "ROKT": flat_index(days)}
    activity = [row("2025-01-02", "deposit", 5000), row("2025-01-03", "sell", 1100, "ROKT", -10, 110), row("2025-01-03", "buy", -1000, "ROKT", 10, 100)]
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["you"]["end_value"] == 5100.0 and view["quality"] == "ok" and not view["notes"]


def test_cash_sweep_rows_and_other_accounts_are_ignored():
    activity, series = capped_world()
    activity += [
        row("2025-01-02", "buy", -10000, "SPAXX", 10000, 1),
        {**row("2025-01-02", "reinvest", -5, "FDRXX", 5, 1), "core": True},
        row("2025-01-02", "deposit", 99999, acct="roth-0009"),
    ]
    assert replay.run("2025-06-30", activity, COVER, series)["you"]["end_value"] == 8500.0


# ---- Not ready and partial ----


def test_not_ready_without_history_or_an_index():
    activity, series = capped_world()
    assert replay.run("2025-06-30", activity, {}, series)["status"] == "not_ready"
    no_index = replay.run("2025-06-30", activity, COVER, {"ROKT": series["ROKT"]})
    assert no_index["status"] == "not_ready" and "S&P 500" in no_index["reason"] and no_index["variants"] == []


def test_unpriced_names_are_left_alone_and_flagged():
    activity, series = capped_world()
    view = replay.run("2025-06-30", activity, COVER, {"SPY": series["SPY"]})
    assert view["status"] == "partial" and view["quality"] == "pro_forma" and view["unpriced"] == ["ROKT"]
    assert view["you"]["end_value"] == 7750.0 + 15 * 50
    assert all(v["change_usd"] == 0.0 for v in view["variants"])


def test_an_index_that_starts_late_is_flagged():
    activity, series = capped_world()
    series["SPY"] = {d: v for d, v in series["SPY"].items() if d >= "2025-02-03"}
    view = replay.run("2025-06-30", activity, COVER, series)
    assert view["status"] == "partial" and view["quality"] == "pro_forma" and "SPY prices start on 2025-02-03" in view["notes"][0]
    assert view["you"]["end_value"] == 8500.0 and variants(view)["buy-cap-10"]["change_usd"] == 1000.0


def test_a_gap_to_the_holdings_marks_the_replay_modelled():
    activity, series = capped_world()
    view = replay.run("2025-06-30", activity, COVER, series, held_value=9000.0)
    assert view["quality"] == "modelled" and view["you"]["gap_usd"] == -500.0 and "more than 1% away" in view["notes"][-1]


def test_sizing_reads_each_buy_against_the_account():
    activity, series = capped_world()
    sizing = replay.run("2025-06-30", activity, COVER, series)["sizing"]
    assert sizing == {
        "buys": 1,
        "median_pct": 30.0,
        "over_10": 1,
        "on_margin": 0,
        "largest": {"date": "2025-01-03", "symbol": "ROKT", "pct": 30.0, "usd": 3000.0},
    }


def test_house_rule_is_the_position_cap_with_no_margin():
    house = replay.presets()[0]
    assert house.id == replay.HEADLINE and house.position_cap == 0.10 and house.no_margin
    assert len({r.id for r in replay.presets()}) == len(replay.presets())


@pytest.mark.parametrize("rule", [r.id for r in replay.presets()])
def test_every_rule_adds_up_by_symbol(rule):
    days = weekdays("2024-01-01", "2025-06-30")
    series = {
        "SPY": path(days, [("2024-01-01", 100.0), ("2024-09-02", 120.0), ("2025-03-03", 110.0)]),
        "ROKT": path(days, [("2024-01-01", 40.0), ("2024-06-03", 90.0), ("2024-12-02", 55.0), ("2025-04-01", 30.0)]),
        "NOVA": path(days, [("2024-01-01", 20.0), ("2024-08-01", 26.0), ("2025-02-03", 44.0)]),
    }
    activity = [
        row("2024-01-02", "deposit", 4000),
        row("2024-01-03", "buy", -2000, "ROKT", 50, 40),
        row("2024-02-01", "buy", -3000, "NOVA", 150, 20),
        row("2024-03-01", "margin_interest", -9),
        row("2024-03-04", "deposit", 3000),
        row("2024-07-01", "sell", 2700, "ROKT", -30, 90),
        row("2024-12-03", "buy", -2750, "ROKT", 50, 55),
        row("2025-02-04", "sell", 2200, "NOVA", -50, 44),
        row("2025-03-03", "withdrawal", -1500),
    ]
    view = replay.run("2025-06-30", activity, COVER, series)
    v = variants(view)[rule]
    assert round(sum(e["usd"] for e in v["by_symbol"]), 2) == pytest.approx(v["change_usd"], abs=0.05)
    assert v["end_value"] == pytest.approx(view["you"]["end_value"] + v["change_usd"], abs=0.02)
    assert v["values"][-1] == v["end_value"]


# ---- Engine run, API and backfill ----


def test_engine_run_stores_the_replay_and_the_api_serves_it(cfg, mirror, app_client):
    days = ["2026-10-01", "2026-10-21", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    mirror.put("priceCloses", "SPY_2026", closes_doc("SPY", 2026, [[d, 500, 500] for d in days]))
    seed(mirror)
    drop(cfg, "history.json", export(run_rows(), start="2026-09-01", end="2026-11-04"))
    assert engine_main.run_history(cfg)["ok"]
    run_holdings(cfg)
    view = computed(cfg).views["replay"]
    assert view["status"] == "ok" and view["quality"] == "ok" and view["accounts"] == [IND]
    assert view["you"]["end_value"] == 1377.5 and view["you"]["gap_usd"] == -12.5
    assert [v["id"] for v in view["variants"]] == [r.id for r in replay.presets()]
    assert view["margin"]["interest_usd"] == 12.5
    assert view["tax_rates"] is None and view["variants"][0]["tax_usd"] is None
    assert app_client().get("/api/engine/replay").json() == view


def test_the_api_answers_before_the_engine_has_run(client):
    body = client.get("/api/engine/replay").json()
    assert body["status"] == "not_ready" and body["variants"] == []


def test_traded_names_join_the_price_backfill(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    rows = run_rows() + [
        txn(IND_NUM, "2026-10-02", "Buy", symbol="SPAXX", qty=5, net=5, price=1, sec="Mutual Fund"),
        txn(IND_NUM, "2026-10-05", "Buy", symbol="NOVA", qty=1, net=50, price=50),
        txn(IND_NUM, "2026-10-06", "Sell", symbol="NOVA", qty=-1, net=55, price=55, dw="D"),
    ]
    drop(cfg, "history.json", export(rows, start="2026-09-01"))
    broker.import_inbox(cfg, conn)
    assert backfill.traded_symbols(conn) == ["NOVA", "ROKT"]
    backfill.sync_roles(conn)
    found = {r["symbol"]: (r["role"], r["priority"]) for r in conn.execute("SELECT symbol, role, priority FROM market_symbols WHERE role='history'")}
    assert found == {"NOVA": ("history", 2), "ROKT": ("history", 2)}
    conn.close()
