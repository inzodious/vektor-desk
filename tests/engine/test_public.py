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
SEC_LIST = {"AAA": 101, "BBB": 102, "BBBL": 102, "GGG": 107, "BARS": 108}
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
    ("BARS", "NYSE ARCA", "ETF", "USD", "2004-11-18", TODAY),
    ("GGG", "NYSE ARCA", "ETF", "USD", "2019-05-01", TODAY),
    ("GOOG", "NASDAQ", "Stock", "USD", "2014-03-27", TODAY),
    ("GOOGL", "NASDAQ", "Stock", "USD", "2004-08-19", TODAY),
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
    110: ["goog-20101231.xml"],
}


def accn(cik: int, year: int = 11) -> str:
    return f"{cik:010d}-{year}-000001"


class Res:
    def __init__(self, status, body=None, text="", content=b""):
        self.status_code, self._body, self.text, self.content = status, body, text, content

    def json(self):
        return self._body


class Http:
    def __init__(self, *, companies=COMPANIES, limit_after=None, tiingo_status=200, extra=(), shares=None, assets=None):
        self.calls, self.companies, self.limit_after, self.tiingo_status, self.extra = [], list(companies), limit_after, tiingo_status, list(extra)
        self.filing_calls = 0
        self.shares = shares if shares is not None else {c: v / 40 for c, _n, v, _end, _f in self.companies}
        self.assets = assets if assets is not None else {c: v for c, _n, v, _end, _f in self.companies}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "sec.gov" in url:
            assert headers == {"User-Agent": CONTACT}
        frame = re.search(r"frames/([a-z-]+)/(\w+)/(\w+)/CY(\d{4})Q(\d)I\.json$", url)
        if frame:
            concept, want = frame.group(2), (int(frame.group(4)), int(frame.group(5)))
            if concept == "EntityPublicFloat":
                assert frame.group(1, 3) == ("dei", "USD")
                rows = [{"accn": accn(c), "cik": c, "entityName": n, "loc": "US-NY", "end": end, "val": v} for c, n, v, end, f in self.companies if f == want]
                return Res(200, {"taxonomy": "dei", "tag": "EntityPublicFloat", "data": rows + [r for f, r in self.extra if f == want]})
            side = {"EntityCommonStockSharesOutstanding": ("dei", "shares", self.shares), "Assets": ("us-gaap", "USD", self.assets)}[concept]
            assert frame.group(1, 3) == side[:2]
            if want != (2011, 2):
                return Res(404)
            return Res(200, {"tag": concept, "data": [{"accn": "side", "cik": c, "entityName": "", "end": "2011-06-30", "val": v} for c, v in side[2].items()]})
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
            assert filing.group(2) in (accn(cik).replace("-", ""), accn(cik, 10).replace("-", ""))
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
        "The largest are Alder Works Inc, Birch Holdings Corp and Cedar Systems Inc. "
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
        ((2011, 4), {"accn": "late", "cik": 203, "entityName": "Next Year Co", "end": "2012-01-28", "val": 5.0e10}),
        ((2010, 2), {"accn": "gone", "cik": 204, "entityName": "Gone By Then Co", "end": "2010-06-30", "val": 5.0e10}),
    ]
    http = Http(extra=extra)
    top, left = public.largest(http, CONTACT, sleep=lambda s: None)
    assert [(r["rank"], r["cik"]) for r in top] == [(i, c) for i, (c, *_rest) in enumerate(COMPANIES, 1)]
    assert (top[0]["float_usd"], top[0]["float_at"], top[0]["accn"]) == (9.0e10, "2011-06-30", accn(101))
    assert [(r["name"], r["why"]) for r in left] == [("Typo Billions Inc", "too_big")]
    assert [r["cik"] for r in public.largest(Http(), CONTACT, sleep=lambda s: None, size=3)[0]] == [101, 102, 103]
    asked = [re.search(r"frames/[a-z-]+/(\w+)/\w+/CY(\d{4})Q(\d)I", u).groups() for u in http.calls]
    assert [(y, q) for c, y, q in asked if c == "EntityPublicFloat"] == [(str(y), str(q)) for y, q in (*public.BEFORE, *public.FRAMES)]
    assert sum(c == "EntityCommonStockSharesOutstanding" for c, *_ in asked) == sum(c == "Assets" for c, *_ in asked) == len(public.AROUND)


