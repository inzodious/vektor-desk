import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from desk.db import connect
from desk.engine import asof, brief
from desk.engine.__main__ import run_daily, run_quotes, run_restate, run_review
from desk.engine.cash import picture
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"
HSA = "hsa-2222"
MON, TUE, WED, THU = "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"


class Res:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def json(self):
        return self._body


class Quotes:
    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return Res(self.quotes.get(params["symbol"]) or {"c": 0, "t": 0})


def et(day, hh, mm):
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def stamp(day, hh, mm):
    return int(et(day, hh, mm).timestamp())


def at(monkeypatch, now):
    monkeypatch.setattr("desk.engine.asof.now_utc", lambda: now)
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: now)


def seed(m, *, margin=False):
    cash = -300.0 if margin else 300.0
    m.put("snapshots", 1, snapshot(1, f"{MON}T08:00", 1200.0 + cash + (120.0 if margin else 0.0), 4 if margin else 3))
    m.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0, 900.0))
    m.put("positions", 2, position(2, 1, IND, "ACME", 10, 200.0, 250.0))
    m.put("positions", 3, position(3, 1, IND, "SPAXX", cash, cash, cash=True))
    if margin:
        m.put("positions", 4, position(4, 1, HSA, "FDRXX", 120, 120.0, cash=True))
        m.put("activity", "a1", {"date": TUE, "accountKey": IND, "kind": "buy", "symbol": "ACME", "quantity": 0, "amount": 0.0, "core": False})
    m.put("priceProfiles", "ACME", {"symbol": "ACME", "kind": "stock"})
    m.put("priceProfiles", "FXAIX", {"symbol": "FXAIX", "kind": "mutual_fund"})
    m.put("priceCloses", "FXAIX_2026", closes_doc("FXAIX", 2026, [[MON, 200.0, 200.0], [TUE, 202.0, 202.0]]))
    m.put("priceCloses", "ACME_2026", closes_doc("ACME", 2026, [[MON, 20.0, 20.0], [TUE, 21.0, 21.0]]))
    m.put("priceCloses", "SPY_2026", closes_doc("SPY", 2026, [[MON, 600.0, 600.0], [TUE, 606.0, 606.0]]))
    m.pull(f"{WED}T12:00:00+00:00")


def closing(day=WED):
    return Quotes({"ACME": {"c": 23.1, "pc": 21.0, "t": stamp(day, 16, 0)}, "SPY": {"c": 612.0, "pc": 606.0, "t": stamp(day, 16, 0)}})


def book(cfg, now):
    conn = connect(cfg.desk_db, readonly=True)
    try:
        return asof.view(conn, now=now)
    finally:
        conn.close()


def bars(cfg, rows):
    conn = connect(cfg.desk_db)
    with conn:
        conn.executemany("INSERT OR REPLACE INTO price_bars (symbol, date, close, adj_close) VALUES (?, ?, ?, ?)", [(s, d, c, c) for s, d, c in rows])
    conn.close()


# ---- The clock ----


def test_last_session_turns_over_at_the_close():
    assert asof.last_session(et(WED, 15, 59)) == TUE
    assert asof.last_session(et(WED, 16, 0)) == WED
    assert asof.last_session(et(THU, 1, 25)) == WED
    assert asof.last_session(et("2026-11-14", 12, 0)) == "2026-11-13"
    assert asof.last_session(et("2026-11-27", 13, 5)) == "2026-11-27"
    assert asof.last_session(et("2026-11-26", 18, 0)) == "2026-11-25"


def test_quotes_are_fetched_once_more_right_after_the_close(cfg, mirror, monkeypatch):
    seed(mirror)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    http = closing()
    for hh, mm, fetched in ((15, 55, True), (16, 0, True), (16, 5, True), (16, 10, False), (16, 40, True)):
        at(monkeypatch, et(WED, hh, mm))
        result = run_quotes(cfg, http)
        assert ("skipped" not in result) is fetched, (hh, mm, result)


# ---- Today's day, provisional then restated ----


