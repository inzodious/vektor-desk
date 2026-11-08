import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import pytest

from desk.db import connect
from desk.engine import __main__ as engine_main
from desk.engine import alpaca, filings, schema, universe
from desk.engine.market import ET

NOW = datetime(2026, 11, 6, 23, 45, tzinfo=UTC)
DAYS = [date(2026, 10, 9) + timedelta(days=i) for i in range(30)]
SESSIONS = [d for d in DAYS if d.weekday() < 5][-22:]
LAST = SESSIONS[-1].isoformat()

COMPANIES = {
    "SMOL": (1001, "Smol Robotics Inc", "NASDAQ", 50e6, 10.0, 200_000),
    "MIDZ": (1002, "Midz Energy Corp", "NYSE", 100e6, 15.0, 80_000),
    "BIGG": (1003, "Bigg Holdings Inc", "NYSE", 500e6, 20.0, 1_000_000),
    "TINY": (1004, "Tiny Bio Inc", "NASDAQ", 2e6, 4.0, 500_000),
    "THIN": (1005, "Thin Trade Inc", "AMEX", 30e6, 10.0, 1_000),
    "ETFX": (1006, "Rocket Tech ETF", "NASDAQ", 30e6, 10.0, 200_000),
    "ADRY": (1007, "Faraway Mining ADR", "NYSE", 30e6, 10.0, 200_000),
    "OTCQ": (1008, "Pink Sheet Corp", "OTC", 30e6, 10.0, 200_000),
    "WARR": (1009, "Smol Robotics Warrants", "NASDAQ", 30e6, 10.0, 200_000),
    "FNDY": (1010, "Plain Name Corp", "NASDAQ", 30e6, 10.0, 200_000),
}


def midnight(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=ET).astimezone(UTC).isoformat().replace("+00:00", "Z")


class Res:
    def __init__(self, status, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        return self._body


class FakeWeb:
    def __init__(self, index=None, docs=None, items="2.02,9.01"):
        self.calls: list[str] = []
        self.index = index or {}
        self.docs = docs or {}
        self.items = items

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        host, path = urlparse(url).hostname, urlparse(url).path
        if host == "paper-api.alpaca.markets" and path == "/v2/assets":
            return Res(200, [{"symbol": s, "name": c[1], "exchange": c[2], "tradable": True} for s, c in COMPANIES.items()])
        if host == "data.alpaca.markets":
            assert headers["APCA-API-KEY-ID"] == "paper-id"
            out = {}
            for s in params["symbols"].split(","):
                _, _, _, _, px, vol = COMPANIES.get(s, (0, "", "", 0, 200.0, 1_000_000))
                scale = 0.5 if params["adjustment"] == "all" else 1.0
                out[s] = [
                    {"t": midnight(d), "o": px, "h": px, "l": px, "c": px * scale, "v": vol, "vw": px} for d in SESSIONS if d.isoformat() >= params["start"]
                ]
            return Res(200, {"bars": out, "next_page_token": None})
        if url.endswith("company_tickers.json"):
            return Res(200, {str(i): {"ticker": s, "cik_str": c[0], "title": c[1]} for i, (s, c) in enumerate(COMPANIES.items())})
        if "/frames/" in url:
            return Res(200, {"data": [{"cik": c[0], "end": "2026-09-30", "val": c[3], "accn": "x"} for c in COMPANIES.values()]})
        if "/daily-index/" in url:
            stamp = url.rsplit(".", 2)[-2]
            return Res(200, text=self.index[stamp]) if stamp in self.index else Res(403, text="")
        if "/submissions/" in url:
            cik = int(url.split("CIK")[1].split(".")[0])
            accs = [a for a in self.docs if a.startswith(f"{cik:010d}")]
            return Res(
                200,
                {
                    "sicDescription": "Electronic Computers",
                    "filings": {
                        "recent": {
                            "accessionNumber": accs,
                            "acceptanceDateTime": ["2026-11-05T16:31:22.000Z" for _ in accs],
                            "filingDate": ["2026-11-05" for _ in accs],
                            "form": [self.docs[a][0] for a in accs],
                            "items": [self.items if self.docs[a][0] == "8-K" else "" for a in accs],
                            "primaryDocument": [f"{a}.htm" for a in accs],
                        }
                    },
                },
            )
        if "/Archives/edgar/data/" in url:
            acc = url.rsplit("/", 1)[1].removesuffix(".htm")
            return Res(200, text=self.docs[acc][1])
        return Res(404, {})


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "paper-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "Desk test@example.com")
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)


