import json
import sqlite3

import pytest

from desk.engine import schema
from desk.engine.lab import fund
from desk.engine.lab import library as features
from desk.engine.lab.data import EXPORT_SCHEMA, PUBLIC_COVERAGE, PUBLIC_ROLE, load
from desk.engine.lab.spec import FIGURE_NOTES, SpecError, parse
from tests.engine.test_shelf import weekdays

ENDS = ("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31")
REPORTED = ("2023-04-25", "2023-07-25", "2023-10-24", "2024-01-30", "2024-04-23")


def quarter(end, reported, eps=1.0, revenue=100.0, operating_income=20.0):
    return {"period_end": end, "reported": reported, "eps": eps, "revenue": revenue, "operating_income": operating_income}


# ---- Trailing four quarters ----


def test_four_quarters_add_up_and_count_from_the_day_the_last_was_reported():
    rows = fund.trailing([quarter(e, r, eps=i + 1.0, operating_income=10.0 * (i + 1)) for i, (e, r) in enumerate(zip(ENDS, REPORTED, strict=True))])
    assert [(r["known"], r["eps"], round(r["margin"], 4), r["lagged"]) for r in rows] == [("2024-01-30", 10.0, 0.25, False), ("2024-04-23", 14.0, 0.35, False)]
    assert fund.trailing([quarter(e, r) for e, r in zip(ENDS[:3], REPORTED[:3], strict=True)]) == []


def test_a_missing_quarter_a_missing_figure_and_a_missing_report_day_are_each_handled():
    gap = [quarter(e, r) for e, r in zip(ENDS, REPORTED, strict=True) if e != "2023-09-30"]
    assert fund.trailing(gap) == []
    no_sales = [quarter(e, r, revenue=None) for e, r in zip(ENDS, REPORTED, strict=True)]
    assert [(r["eps"], r["margin"]) for r in fund.trailing(no_sales)] == [(4.0, None), (4.0, None)]
    no_eps = [quarter(e, r, eps=None if e == ENDS[0] else 1.0) for e, r in zip(ENDS, REPORTED, strict=True)]
    assert [(r["eps"], r["margin"]) for r in fund.trailing(no_eps)] == [(None, 0.2), (4.0, 0.2)]
    undated = [quarter(e, None if e == ENDS[3] else r) for e, r in zip(ENDS, REPORTED, strict=True)]
    first, second = fund.trailing(undated)
    assert (first["known"], first["lagged"]) == ("2024-03-15", True) and (second["known"], second["lagged"]) == ("2024-04-23", False)
    assert fund.LAG_DAYS == 75 and fund.trailing([quarter(e, r, revenue=0.0) for e, r in zip(ENDS, REPORTED, strict=True)])[0]["margin"] is None


def test_the_same_quarter_under_two_nearby_end_dates_is_one_quarter():
    split = []
    for e, r in zip(ENDS, REPORTED, strict=True):
        split.append({"period_end": e[:8] + "28", "reported": r, "eps": 1.0})
        split.append({"period_end": e, "reported": None, "revenue": 100.0, "operating_income": 20.0})
    rows = fund.trailing(split)
    assert [(r["known"], r["eps"], r["margin"], r["lagged"]) for r in rows] == [("2024-01-30", 4.0, 0.2, False), ("2024-04-23", 4.0, 0.2, False)]


# ---- Export: public list names only, in the share count the earnings are quoted in ----


@pytest.fixture
def desk(tmp_path):
    conn = sqlite3.connect(tmp_path / "desk.db")
    conn.row_factory = sqlite3.Row
    schema.apply(conn)
    yield conn
    conn.close()


def bars(conn, symbol, days, close, splits=None):
    rows = [(symbol, d, close(d), close(d), (splits or {}).get(d, 1.0)) for d in days]
    conn.executemany("INSERT INTO price_bars (symbol, date, close, adj_close, split_factor) VALUES (?, ?, ?, ?, ?)", rows)