def test_the_evening_run_closes_today_from_the_closing_quotes(cfg, mirror, monkeypatch):
    seed(mirror)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    at(monkeypatch, et(WED, 8, 20))
    assert run_daily(cfg)["core"]["as_of"] == TUE
    morning = book(cfg, et(WED, 8, 30))
    assert morning["day"] == TUE and morning["status"] == "final" and morning["behind"] is None and morning["live"] is None
    assert morning["words"] == "Tue Nov 10, at the close."

    at(monkeypatch, et(WED, 16, 5))
    run_quotes(cfg, closing())
    late = Quotes({"ACME": {"c": 25.0, "pc": 21.0, "t": stamp(WED, 16, 45)}, "SPY": {"c": 613.0, "pc": 606.0, "t": stamp(WED, 16, 45)}})
    at(monkeypatch, et(WED, 16, 50))
    run_quotes(cfg, late)
    before = book(cfg, et(WED, 17, 0))
    assert before["day"] == TUE and before["behind"]["sessions"] == 1 and before["expected_day"] == WED
    assert before["live"]["day"] == WED and before["live"]["state"] == "after" and before["live"]["words"].startswith("Live, Wed Nov 11, ")

    at(monkeypatch, et(WED, 17, 20))
    ran = run_daily(cfg)
    assert ran["closes"] == {"restated": 0, "left": 0, "day": WED, "stamped": 2} and ran["core"]["as_of"] == WED
    assert ran["core"]["checks"]["closes"] == "ok"
    run_review(cfg)
    evening = book(cfg, et(WED, 17, 50))
    assert evening["day"] == WED and evening["provisional"] and evening["status"] == "provisional"
    assert evening["previous_day"] == TUE and evening["behind"] is None and evening["live"] is None
    assert evening["prices"] == {"official": 0, "quoted": 1, "carried": ["FXAIX"]}
    assert evening["numbers"]["value"] == 10 * 23.1 + 5 * 202.0 + 300.0
    assert evening["numbers"]["day_change"] == pytest.approx(21.0)
    assert evening["numbers"]["cash_ready"] == 300.0 and evening["numbers"]["margin_debit"] == 0.0
    assert evening["words"].startswith("Wed Nov 11, ") and evening["words"].endswith("Provisional until official closes land overnight.")
    assert evening["review"]["day"] == WED and evening["debrief"] is None

    conn = connect(cfg.desk_db, readonly=True)
    health = dict(conn.execute("SELECT check_name, detail FROM data_health WHERE as_of=?", (WED,)).fetchall())
    packs = [r[0] for r in conn.execute('SELECT "end" FROM period_reviews WHERE kind=\'day\' ORDER BY "end"')]
    conn.close()
    assert "priced from the closing quotes" in health["closes"] and "FXAIX" in health["closes"]
    assert packs[-1] == WED


def test_official_closes_restate_the_day_overnight_and_only_once(cfg, mirror, monkeypatch):
    seed(mirror)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    at(monkeypatch, et(WED, 16, 5))
    run_quotes(cfg, closing())
    at(monkeypatch, et(WED, 17, 20))
    run_daily(cfg)
    run_review(cfg)
    at(monkeypatch, et(THU, 0, 25))
    assert "skipped" in run_restate(cfg)

    bars(cfg, [("ACME", WED, 23.0), ("FXAIX", WED, 204.0), ("SPY", WED, 611.0)])
    at(monkeypatch, et(THU, 1, 25))
    done = run_restate(cfg)
    assert done["ok"] and "official closes landed" in done["why"] and done["daily"]["closes"]["restated"] == 2
    final = book(cfg, et(THU, 6, 30))
    assert final["day"] == WED and not final["provisional"] and final["status"] == "final" and final["words"] == "Wed Nov 11, at the close."
    assert final["prices"] == {"official": 2, "quoted": 0, "carried": []}
    assert final["numbers"]["value"] == 10 * 23.0 + 5 * 204.0 + 300.0
    assert final["live"] is None and final["behind"] is None
    at(monkeypatch, et(THU, 2, 25))
    assert "skipped" in run_restate(cfg)


def test_a_book_left_behind_catches_up_by_itself_from_stored_quotes(cfg, mirror, monkeypatch):
    seed(mirror)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    at(monkeypatch, et(WED, 16, 5))
    run_quotes(cfg, closing())
    night = book(cfg, et(WED, 23, 0))
    assert night["day"] == TUE and night["behind"]["sessions"] == 1 and "Closing quotes are in" in night["behind"]["reason"]
    assert night["live"]["day"] == WED and night["live"]["words"].startswith("Wed Nov 11, last quotes ")

    at(monkeypatch, et(WED, 23, 30))
    caught = run_restate(cfg)
    assert caught["ok"] and "closing quotes for 2026-11-11 are in" in caught["why"]
    after = book(cfg, et(THU, 6, 30))
    assert after["day"] == WED and after["provisional"] and after["behind"] is None and after["review"]["day"] == WED
    at(monkeypatch, et(THU, 1, 25))
    assert run_restate(cfg)["skipped"]


