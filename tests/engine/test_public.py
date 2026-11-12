import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from desk.db import connect
from desk.engine import public, schema
from desk.engine.__main__ import JOBS as COMMANDS
from desk.scheduler import package_jobs

NOW = datetime(2026, 11, 13, 15, 30, tzinfo=UTC)
TODAY = "2026-11-12"
CONTACT = "Desk Test desk@example.com"
NOT_PLAIN = re.compile(r"[A-Z]{3,}_[A-Z_]{2,}|\d{4}-\d{2}-\d{2}|`|\{|python -m|\bcik\b")

COMPANIES = [
    (101, "Alder Works Inc", 9.0e10, "2011-06-30", (2011, 2)),
    (102, "Birch Holdings Corp", 8.0e10, "2010-12-31", (2010, 4)),
    (103, "Cedar Systems Inc", 7.0e10, "2011-03-26", (2011, 1)),
    (104, "Dogwood Energy Co", 6.0e10, "2011-06-30", (2011, 2)),
    (105, "Elm Retail Group", 5.0e10, "2011-07-31", (2011, 2)),
    (106, "Fir Paper Co", 4.0e10, "2011-06-30", (2011, 2)),
    (107, "Gum Tree Foods Inc", 3.0e10, "2010-09-30", (2010, 3)),
]
SEC_LIST = {"AAA": 101, "BBB": 102, "BBBL": 102, "GGG": 107}
TIINGO = [
    ("AAA", "NYSE", "Stock", "USD", "2001-05-01", TODAY),
    ("BBB", "NASDAQ", "Stock", "USD", "2014-04-03", TODAY),
    ("BBBL", "NASDAQ", "Stock", "USD", "2004-08-19", TODAY),
    ("CCC", "NYSE", "Stock", "USD", "1998-01-02", "2016-09-07"),
    ("DDD", "NYSE", "Stock", "USD", "1999-01-04", TODAY),
    ("EEE", "NASDAQ", "Stock", "USD", "2015-06-01", TODAY),
    ("AAA", "NYSE", "ETF", "USD", "1990-01-02", TODAY),
    ("ZZZ", "SHE", "Stock", "CNY", "1990-01-02", TODAY),
    ("QQQQ", "NASDAQ", "Stock", "USD", "", ""),
]
PAGE = """<table class="report"><tr class="ro"><td class="pl"><a class="a" href="javascript:void(0);">Entity Registrant Name</a></td>
<td class="text">CEDAR SYSTEMS INC<span></span></td></tr>
<tr class="re"><td class="pl"><a class="a" href="javascript:void(0);">Trading Symbol</a></td>
<td class="text">ccc<span></span>
</td></tr><tr class="ro"><td class="pl"><a class="a">Entity Well-known Seasoned Issuer</a></td><td class="text">Yes<span></span></td></tr></table>"""
FILINGS = {
    103: ["0000000103-11-000001-index.htm", "R1.htm", "cedar-20110924.xml", "cedar-20110924_cal.xml"],
    104: ["Financial_Report.xls", "ddd-20111231.xml", "ddd-20111231_lab.xml"],
    105: ["eee-20120128.xml"],
    107: ["gumtreefoods-20110630.xml"],
}


def accn(cik: int) -> str:
    return f"{cik:010d}-11-000001"


class Res:
    def __init__(self, status, body=None, text="", content=b""):
        self.status_code, self._body, self.text, self.content = status, body, text, content

    def json(self):
        return self._body