def quarters(conn, symbol, rows, fetched="2024-06-01T02:10:00+00:00"):
    conn.executemany(
        "INSERT INTO av_quarters (symbol, period_end, reported, eps, revenue, operating_income) VALUES (?, ?, ?, ?, ?, ?)",
        [(symbol, q["period_end"], q["reported"], q["eps"], q["revenue"], q["operating_income"]) for q in rows],
    )
    conn.execute("INSERT INTO av_fetches VALUES (?, ?, ?, NULL)", (symbol, fetched, len(rows)))


def test_the_price_is_put_in_the_share_count_the_earnings_were_fetched_in(desk):
    days = weekdays("2024-01-02", "2024-08-30")
    bars(desk, "AAA", days, lambda d: 400.0 if d < "2024-03-01" else (100.0 if d < "2024-07-01" else 50.0), {"2024-03-01": 4.0, "2024-07-01": 2.0})
    want = ["2024-01-30", "2024-04-23", "2024-01-28", "2023-12-01"]
    assert fund.split_closes(desk, "AAA", want, "2024-06-01") == {"2024-01-30": 100.0, "2024-04-23": 100.0, "2024-01-28": 100.0}
    assert fund.split_closes(desk, "AAA", want, "2024-08-01") == {"2024-01-30": 50.0, "2024-04-23": 50.0, "2024-01-28": 50.0}
    assert fund.split_closes(desk, "AAA", want, "2024-02-01")["2024-01-30"] == 400.0 and fund.split_closes(desk, "NONE", want, "2024-06-01") == {}


def test_only_public_list_names_are_exported_and_coverage_says_what_is_still_to_load(desk):
    days = weekdays("2023-01-02", "2024-06-28")
    spans = {s: (days[0], days[-1]) for s in ("AAA", "BBB", "CCC", "BRK-B", "ODD")}
    for sym in ("AAA", "BBB", "MINE", "ODD"):
        bars(desk, sym, days, lambda d: 50.0)
    rows = [quarter(e, r) for e, r in zip(ENDS, REPORTED, strict=True)]
    quarters(desk, "AAA", rows)
    quarters(desk, "MINE", rows)
    quarters(desk, "ODD", [q | {"eps": 30.0} for q in rows])
    out, cover = fund.build(desk, {"AAA", "BBB", "CCC", "BRK-B", "ODD", "UNPRICED"}, spans, "2023-01-02")
    assert out == [("AAA", "2024-01-30", 0.08, 0.2), ("AAA", "2024-04-23", 0.08, 0.2), ("ODD", "2024-01-30", None, 0.2), ("ODD", "2024-04-23", None, 0.2)]
    assert cover == {
        "listed": 5,
        "asked": 2,
        "loading": 2,
        "lagged": 0,
        "odd": 2,
        "eps_basis": fund.TODAYS_SHARES,
        "split_votes": [0, 0],
        fund.YIELD: {"have": 1, "from": None},
        fund.MARGIN: {"have": 2, "from": None},
    }
    quarters(desk, "BBB", rows)
    quarters(desk, "CCC", [])
    out, cover = fund.build(desk, {"AAA", "BBB", "CCC", "ODD"}, {s: spans[s] for s in ("AAA", "BBB", "CCC", "ODD")}, "2023-01-02")
    assert cover["loading"] == 0 and cover["asked"] == 4 and cover[fund.YIELD] == {"have": 2, "from": None}
    assert fund.build(desk, {"AAA", "BBB"}, {s: spans[s] for s in ("AAA", "BBB")}, "2023-01-02")[1][fund.YIELD] == {"have": 2, "from": "2024-04-01"}
    assert fund.build(desk, set(), spans, None) == ([], None)


