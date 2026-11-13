import json
from datetime import date, timedelta

import pytest

from desk.engine.lab import grammar, listrules, rulebook
from desk.engine.lab.data import PUBLIC_COVERAGE, PUBLIC_ROLE, DayIndex, LabData, Series
from desk.engine.lab.listrules import Case
from desk.engine.lab.rulebook import RuleError
from desk.engine.lab.sim import FUND_BPS, LTCG, STOCK_BPS
from desk.engine.lab.spec import PUBLIC_EXITS

SB, FB, RATE = STOCK_BPS / 10_000, FUND_BPS / 10_000, 0.24
COVER = {"as_of": "2011-06-30", "tests_from": "2012-01-02", "listed": 3, "priced": 3, "loading": 0, "missing": 0, "stopped": 0, "pct": 100.0, "enough": True}


def weekdays(start: str, end: str) -> list[str]:
    out, d, e = [], date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DAYS = weekdays("2010-01-04", "2022-12-30")
AT = {d: i for i, d in enumerate(DAYS)}


def steps(*moves, last: str | None = None) -> list[float]:
    out, px, at = [], 100.0, dict(moves)
    for d in DAYS:
        if last and d > last:
            break
        px = at.get(d, px)
        out.append(px)
    return out


def lab(stocks: dict[str, list[float]], spy: list[float] | None = None, cover: dict | None = COVER) -> LabData:
    pos = dict(AT)
    series, kinds, roles = {}, {"SPY": "etf"}, {"SPY": "benchmark"}
    for sym, path in {"SPY": spy or [100.0] * len(DAYS), **stocks}.items():
        dates = DAYS[: len(path)]
        series[sym] = Series(dates, path, path, [1e6] * len(path), DayIndex(pos, dates))
        if sym != "SPY":
            kinds[sym], roles[sym] = "stock", PUBLIC_ROLE
    settings = {"marginal_rate_pct": "24"} | ({PUBLIC_COVERAGE: json.dumps(cover)} if cover else {})
    return LabData(series, kinds, roles, {s: x.dates[-1] for s, x in series.items()}, {}, {}, settings, DAYS)


def ctx_of(data: LabData) -> listrules.Ctx:
    start = "2012-01-02"
    firsts = listrules._firsts
    names, gone = listrules._names(data), listrules.gone_before(DAYS)
    return listrules.Ctx(data, DAYS, data.series["SPY"], RATE, gone, names, firsts(DAYS, 3, start), firsts(DAYS, 12, start))


def after(value: float, basis: float, rate: float) -> float:
    return value - (value - basis) * rate


def request(rule: str, params: dict, **more) -> dict:
    return {"request": "rule", "id": f"t-{rule}", "version": 1, "rule": rule, "params": params, **more}


# ---- Cases ----


def test_a_case_is_the_first_close_that_far_under_the_one_year_high_and_waits_a_year_to_count_again():
    data = lab({"AAA": steps(("2013-03-01", 50.0), ("2013-06-03", 45.0), ("2016-02-01", 20.0)), "BBB": steps(("2013-03-01", 51.0))})
    ctx = ctx_of(data)
    cases = listrules._drops(ctx, "AAA", 50)
    assert [(c.day, c.high, c.high_day) for c in cases] == [("2013-03-04", 100.0, "2013-02-28"), ("2016-02-02", 45.0, "2016-01-29")]
    assert listrules._drops(ctx, "BBB", 50) == [] and [c.day for c in listrules._drops(ctx, "BBB", 30)] == ["2013-03-04"]
    cheap = lab({"AAA": [x / 25 for x in steps(("2013-03-01", 50.0))]})
    assert listrules._drops(ctx_of(cheap), "AAA", 50) == []
    young = lab({"AAA": steps(("2010-06-01", 40.0))})
    assert listrules._drops(ctx_of(young), "AAA", 50) == []
    assert ctx.quarters[:3] == ["2012-01-02", "2012-04-02", "2012-07-02"] and ctx.januaries[:2] == ["2012-01-02", "2013-01-01"]


# ---- Averaging down ----