def test_premarket_quotes_that_still_carry_yesterday_are_not_live(cfg, mirror, monkeypatch):
    seed(mirror)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    at(monkeypatch, et(WED, 16, 5))
    run_daily(cfg)
    run_quotes(cfg, closing())
    at(monkeypatch, et(WED, 17, 20))
    run_daily(cfg)
    at(monkeypatch, et(THU, 7, 0))
    run_quotes(cfg, closing())
    early = book(cfg, et(THU, 7, 5))
    assert early["day"] == WED and early["live"] is None and early["market"] == {"state": "pre", "day": THU}
    at(monkeypatch, et(THU, 10, 0))
    run_quotes(cfg, Quotes({"ACME": {"c": 22.0, "pc": 23.1, "t": stamp(THU, 9, 59)}, "SPY": {"c": 610.0, "pc": 612.0, "t": stamp(THU, 9, 59)}}))
    midday = book(cfg, et(THU, 10, 1))
    assert midday["day"] == WED and midday["behind"] is None
    assert midday["live"]["day"] == THU and midday["live"]["state"] == "open" and midday["live"]["day_change"] == pytest.approx(-11.0)


def test_asof_is_empty_before_the_first_run_and_served_over_the_api(cfg, mirror, app_client, monkeypatch):
    client = app_client(packages=["engine"])
    empty = client.get("/api/asof").json()
    assert empty["day"] is None and empty["status"] == "empty" and empty["numbers"] == {} and empty["words"] == "The engine has not run yet."
    seed(mirror)
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    body = client.get("/api/asof").json()
    metrics = {m["metric_id"]: m["value"] for m in client.get("/api/engine/metrics?scope=portfolio&window=now").json()["metrics"]}
    assert body["day"] == TUE == client.get("/api/engine/metrics").json()["as_of"]
    assert body["numbers"]["value"] == metrics["value.market"] and body["numbers"]["cash_ready"] == metrics["cash.ready"]
    assert body["numbers"]["margin_debit"] == metrics["margin.debit"] and body["numbers"]["day_change"] == metrics["value.day_change"]
    assert set(body) >= {"day", "at", "provisional", "words", "previous_day"}


# ---- One ready cash ----


def test_ready_cash_is_never_negative_and_debt_stays_in_margin():
    rows = [
        {"account": IND, "is_cash": 1, "value": -300.0, "quality": "modelled"},
        {"account": IND, "is_cash": 0, "value": 1000.0, "quality": "ok"},
        {"account": HSA, "is_cash": 1, "value": 120.0, "quality": "ok"},
        {"account": HSA, "is_cash": 1, "value": 5.0, "quality": "ok"},
    ]
    pic = picture(rows)
    assert pic["ready"] == 125.0 and pic["debit"] == 300.0 and pic["modelled"]
    assert pic["ready_by_account"] == {HSA: 125.0} and pic["debit_by_account"] == {IND: 300.0}
    netted = picture([{"account": IND, "is_cash": 1, "value": 100.0}, {"account": IND, "is_cash": 1, "value": -500.0}])
    assert netted["ready"] == 0.0 and netted["debit"] == 400.0


def test_every_panel_reads_the_same_cash_and_margin(cfg, mirror, monkeypatch):
    seed(mirror, margin=True)
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    m = {(r["metric_id"], r["scope"], r["scope_id"]): r["value"] for r in conn.execute("SELECT * FROM metric_values WHERE \"window\"='now'")}
    conn.close()
    assert m[("cash.ready", "portfolio", "all")] == 120.0
    assert m[("cash.ready", "account", HSA)] == 120.0 and m[("cash.ready", "account", IND)] == 0.0
    assert m[("margin.debit", "portfolio", "all")] == 300.0
    numbers = book(cfg, et(WED, 8, 30))["numbers"]
    assert numbers["cash_ready"] == 120.0 and numbers["margin_debit"] == 300.0
    keeper = brief.desk_slice(cfg, "plan_keeper")
    cash = {(i["scope"], i["scope_id"]): i["value"] for i in keeper["sections"]["cash"] if i["metric_id"] == "cash.ready"}
    assert cash == {("portfolio", "all"): 120.0, ("account", HSA): 120.0, ("account", IND): 0.0}
    assert keeper["day"]["day"] == TUE and keeper["day"]["provisional"] is False


# ---- The rule flag is not a count ----