ROUGH_2011 = [
    (34088, "Exxon Mobil Corp", 4.009e11, "2011-06-30", 2.90e11, 4.9e9, 3.3e11),
    (320193, "Apple Inc", 3.22e11, "2011-03-25", 2.09e11, 9.2e8, 1.07e11),
    (789019, "Microsoft Corp", 2.05e11, "2010-12-31", 2.45e11, 8.4e9, 1.0e11),
    (51143, "International Business Machines Corp", 2.07e11, "2011-06-30", 1.57e11, 1.2e6, 1.1e11),
    (93410, "Chevron Corp", 2.06e11, "2011-06-30", 1.36e11, 2.0e9, 2.0e11),
    (40545, "General Electric Co", 2.00e11, "2011-06-30", 1.54e11, 1.06e10, 7.4e11),
    (104169, "Wal Mart Stores Inc", 9.8e10, "2011-07-29", 9.6e10, 3.4e9, 1.9e11),
    (200406, "Johnson & Johnson", 1.82e8, "2011-06-30", 1.63e11, 2.7e9, 1.1e11),
    (80424, "Procter & Gamble Co", 1.76e11, "2010-12-31", 1.77e11, 2.8e9, 1.4e11),
    (732717, "AT&T Inc", 1.86e14, "2011-06-30", 1.43e11, 5.9e9, 2.7e11),
]
MISTYPED = [
    (901, "Small Devices Inc", 6.2e11, 2.3e7, 9.0e8, "too_big"),
    (902, "Harbor Private Bank Corp", 5.0e11, 7.7e7, 6.0e9, "too_big"),
    (903, "Prairie Farm Life Group", 3.5e11, 3.0e7, 1.5e10, "unbacked"),
    (904, "Shoreline Re Ltd", 4.0e10, None, 3.0e9, "unbacked"),
    (905, "Model Apparel Inc", 3.0e10, 3.0e9, 4.0e8, "over_assets"),
]
FRAME_OF = {"2010-12-31": (2010, 4), "2011-03-25": (2011, 1), "2011-06-30": (2011, 2), "2011-07-29": (2011, 2)}


def giants() -> Http:
    floats, shares, assets = [], {}, {}
    for cik, name, val, end, before, count, total in ROUGH_2011:
        year_before = f"{int(end[:4]) - 1}{end[4:]}"
        floats.append((FRAME_OF[end], {"accn": accn(cik), "cik": cik, "entityName": name, "end": end, "val": val}))
        floats.append(((FRAME_OF[end][0] - 1, FRAME_OF[end][1]), {"accn": accn(cik, 10), "cik": cik, "entityName": name, "end": year_before, "val": before}))
        shares[cik], assets[cik] = count, total
    for cik, name, val, count, total, _why in MISTYPED:
        floats.append(((2011, 2), {"accn": accn(cik), "cik": cik, "entityName": name, "end": "2011-06-30", "val": val}))
        assets[cik] = total
        if count:
            shares[cik] = count
    floats.append(((2011, 2), {"accn": accn(906), "cik": 906, "entityName": "New Motors Co", "end": "2011-06-30", "val": 4.5e10}))
    floats.append(((2011, 2), {"accn": accn(907), "cik": 907, "entityName": "Honest Small Co", "end": "2011-06-30", "val": 4.0e8}))
    shares |= {906: 1.5e9, 907: 2.0e7}
    assets |= {906: 1.4e11, 907: 3.0e8}
    return Http(companies=[], extra=floats, shares=shares, assets=assets)