def test_averaging_down_compares_a_dollar_in_the_fallen_company_with_a_dollar_in_the_index_after_tax():
    data = lab({"AAA": steps(("2013-03-01", 50.0), ("2013-09-02", 75.0))}, spy=steps(("2013-09-02", 110.0)))
    ctx = ctx_of(data)
    rule = listrules.parse(request("average_down", {"drop_pct": 50}), data)
    case = listrules._drops(ctx, "AAA", 50)[0]
    diff, tax, tracking = listrules._average_down(ctx, rule, {"drop_pct": 50}, case, "2014-03-04")
    stock, index = 1.5 * (1 - SB) ** 2, 1.1 * (1 - FB) ** 2
    assert diff == pytest.approx((after(stock, 1, LTCG) - after(index, 1, LTCG)) * 100) and tax is None and tracking is None
    assert diff == pytest.approx(33.71, abs=0.01)


def test_a_company_that_stops_trading_leaves_at_its_last_price_and_the_money_moves_to_the_index():
    bought = lab({"AAA": steps(("2013-03-01", 50.0), ("2013-06-03", 80.0), last="2013-08-30")}, spy=steps(("2013-12-02", 120.0)))
    ctx = ctx_of(bought)
    assert listrules._grow(ctx, "AAA", "2013-03-04", "2014-03-04") == pytest.approx(80 / 50 * 1.2)
    failed = lab({"AAA": steps(("2013-03-01", 50.0), ("2013-06-03", 10.0), last="2013-08-30")}, spy=steps(("2013-12-02", 120.0)))
    assert listrules._grow(ctx_of(failed), "AAA", "2013-03-04", "2014-03-04") == pytest.approx(10 / 50 * 0.7 * 1.2)
    assert listrules._grow(ctx, "AAA", "2013-09-02", "2014-03-04") is None and listrules._grow(ctx, "SPY", "2013-03-04", "2014-03-04") == pytest.approx(1.2)


# ---- Capping a position ----


def test_a_capped_position_is_trimmed_on_day_one_and_each_quarter_and_pays_tax_on_the_gain_it_sells():
    data = lab({"AAA": steps(("2012-02-01", 200.0))})
    ctx = ctx_of(data)
    t0, t1 = "2012-01-02", "2015-01-02"
    run = listrules._held(ctx, "AAA", t0, t1, 0.30, None)
    n0, s0 = 0.30 * (1 - SB) / 100, 0.70 * (1 - FB) / 100
    assert run == pytest.approx(after(n0 * 200 * (1 - SB), n0 * 100, LTCG) + after(s0 * 100 * (1 - FB), s0 * 100, LTCG))
    cost = SB + FB * (1 - SB)
    sold = (n0 * 100 - 0.25 * (n0 + s0) * 100) / (1 - 0.25 * cost) / 100
    n1, s1 = n0 - sold, sold * 100 * (1 - SB) * (1 - FB) / 100
    assert n1 * 100 == pytest.approx(0.25 * (n1 + s0 + s1) * 100)
    cost = SB + 0.5 * RATE
    cost += FB * (1 - cost)
    worth, total = n1 * 200, n1 * 200 + (s0 + s1) * 100
    sold = (worth - 0.25 * total) / (1 - 0.25 * cost) / 200
    n2, s2 = n1 - sold, (sold * 200 * (1 - SB) - sold * 100 * RATE) * (1 - FB) / 100
    assert n2 * 200 == pytest.approx(0.25 * (n2 * 200 + (s0 + s1 + s2) * 100))
    capped = after(n2 * 200 * (1 - SB), n2 * 100, LTCG) + sum(after(s * 100 * (1 - FB), s * 100, LTCG) for s in (s0, s1, s2))
    assert listrules._held(ctx, "AAA", t0, t1, 0.30, 0.25) == pytest.approx(capped)
    rule = listrules.parse(request("cap_position", {"cap_pct": [25, 10]}), data)
    diff = listrules._cap_position(ctx, rule, {"cap_pct": 25.0}, Case("AAA", t0), t1)[0]
    assert diff == pytest.approx((capped - run) * 100) and diff < 0
    assert listrules._cap_position(ctx, rule, {"cap_pct": 10.0}, Case("AAA", t0), t1)[0] < diff