def test_a_broken_rule_says_what_breaks_it_and_how_many(cfg, mirror, monkeypatch):
    seed(mirror, margin=True)
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    flag = conn.execute("SELECT value, unit FROM metric_values WHERE metric_id='plan.rules' AND scope_id='no-margin-buys'").fetchone()
    count = conn.execute("SELECT value, unit FROM metric_values WHERE metric_id='plan.rule_breaks' AND scope_id='no-margin-buys'").fetchone()
    rules = json.loads(conn.execute("SELECT body FROM engine_views WHERE name='rules'").fetchone()[0])
    fired = conn.execute("SELECT detail FROM triggers WHERE kind='rule_breach' AND scope_id='no-margin-buys'").fetchone()
    conn.close()
    assert tuple(flag) == (0.0, "flag") and tuple(count) == (1.0, "count")
    broken = next(r for r in rules["rules"] if r["id"] == "no-margin-buys")
    assert (
        broken["holds"] is False
        and broken["count"] == 1
        and broken["breaks"] == [f"ACME was bought on {TUE} with borrowed money: the account's cash was negative that day."]
    )
    detail = json.loads(fired["detail"])
    assert detail["breaks"] == 1 and detail["what"] == broken["breaks"]
    keeper = brief.desk_slice(cfg, "plan_keeper")
    item = next(i for i in keeper["sections"]["rules"] if i["metric_id"] == "plan.rules" and i["scope_id"] == "no-margin-buys")
    assert item["state"] == "broken" and item["unit"] == "flag" and "not a count" in item["meaning"]
    counted = next(i for i in keeper["sections"]["rules"] if i["metric_id"] == "plan.rule_breaks" and i["scope_id"] == "no-margin-buys")
    assert counted["value"] == 1 and "state" not in counted


# ---- One margin rate ----


def test_margin_rate_comes_from_the_setting_then_the_profile(cfg, monkeypatch):
    from desk.decisions import profile
    from desk.engine.cash import margin_rate

    monkeypatch.delenv("DESK_MARGIN_RATE_PCT", raising=False)
    monkeypatch.delattr(profile, "margin_rate", raising=False)
    assert margin_rate(cfg) == (None, "none")
    monkeypatch.setattr(profile, "active_profile", lambda cfg: type("P", (), {"data": {}})())
    monkeypatch.setattr(profile, "margin_rate", lambda data: {"rate_pct": 12, "source": "default"}, raising=False)
    assert margin_rate(cfg) == (12.0, "default")
    monkeypatch.setenv("DESK_MARGIN_RATE_PCT", "9.5")
    assert margin_rate(cfg) == (9.5, "env")


def test_a_default_margin_rate_prices_the_debit_as_modelled_without_a_warning(cfg, mirror, monkeypatch):
    from desk.decisions import profile

    monkeypatch.delenv("DESK_MARGIN_RATE_PCT", raising=False)
    monkeypatch.setattr(profile, "margin_rate", lambda data: {"rate_pct": 12, "source": "default"}, raising=False)
    seed(mirror, margin=True)
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    cost = conn.execute("SELECT value, quality FROM metric_values WHERE metric_id='margin.cost_month'").fetchone()
    health = conn.execute("SELECT status, detail FROM data_health WHERE check_name='margin_rate'").fetchone()
    conn.close()
    assert tuple(cost)[0] == 3.0 and cost["quality"] in ("modelled", "stale")
    assert health["status"] == "ok" and "typical 12%" in health["detail"]
    assert book(cfg, et(WED, 8, 30))["numbers"]["margin_cost_month"] == 3.0


def test_an_overnight_restate_never_rings_the_phone(cfg, mirror, monkeypatch):
    from desk.engine import triggers

    sent = []
    monkeypatch.setattr(triggers, "publish", lambda topic, title, body, priority, **kw: sent.append((title, priority)))
    seed(mirror, margin=True)
    at(monkeypatch, et(WED, 8, 20))
    run_daily(cfg)
    conn = connect(cfg.desk_db)
    found = [(TUE, "margin_debit", "portfolio", {"debit": 300.0}), (TUE, "daily_move", "ACME", {"ret_pct": 9.0, "dial_pct": 5.0})]
    conn.execute("DELETE FROM triggers")
    triggers.record(cfg, conn, found[:1], now=et(WED, 17, 20))
    triggers.record(cfg, conn, found[1:], now=et(THU, 1, 25))
    conn.close()
    assert ("Margin debit on the desk", "high") in sent and ("Big move today", "low") in sent
