from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.engine import brief, core, triggers
from desk.engine.__main__ import run_holdings, run_research
from desk.engine.research import macro, signals
from desk.engine.source import open_mirror
from tests.engine.test_preflight import seed

NOW = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)

TICKERS = {"0": {"cik_str": 1234, "ticker": "ACME", "title": "Acme Corp"}, "1": {"cik_str": 99, "ticker": "OTHER", "title": "Other"}}
SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-23-000003"],
            "filingDate": ["2026-10-15", "2026-08-01", "2023-02-01"],
            "reportDate": ["2026-10-13", "2026-06-30", "2022-12-31"],
            "form": ["4", "10-Q", "10-K"],
            "primaryDocument": ["form4.xml", "acme-10q.htm", "acme-10k.htm"],
            "primaryDocDescription": ["", "10-Q", "10-K"],
        }
    }
}


def fy(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "fy": int(end[:4]), "fp": "FY", "form": "10-K", "filed": filed}


FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        fy("2024-01-01", "2024-12-31", 1000.0, "2025-02-10"),
                        fy("2025-01-01", "2025-12-31", 1200.0, "2026-02-10"),
                        {"start": "2026-04-01", "end": "2026-06-30", "val": 300.0, "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-08-01"},
                    ]
                }
            },
            "NetIncomeLoss": {"units": {"USD": [fy("2025-01-01", "2025-12-31", 120.0, "2026-02-10")]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [{"end": "2025-07-31", "val": 100.0, "form": "10-Q"}, {"end": "2026-07-31", "val": 110.0, "form": "10-Q"}]}
            }
        },
    }
}
FRED = {
    "DGS10": [{"date": "2026-11-03", "value": "4.20"}, {"date": "2026-11-04", "value": "."}],
    "DGS2": [{"date": "2026-11-03", "value": "4.00"}],
    "DGS3MO": [{"date": "2026-11-03", "value": "4.10"}],
    "CPIAUCSL": [{"date": "2025-10-01", "value": "300"}, {"date": "2026-10-01", "value": "309"}],
    "BAMLH0A0HYM2": [],
    "VIXCLS": [{"date": "2026-11-03", "value": "18.5"}],
}


def earn(day, act, est, rev_act=None, rev_est=None, quarter=3):
    return {
        "date": day,
        "epsActual": act,
        "epsEstimate": est,
        "revenueActual": rev_act,
        "revenueEstimate": rev_est,
        "hour": "amc",
        "quarter": quarter,
        "year": 2026,
    }


def trade(name, change, price, code, day, filed):
    return {
        "name": name,
        "change": change,
        "share": abs(change),
        "transactionPrice": price,
        "transactionCode": code,
        "transactionDate": day,
        "filingDate": filed,
    }


EARNINGS = {"earningsCalendar": [earn("2026-11-04", 1.1, 1.0, 330.0, 300.0), earn("2027-02-01", None, 1.2, quarter=4)]}
INSIDERS = {
    "data": [
        trade("CEO", -1000, 20.0, "S", "2026-10-01", "2026-10-03"),
        trade("Director", 500, 19.0, "P", "2026-09-15", "2026-09-16"),
        trade("CFO", 200, 0.0, "M", "2026-09-20", "2026-09-21"),
        trade("Old", 9000, 10.0, "P", "2026-01-02", "2026-01-03"),
    ]
}


class Res:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class Http:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "sec.gov" in url and not (headers or {}).get("User-Agent"):
            return Res(403, {})
        if url.endswith("company_tickers.json"):
            return Res(200, TICKERS)
        if "submissions/CIK0000001234" in url:
            return Res(200, SUBMISSIONS)
        if "companyfacts/CIK0000001234" in url:
            return Res(200, FACTS)
        if "stlouisfed" in url:
            return Res(200, {"observations": FRED[params["series_id"]]})
        if "calendar/earnings" in url:
            return Res(200, EARNINGS)
        if "insider-transactions" in url:
            return Res(200, INSIDERS)
        return Res(404, {})


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "vektor-desk test")
    monkeypatch.setenv("FRED_API_KEY", "f")
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr("desk.engine.research.SEC_GAP", 0)