def test_the_share_count_old_earnings_are_quoted_in_is_read_off_the_splits(desk):
    ends = ("2022-12-31", *ENDS, "2024-06-30")
    days = ("2023-01-31", *REPORTED, "2024-07-23")
    cuts = [("2024-03-01", 4.0)]
    in_todays = [quarter(e, r, eps=1.0 + 0.05 * i) for i, (e, r) in enumerate(zip(ends, days, strict=True))]
    as_first = [q | {"eps": q["eps"] * (4.0 if q["reported"] < "2024-03-01" else 1.0)} for q in in_todays]
    assert fund.split_votes(in_todays, cuts) == (1, 0) and fund.split_votes(as_first, cuts) == (0, 1)
    assert fund.split_votes(as_first, [("2024-03-01", 1.02)]) == (0, 0) and fund.split_votes(as_first[:5], cuts) == (0, 0)
    assert [round(q["eps"], 4) for q in fund.restated(as_first, cuts)] == [round(q["eps"], 4) for q in in_todays]
    span = weekdays("2022-06-01", "2024-08-30")
    bars(desk, "AAA", span, lambda d: 400.0 if d < "2024-03-01" else 100.0, {"2024-03-01": 4.0})
    quarters(desk, "AAA", as_first, fetched="2024-08-01T02:10:00+00:00")
    assert fund.splits(desk, "AAA", "2024-08-01") == [("2024-03-01", 4.0)] and fund.splits(desk, "AAA", "2024-02-01") == []
    out, cover = fund.build(desk, {"AAA"}, {"AAA": (span[0], span[-1])}, "2022-06-01")
    assert (cover["eps_basis"], cover["split_votes"], cover["odd"]) == (fund.AS_REPORTED, [0, 1], 0)
    assert [(day, round(ey, 4)) for _, day, ey, _ in out] == [("2023-10-24", 0.043), ("2024-01-30", 0.045), ("2024-04-23", 0.047), ("2024-07-23", 0.049)]
    desk.execute("DELETE FROM av_quarters")
    desk.execute("DELETE FROM av_fetches")
    quarters(desk, "AAA", in_todays, fetched="2024-08-01T02:10:00+00:00")
    again, cover = fund.build(desk, {"AAA"}, {"AAA": (span[0], span[-1])}, "2022-06-01")
    assert (cover["eps_basis"], cover["split_votes"]) == (fund.TODAYS_SHARES, [1, 0]) and again == pytest.approx(out)


def test_coverage_starts_the_first_quarter_nine_in_ten_live_names_have_figures():
    spans = {f"S{i}": ("2010-01-04", "2024-12-31") for i in range(10)} | {"LATE": ("2015-06-01", "2024-12-31"), "GONE": ("2010-01-04", "2012-03-30")}
    firsts = {f"S{i}": "2011-05-01" for i in range(8)} | {"S8": "2013-02-10", "S9": "2019-01-01", "LATE": "2016-08-01"}
    assert fund.quarter_starts("2012-01-03", "2012-12-31") == ["2012-01-03", "2012-04-01", "2012-07-01", "2012-10-01"]
    assert fund.first_covered(firsts, spans, "2012-01-03", "2024-12-31") == "2013-04-01"
    assert fund.first_covered({k: v for k, v in firsts.items() if k not in ("S7", "S8")}, spans, "2012-01-03", "2024-12-31") is None


# ---- In the lab: the feature, and when a screen may use it ----


@pytest.fixture
def lab_file(tmp_path):
    days = weekdays("2014-01-02", "2024-12-31")
    path = tmp_path / "lab.db"
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    for n, sym in enumerate(("SPY", "AAA", "BBB", "CCC")):
        rows = [(sym, d, 100.0 + i * 0.01 * n, 100.0 + i * 0.01 * n, 100.0 + i * 0.01 * n, 5e6) for i, d in enumerate(days)]
        conn.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute(
            "INSERT INTO symbols VALUES (?, ?, ?, ?, ?)",
            (sym, "etf" if sym == "SPY" else "stock", "benchmark" if sym == "SPY" else PUBLIC_ROLE, days[0], days[-1]),
        )
    conn.executemany(
        "INSERT INTO fundamentals VALUES (?, ?, ?, ?)", [("AAA", days[10], 0.05, 0.3), ("AAA", days[200], 0.06, None), ("BBB", days[10], None, 0.1)]
    )
    public = {
        "as_of": "2013-06-28",
        "tests_from": "2014-01-02",
        "listed": 3,
        "priced": 3,
        "loading": 0,
        "missing": 0,
        "stopped": 0,
        "pct": 100.0,
        "enough": True,
    }
    conn.execute("INSERT INTO settings VALUES (?, ?)", (PUBLIC_COVERAGE, json.dumps(public)))
    conn.commit()
    conn.close()
    return path