def test_the_obvious_giants_of_mid_2011_lead_the_list_and_no_mistyped_small_company_is_on_it(desk):
    top, left = public.largest(giants(), CONTACT, sleep=lambda s: None)
    assert {r["name"] for r in top[:10]} == {name for _c, name, *_rest in ROUGH_2011}
    assert [r["name"] for r in top[:3]] == ["Exxon Mobil Corp", "Apple Inc", "International Business Machines Corp"]
    assert top[10]["name"] == "New Motors Co" and len(top) == 11
    assert not {r["cik"] for r in top} & {cik for cik, *_rest in MISTYPED} and all(r["float_usd"] <= public.FLOAT_MAX for r in top)
    assert [(r["name"], r["why"]) for r in left] == [(name, why) for _c, name, _v, _s, _a, why in MISTYPED]
    by = {r["name"]: r for r in top}
    assert (by["AT&T Inc"]["float_usd"], by["AT&T Inc"]["float_at"]) == (1.43e11, "2010-06-30")
    assert (by["Johnson & Johnson"]["float_usd"], by["Johnson & Johnson"]["float_at"]) == (1.63e11, "2010-06-30")
    assert by["International Business Machines Corp"]["float_usd"] == 2.07e11 and by["Wal Mart Stores Inc"]["float_at"] == "2011-07-29"
    out = run(desk, giants())
    assert out["ok"] and out["listed"] == 11 and out["top"][:2] == ["Exxon Mobil Corp", "Apple Inc"] and out["left_out_count"] == 5
    assert out["left_out"][0] == "Small Devices Inc ($620 billion, larger than any company was)"
    assert out["left_out"][2] == "Prairie Farm Life Group ($350 billion, nothing else the company reported backs it)"
    assert out["left_out"][4] == "Model Apparel Inc ($30 billion, far above its own balance sheet)"
    assert "The largest are Exxon Mobil Corp, Apple Inc and International Business Machines Corp." in out["detail"]
    assert "5 companies were left out because the size they reported looks mistyped." in out["detail"] and not NOT_PLAIN.search(out["detail"])
    assert len(public.names(desk)) == 11 and [r["name"] for r in public.left_out(desk)] == [name for _c, name, *_rest in MISTYPED]
    assert public.coverage(desk, set())["listed"] == 11
    view = public.view(desk, now=NOW)
    assert len(view["names"]) == 11 and view["left_out_names"][0] == {
        "name": "Small Devices Inc",
        "cik": 901,
        "float_usd": 6.2e11,
        "float_at": "2011-06-30",
        "why": "larger than any company was",
    }


def test_a_fund_is_left_out_so_the_next_company_takes_its_place_and_google_is_read_through_its_older_shares(desk, monkeypatch):
    more = [
        (108, "Bullion Bars Trust", 8.5e10, "2011-06-30", (2011, 2)),
        (110, "Search Engine Inc", 2.0e10, "2010-12-31", (2010, 4)),
        (111, "Hickory Tools Co", 1.0e10, "2011-06-30", (2011, 2)),
    ]
    monkeypatch.setattr(public, "SIZE", 8)
    http = Http(companies=COMPANIES + more)
    out = run(desk, http)
    rows = public.names(desk)
    assert [r["name"].split()[0] for r in rows] == ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Gum", "Search"]
    assert [r["rank"] for r in rows] == list(range(1, 9)) and out["listed"] == out["wanted"] == 8
    search = rows[-1]
    assert (search["symbol"], search["source"], search["state"], search["trading"], search["first_bar"]) == ("GOOGL", "filing_file", "priced", 1, "2004-08-19")
    assert by_name(desk)["Gum"]["state"] == "missing"
    assert out["funds"] == ["Bullion Bars Trust"] and out["left_out_count"] == 0 and out["left_out"] == []
    assert "1 fund or trust was left out because it is not a company." in out["detail"] and "mistyped" not in out["detail"]
    assert not NOT_PLAIN.search(out["detail"]) and not any("/edgar/data/108/" in u for u in http.calls)
    assert [(r["name"], r["source"]) for r in public.left_out(desk)] == [("Bullion Bars Trust", "fund")]
    aside = public.view(desk, now=NOW)["left_out_names"]
    assert [(r["name"], r["why"]) for r in aside] == [("Bullion Bars Trust", "a fund or trust, not a company")]
    assert public.coverage(desk, set())["listed"] == 8
    two = dict(out, funds=["Bullion Bars Trust", "Silver Bars Trust"])
    assert "2 funds or trusts were left out because they are not companies." in public.words(two)


