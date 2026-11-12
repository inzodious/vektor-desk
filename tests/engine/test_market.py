from datetime import UTC, datetime

from desk.db import connect
from desk.engine import jobs, schema
from desk.engine.__main__ import run_holdings, run_market_backfill, run_quotes
from desk.engine.backfill import ASK_HOURS, ASK_WORDS, NO_PRICES, add_symbols, due, parked_until, usage
from desk.engine.live import live_view
from desk.engine.market import BENCHMARKS, QUALITY, last_trading_day, session
from tests.engine.helpers import closes_doc, position, snapshot

IND = "individual-1111"


class Res:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, quotes=None, bars=None, status=200):
        self.quotes = quotes or {}
        self.bars = bars or {}
        self.status = status
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if self.status is None:
            raise ConnectionError("no route")
        if self.status != 200:
            return Res(self.status, {})
        if "finnhub" in url:
            q = self.quotes.get(params["symbol"])
            return Res(200, q or {"c": 0, "t": 0})
        symbol = url.split("/daily/")[1].split("/")[0].upper()
        if symbol not in self.bars:
            return Res(404, {})
        return Res(200, [b for b in self.bars[symbol] if b["date"][:10] >= params["startDate"]])


def bar(day, close):
    return {
        "date": f"{day}T00:00:00.000Z",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adjClose": close,
        "volume": 1000,
        "divCash": 0.0,
        "splitFactor": 1.0,
    }


def et(y, m, d, hh, mm):
    from zoneinfo import ZoneInfo

    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def seed(m):
    m.put("snapshots", 1, snapshot(1, "2026-11-04T08:00", 1300.0, 2))
    m.put("positions", 1, position(1, 1, IND, "FXAIX", 5, 1000.0))
    m.put("positions", 2, position(2, 1, IND, "SPAXX", 300, 300.0, cash=True))
    m.put("priceCloses", "FXAIX_2026", closes_doc("FXAIX", 2026, [["2026-11-03", 195.0, 195.0], ["2026-11-04", 200.0, 200.0]]))
    m.pull("2026-11-04T22:00:00+00:00")


def test_market_clock():
    assert session(et(2026, 11, 9, 10, 0)).state == "open"
    assert session(et(2026, 11, 9, 8, 0)).state == "pre"
    assert session(et(2026, 11, 9, 17, 0)).state == "after"
    assert session(et(2026, 11, 9, 21, 0)).state == "closed"
    assert session(et(2026, 11, 7, 12, 0)).state == "closed"
    assert session(et(2026, 11, 26, 12, 0)).state == "closed"
    assert session(et(2026, 11, 27, 13, 30)).state == "after"
    assert not session(et(2028, 3, 1, 10, 0)).known_calendar
    assert last_trading_day(datetime(2026, 11, 8).date()).isoformat() == "2026-11-06"


def test_quotes_live_value_and_mutual_fund_fallback(cfg, mirror, monkeypatch):
    seed(mirror)
    run_holdings(cfg)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    http = FakeHttp(quotes={"SPY": {"c": 600.0, "pc": 590.0, "t": 1794240000}})
    now = et(2026, 11, 9, 10, 0)
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: now)
    result = run_quotes(cfg, http)
    assert result["ok"] and result["quotes"] == 2 and result["missing"] == []
    conn = connect(cfg.desk_db, readonly=True)
    src = dict(conn.execute("SELECT symbol, source FROM quotes_live").fetchall())
    assert src == {"SPY": "finnhub", "FXAIX": "close"}
    view = live_view(conn, now=now)
    conn.close()
    assert view["state"] == "open" and view["value"] == 1300.0 and view["day_change"] == 0.0 and view["quality"] == "ok"
    assert "SPY" in view["benchmarks"]


def test_quotes_skip_when_closed_and_throttle_extended_hours(cfg, mirror, monkeypatch):
    seed(mirror)
    run_holdings(cfg)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    http = FakeHttp()
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 7, 12, 0))
    assert run_quotes(cfg, http)["skipped"].startswith("market closed")
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 9, 7, 0))
    pre = run_quotes(cfg, http)
    assert pre["quotes"] == 1 and pre["missing"] == ["SPY"]
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 9, 7, 10))
    assert "refreshed" in run_quotes(cfg, http)["skipped"]