def cover(path, **change):
    body = {
        "listed": 3,
        "asked": 3,
        "loading": 0,
        "lagged": 0,
        "odd": 0,
        fund.YIELD: {"have": 3, "from": "2014-04-01"},
        fund.MARGIN: {"have": 3, "from": "2015-01-01"},
    }
    conn = sqlite3.connect(path)
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (fund.COVERAGE, json.dumps(body | change)))
    conn.commit()
    conn.close()
    return load(path)


def screen(metric, **more):
    spec = {"id": "figures-screen", "version": 1, "title": "Figures", "hypothesis": "Figures matter.", "predicted_effect": "+1 point a year", "horizons": [3]}
    spec |= {
        "universe": {"type": "screen"},
        "signals": [{"metric_id": metric, "window": "126d", "transform": "rank"}],
        "entry": {"top_n": 2},
        "benchmark": "SPY",
    }
    return spec | {"rebalance": "quarterly", "sizing": "equal", "exit": "rebalance", "success_criteria": {"excess_vs_plan_pts": 0.0}} | more


def test_the_yield_moves_with_the_price_and_a_report_goes_stale(lab_file):
    data = load(lab_file)
    s = data.series["AAA"]
    events = data.fund[fund.YIELD]["AAA"]
    assert features.value(fund.YIELD, s, 5, 126, events) is None and features.value(fund.YIELD, s, 10, 126, events) == 0.05
    assert features.value(fund.YIELD, s, 110, 126, events) == pytest.approx(0.05 * s.adj[10] / s.adj[110]) and s.adj[110] > s.adj[10]
    assert features.value(fund.YIELD, s, 136, 126, events) is None and features.value(fund.YIELD, s, 200, 126, events) == 0.06
    margins = data.fund[fund.MARGIN]
    assert features.value(fund.MARGIN, s, 100, 126, margins["AAA"]) == 0.3 and features.value(fund.MARGIN, s, 200, 126, margins["AAA"]) is None
    assert set(margins) == {"AAA", "BBB"} and set(data.fund[fund.YIELD]) == {"AAA"} and features.value(fund.MARGIN, s, 100, 126, None) is None
    kinds = {c["metric_id"]: c["kind"] for c in features.catalog()}
    assert kinds[fund.YIELD] == kinds[fund.MARGIN] == "fundamental"


def test_a_screen_on_company_figures_waits_until_every_company_is_loaded(lab_file):
    with pytest.raises(SpecError, match="is not in the lab's data yet"):
        parse(screen(fund.YIELD), load(lab_file))
    with pytest.raises(SpecError, match="still loading: 2 of 3 listed companies are in and 1 are on the way"):
        parse(screen(fund.YIELD), cover(lab_file, asked=2, loading=1))
    with pytest.raises(SpecError, match="only reaches 2 of 3 listed companies"):
        parse(screen(fund.MARGIN), cover(lab_file, **{fund.MARGIN: {"have": 2, "from": "2015-01-01"}}))
    with pytest.raises(SpecError, match="too few to test"):
        parse(screen(fund.MARGIN), cover(lab_file, **{fund.MARGIN: {"have": 3, "from": None}}))
    with pytest.raises(SpecError, match="only reaches back to 2021-01-01"):
        parse(screen(fund.MARGIN), cover(lab_file, **{fund.MARGIN: {"have": 3, "from": "2021-01-01"}}))
    with pytest.raises(SpecError, match="needs a screen universe"):
        parse(screen(fund.YIELD, universe={"type": "fund_list", "symbols": ["SPY"]}), cover(lab_file))
    data = cover(lab_file)
    cheap, rich = parse(screen(fund.YIELD), data), parse(screen(fund.MARGIN), data)
    assert (cheap.start, rich.start) == ("2014-04-01", "2015-01-01")
    assert FIGURE_NOTES[fund.YIELD] in cheap.caveats and FIGURE_NOTES[fund.MARGIN] in rich.caveats and FIGURE_NOTES[fund.MARGIN] not in cheap.caveats
    words = next(c for c in cheap.caveats if c.startswith("Company figures"))
    assert "3 of 3 listed companies have them, and the test starts 2014-04-01" in words and "DESK_" not in words and "{" not in words