def fetched(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    http = Http()
    return run_research(cfg, http), http


# ---- Fetchers ----


def test_fetchers_skip_without_keys(cfg, mirror, monkeypatch):
    for name in ("DESK_SEC_USER_AGENT", "FRED_API_KEY", "FINNHUB_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    result, http = fetched(cfg, mirror)
    assert result["symbols"] == ["ACME"] and http.calls == []
    assert all("not set" in result[k]["skipped"] for k in ("edgar", "fred", "finnhub"))


def test_fetchers_store_filings_facts_macro_earnings_and_insiders(cfg, mirror, keys):
    result, http = fetched(cfg, mirror)
    assert result["edgar"]["symbols"] == ["ACME"] and result["fred"]["series"]["DGS10"] == 1 and result["finnhub"]["symbols"] == ["ACME"]
    conn = connect(cfg.desk_db, readonly=True)
    try:
        filings = [(r["form"], r["url"]) for r in conn.execute("SELECT * FROM filings ORDER BY filed DESC")]
        concepts = {r[0] for r in conn.execute("SELECT DISTINCT concept FROM fundamentals")}
        insiders = conn.execute("SELECT count(*) FROM insider_trades").fetchone()[0]
    finally:
        conn.close()
    assert filings == [
        ("4", "https://www.sec.gov/Archives/edgar/data/1234/000126000001/form4.xml"),
        ("10-Q", "https://www.sec.gov/Archives/edgar/data/1234/000126000002/acme-10q.htm"),
    ]
    assert concepts == {"revenue", "net_income", "shares_outstanding"} and insiders == 4
    calls = len(http.calls)
    run_research(cfg, http)
    assert len(http.calls) == calls


def test_signals_and_macro(cfg, mirror, keys):
    fetched(cfg, mirror)
    conn = connect(cfg.desk_db, readonly=True)
    try:
        sig = {(m, w): v for m, _, v, _, w, _ in signals(conn, ["ACME"], "2026-11-04", "2026-11-03")}
        mac = {m: v for m, _, v, _ in macro(conn, "2026-11-04")}
    finally:
        conn.close()
    assert sig[("sig.earnings_days", "now")] == 89 and sig[("sig.eps_surprise", "now")] == pytest.approx(10.0)
    assert sig[("sig.revenue_surprise", "now")] == pytest.approx(10.0) and sig[("sig.earnings_reported", "now")] == 1
    assert sig[("sig.insider_net", "90D")] == -10500.0 and sig[("sig.insider_buyers", "90D")] == 1
    assert sig[("sig.dilution", "1Y")] == pytest.approx(10.0)
    assert sig[("fund.revenue_growth", "FY")] == pytest.approx(20.0) and sig[("fund.net_margin", "FY")] == pytest.approx(10.0)
    assert mac["macro.y10"] == 4.2 and mac["macro.curve_10y2y"] == pytest.approx(0.2) and mac["macro.cpi_yoy"] == pytest.approx(3.0)
    assert mac["macro.vix"] == 18.5 and "macro.hy_spread" not in mac


def test_core_signals_earnings_trigger_brief_and_api(cfg, mirror, keys, monkeypatch, app_client):
    monkeypatch.setattr(triggers, "publish", lambda *a, **k: True)
    fetched(cfg, mirror)
    desk = connect(cfg.desk_db)
    with desk:
        desk.execute("INSERT INTO metric_values VALUES ('value.market', 'portfolio', 'all', 'now', '2026-11-03', 1.0, 'usd', NULL, 'ok', 'x')")
    mirror_conn = open_mirror(cfg)
    try:
        stored = core.store(desk, core.compute(cfg, mirror_conn, desk, now=NOW))
        fired = triggers.run(cfg, desk, stored["as_of"], now=NOW)
    finally:
        mirror_conn.close()
        desk.close()
    assert stored["checks"]["research"] == "ok" and "earnings" in fired["kinds"]
    research = brief.desk_slice(cfg, "research")
    assert {i["metric_id"] for i in research["sections"]["signals"]} >= {"sig.dilution", "sig.insider_net", "sig.earnings_days"}
    assert [f["form"] for f in research["sections"]["filings"]] == ["4", "10-Q"]
    assert {i["metric_id"] for i in brief.desk_slice(cfg, "risk")["sections"]["macro"]} >= {"macro.y10", "macro.curve_10y2y"}
    client = app_client(packages=["engine"])
    body = client.get("/api/engine/research", params={"symbol": "acme"}).json()
    assert len(body["filings"]) == 2 and body["fundamentals"]["revenue"][0]["value"] == 300.0 and len(body["insiders"]) == 4
    assert {s["metric_id"] for s in body["signals"]} >= {"fund.revenue_growth", "sig.eps_surprise"}
    assert client.get("/api/engine/macro", params={"start": "2026-01-01"}).json()["series"]["CPIAUCSL"] == [{"date": "2026-10-01", "value": 309.0}]


def test_empty_research_endpoints(cfg, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/research", params={"symbol": "ACME"}).json()["filings"] == []
    assert client.get("/api/engine/macro").json()["series"] == {}
