from datetime import UTC, date, datetime, timedelta

import pytest

from desk.db import connect
from desk.engine import core, lookthrough, risk
from desk.engine.__main__ import run_holdings, run_lookthrough
from desk.engine.compare import CompareError, compare
from desk.engine.source import open_mirror
from tests.engine.test_preflight import IND, seed

NOW = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)
DEMO_NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


def run_core(cfg, now=NOW):
    mirror, desk = open_mirror(cfg), connect(cfg.desk_db)
    try:
        stored = core.store(desk, core.compute(cfg, mirror, desk, now=now))
        rows = desk.execute("SELECT * FROM metric_values WHERE as_of=?", (stored["as_of"],)).fetchall()
    finally:
        desk.close()
        mirror.close()
    return stored, {(r["metric_id"], r["scope_id"], r["window"]): (r["value"], r["quality"]) for r in rows}


def weekdays(start: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def bars(cfg, symbol, days, prices):
    desk = connect(cfg.desk_db)
    with desk:
        desk.executemany(
            "INSERT OR REPLACE INTO price_bars (symbol, date, close, adj_close) VALUES (?, ?, ?, ?)",
            [(symbol, d, p, p) for d, p in zip(days, prices, strict=True)],
        )
    desk.close()


def walk(n, start, moves):
    out = [start]
    for i in range(n - 1):
        out.append(out[-1] * (1 + moves[i % len(moves)]))
    return out


# ---- Math ----


def test_var_cvar_and_downside():
    rets = [-0.05, -0.04, -0.03, -0.02, -0.01] + [0.01] * 95
    var, cvar = risk.var_cvar(rets)
    assert var == pytest.approx(0.01) and cvar == pytest.approx(0.03)
    assert risk.var_cvar(rets[:10]) == (None, None)
    month = risk.horizon_returns([0.1, 0.1, -0.5], 2)
    assert month == pytest.approx([0.21, -0.45])
    assert risk.downside_dev([0.01, -0.02, 0.03, -0.04]) == pytest.approx(((0.0004 + 0.0016) / 4) ** 0.5 * 252**0.5)


def test_beta_corr_capture_active_share():
    m = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.005] * 2
    double = [2 * x for x in m]
    assert risk.beta(double, m) == pytest.approx(2.0) and risk.corr(double, m) == pytest.approx(1.0)
    assert risk.corr([-x for x in m], m) == pytest.approx(-1.0)
    up, down = risk.capture(m, m)
    assert up == pytest.approx(100.0) and down == pytest.approx(100.0)
    assert risk.capture(m[:3], m[:3]) == (None, None)
    assert risk.active_share({"FXAIX": 700.0, "ACME": 300.0}, {"FXAIX": 0.8, "VXUS": 0.2}) == pytest.approx(30.0)
    assert risk.sharpe([0.01] * 10, 0.0) is None


# ---- Engine run ----


def test_demo_run_fills_the_risk_table(demo_cfg):
    run_holdings(demo_cfg)
    stored, m = run_core(demo_cfg, DEMO_NOW)
    for key in (("risk.var95", "all", "1D"), ("risk.cvar95", "all", "1M"), ("risk.beta", "all", "252D"), ("risk.downside_dev", "all", "63D")):
        assert m[key][1] == "ok" and m[key][0] > 0
    assert m[("risk.cvar95", "all", "1D")][0] >= m[("risk.var95", "all", "1D")][0]
    assert m[("risk.sharpe", "all", "1Y")][1] == "modelled" and ("risk.sortino", "all", "ITD") in m
    pairs = [k for k in m if k[0] == "risk.corr" and "|" in k[1]]
    assert len(pairs) == 10 and all(-1 <= m[k][0] <= 1 for k in pairs)
    assert ("risk.corr_shift", "ACME", "63D") in m and ("bm.capture", "up", "ITD") in m
    acme = m[("value.market", "ACME", "now")][0]
    assert m[("risk.scenario", "satellite_-50", "now")][0] == pytest.approx(-acme / 2, abs=0.01)
    assert m[("risk.scenario", "gfc_2008", "now")][1] == "insufficient_history"
    assert 0 <= m[("plan.adherence", "all", "ITD")][0] <= 100
    assert m[("ret.after_tax", "hsa-0002", "1Y")][0] == pytest.approx(m[("ret.twr", "hsa-0002", "1Y")][0], abs=1e-3)
    assert stored["checks"]["lookthrough"] == "warn"
    desk = connect(demo_cfg.desk_db, readonly=True)
    scopes = {(r[0], r[1]) for r in desk.execute("SELECT DISTINCT scope, scope_id FROM series_daily WHERE series_id='twr_index'")}
    desk.close()
    assert {("account", "hsa-0002"), ("shadow", "plan_shadow"), ("portfolio", "all")} <= scopes