def desk(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    with conn:
        conn.execute("INSERT INTO sec_funds VALUES ('FNDY', 1010, 'S1', NULL, '2026-11-06')")
    return conn


def no_sleep(_):
    return None


# ---- Universe ----


def test_universe_applies_the_rule(cfg, keys):
    conn = desk(cfg)
    result = universe.run(conn, FakeWeb(), now=NOW, sleep=no_sleep)
    assert result["ok"] and result["date"] == LAST
    picked = {m["symbol"]: m for m in universe.members(conn)}
    assert set(picked) == {"SMOL", "MIDZ"}
    assert picked["SMOL"]["market_cap"] == 500e6 and picked["SMOL"]["dollar_volume"] == 2e6
    bar = conn.execute("SELECT close, adj_close FROM alpaca_bars WHERE symbol='SMOL' AND date=?", (LAST,)).fetchone()
    assert tuple(bar) == (10.0, 5.0)
    conn.close()


def test_universe_is_point_in_time(cfg, keys):
    conn = desk(cfg)
    universe.run(conn, FakeWeb(), now=NOW, sleep=no_sleep)
    with conn:
        conn.execute("UPDATE sec_shares SET val=val*100 WHERE cik=1001")
        conn.execute("INSERT INTO alpaca_bars (symbol, date, close, volume) VALUES ('SMOL', '2026-11-09', 10, 200000)")
    universe.build(conn, "2026-11-09")
    assert {m["symbol"] for m in universe.members(conn, LAST)} == {"SMOL", "MIDZ"}
    assert {m["symbol"] for m in universe.members(conn, "2026-11-09")} == set()
    conn.close()


def test_market_data_never_follows_the_trading_url(cfg, keys, monkeypatch):
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    web = FakeWeb()
    conn = desk(cfg)
    universe.run(conn, web, now=NOW, sleep=no_sleep)
    hosts = {urlparse(u).hostname for u in web.calls if "alpaca" in u}
    assert hosts == {"paper-api.alpaca.markets", "data.alpaca.markets"}
    assert alpaca.DATA_URL == "https://data.alpaca.markets"
    conn.close()


def test_a_live_trading_url_is_refused(cfg, keys, monkeypatch):
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    web = FakeWeb()
    conn = desk(cfg)
    result = universe.run(conn, web, now=NOW, sleep=no_sleep)
    assert not result["ok"] and "paper" in result["error"]
    assert not any("api.alpaca.markets/v2/assets" in u and "paper" not in u for u in web.calls)
    conn.close()


def test_universe_waits_for_keys(cfg, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    conn = desk(cfg)
    assert "skipped" in universe.run(conn, FakeWeb(), now=NOW, sleep=no_sleep)
    conn.close()


# ---- Filings ----


INDEX = """Description:           Daily Index of EDGAR Dissemination Feed by Company Name
CIK|Company Name|Form Type|Date Filed|File Name
--------------------------------------------------------------------------------
1001|Smol Robotics Inc|8-K|20261105|edgar/data/1001/0000001001-26-000010.txt
1001|Smol Robotics Inc|4|20261105|edgar/data/1001/0000001001-26-000011.txt
1001|Smol Robotics Inc|SC 13G|20261105|edgar/data/1001/0000001001-26-000012.txt
1003|Bigg Holdings Inc|8-K|20261105|edgar/data/1003/0000001003-26-000020.txt
1002|Midz Energy Corp|424B5|20261105|edgar/data/1002/0000001002-26-000030.txt
"""
DOCS = {
    "0000001001-26-000010": ("8-K", "<html><head><style>x{}</style></head><body><p>Revenue rose to $12.4 million.</p><p>Q3&nbsp;results</p></body></html>"),
    "0000001001-26-000011": ("4", "<html><body>Form 4 purchase of 10,000 shares</body></html>"),
    "0000001002-26-000030": ("424B5", "<html><body>Offering of 5,000,000 shares at $2.00</body></html>"),
}


def fetched(cfg):
    conn = desk(cfg)
    universe.run(conn, FakeWeb(), now=NOW, sleep=no_sleep)
    web = FakeWeb(index={"20261105": INDEX}, docs=DOCS)
    result = filings.run(conn, web, now=NOW, sleep=no_sleep)
    return conn, web, result


def test_filings_fetch_universe_names_with_items_and_excerpts(cfg, keys):
    conn, _, result = fetched(cfg)
    assert result["ok"] and result["filings"] == 3 and result["excerpts"] == 3
    rows = {r["accession"]: dict(r) for r in conn.execute("SELECT * FROM filings_feed")}
    assert set(rows) == set(DOCS)
    k8 = rows["0000001001-26-000010"]
    assert json.loads(k8["items"]) == ["2.02", "9.01"] and k8["filed_at"] == "2026-11-05T16:31:22.000Z" and k8["sector"] == "Electronic Computers"
    assert k8["excerpt"] == "Revenue rose to $12.4 million.\nQ3 results"
    conn.close()


def test_done_days_are_not_fetched_again(cfg, keys):
    conn, _, _ = fetched(cfg)
    web = FakeWeb(index={"20261105": INDEX}, docs=DOCS)
    again = filings.run(conn, web, now=NOW, sleep=no_sleep)
    assert again["filings"] == 0 and not any("20261105" in u for u in web.calls)
    conn.close()


def test_pending_orders_by_materiality(cfg, keys):
    conn, _, _ = fetched(cfg)
    conn.close()
    queue = filings.pending(cfg, 10)
    assert [q["form"] for q in queue] == ["8-K", "424B5", "4"]
    top = queue[0]
    assert (
        top["symbol"] == "SMOL"
        and top["items"] == ["2.02", "9.01"]
        and top["company"] == {"name": "Smol Robotics Inc", "market_cap": 500e6, "sector": "Electronic Computers"}
    )
    assert len(filings.pending(cfg, 1)) == 1


def good(**over):
    base = {
        "direction": 1,
        "confidence": 0.7,
        "event_type": "earnings",
        "horizon_days": 20,
        "rationale": "Revenue up.",
        "numbers_cited": ["$12.4 million"],
        "model": "claude-test",
        "scored_at": "2026-11-06T09:15:00+00:00",
        "run_id": "r1",
    }
    return base | over


def test_record_is_first_write_wins_and_validated(cfg, keys):
    conn, _, _ = fetched(cfg)
    conn.close()
    acc = "0000001001-26-000010"
    filings.record(cfg, acc, good())
    filings.record(cfg, acc, good(direction=-2, scored_at="2026-11-07T09:15:00+00:00"))
    conn = connect(cfg.desk_db, readonly=True)
    row = dict(conn.execute("SELECT * FROM filing_signals WHERE accession=?", (acc,)).fetchone())
    assert row["direction"] == 1 and row["symbol"] == "SMOL" and row["form"] == "8-K" and json.loads(row["numbers_cited"]) == ["$12.4 million"]
    assert filings.lane_start(conn) == "2026-11-06T09:15:00+00:00"
    conn.close()
    assert acc not in {q["accession"] for q in filings.pending(cfg, 10)}
    for bad in (good(direction=3), good(direction=True), good(confidence=1.2), good(event_type="vibes"), good(horizon_days=0), good(model="")):
        with pytest.raises(ValueError):
            filings.record(cfg, "0000001001-26-000011", bad)
    with pytest.raises(ValueError):
        filings.record(cfg, "0000009999-26-000001", good())
    long = good(rationale="x" * 400)
    filings.record(cfg, "0000001001-26-000011", long)
    conn = connect(cfg.desk_db, readonly=True)
    assert len(conn.execute("SELECT rationale FROM filing_signals WHERE accession='0000001001-26-000011'").fetchone()[0]) == 280
    conn.close()


def test_pending_is_not_ready_before_the_tables_exist(cfg):
    with pytest.raises(filings.NotReady):
        filings.pending(cfg, 5)


def test_pending_is_empty_before_the_first_fetch(cfg):
    desk(cfg).close()
    assert filings.pending(cfg, 5) == []


def test_filings_wait_for_a_universe(cfg, keys):
    conn = desk(cfg)
    assert "skipped" in filings.run(conn, FakeWeb(), now=NOW, sleep=no_sleep)
    conn.close()


def test_materiality_ranks_events():
    assert filings.materiality("8-K", ["1.03"]) > filings.materiality("8-K", ["2.02"]) > filings.materiality("10-Q", [])
    assert filings.materiality("424B5", []) > filings.materiality("4", [])
    assert filings.materiality("8-K/A", ["2.02"]) < filings.materiality("8-K", ["2.02"])


def test_jobs_are_scheduled():
    from desk.engine.jobs import JOBS

    commands = {c for _, c in JOBS}
    assert {"python -m desk.engine universe", "python -m desk.engine filings"} <= commands
    assert {"universe", "filings"} <= set(engine_main.JOBS)


def test_bar_dates_are_eastern():
    assert alpaca._day("2026-11-05T05:00:00Z") == "2026-11-05"
    assert datetime(2026, 11, 5, tzinfo=ET).date().isoformat() == "2026-11-05"
