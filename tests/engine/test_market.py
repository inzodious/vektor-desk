from datetime import UTC, datetime

from desk.db import connect
from desk.engine import schema
from desk.engine.__main__ import run_holdings, run_market_backfill, run_quotes
from desk.engine.backfill import add_symbols, usage
from desk.engine.live import live_view
from desk.engine.market import last_trading_day, session
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
    assert view["state"] == "open" and view["value"] == 1300.0 and view["day_change"] == 25.0 and view["quality"] == "ok"
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
    assert run_market_backfill(cfg, FakeHttp())["ok"] is False


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
    assert len(first["fetched"]) + len(first["errors"]) == 3 and first["skipped_for_month_cap"] > 0
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    assert usage(conn, now)["month_symbols"] == 3
    assert conn.execute("SELECT count(*) FROM price_bars").fetchone()[0] == 5 * len(first["fetched"])
    assert http.calls[0][1]["startDate"] == "2005-01-01"
    assert add_symbols(conn, ["SPY", "NEWCO"], "held") == 2
    assert conn.execute("SELECT role, priority FROM market_symbols WHERE symbol='SPY'").fetchone()[:] == ("held", 0)
    conn.close()


def test_backfill_stops_on_rate_limit(cfg, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    result = run_market_backfill(cfg, FakeHttp(status=429))
    assert not result["ok"] and len(result["errors"]) == 1 and "rate limit" in result["errors"][0]


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
