from datetime import UTC, date, datetime

from desk.engine import rapid
from desk.engine.__main__ import run_market_backfill
from desk.engine.market import ProviderError
from tests.engine.test_market import NOV_12, WEEK, FakeHttp, Res, at, bar, ledger

EPOCH = {"2026-11-09": 1794234600, "2026-11-10": 1794321000, "2026-11-11": 1794407400}


def av_body(days, close):
    rows = {}
    for d in days:
        rows[d] = {
            "1. open": str(close),
            "2. high": str(close),
            "3. low": str(close),
            "4. close": str(close),
            "5. adjusted close": str(close - 1),
            "6. volume": "1000",
            "7. dividend amount": "0.0000",
            "8. split coefficient": "1.0",
        }
    return {"Meta Data": {}, "Time Series (Daily)": rows}


class Providers(FakeHttp):
    def __init__(self, tiingo=None, av=None, fmp=None, yh=None, av_note=False):
        super().__init__(bars=tiingo or {})
        self.av, self.fmp, self.yh, self.av_note = av or set(), fmp or set(), yh or set(), av_note

    def get(self, url, params=None, headers=None, timeout=None):
        if "rapidapi" not in url:
            return super().get(url, params, headers, timeout)
        self.calls.append((url, params))
        assert headers["X-RapidAPI-Key"] == "rk" and headers["X-RapidAPI-Host"] in url
        if "alpha-vantage" in url:
            if self.av_note:
                return Res(200, {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 5 requests per minute."})
            sym = params["symbol"]
            return Res(200, av_body(WEEK, 40.0) if sym in self.av else {"Error Message": "Invalid API call."})
        if "financial-modeling-prep" in url:
            sym = url.rsplit("/", 1)[1]
            if sym not in self.fmp:
                return Res(200, {})
            rows = [{"date": d, "open": 41, "high": 41, "low": 41, "close": 41, "adjClose": 41, "volume": 9} for d in reversed(WEEK)]
            return Res(200, {"symbol": sym, "historical": rows})
        sym = params["symbol"]
        if sym not in self.yh:
            return Res(404, {})
        row = {"open": 42, "high": 42, "low": 42, "close": 42, "volume": 9, "adjclose": 42}
        return Res(200, {"meta": {}, "body": {str(EPOCH[d]): row | {"date_utc": EPOCH[d]} for d in WEEK}})


def hosts(http):
    return [c[0].split("//")[1].split(".")[0] for c in http.calls if "rapidapi" in c[0]]


# ---- Reading each provider ----


def test_each_provider_reads_into_the_same_bar_shape():
    day = date(2026, 11, 12)
    av = rapid.av_daily(Providers(av={"ACME"}), "ACME", "rk", "2026-11-10", today=day)
    assert [b["date"] for b in av] == ["2026-11-10", "2026-11-11"]
    prices = {"open": 40.0, "high": 40.0, "low": 40.0, "close": 40.0, "adj_close": 39.0}
    assert av[0] == {"date": "2026-11-10", **prices, "volume": 1000.0, "div_cash": 0.0, "split_factor": 1.0}
    http = Providers(av={"ACME"})
    rapid.av_daily(http, "ACME", "rk", "2005-01-01", today=day)
    rapid.av_daily(http, "ACME", "rk", "2026-11-01", today=day)
    assert [c[1]["outputsize"] for c in http.calls] == ["full", "compact"] and http.calls[0][1]["function"] == "TIME_SERIES_DAILY_ADJUSTED"
    fmp = rapid.fmp_daily(Providers(fmp={"ACME"}), "ACME", "rk", "2026-11-10")
    assert [(b["date"], b["close"], b["div_cash"], b["split_factor"]) for b in fmp] == [("2026-11-10", 41.0, 0.0, 1.0), ("2026-11-11", 41.0, 0.0, 1.0)]
    yh = rapid.yh_daily(Providers(yh={"ACME"}), "ACME", "rk", "2026-11-10")
    assert [(b["date"], b["adj_close"]) for b in yh] == [("2026-11-10", 42.0), ("2026-11-11", 42.0)]
    for http, err in ((Providers(av_note=True), "Alpha Vantage rate limit"), (Providers(), "Alpha Vantage has no daily prices for ZZZ")):
        try:
            rapid.av_daily(http, "ZZZ", "rk", "2026-11-10", today=day)
        except ProviderError as e:
            assert str(e) == err
        else:
            raise AssertionError(err)


# ---- Filling in for Tiingo ----


def test_without_the_rapidapi_key_nothing_changes_and_no_backup_is_asked(cfg, monkeypatch):
    conn = ledger(cfg, [("ACME", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    at(monkeypatch, NOV_12)
    monkeypatch.setenv("DESK_TIINGO_HOURLY", "0")
    http = Providers(av={"ACME"})
    out = run_market_backfill(cfg, http)
    assert hosts(http) == [] and out["backups"] == {} and out["fetched"] == [] and out["left"] > 0
    conn.close()


def test_tiingos_hourly_cap_just_waits_an_hour_and_spends_no_backup_calls(cfg, monkeypatch):
    conn = ledger(cfg, [("HELDA", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    at(monkeypatch, NOV_12)
    monkeypatch.setenv("DESK_TIINGO_HOURLY", "0")
    http = Providers(av={"HELDA"})
    out = run_market_backfill(cfg, http)
    assert http.calls == [] and out["backups"] == {} and out["left"] > 0
    conn.close()


def test_when_tiingo_is_capped_alpha_vantage_fills_in_then_fmp_for_recent_days_and_yh_only_for_held_names(cfg, monkeypatch):
    conn = ledger(
        cfg,
        [
            ("HELDA", "held", "2026-11-10", None, None),
            ("HELDB", "held", "2026-11-10", None, None),
            ("WATCHA", "watch", "2026-11-10", None, None),
            ("NEWW", "watch", None, None, None),
        ],
    )
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    at(monkeypatch, NOV_12)
    monkeypatch.setenv("DESK_TIINGO_DAILY", "0")
    for name in ("ALPHAVANTAGE", "FMP", "YHFINANCE"):
        monkeypatch.setenv(f"DESK_{name}_PER_RUN", "1")
    http = Providers(av={"HELDA"}, fmp={"HELDB"}, yh={"WATCHA", "HELDB"})
    out = run_market_backfill(cfg, http)
    assert [c for c in http.calls if "tiingo" in c[0]] == []
    assert out["backups"] == {"Alpha Vantage": ["HELDA"], "FMP": ["HELDB"]} and out["fetched"] == ["HELDA", "HELDB"]
    assert "Alpha Vantage filled in for HELDA. FMP filled in for HELDB." in out["detail"] and "Asked Tiingo" not in out["detail"]
    bars = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT symbol, max(date), max(close) FROM price_bars GROUP BY symbol")}
    assert bars == {"HELDA": ("2026-11-11", 40.0), "HELDB": ("2026-11-11", 41.0)}
    calls = dict(conn.execute("SELECT provider, count(*) FROM api_calls GROUP BY provider").fetchall())
    assert calls == {"alphavantage": 1, "fmp": 1}
    rows = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM market_symbols WHERE symbol IN ('HELDA', 'HELDB', 'WATCHA', 'NEWW')")}
    assert rows["HELDA"]["last_bar"] == "2026-11-11" and rows["HELDA"]["error"] is None and rows["WATCHA"]["fetched_at"] is None
    conn.close()


def test_a_backup_stops_for_the_run_at_its_rate_limit_and_counts_against_its_daily_cap(cfg, monkeypatch):
    conn = ledger(cfg, [("HELDA", "held", "2026-11-10", None, None), ("HELDB", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    at(monkeypatch, NOV_12)
    monkeypatch.setenv("DESK_TIINGO_DAILY", "0")
    monkeypatch.setenv("DESK_FMP_DAILY", "0")
    monkeypatch.setenv("DESK_YHFINANCE_MONTHLY", "0")
    http = Providers(av_note=True)
    out = run_market_backfill(cfg, http)
    assert hosts(http) == ["alpha-vantage"] and out["backups"] == {}
    assert out["backup_use"]["alphavantage"]["used"]["day"] == 1 and out["backup_use"]["fmp"]["limits"]["day"] == 0
    monkeypatch.setenv("DESK_ALPHAVANTAGE_DAILY", "1")
    again = Providers(av={"HELDA", "HELDB"})
    run_market_backfill(cfg, again)
    assert hosts(again) == []
    conn.close()


def test_tiingo_still_goes_first_and_a_backup_only_answers_what_tiingo_could_not(cfg, monkeypatch):
    conn = ledger(cfg, [("HELDA", "held", "2026-11-10", None, None), ("GONE", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    at(monkeypatch, NOV_12)
    tiingo = {"HELDA": [bar(d, 50.0) for d in WEEK]} | {s: [bar(d, 1.0) for d in WEEK] for s in ("SPY",)}
    http = Providers(tiingo=tiingo, av={"GONE"})
    out = run_market_backfill(cfg, http)
    assert "HELDA" in out["fetched"] and out["backups"]["Alpha Vantage"][0] == "GONE"
    assert all(c[1]["symbol"] != "HELDA" for c in http.calls if "rapidapi" in c[0])
    assert conn.execute("SELECT close FROM price_bars WHERE symbol='HELDA' AND date='2026-11-11'").fetchone()[0] == 50.0
    assert conn.execute("SELECT error FROM market_symbols WHERE symbol='GONE'").fetchone()[0] is None
    conn.close()


def test_the_key_is_one_the_box_settings_accept():
    from desk import boxkeys

    assert boxkeys.KNOWN[rapid.KEY].file == "desk.env" and boxkeys.KNOWN[rapid.KEY].secret
    assert datetime.fromtimestamp(EPOCH["2026-11-10"], UTC).date().isoformat() == "2026-11-10"


# ---- Earnings history ----


class Earnings(FakeHttp):
    def __init__(self, limited_after=None):
        super().__init__()
        self.limited_after = limited_after

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if self.limited_after is not None and len(self.calls) > self.limited_after:
            return Res(200, {"Information": "You have reached your daily limit."})
        if params["function"] == "EARNINGS":
            rows = [
                {"fiscalDateEnding": "2026-06-30", "reportedDate": "2026-07-30", "reportedEPS": "1.5", "estimatedEPS": "1.4"},
                {"fiscalDateEnding": "2026-09-30", "reportedDate": "2026-10-29", "reportedEPS": "1.6", "estimatedEPS": "None"},
            ]
            return Res(200, {"symbol": params["symbol"], "quarterlyEarnings": rows})
        reports = [{"fiscalDateEnding": "2026-09-30", "totalRevenue": "1000", "grossProfit": "400", "operatingIncome": "300", "netIncome": "250"}]
        return Res(200, {"symbol": params["symbol"], "quarterlyReports": reports})


def test_earnings_history_loads_each_quarter_with_the_day_it_was_reported_inside_alpha_vantages_day(cfg, monkeypatch):
    from desk.engine import avhistory
    from desk.engine.__main__ import run_av_history

    conn = ledger(cfg, [("HELDA", "held", "2026-11-10", None, None), ("PUBB", "public", None, None, None), ("WATC", "watch", None, None, None)])
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    assert run_av_history(cfg, Earnings())["skipped"].startswith("The RapidAPI key is not set")
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    monkeypatch.setenv("DESK_AV_HISTORY_CALLS", "4")
    first = run_av_history(cfg, Earnings())
    assert first["ok"] and first["loaded"] == ["HELDA", "WATC"] and first["left"] >= 0 and first["calls"] == 4
    rows = [tuple(r) for r in conn.execute("SELECT symbol, period_end, reported, eps, eps_estimate, revenue, net_income FROM av_quarters WHERE symbol='HELDA'")]
    assert rows == [("HELDA", "2026-06-30", "2026-07-30", 1.5, 1.4, None, None), ("HELDA", "2026-09-30", "2026-10-29", 1.6, None, 1000.0, 250.0)]
    assert conn.execute("SELECT count(*) FROM api_calls WHERE provider='alphavantage'").fetchone()[0] == 4
    assert avhistory.wanted(conn, datetime.now(UTC)) == []
    monkeypatch.setenv("DESK_AV_HISTORY_CALLS", "100")
    with conn:
        conn.executemany("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('alphavantage', ?, 'X', 1)", [(datetime.now(UTC).isoformat(),)] * 489)
    assert avhistory._budget(conn, datetime.now(UTC)) == 0
    conn.close()


def test_a_daily_limit_answer_stops_the_night_and_the_name_is_tried_again_later(cfg, monkeypatch):
    from desk.engine.__main__ import run_av_history

    conn = ledger(cfg, [("HELDA", "held", "2026-11-10", None, None), ("HELDB", "held", "2026-11-10", None, None)])
    monkeypatch.setenv("RAPIDAPI_KEY", "rk")
    http = Earnings(limited_after=2)
    out = run_av_history(cfg, http)
    assert out["loaded"] == ["HELDA"] and out["errors"] == ["HELDB: Alpha Vantage rate limit"] and len(http.calls) == 3
    assert conn.execute("SELECT error FROM av_fetches WHERE symbol='HELDB'").fetchone()[0] == "Alpha Vantage rate limit"
    conn.close()