def test_capping_helps_when_the_company_falls_and_a_flat_one_only_costs_the_fees():
    data = lab({"DOWN": steps(("2012-02-01", 40.0)), "FLAT": steps(), "GONE": steps(("2012-02-01", 30.0), last="2012-08-31")})
    ctx = ctx_of(data)
    rule = listrules.parse(request("cap_position", {"cap_pct": 10}), data)
    t0, t1 = "2012-01-02", "2015-01-02"
    down, flat, gone = (listrules._cap_position(ctx, rule, {"cap_pct": 10.0}, Case(s, t0), t1)[0] for s in ("DOWN", "FLAT", "GONE"))
    assert down == pytest.approx(0.20 * 0.6 * (1 - LTCG) * 100, abs=0.1) and -0.1 < flat < 0 and gone > down
    assert listrules._held(ctx, "GONE", t0, t1, 0.30, None) == pytest.approx(after(0.3 * 0.3 * 0.7, 0.3, RATE) + 0.7, abs=0.002)
    with pytest.raises(RuleError, match="cap_pct must sit under the starting 30%"):
        listrules.parse(request("cap_position", {"cap_pct": [25, 40]}), data)


# ---- Harvest and return ----


def test_harvest_and_return_reports_the_tax_value_and_the_month_away_apart():
    data = lab({"AAA": steps(("2013-03-01", 60.0))})
    ctx = ctx_of(data)
    rule = listrules.parse(request("harvest_return", {"drop_pct": 30}), data)
    case = listrules._drops(ctx, "AAA", 30)[0]
    assert (case.day, case.high, case.high_day) == ("2013-03-04", 100.0, "2013-02-28")
    total, tax, tracking = listrules._harvest_return(ctx, rule, {"drop_pct": 30.0}, case, "2014-03-04")
    hold = 0.6 * (1 - SB)
    sold = 0.6 * (1 - SB)
    away = sold * (1 - FB) ** 2
    ended = away * (1 - SB) ** 2
    harvest = after(ended, away, RATE) - (away - sold) * RATE + (1 - sold) * RATE
    assert total == pytest.approx((harvest - after(hold, 1, LTCG)) * 100) and tracking == pytest.approx((ended - hold) * 100)
    assert tax == pytest.approx(total - tracking) and tax == pytest.approx(0.4 * (RATE - LTCG) * 100, abs=0.1) and -0.3 < tracking < 0
    ran = lab({"AAA": steps(("2013-03-01", 60.0), ("2013-03-15", 90.0))})
    total, tax, tracking = listrules._harvest_return(ctx_of(ran), rule, {"drop_pct": 30.0}, listrules._drops(ctx_of(ran), "AAA", 30)[0], "2014-03-04")
    assert tracking == pytest.approx((0.6 - 0.9) * 100, abs=0.3) and total < 0 and tax == pytest.approx(total - tracking)
    bought = lab({"AAA": steps(("2013-03-01", 60.0), last="2013-03-20")})
    out = listrules._harvest_return(ctx_of(bought), rule, {"drop_pct": 30.0}, listrules._drops(ctx_of(bought), "AAA", 30)[0], "2014-03-04")
    assert out is not None and out[2] == pytest.approx(0.0, abs=0.2)


# ---- The whole run ----


def many(n: int = 8) -> dict[str, list[float]]:
    out = {}
    for k in range(n):
        fall = DAYS[AT["2013-03-01"] + 23 * k]
        back = DAYS[AT[fall] + 150]
        out[f"S{k}"] = steps((fall, 45.0), (back, 45.0 + 15.0 * k))
    return out


def test_each_month_gets_one_vote_and_too_few_months_is_no_result():
    got = [("2013-03", "A", 10.0, 4.0, 6.0), ("2013-03", "B", -30.0, 2.0, -32.0), ("2013-04", "C", 5.0, 1.0, 4.0)]
    assert listrules._summary(got) == {"starts": 0, "too_few": 2, "cases": 3}
    got += [(f"2014-{m:02d}", "D", float(m), 1.0, m - 1.0) for m in range(1, 6)]
    out = listrules._summary(got)
    assert out["starts"] == 7 and out["cases"] == 8 and out["names"] == 4 and out["share_better"] == pytest.approx(6 / 7, abs=1e-4)
    assert out["mean_pts"] == pytest.approx((-10 + 5 + 15) / 7, abs=1e-4) and out["case_share_better"] == 0.875
    assert out["tax_pts"] + out["tracking_pts"] == pytest.approx(out["mean_pts"], abs=1e-3)
    assert "tax_pts" not in listrules._summary([(f"2014-{m:02d}", "D", float(m), None, None) for m in range(1, 8)])