def test_short_history_uses_pro_forma_and_replays_scenarios(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    days = weekdays("2019-06-03", 1500)
    bars(cfg, "SPY", days, walk(len(days), 100.0, [0.01, -0.012, 0.004, 0.006, -0.007]))
    bars(cfg, "FXAIX", days, walk(len(days), 50.0, [0.01, -0.012, 0.004, 0.006, -0.007]))
    _, m = run_core(cfg)
    assert m[("risk.var95", "all", "1D")][1] == "pro_forma" and m[("risk.beta", "all", "252D")][1] == "pro_forma"
    assert m[("risk.sharpe", "all", "1Y")][1] == "insufficient_history"
    desk = connect(cfg.desk_db, readonly=True)
    spy = dict(desk.execute("SELECT date, close FROM price_bars WHERE symbol='SPY'").fetchall())
    desk.close()
    fx = spy["2020-03-23"] / spy[max(d for d in spy if d <= "2020-02-19")] - 1
    want = 1000.0 * fx + 200.0 * fx * 1.0
    value, quality = m[("risk.scenario", "covid_2020", "now")]
    assert value == pytest.approx(want, abs=0.05) and quality == "pro_forma"


def test_rate_shock_reads_sensitivity_from_ten_year_moves(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    days = weekdays("2023-06-01", 700)
    moves = [0.05, -0.03, 0.02, -0.04, 0.01]
    levels = [4.0]
    for i in range(len(days) - 1):
        levels.append(levels[-1] + moves[i % len(moves)])
    prices = [100.0]
    for i in range(1, len(days)):
        prices.append(prices[-1] * (1 - 0.05 * (levels[i] - levels[i - 1])))
    bars(cfg, "FXAIX", days, prices)
    bars(cfg, "SPY", days, prices)
    desk = connect(cfg.desk_db)
    with desk:
        desk.executemany("INSERT INTO macro_daily VALUES ('DGS10', ?, ?)", list(zip(days, levels, strict=True)))
    desk.close()
    _, m = run_core(cfg)
    value, quality = m[("risk.scenario", "rates_+2", "now")]
    assert quality == "modelled" and value == pytest.approx(-0.10 * 1000.0, rel=0.02)


# ---- Look-through ----


NPORT = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport" xmlns:com="http://www.sec.gov/edgar/common">
  <formData>
    <genInfo><seriesId>{series}</seriesId><repPdDate>2026-09-30</repPdDate></genInfo>
    <invstOrSecs>
      <invstOrSec><name>Acme Corp</name><cusip>000000001</cusip><identifiers><isin value="US0000000001"/></identifiers>
        <pctVal>6.0</pctVal><assetCat>EC</assetCat><invCountry>US</invCountry></invstOrSec>
      <invstOrSec><name>Rocket Works Inc.</name><cusip>000000002</cusip><identifiers><ticker value="RKTW"/></identifiers>
        <pctVal>4.0</pctVal><assetCat>EC</assetCat><invCountry>US</invCountry></invstOrSec>
      <invstOrSec><name>US Treasury Note</name><cusip>000000003</cusip><identifiers/>
        <pctVal>2.0</pctVal><assetCat>DBT</assetCat><invCountry>US</invCountry></invstOrSec>
      <invstOrSec><name>Broken row</name><pctVal>n/a</pctVal></invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>"""
MF = {"fields": ["cik", "seriesId", "classId", "symbol"], "data": [[777, "S000000001", "C000000001", "FXAIX"], [777, "S000000002", "C000000002", "OTHRX"]]}
SUBS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000777-26-000002", "0000777-26-000001"],
            "form": ["NPORT-P", "NPORT-P"],
            "primaryDocument": ["primary_doc.xml", "primary_doc.xml"],
            "filingDate": ["2026-10-20", "2026-10-19"],
        }
    }
}


class Res:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


class Http:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if url.endswith("company_tickers.json"):
            return Res(200, {"0": {"cik_str": 1234, "ticker": "ACME", "title": "Acme Corp"}, "1": {"cik_str": 55, "ticker": "RKTW", "title": "Rocket Works"}})
        if url.endswith("company_tickers_mf.json"):
            return Res(200, MF)
        if "submissions/CIK0000000777" in url:
            return Res(200, SUBS)
        if "000077726000002/primary_doc.xml" in url:
            return Res(200, text=NPORT.format(series="S000000002"))
        if "000077726000001/primary_doc.xml" in url:
            return Res(200, text=NPORT.format(series="S000000001"))
        if "stock/profile2" in url:
            industry = {"ACME": "Aerospace & Defense", "RKTW": "Semiconductors"}.get(params["symbol"], "")
            return Res(200, {"name": params["symbol"], "finnhubIndustry": industry})
        return Res(404, {})


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "vektor-desk test")
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr("desk.engine.research.SEC_GAP", 0)
    monkeypatch.setattr("desk.engine.lookthrough.FINNHUB_GAP", 0)


def test_parse_nport_refuses_a_dtd():
    parsed = lookthrough.parse_nport(NPORT.format(series="S1"))
    assert parsed["series"] == "S1" and parsed["period"] == "2026-09-30" and len(parsed["holdings"]) == 3
    assert parsed["holdings"][1]["ticker"] == "RKTW" and parsed["holdings"][0]["name"] == "Acme Corp"
    with pytest.raises(ValueError):
        lookthrough.parse_nport('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    assert lookthrough.norm_name("Rocket Works, Inc. Class A") == "ROCKET WORKS"
    assert lookthrough.sector_of("Semiconductors") == "Technology" and lookthrough.sector_of("Space tourism") == "Space tourism"


def test_lookthrough_job_core_metrics_and_api(cfg, mirror, keys, app_client):
    seed(mirror)
    run_holdings(cfg)
    http = Http()
    result = run_lookthrough(cfg, http)
    assert result["nport"]["funds"] == ["FXAIX"] and set(result["profiles"]["symbols"]) == {"ACME", "RKTW"}
    calls = len(http.calls)
    run_lookthrough(cfg, http)
    assert len(http.calls) == calls + 0
    _, m = run_core(cfg)
    fx_w = 1000.0 / 1500.0 * 100
    acme = m[("risk.lookthrough", "ACME", "now")][0]
    assert acme == pytest.approx(200.0 / 1500.0 * 100 + fx_w * 0.06, abs=1e-3)
    assert m[("risk.lookthrough", "RKTW", "now")][0] == pytest.approx(fx_w * 0.04, abs=1e-3)
    assert m[("risk.lookthrough_coverage", "all", "now")][0] == pytest.approx(100.0)
    assert m[("risk.sector", "Industrials", "now")][0] == pytest.approx(acme, abs=1e-3)
    assert m[("risk.sector", "Bonds and other", "now")][0] == pytest.approx(fx_w * 0.02, abs=1e-3)
    client = app_client(packages=["engine"])
    body = client.get("/api/engine/lookthrough", params={"fund": "fxaix"}).json()
    top = body["rows"][0]
    assert top["holding"] == "ACME" and top["direct"] == pytest.approx(200.0 / 1500.0 * 100, abs=1e-3) and set(top["via"]) == {"FXAIX"}
    assert [h["holding"] for h in body["holdings"]] == ["ACME", "RKTW", "US TREASURY NOTE"] and body["funds"][0]["fund"] == "FXAIX"
    desk = connect(cfg.desk_db, readonly=True)
    assert lookthrough.overlap(desk, "FXAIX", "ACME") == pytest.approx(6.0) and lookthrough.overlap(desk, "ACME", IND) is None
    desk.close()


def test_lookthrough_skips_without_agent(cfg, mirror, monkeypatch):
    monkeypatch.delenv("DESK_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    seed(mirror)
    run_holdings(cfg)
    http = Http()
    result = run_lookthrough(cfg, http)
    assert "not set" in result["nport"]["skipped"] and http.calls == []


# ---- Compare ----


def test_compare_aligns_rebases_and_clips(demo_cfg, app_client):
    run_holdings(demo_cfg)
    run_core(demo_cfg, DEMO_NOW)
    desk = connect(demo_cfg.desk_db, readonly=True)
    try:
        body = compare(desk, ["fxaix", "FTEC", "portfolio", "shadow:plan_shadow"], "1Y")
        long = compare(desk, ["FXAIX", "account:hsa-0002"], "10Y")
        with pytest.raises(CompareError):
            compare(desk, ["FXAIX"], "1Y")
        with pytest.raises(CompareError):
            compare(desk, ["FXAIX", "NOPE"], "1Y")
        with pytest.raises(CompareError):
            compare(desk, ["FXAIX", "FTEC"], "2W")
    finally:
        desk.close()
    assert body["ids"] == ["FXAIX", "FTEC", "portfolio", "shadow:plan_shadow"] and not body["clipped"]
    assert all(s[0]["value"] == 100.0 for s in body["series"].values()) and len({len(s) for s in body["series"].values()}) == 1
    table = {r["id"]: r for r in body["table"]}
    assert table["FXAIX"]["corr"] == 1.0 and table["portfolio"]["kind"] == "portfolio" and table["FTEC"]["vol_pct"] > 0
    assert long["clipped"] and "starts on" in long["note"] and long["start"] >= "2024-11-08"
    client = app_client(packages=["engine"])
    assert client.get("/api/compare", params={"ids": "FXAIX,FTEC", "window": "6M"}).status_code == 200
    assert client.get("/api/compare", params={"ids": "FXAIX", "window": "1Y"}).status_code == 400


def test_after_tax_charges_dividends_in_a_taxable_account(cfg, mirror):
    seed(mirror)
    mirror.put(
        "prefs",
        "taxEngine",
        {"key": "taxEngine", "value": {"res": {"ok": True, "federal": {"tax": 1000.0}, "stateTax": 0.0, "raise": {"federal": 1220.0, "state": 0.0}}}},
    )
    mirror.put("activity", "d1", {"date": "2026-11-03", "accountKey": IND, "kind": "dividend", "symbol": "FXAIX", "amount": 15.0})
    mirror.pull("2026-11-04T21:30:00+00:00")
    run_holdings(cfg)
    _, m = run_core(cfg)
    twr = m[("ret.twr", IND, "ITD")][0]
    assert m[("ret.after_tax", IND, "ITD")][0] == pytest.approx(twr - 15.0 * 0.22 / 1500.0 * 100, abs=1e-3)
    assert core.account_sheltered("hsa-2222") and core.account_sheltered("roth-ira-1") and not core.account_sheltered(IND)
