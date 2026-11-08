import io
import zipfile
from datetime import UTC, date, datetime, timedelta

from desk.db import connect
from desk.engine import insider, schema
from desk.engine.lab import library as features
from desk.engine.lab.data import data_path, export, load
from desk.engine.lab.sim import simulate, universe
from desk.engine.lab.spec import parse, resolve

NOW = datetime(2026, 11, 8, 4, 0, tzinfo=UTC)


def tsv(rows: list[dict]) -> str:
    keys = list(rows[0])
    return "\n".join(["\t".join(keys)] + ["\t".join(str(r[k]) for k in keys) for r in rows]) + "\n"


def bulk_zip() -> bytes:
    subs = [
        {"ACCESSION_NUMBER": "0001-24-000001", "FILING_DATE": "04-MAR-2024", "DOCUMENT_TYPE": "4", "ISSUERCIK": "111", "ISSUERTRADINGSYMBOL": "smol"},
        {"ACCESSION_NUMBER": "0001-24-000002", "FILING_DATE": "05-MAR-2024", "DOCUMENT_TYPE": "4/A", "ISSUERCIK": "111", "ISSUERTRADINGSYMBOL": "SMOL"},
        {"ACCESSION_NUMBER": "0001-24-000003", "FILING_DATE": "05-MAR-2024", "DOCUMENT_TYPE": "4", "ISSUERCIK": "222", "ISSUERTRADINGSYMBOL": "FUND"},
        {"ACCESSION_NUMBER": "0001-24-000004", "FILING_DATE": "06-MAR-2024", "DOCUMENT_TYPE": "3", "ISSUERCIK": "111", "ISSUERTRADINGSYMBOL": "SMOL"},
        {"ACCESSION_NUMBER": "0001-24-000005", "FILING_DATE": "07-MAR-2024", "DOCUMENT_TYPE": "4", "ISSUERCIK": "111", "ISSUERTRADINGSYMBOL": "SMOL"},
    ]
    owners = [
        {"ACCESSION_NUMBER": "0001-24-000001", "RPTOWNERCIK": "9001", "RPTOWNER_RELATIONSHIP": "Director"},
        {"ACCESSION_NUMBER": "0001-24-000001", "RPTOWNERCIK": "9002", "RPTOWNER_RELATIONSHIP": "Officer,TenPercentOwner"},
        {"ACCESSION_NUMBER": "0001-24-000002", "RPTOWNERCIK": "9003", "RPTOWNER_RELATIONSHIP": "Officer"},
        {"ACCESSION_NUMBER": "0001-24-000003", "RPTOWNERCIK": "9004", "RPTOWNER_RELATIONSHIP": "TenPercentOwner"},
        {"ACCESSION_NUMBER": "0001-24-000004", "RPTOWNERCIK": "9005", "RPTOWNER_RELATIONSHIP": "Director"},
        {"ACCESSION_NUMBER": "0001-24-000005", "RPTOWNERCIK": "9006", "RPTOWNER_RELATIONSHIP": "Director"},
    ]

    def t(acc, code, shares, px, ad="A", day="01-MAR-2024"):
        return {
            "ACCESSION_NUMBER": acc,
            "TRANS_DATE": day,
            "TRANS_CODE": code,
            "TRANS_SHARES": shares,
            "TRANS_PRICEPERSHARE": px,
            "TRANS_ACQUIRED_DISP_CD": ad,
        }

    trans = [
        t("0001-24-000001", "P", "1000", "5.00"),
        t("0001-24-000001", "P", "500", "5.20", day="02-MAR-2024"),
        t("0001-24-000002", "P", "2000", "5.10"),
        t("0001-24-000003", "P", "9999", "1.00"),
        t("0001-24-000004", "P", "10", "5.00"),
        t("0001-24-000005", "S", "300", "5.50", ad="D"),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2024q1_form345/SUBMISSION.tsv", tsv(subs))
        z.writestr("2024q1_form345/REPORTINGOWNER.tsv", tsv(owners))
        z.writestr("2024q1_form345/NONDERIV_TRANS.tsv", tsv(trans))
    return buf.getvalue()


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerCik>0000000111</issuerCik><issuerTradingSymbol>smol</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0000009007</rptOwnerCik></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-03</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>400</value></transactionShares>
        <transactionPricePerShare><value>6.25</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-03</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>9000</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


class Res:
    def __init__(self, status, content=b"", text=""):
        self.status_code, self.content, self.text = status, content, text


class FakeSec:
    def __init__(self, published=("2024q1",)):
        self.published = set(published)
        self.urls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        if url.endswith("_form345.zip"):
            key = url.rsplit("/", 1)[1].split("_")[0]
            return Res(200, bulk_zip()) if key in self.published else Res(404)
        if url.endswith("form4.xml"):
            return Res(200, text=FORM4)
        if "frames" in url:
            return Res(200, text='{"data": [{"cik": 111, "end": "2023-12-31", "val": 20000000, "accn": "x"}]}')
        return Res(404)


def desk(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


# ---- Parsing ----


def test_bulk_keeps_open_market_buys_by_directors_and_officers():
    rows = insider.parse_bulk(bulk_zip())
    got = {(r[0], r[1]): r for r in rows}
    assert set(got) == {("0001-24-000001", 9001), ("0001-24-000001", 9002), ("0001-24-000002", 9003)}
    first = got[("0001-24-000001", 9001)]
    assert first[3] == "SMOL" and first[4] == "2024-03-02" and first[5] == "2024-03-04" and first[7] == 7600.0 and first[8] == "director"
    assert got[("0001-24-000001", 9002)][8] == "officer" and got[("0001-24-000002", 9003)][9] == "bulk"


def test_form4_xml_counts_only_purchases():
    rows = insider.parse_form4(FORM4, "0001-26-000099", "2026-11-04")
    assert rows == [("0001-26-000099", 9007, 111, "SMOL", "2026-11-03", "2026-11-04", 400.0, 2500.0, "director", "form4")]
    assert insider.parse_form4("<oops", "a", "2026-11-04") == []
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ownershipDocument><documentType>&a;</documentType></ownershipDocument>'
    assert insider.parse_form4(bomb, "a", "2026-11-04") == []
    assert insider.xml_url("https://www.sec.gov/Archives/edgar/data/111/000126000099/xslF345X05/form4.xml").endswith("/000126000099/form4.xml")


def test_known_day_is_the_session_after_filing():
    assert insider.known_day("2024-03-04") == "2024-03-05"
    assert insider.known_day("2026-11-06") == "2026-11-09"


# ---- Fetch ----


def test_bulk_quarters_fetch_once_and_skip_unpublished(cfg, monkeypatch):
    monkeypatch.setattr(insider, "FIRST_QUARTER", (2024, 1))
    conn = desk(cfg)
    web = FakeSec()
    out = insider.fetch_bulk(conn, web, "test agent", now=datetime(2024, 7, 2, tzinfo=UTC), sleep=lambda _: None)
    assert out == {"quarters": 1, "rows": 3, "not_published": ["2024Q2"]}
    again = insider.fetch_bulk(conn, web, "test agent", now=datetime(2024, 7, 2, tzinfo=UTC), sleep=lambda _: None)
    assert again == {"quarters": 0, "rows": 0, "not_published": ["2024Q2"]}
    assert conn.execute("SELECT rows FROM insider_quarters WHERE quarter='2024Q1'").fetchone()[0] == 3
    conn.close()


def test_live_form4s_come_from_the_filings_feed(cfg):
    conn = desk(cfg)
    with conn:
        conn.execute(
            "INSERT INTO filings_feed (accession, cik, symbol, form, items, filed_at, filed_date, url, materiality, fetched_at) "
            "VALUES ('0001-26-000099', 111, 'SMOL', '4', '[]', '2026-11-04T18:00:00-05:00', '2026-11-04', "
            "'https://www.sec.gov/Archives/edgar/data/111/000126000099/xslF345X05/form4.xml', 3, 'x')"
        )
    web = FakeSec()
    assert insider.fetch_form4(conn, web, "test agent", sleep=lambda _: None) == {"form4": 1, "rows": 1}
    assert insider.fetch_form4(conn, web, "test agent", sleep=lambda _: None) == {"form4": 0, "rows": 0}
    assert web.urls == ["https://www.sec.gov/Archives/edgar/data/111/000126000099/form4.xml"]
    conn.close()


def test_job_skips_without_an_sec_agent(cfg, monkeypatch):
    monkeypatch.delenv("DESK_SEC_USER_AGENT", raising=False)
    conn = desk(cfg)
    assert "DESK_SEC_USER_AGENT" in insider.run(conn, FakeSec(), now=NOW)["skipped"]
    conn.close()


# ---- Clusters and membership ----


def buy(conn, acc, owner, sym, filed, usd=10000.0, cik=111):
    conn.execute("INSERT INTO insider_buys VALUES (?, ?, ?, ?, ?, ?, 100, ?, 'director', 'bulk')", (acc, owner, cik, sym, filed, filed, usd))


def test_clusters_need_two_insiders_inside_thirty_days(cfg):
    conn = desk(cfg)
    with conn:
        buy(conn, "a1", 1, "SMOL", "2024-03-01")
        buy(conn, "a2", 2, "SMOL", "2024-03-20")
        buy(conn, "b1", 1, "LONE", "2024-03-01")
        buy(conn, "b2", 1, "LONE", "2024-03-05")
        buy(conn, "c1", 1, "FAR", "2024-01-01")
        buy(conn, "c2", 2, "FAR", "2024-03-01")
    assert insider.clusters(conn) == {"SMOL": "2024-03-01"}
    conn.close()


def sessions(start: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_membership_uses_lagged_share_counts_and_liquidity(cfg):
    conn = desk(cfg)
    days = sessions("2024-01-02", 80)
    with conn:
        buy(conn, "a1", 1, "SMOL", "2024-03-01")
        buy(conn, "t1", 1, "THIN", "2024-03-01", cik=333)
        conn.executemany("INSERT INTO sec_shares VALUES (?, ?, ?, 'x', 'x')", [(111, "2023-12-31", 20e6), (333, "2023-12-31", 20e6)])
        rows = [("SMOL", d, 5, 5, 5, 5.0, 5.0, 200000, 5) for d in days] + [("THIN", d, 5, 5, 5, 5.0, 5.0, 1000, 5) for d in days]
        conn.executemany("INSERT INTO alpaca_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    assert insider.months(conn) == 2
    got = [tuple(r) for r in conn.execute("SELECT symbol, month, market_cap FROM smallcap_months ORDER BY month")]
    assert got == [("SMOL", "2024-03", 1e8), ("SMOL", "2024-04", 1e8)]
    conn.close()


# ---- Lab: features, universe, backtest ----


def lab_desk(cfg):
    conn = desk(cfg)
    days = sessions("2023-01-02", 400)
    with conn:
        conn.executemany(
            "INSERT INTO price_bars (symbol, date, open, high, low, close, adj_close, volume) VALUES ('SPY', ?, 400, 400, 400, 400, 400, 1e7)",
            [(d,) for d in days],
        )
        for sym, drift in (("SMOL", 0.004), ("DULL", 0.0), ("IWM", 0.0005)):
            px, rows = 10.0, []
            for d in days:
                rows.append((sym, d, px, px, px, px, px, 1e6, px))
                px *= 1 + drift
            conn.executemany("INSERT INTO alpaca_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        months = sorted({d[:7] for d in days})
        conn.executemany("INSERT INTO smallcap_months VALUES (?, ?, 1e8, 1e6)", [(s, m) for s in ("SMOL", "DULL") for m in months])
        buy(conn, "a1", 1, "SMOL", "2024-01-02")
        buy(conn, "a2", 2, "SMOL", "2024-01-03", usd=50000.0)
        buy(conn, "d1", 3, "DULL", "2024-01-03")
    return conn, days


SPEC = {
    "id": "insider-cluster",
    "version": 1,
    "title": "Insider clusters",
    "hypothesis": "Two or more insiders buying within a month predicts small-cap outperformance.",
    "predicted_effect": "+5 points a year",
    "universe": {"type": "small_caps"},
    "signals": [{"metric_id": "insider.buyers", "window": "21d", "transform": "raw"}],
    "entry": {"top_n": 3, "min_signal": 1},
    "exit": "rebalance",
    "rebalance": "weekly",
    "sizing": "equal",
    "params": {},
    "success_criteria": {"excess_vs_plan_pts": 0.0},
    "horizons": [3],
}


def test_insider_features_count_buyers_known_inside_the_window(cfg):
    conn, days = lab_desk(cfg)
    result = export(cfg, conn, {}, {})
    assert result["small_caps"] == 2
    data = load(data_path(cfg))
    assert data.kinds["SMOL"] == "stock" and data.roles["SMOL"] == "small_cap" and data.kinds["IWM"] == "fund"
    s = data.series["SMOL"]
    at = s.index["2024-01-04"]
    assert features.value("insider.buyers", s, at, 21, data.insider["SMOL"]) == 2.0
    assert features.value("insider.buy_usd", s, at, 21, data.insider["SMOL"]) == 60000.0
    assert features.value("insider.buyers", s, s.index["2024-01-03"], 21, data.insider["SMOL"]) == 1.0
    assert features.value("insider.buyers", s, s.index["2024-03-01"], 21, data.insider["SMOL"]) == 0.0
    assert {f["metric_id"]: f["kind"] for f in features.catalog()}["insider.buyers"] == "insider"
    conn.close()


def test_a_cluster_spec_buys_after_the_news_is_public(cfg):
    conn, days = lab_desk(cfg)
    export(cfg, conn, {}, {})
    data = load(data_path(cfg))
    spec = parse(SPEC, data, model="test")
    assert spec.benchmark == "IWM" and spec.universe == {"kind": "small_caps", "min_price": 2.0}
    assert universe(data, spec, "2024-01-05") == ["DULL", "SMOL"]
    res = simulate(data, spec, resolve(spec, {}), "2023-12-01", "2024-03-29")
    buys = [(d, s) for d, s, side, *_ in res.trades if side == "buy"]
    assert buys and buys[0][1] == "SMOL" and buys[0][0] > "2024-01-04" and all(s == "SMOL" for _, s in buys)
    conn.close()


def test_small_caps_need_the_history_first(cfg):
    from desk.engine.lab.spec import SpecError

    conn, _ = lab_desk(cfg)
    with conn:
        conn.execute("DELETE FROM smallcap_months")
    export(cfg, conn, {}, {})
    data = load(data_path(cfg))
    try:
        parse(SPEC, data, model="test")
        raise AssertionError("expected SpecError")
    except SpecError as e:
        assert "insider job" in str(e)
    conn.close()


def test_nightly_job_without_alpaca_keys_still_loads_sec_data(cfg, monkeypatch):
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    monkeypatch.setenv("DESK_SEC_USER_AGENT", "Vektor Desk test")
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.setattr(insider, "FIRST_QUARTER", (2024, 1))
    conn = desk(cfg)
    out = insider.run(conn, FakeSec(), now=datetime(2024, 7, 2, tzinfo=UTC), sleep=lambda _: None)
    assert out["ok"] and out["bulk"]["rows"] == 3 and out["frames"] > 0 and "not set" in out["history"]["skipped"] and out["buys"] == 3
    assert conn.execute("SELECT count(*) FROM sec_shares").fetchone()[0] == 1
    conn.close()
    assert "insider" in engine_main.JOBS and ("20 23 * * *", "python -m desk.engine insider") in JOBS


# ---- Survivorship ----


def test_coverage_counts_cluster_names_without_prices(cfg):
    conn = desk(cfg)
    with conn:
        for sym in ("GOOD", "GONE", "WAIT", "LATE", "DIED"):
            buy(conn, f"{sym}1", 1, sym, "2024-03-01")
            buy(conn, f"{sym}2", 2, sym, "2024-03-04")
        conn.executemany("INSERT INTO alpaca_history VALUES (?, '2016-01-01', ?, 'x')", [("GOOD", 300), ("GONE", 0), ("LATE", 10), ("DIED", 20)])
        rows = [("GOOD", d) for d in sessions("2024-02-01", 300)] + [("LATE", d) for d in sessions("2024-06-03", 10)]
        rows += [("DIED", d) for d in sessions("2024-02-20", 40)]
        conn.executemany("INSERT INTO alpaca_bars VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1)", rows)
    cov = insider.coverage(conn)
    assert cov == {"clusters": 5, "priced": 2, "unpriced": 2, "pending": 1, "ended_within_a_year": 1, "unpriced_symbols": ["GONE", "LATE"]}
    conn.close()


def test_survivorship_holds_the_verdict_until_prices_are_complete():
    from desk.engine.lab.runner import _survivorship

    stress = {"excess_vs_bench_pts": 1.5}
    full = {"clusters": 100, "priced": 98, "unpriced": 2, "pending": 0, "ended_within_a_year": 7, "unpriced_symbols": ["GONE"]}
    ok = _survivorship(full, stress)
    assert ok["coverage_ok"] is True and ok["missing_share"] == 0.02 and "2 of 100" in ok["note"] and "beats the benchmark by 1.50 points" in ok["note"]
    assert _survivorship(full | {"unpriced": 9}, stress)["coverage_ok"] is None
    assert _survivorship(full | {"pending": 1}, stress)["coverage_ok"] is None
    assert _survivorship(None, stress)["coverage_ok"] is None


def test_delistings_can_count_as_a_total_loss(cfg):
    conn, days = lab_desk(cfg)
    with conn:
        conn.execute("DELETE FROM alpaca_bars WHERE symbol='SMOL' AND date > '2024-02-15'")
        buy(conn, "a3", 4, "SMOL", "2024-02-01")
        buy(conn, "a4", 5, "SMOL", "2024-02-02")
    export(cfg, conn, {}, {})
    data = load(data_path(cfg))
    spec = parse(SPEC, data, model="test")
    v = resolve(spec, {})
    soft = simulate(data, spec, v, "2023-12-01", "2024-03-29")
    hard = simulate(data, spec, v, "2023-12-01", "2024-03-29", delist_haircut=1.0)
    assert "SMOL" in soft.delisted and hard.values[-1] < soft.values[-1]
    conn.close()


def test_finalize_shows_survivorship_in_the_verdict(cfg):
    import json

    from desk.engine.lab.runner import finalize, ledger

    conn, _ = lab_desk(cfg)
    export(cfg, conn, {}, {})
    conn.close()
    data = load(data_path(cfg))
    led = ledger(cfg)
    spec = parse(SPEC, data, model="test")
    with led:
        led.execute(
            "INSERT INTO strategies VALUES (?, 1, ?, NULL, ?, 'lab', '2024-04-01T00:00:00', 'test', NULL, ?)",
            (spec.id, spec.hash, spec.title, json.dumps(SPEC)),
        )
        exp = {
            "deploy_params": {"seed": 0},
            "windows": {"start": "2023-12-01", "end": "2024-01-31", "holdout_start": "2024-02-01"},
            "walk_forward": {},
            "caveats": [],
        }
        led.execute("INSERT INTO lab_results VALUES (?, 1, 'experiment', '2024-04-01T00:00:00', ?)", (spec.id, json.dumps(exp)))
    body = finalize(cfg, led, data, {"strategy_id": spec.id, "version": 1}, now=NOW)
    led.close()
    assert body["verdict"] == "fail" and body["paper_start"] is None
    assert body["bars"]["price_coverage"] is None and body["bars"]["delist_total_loss"] is False
    assert "trails the benchmark" in body["survivorship"]["note"]
    assert body["survivorship"]["clusters"] == 1 and body["survivorship"]["pending"] == 1 and "still loading" in body["caveats"][-1]