def test_a_rule_runs_across_the_public_list_and_stores_a_result_shaped_like_a_deposit_rule(cfg):
    from desk.engine.lab.runner import ledger

    data = lab(many())
    conn = ledger(cfg)
    now = rulebook.datetime(2023, 1, 3, 6, 0)
    body = rulebook.run(conn, data, request("average_down", {"drop_pct": 50}, library_rev=2), now=now)
    assert body["kind"] == "rule" and body["rule"] == "average_down" and body["across"] == "public_stock_list" and body["names"] == 8
    assert body["windows"] == {"start": "2012-01-02", "end": "2020-12-29", "holdout_start": "2020-12-30", "last": "2022-12-30"}
    on_the_list = "Tested on the 3 largest US companies of mid-2011, a list that owes nothing to what you hold. All 3 have prices."
    assert body["caveats"][:2] == [on_the_list, PUBLIC_EXITS]
    assert body["caveats"][-1].startswith("Only 8 months with a case fit before the two-year holdout")
    v = body["variants"][0]
    assert [h["years"] for h in v["horizons"]] == [1, 3, 5] and {h["starts"] for h in v["horizons"]} == {8} and {h["cases"] for h in v["horizons"]} == {8}
    assert v["full"] == {"years": 5, "starts": 8, "cases": 8, "names": 8} and v["holdout"] == {"starts": 0, "too_few": 0, "cases": 0}
    assert v["horizons"][0]["share_better"] == 0.875 and v["verdict"] == body["verdict"] == "no_clear_edge" and body[PUBLIC_COVERAGE] == COVER
    stored = conn.execute("SELECT kind, body FROM lab_results WHERE strategy_id='t-average_down'").fetchone()
    assert stored[0] == "rule" and json.loads(stored[1])["library_rev"] == 2
    assert tuple(conn.execute("SELECT kind, count(*) FROM strategy_trials").fetchone()) == ("rule", 1)
    for name, params in (("cap_position", {"cap_pct": [25, 10]}), ("harvest_return", {"drop_pct": 30})):
        body = rulebook.run(conn, data, request(name, params), now=now)
        assert body["kind"] == "rule" and body["trials"] == len(body["variants"]) and all(v["verdict"] for v in body["variants"])
        assert (body["start_pct"] == 30.0) == (name == "cap_position") and body["marginal_rate_pct"] == 24.0
    conn.close()


def test_a_request_the_list_cannot_answer_is_refused_in_plain_words(cfg):
    from desk.engine.lab import shelf
    from desk.engine.lab.runner import ledger

    conn = ledger(cfg)
    now = rulebook.datetime(2023, 1, 3, 6, 0)
    none = rulebook.run(conn, lab(many(), cover=None), request("average_down", {"drop_pct": 50}), now=now)
    assert none["kind"] == "rejected" and shelf.plain(none["problems"]) == "The public stock list is still loading its prices. This runs once that finishes."
    loading = COVER | {"priced": 2, "loading": 1, "pct": 66.7, "enough": False}
    wait = rulebook.run(conn, lab(many(), cover=loading), request("average_down", {"drop_pct": 50}), now=now)
    assert wait["kind"] == "rejected" and "2 of 3 are in and 1 are on the way" in wait["problems"][0]
    thin = COVER | {"priced": 2, "missing": 1, "pct": 66.7, "enough": False}
    ran = rulebook.run(conn, lab(many(), cover=thin), request("average_down", {"drop_pct": 50}), now=now)
    assert ran["kind"] == "rule" and ran["caveats"][0].endswith("That is under 90%, so this stays research only.") and not ran[PUBLIC_COVERAGE]["enough"]
    conn.close()
    data = lab(many())
    for raw, words in (
        (request("average_down", {}), "average_down needs params.drop_pct"),
        (request("average_down", {"drop_pct": 5}), "must sit between 10 and 90"),
        (request("harvest_return", {"drop_pct": 30, "cap_pct": 10}), "harvest_return has no param 'cap_pct'"),
        (request("cap_position", {"cap_pct": 10}, horizons=[2]), "horizons must include 1, 3, 5 or 10"),
        (request("harvest_return", {"drop_pct": 30}, account="roth ira"), "taxable account"),
    ):
        with pytest.raises(RuleError, match=words):
            listrules.parse(raw, data)
    with pytest.raises(RuleError, match="rule must be one of .*paydown, average_down, cap_position, harvest_return"):
        rulebook.parse({"id": "x", "rule": "nope"}, data)
    assert rulebook.LIST_RULES == tuple(listrules.RULES) == tuple(listrules.UNIT) == tuple(listrules.OUTCOME) and not set(rulebook.RULES) & set(listrules.RULES)
    assert set(grammar()["list_rule"]["rules"]) == set(listrules.RULES)