def test_live_view_is_stale_when_quotes_are_old(cfg, mirror, monkeypatch):
    seed(mirror)
    run_holdings(cfg)
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 9, 10, 0))
    run_quotes(cfg, FakeHttp())
    conn = connect(cfg.desk_db, readonly=True)
    assert live_view(conn, now=et(2026, 11, 9, 11, 0))["quality"] == "stale"
    conn.close()


def test_api_live(cfg, mirror, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/live").json()["quality"] == "insufficient_history"
    seed(mirror)
    run_holdings(cfg)
    body = client.get("/api/live").json()
    assert body["value"] == 1300.0 and body["rows"][0]["symbol"] == "FXAIX"


def test_backfill_needs_a_key(cfg, monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    result = run_market_backfill(cfg, FakeHttp())
    assert result["ok"] is False and result["error"] == "The Tiingo key is not set. Add it in Settings, Data, Keys."


def test_backfill_fetches_history_then_tops_up_and_respects_caps(cfg, mirror, monkeypatch):
    seed(mirror)
    run_holdings(cfg)
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("DESK_TIINGO_MONTHLY_SYMBOLS", "3")
    monkeypatch.setenv("DESK_TIINGO_HOURLY", "40")
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    bars = {s: [bar(d, 100.0 + i) for i, d in enumerate(days)] for s in ("SPY", "VTI", "VXUS", "AGG")}
    http = FakeHttp(bars=bars)
    now = datetime(2026, 11, 9, 6, 10, tzinfo=UTC)
    monkeypatch.setattr("desk.engine.backfill.datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: now)}))
    first = run_market_backfill(cfg, http)
    assert len(first["fetched"]) + len(first["errors"]) + len(first["unpriced"]) == 3 and first["skipped_for_month_cap"] > 0
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    assert usage(conn, now)["month_symbols"] == 3
    assert conn.execute("SELECT count(*) FROM price_bars").fetchone()[0] == 5 * len(first["fetched"])
    assert http.calls[0][1]["startDate"] == "2005-01-01"
    assert add_symbols(conn, ["SPY", "NEWCO"], "held") == 2
    assert conn.execute("SELECT role, priority FROM market_symbols WHERE symbol='SPY'").fetchone()[:] == ("held", 0)
    conn.close()


def test_the_scanners_names_are_refetched_daily_and_scanned_again(cfg, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    add_symbols(conn, ["NVDA", "OLDCO"], "past")
    with conn:
        conn.execute("UPDATE market_symbols SET first_bar='2026-01-02', last_bar='2026-11-09', fetched_at='2026-11-10T06:10:00+00:00'")
    now = datetime(2026, 11, 12, 9, 10, tzinfo=UTC)
    assert [r["symbol"] for r in due(conn, now)] == ["NVDA"]
    assert [r["symbol"] for r in due(conn, datetime(2027, 2, 12, 9, 10, tzinfo=UTC))] == ["NVDA", "OLDCO"]
    monkeypatch.setattr("desk.engine.backfill.datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: now)}))
    http = FakeHttp(bars={"NVDA": [bar(d, 100.0) for d in ("2026-11-09", "2026-11-10", "2026-11-11")]})
    first = run_market_backfill(cfg, http)
    assert first["fetched"] == ["NVDA"] and first["discounts"]["ok"] is True
    assert len(http.calls) == len(set(BENCHMARKS) | set(QUALITY)) <= 40
    row = conn.execute("SELECT role, priority, last_bar FROM market_symbols WHERE symbol='NVDA'").fetchone()
    assert row[:] == ("past", 3, "2026-11-11")
    assert conn.execute("SELECT count(*) FROM market_symbols WHERE role='universe'").fetchone()[0] == len(set(QUALITY) - set(BENCHMARKS) - {"NVDA"})
    again = run_market_backfill(cfg, http)
    assert again["fetched"] == [] and "discounts" not in again
    conn.close()


def test_backfill_stops_on_rate_limit(cfg, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    result = run_market_backfill(cfg, FakeHttp(status=429))
    assert not result["ok"] and len(result["errors"]) == 1 and "rate limit" in result["errors"][0]


NOV_12 = datetime(2026, 11, 12, 11, 10, tzinfo=UTC)
WEEK = ("2026-11-09", "2026-11-10", "2026-11-11")


def ledger(cfg, rows):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    for symbol, role, last_bar, fetched_at, error in rows:
        add_symbols(conn, [symbol], role)
        with conn:
            conn.execute(
                "UPDATE market_symbols SET first_bar=?, last_bar=?, fetched_at=?, error=? WHERE symbol=?", ("2026-01-02", last_bar, fetched_at, error, symbol)
            )
    return conn


def at(monkeypatch, now):
    monkeypatch.setattr("desk.engine.backfill.datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: now)}))


def everything_else():
    return {s: [bar(d, 100.0) for d in WEEK] for s in set(BENCHMARKS) | set(QUALITY)}


def test_only_a_name_tiingo_never_priced_is_parked_and_a_held_one_for_under_a_day(cfg, monkeypatch):
    hour_ago, two_days = "2026-11-12T10:10:00+00:00", "2026-11-10T10:10:00+00:00"
    conn = ledger(
        cfg,
        [
            ("FUNDA", "held", "2026-11-10", hour_ago, "Tiingo rate limit"),
            ("FUNDB", "held", "2026-11-10", hour_ago, "Tiingo 500 for FUNDB"),
            ("FUNDC", "held", "2026-11-10", hour_ago, f"{NO_PRICES} for FUNDC"),
            ("FUNDD", "held", None, hour_ago, f"{NO_PRICES} for FUNDD"),
            ("WATCH", "watch", None, two_days, f"{NO_PRICES} for WATCH"),
            ("ERRW", "watch", "2026-11-10", two_days, "Tiingo did not answer for ERRW"),
        ],
    )
    assert [r["symbol"] for r in due(conn, NOV_12)] == ["FUNDA", "FUNDB", "FUNDC", "ERRW"]
    rows = {r["symbol"]: r for r in conn.execute("SELECT * FROM market_symbols")}
    assert parked_until(rows["FUNDA"]) is None and parked_until(rows["FUNDC"]) is None and parked_until(rows["ERRW"]) is None
    assert parked_until(rows["FUNDD"]).isoformat() == "2026-11-13T06:10:00+00:00"
    assert parked_until(rows["WATCH"]).isoformat() == "2026-11-17T10:10:00+00:00"
    assert "FUNDD" in [r["symbol"] for r in due(conn, datetime(2026, 11, 13, 6, 10, tzinfo=UTC))]
    assert "WATCH" not in [r["symbol"] for r in due(conn, datetime(2026, 11, 16, 6, 10, tzinfo=UTC))]
    assert "WATCH" in [r["symbol"] for r in due(conn, datetime(2026, 11, 17, 10, 10, tzinfo=UTC))]
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    at(monkeypatch, NOV_12)
    funds = {s: [bar(d, 50.0) for d in WEEK] for s in ("FUNDA", "FUNDB", "FUNDC")}
    cleared = run_market_backfill(cfg, FakeHttp(bars=everything_else() | funds))
    assert {"FUNDA", "FUNDB", "FUNDC"} <= set(cleared["advanced"]) and cleared["unpriced"] == ["ERRW"] and cleared["errors"] == []
    assert conn.execute("SELECT count(*) FROM market_symbols WHERE symbol LIKE 'FUND_' AND error IS NULL AND last_bar='2026-11-11'").fetchone()[0] == 3
    conn.close()


def test_the_result_names_what_advanced_and_what_answered_with_nothing_new(cfg, monkeypatch):
    conn = ledger(cfg, [("FUNDA", "held", "2026-11-10", None, None), ("FUNDB", "held", "2026-11-10", None, None), ("ETFA", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    at(monkeypatch, NOV_12)
    bars = everything_else() | {"ETFA": [bar(d, 30.0) for d in WEEK], "FUNDA": [bar(d, 50.0) for d in WEEK[:2]], "FUNDB": [bar(d, 20.0) for d in WEEK[:2]]}
    http = FakeHttp(bars=bars)
    first = run_market_backfill(cfg, http)
    assert first["ok"] and "ETFA" in first["advanced"] and first["behind"] == ["FUNDA", "FUNDB"] and first["left"] == 0
    assert first["detail"].startswith(f"Asked Tiingo for {len(http.calls)} names. FUNDA and FUNDB answered with nothing new for 2026-11-11. New bars for ")
    assert first["detail"].endswith(" more.") and len(first["detail"]) < 300
    asked = len(http.calls)
    again = run_market_backfill(cfg, http)
    assert [c[0].split("/daily/")[1].split("/")[0].upper() for c in http.calls[asked:]] == ["FUNDA", "FUNDB"]
    assert again["advanced"] == [] and "discounts" not in again
    assert again["detail"] == "Asked Tiingo for 2 names. FUNDA and FUNDB answered with nothing new for 2026-11-11."
    http.bars["FUNDA"].append(bar("2026-11-11", 51.0))
    http.bars["FUNDB"].append(bar("2026-11-11", 21.0))
    landed = run_market_backfill(cfg, http)
    assert landed["advanced"] == ["FUNDA", "FUNDB"] and landed["behind"] == [] and landed["detail"] == "Asked Tiingo for 2 names. New bars for FUNDA and FUNDB."
    asked = len(http.calls)
    quiet = run_market_backfill(cfg, http)
    assert len(http.calls) == asked and quiet["ok"] and quiet["fetched"] == [] and quiet["detail"] == "Nothing was behind, so Tiingo was not asked."
    conn.close()


def test_a_run_tiingo_does_not_answer_fails_plainly_and_asks_again_next_time(cfg, monkeypatch):
    conn = ledger(cfg, [("FUNDA", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    at(monkeypatch, NOV_12)
    down = FakeHttp(status=None)
    result = run_market_backfill(cfg, down)
    assert not result["ok"] and len(down.calls) == 1 and result["errors"] == ["FUNDA: Tiingo did not answer for FUNDA"] and result["left"] > 0
    assert (
        result["detail"].startswith("Asked Tiingo for 1 name. Failed: FUNDA: Tiingo did not answer for FUNDA.")
        and "more wait for a later run" in result["detail"]
    )
    assert "FUNDA" in [r["symbol"] for r in due(conn, NOV_12)]
    conn.close()


def test_the_backfill_view_shows_every_name_and_why_it_waits(cfg, app_client, monkeypatch):
    client = app_client(packages=["engine"])
    empty = client.get("/api/engine/backfill").json()
    assert empty["symbols"] == [] and empty["last_run"] is None and empty["asks"] == ASK_WORDS
    conn = ledger(cfg, [("FUNDA", "held", "2026-11-10", None, None), ("FUNDD", "held", None, "2026-11-12T10:10:00+00:00", f"{NO_PRICES} for FUNDD")])
    conn.close()
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    at(monkeypatch, NOV_12)
    run_market_backfill(cfg, FakeHttp(bars=everything_else() | {"FUNDA": [bar(d, 50.0) for d in WEEK[:2]]}))
    body = client.get("/api/engine/backfill").json()
    rows = {r["symbol"]: r for r in body["symbols"]}
    assert set(rows["FUNDA"]) == {"symbol", "role", "priority", "daily", "first_bar", "last_bar", "fetched_at", "error", "parked_until", "behind", "due"}
    assert rows["FUNDA"] | {"first_bar": None} == {
        "symbol": "FUNDA",
        "role": "held",
        "priority": 0,
        "daily": True,
        "first_bar": None,
        "last_bar": "2026-11-10",
        "fetched_at": "2026-11-12T11:10:00+00:00",
        "error": None,
        "parked_until": None,
        "behind": True,
        "due": True,
    }
    assert rows["FUNDD"]["parked_until"] == "2026-11-13T06:10:00+00:00" and rows["FUNDD"]["due"] is False and rows["FUNDD"]["behind"] is True
    assert body["target"] == "2026-11-11" and body["used"]["hour"] == len(body["symbols"]) - 1
    assert (
        body["last_run"]["ok"] is True
        and body["last_run"]["behind"] == ["FUNDA"]
        and "FUNDA answered with nothing new for 2026-11-11." in body["last_run"]["detail"]
    )


def test_the_backfill_schedule_matches_the_words_health_uses():
    lines = [j if isinstance(j, tuple) else (j["schedule"], j["command"]) for j in jobs.JOBS]
    schedule = next(s for s, command in lines if command.endswith(" backfill"))
    assert schedule == f"10 {ASK_HOURS[0]}-{ASK_HOURS[1]} * * *" and ASK_WORDS == "every hour from 1:10 AM to 12:10 PM ET"


def test_stale_quotes_page_ops_during_market_hours(cfg, mirror, monkeypatch):
    seed(mirror)
    run_holdings(cfg)
    sent = []
    monkeypatch.setattr("desk.engine.__main__.publish", lambda topic, title, body="", priority="default", **kw: sent.append((topic, title, kw["key"])))
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 9, 10, 0))
    run_quotes(cfg, FakeHttp())
    assert [s[:2] for s in sent] == [("ops", "Live quotes are stale")]
    monkeypatch.setattr("desk.engine.live.now_utc", lambda: et(2026, 11, 8, 10, 0))
    run_quotes(cfg, FakeHttp())
    assert len(sent) == 1