class Http:
    def __init__(self, *, companies=COMPANIES, limit_after=None, tiingo_status=200, extra=()):
        self.calls, self.companies, self.limit_after, self.tiingo_status, self.extra = [], list(companies), limit_after, tiingo_status, list(extra)
        self.filing_calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "sec.gov" in url:
            assert headers == {"User-Agent": CONTACT}
        frame = re.search(r"EntityPublicFloat/USD/CY(\d{4})Q(\d)I\.json$", url)
        if frame:
            want = (int(frame.group(1)), int(frame.group(2)))
            rows = [{"accn": accn(c), "cik": c, "entityName": n, "loc": "US-NY", "end": end, "val": v} for c, n, v, end, f in self.companies if f == want]
            return Res(200, {"taxonomy": "dei", "tag": "EntityPublicFloat", "data": rows + [r for f, r in self.extra if f == want]})
        if url.endswith("company_tickers.json"):
            return Res(200, {str(i): {"cik_str": c, "ticker": s, "title": s} for i, (s, c) in enumerate(SEC_LIST.items())})
        if url.endswith("supported_tickers.zip"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("supported_tickers.csv", "ticker,exchange,assetType,priceCurrency,startDate,endDate\n" + "\n".join(",".join(r) for r in TIINGO))
            return Res(self.tiingo_status, content=buf.getvalue())
        filing = re.search(r"/edgar/data/(\d+)/(\d+)/(.+)$", url)
        if filing:
            self.filing_calls += 1
            if self.limit_after is not None and self.filing_calls > self.limit_after:
                return Res(429)
            cik, name = int(filing.group(1)), filing.group(3)
            assert filing.group(2) == accn(cik).replace("-", "")
            if cik not in FILINGS:
                return Res(404)
            if name == "index.json":
                return Res(200, {"directory": {"item": [{"name": n, "type": "text.gif"} for n in FILINGS[cik]], "name": url}})
            if name == "R1.htm":
                return Res(200, text=PAGE)
        return Res(404)


@pytest.fixture
def desk(cfg, monkeypatch):
    monkeypatch.setenv("DESK_SEC_USER_AGENT", CONTACT)
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    yield conn
    conn.close()


def run(desk, http=None, now=NOW):
    return public.run(desk, http or Http(), now=now, sleep=lambda s: None)


def by_name(desk):
    return {r["name"].split()[0]: r for r in public.names(desk)}


def test_each_company_gets_the_ticker_tiingo_prices_from_the_start_of_the_tests(desk):
    out = run(desk)
    rows = by_name(desk)
    got = {k: (r["symbol"], r["source"], r["state"], r["trading"]) for k, r in rows.items()}
    assert got == {
        "Alder": ("AAA", "sec_list", "priced", 1),
        "Birch": ("BBBL", "sec_list", "priced", 1),
        "Cedar": ("CCC", "filing_page", "priced", 0),
        "Dogwood": ("DDD", "filing_file", "priced", 1),
        "Elm": ("EEE", "filing_file", "late", 0),
        "Fir": (None, None, "no_ticker", 0),
        "Gum": ("GGG", "sec_list", "missing", 0),
    }
    assert [r["rank"] for r in public.names(desk)] == [1, 2, 3, 4, 5, 6, 7]
    assert (rows["Alder"]["first_bar"], rows["Cedar"]["last_bar"]) == ("2001-05-01", "2016-09-07")
    assert out["ok"] and out["fresh"] is False
    assert (out["listed"], out["with_ticker"], out["priced"], out["still_trading"], out["stopped"]) == (7, 6, 4, 3, 1)
    assert (out["from_sec_list"], out["from_filing_page"], out["from_filing_file"]) == (2, 1, 1)
    assert out["no_ticker"] == ["Fir Paper Co"] and out["not_at_tiingo"] == ["Gum Tree Foods Inc (GGG)"]
    assert out["history_too_short"] == ["Elm Retail Group (EEE)"] and out["check_by_eye"] == ["Dogwood Energy Co (DDD)"]
    assert out["priced_pct"] == 57.1 and out["enough"] is False


def test_the_sentence_is_plain_and_says_when_the_list_is_too_thin_to_test_on(desk):
    out = run(desk)
    assert out["detail"] == (
        "Of the 7 largest US companies of mid-2011, 6 have a ticker and Tiingo prices 4 of them from January 2012 (57.1%). "
        "The SEC lists only 7 of the 200 asked for. 1 of the priced names have since stopped trading. "
        "That is under 90%, so stock screens stay research only. Tiingo has room for 400 more names this month and the list needs 4."
    )
    assert not NOT_PLAIN.search(out["detail"])


def test_a_company_is_ranked_once_by_the_float_nearest_mid_2011_and_misfiled_floats_are_left_out(desk, monkeypatch):
    extra = [
        ((2010, 3), {"accn": "old", "cik": 101, "entityName": "Alder Works Inc", "end": "2010-09-30", "val": 1.0e9}),
        ((2011, 2), {"accn": "x", "cik": 201, "entityName": "Typo Billions Inc", "end": "2011-06-30", "val": 4.0e15}),
        ((2011, 2), {"accn": "x", "cik": 202, "entityName": "Small Float Co", "end": "2011-06-30", "val": 5.0e8}),
        ((2011, 2), {"accn": "x", "cik": None, "entityName": "No Number", "end": "2011-06-30", "val": 5.0e10}),
    ]
    top = public.largest(Http(extra=extra), CONTACT, sleep=lambda s: None)
    assert [(r["rank"], r["cik"]) for r in top] == [(i, c) for i, (c, *_rest) in enumerate(COMPANIES, 1)]
    assert (top[0]["float_usd"], top[0]["float_at"], top[0]["accn"]) == (9.0e10, "2011-06-30", accn(101))
    assert [r["cik"] for r in public.largest(Http(), CONTACT, sleep=lambda s: None, size=3)] == [101, 102, 103]


def test_a_fresh_list_is_not_fetched_again_and_an_old_one_is(desk):
    run(desk)
    again = Http()
    out = run(desk, again, now=NOW + timedelta(days=5))
    assert out["fresh"] is True and again.calls == [] and out["priced"] == 4
    later = Http()
    assert run(desk, later, now=NOW + timedelta(days=7))["fresh"] is False and later.calls


def test_when_the_sec_stops_answering_the_rest_wait_and_the_next_run_asks_again(desk):
    first = run(desk, Http(limit_after=3))
    rows = by_name(desk)
    assert rows["Cedar"]["state"] == "priced" and rows["Dogwood"]["state"] == "priced"
    assert [k for k, r in rows.items() if r["state"] == "unasked"] == ["Elm", "Fir", "Gum"]
    assert first["ok"] and first["not_asked"] == ["Elm Retail Group", "Fir Paper Co", "Gum Tree Foods Inc (GGG)"]
    assert "The SEC did not answer for 3; the next run tries them again." in first["detail"]
    second = run(desk, now=NOW + timedelta(hours=4))
    assert second["fresh"] is False and second["not_asked"] == [] and by_name(desk)["Elm"]["state"] == "late"


def test_a_failed_fetch_leaves_the_stored_list_as_it_was(desk):
    run(desk)
    before = public.names(desk)
    out = run(desk, Http(tiingo_status=403), now=NOW + timedelta(days=8))
    assert out == {"ok": False, "error": "Tiingo's ticker list answered 403. The public stock list was left as it was."}
    assert public.names(desk) == before

    class Down(Http):
        def get(self, url, params=None, headers=None, timeout=None):
            raise OSError("no route to host 10.0.0.1")

    out = run(desk, Down(), now=NOW + timedelta(days=8))
    assert out == {"ok": False, "error": "The SEC did not answer. The public stock list was left as it was."}


def test_without_an_sec_contact_it_skips_with_a_code_and_names_no_setting_key(desk, monkeypatch):
    monkeypatch.delenv("DESK_SEC_USER_AGENT")
    http = Http()
    out = run(desk, http)
    assert out == {"ok": True, "skipped": "The SEC contact is not set. Add it in Settings, Data, Keys.", "skipped_code": "no_sec_contact"}
    assert http.calls == [] and not NOT_PLAIN.search(out["skipped"])


def test_tiingo_room_counts_this_months_names_and_shrinks_the_list_when_it_is_tight(desk):
    with desk:
        desk.executemany(
            "INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('tiingo', ?, ?, 1)",
            [("2026-11-03T12:00:00+00:00", s) for s in ["AAA", "CCC", *(f"X{i}" for i in range(189))]] + [("2026-10-30T12:00:00+00:00", "DDD")],
        )
    out = run(desk)
    assert out["tiingo"] == {"limit": 400, "used": 191, "left": 209, "new_names": 2, "size": 150}
    with desk:
        desk.execute("DELETE FROM api_calls WHERE symbol LIKE 'X1%'")
    assert public.summary(desk, public.names(desk), NOW)["tiingo"]["size"] == 200


def test_the_route_shows_the_stored_list_and_reads_empty_before_the_first_run(cfg, desk, app_client):
    client = app_client(["engine"])
    empty = client.get("/api/engine/public-stocks").json()
    assert (empty["listed"], empty["names"], empty["detail"]) == (0, [], "The public stock list has not been built yet.")
    run(desk)
    body = client.get("/api/engine/public-stocks").json()
    assert body["priced"] == 4 and body["fetched_at"] == NOW.isoformat(timespec="seconds") and len(body["names"]) == 7
    assert body["names"][2] == {
        "rank": 3,
        "name": "Cedar Systems Inc",
        "cik": 103,
        "float_usd": 7.0e10,
        "float_at": "2011-03-26",
        "symbol": "CCC",
        "source": "filing_page",
        "first_bar": "1998-01-02",
        "last_bar": "2016-09-07",
        "state": "priced",
        "trading": 0,
    }
    assert "accn" not in json.dumps(body)


def test_the_job_is_light_runs_in_the_daytime_and_has_a_title_a_person_can_read():
    job = next(j for j in package_jobs(["engine"]) if j.name == "engine-public")
    assert (job.title, job.heavy) == ("Public stock list", False) and "public" in COMMANDS
    assert job.spec[1] and all(9 <= h < 16 for h in job.spec[1])