def test_a_float_needs_a_second_figure_that_agrees_and_must_fit_the_balance_sheet():
    fact = {"val": 4.0e10, "end": "2011-06-30"}
    year_ago, last_quarter = {"val": 3.0e10, "end": "2010-06-30"}, {"val": 3.0e10, "end": "2011-03-31"}
    assert public.doubt(fact, [], None, None) == "unbacked" and public.doubt(fact, [last_quarter], None, None) == "unbacked"
    assert public.doubt(fact, [year_ago], None, None) is None and public.doubt(fact, [], 1.0e9, None) is None
    assert public.doubt(fact, [{"val": 4.0e7, "end": "2010-06-30"}], None, None) == "unbacked"
    assert public.doubt(fact, [], 1.0e6, None) == "unbacked" and public.doubt(fact, [], 1.0e11, None) == "unbacked"
    assert public.doubt(fact, [year_ago], 1.0e6, None) is None
    assert public.doubt(fact, [year_ago], 1.0e9, 2.0e9) == "over_assets" and public.doubt(fact, [year_ago], 1.0e9, 4.0e9) is None
    assert public.doubt({"val": 4.6e11, "end": "2011-06-30"}, [year_ago], 1.0e10, 9.0e11) == "too_big"


def test_a_list_built_before_the_checks_is_built_again_at_once(desk):
    run(desk)
    assert run(desk, now=NOW + timedelta(hours=4))["fresh"] is True
    with desk:
        desk.execute("DELETE FROM api_calls WHERE provider=?", (public.CALLS,))
    again = Http()
    assert run(desk, again, now=NOW + timedelta(hours=8))["fresh"] is False and again.calls


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
    week_on = run(desk, Http(limit_after=0), now=NOW + timedelta(days=8))
    kept = by_name(desk)
    assert (kept["Cedar"]["symbol"], kept["Cedar"]["state"], kept["Cedar"]["trading"]) == ("CCC", "priced", 0) and kept["Dogwood"]["state"] == "priced"
    assert week_on["priced"] == second["priced"] and week_on["not_asked"] == ["Elm Retail Group", "Fir Paper Co", "Gum Tree Foods Inc (GGG)"]


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


def test_coverage_counts_what_the_lab_has_and_only_a_name_never_asked_for_is_still_loading(desk):
    assert public.coverage(desk, set()) is None
    run(desk)
    priced = sorted(r["symbol"] for r in public.names(desk) if r["state"] == public.PRICED)
    assert len(priced) >= 3
    first = public.coverage(desk, set())
    assert first["listed"] == 7 and first["priced"] == 0 and first["loading"] == len(priced) and first["missing"] == 7 - len(priced)
    assert first["as_of"] == public.AS_OF and first["tests_from"] == public.TESTS_FROM and not first["enough"]
    with desk:
        desk.executemany(
            "INSERT INTO market_symbols (symbol, role, priority, added_at, fetched_at) VALUES (?, 'public', 4, ?, ?)",
            [(s, NOW.isoformat(), NOW.isoformat()) for s in priced[:2]],
        )
    part = public.coverage(desk, {priced[0]})
    assert part["priced"] == 1 and part["loading"] == len(priced) - 2 and part["missing"] == 7 - 1 - part["loading"] and part["pct"] == 14.3
    stopped = sum(1 for r in public.names(desk) if r["state"] == public.PRICED and not r["trading"])
    assert public.coverage(desk, set(priced))["stopped"] == stopped and public.coverage(desk, set(priced))["loading"] == 0
    whole = [dict(r) | {"state": public.PRICED, "symbol": r["symbol"] or f"X{r['rank']}", "trading": 1} for r in public.names(desk)]
    public.store(desk, whole, NOW)
    full = public.coverage(desk, {r["symbol"] for r in whole})
    assert full["priced"] == full["listed"] == 7 and full["pct"] == 100.0 and full["enough"] and full["missing"] == 0


def test_the_job_is_light_runs_in_the_daytime_and_has_a_title_a_person_can_read():
    job = next(j for j in package_jobs(["engine"]) if j.name == "engine-public")
    assert (job.title, job.heavy) == ("Public stock list", False) and "public" in COMMANDS
    assert job.spec[1] and all(9 <= h < 16 for h in job.spec[1])
