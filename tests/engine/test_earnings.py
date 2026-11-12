import json
from datetime import UTC, datetime

import pytest

from desk.engine import earnings
from desk.engine.lab import library as features
from desk.engine.lab.data import data_path, export, load
from desk.engine.lab.sim import simulate
from desk.engine.lab.spec import parse, resolve
from tests.engine.test_insider import buy, desk, lab_desk, sessions

NOW = datetime(2026, 11, 8, 4, 50, tzinfo=UTC)


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": f"a-{end}-{filed}"}


FACTS = [
    fact("2023-01-01", "2023-03-31", 0.10, "2023-05-10"),
    fact("2023-01-01", "2023-03-31", 0.12, "2024-05-09"),
    fact("2023-04-01", "2023-06-30", 0.20, "2023-08-09"),
    fact("2023-07-01", "2023-09-30", 0.30, "2023-11-08"),
    fact("2023-01-01", "2023-12-31", 1.00, "2024-03-12", "10-K"),
    fact("2024-01-01", "2024-03-31", 0.25, "2024-05-09"),
    fact("2023-12-01", "2023-12-31", 9.99, "2024-01-15", "8-K"),
]


def concept(facts):
    return {"units": {"USD/shares": facts}}


def test_first_filed_and_a_derived_fourth_quarter():
    facts = earnings.first_filed(concept(FACTS))
    q1 = next(f for f in facts if f["end"] == "2023-03-31")
    assert q1["val"] == 0.10 and q1["filed"] == "2023-05-10" and not any(f["form"] == "8-K" for f in facts)
    q = earnings.quarters(facts)
    assert sorted(q) == ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]
    assert q["2023-12-31"]["val"] == pytest.approx(0.40) and q["2023-12-31"]["derived"] and q["2023-12-31"]["filed"] == "2024-03-12"


SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "8-K", "4"],
            "items": ["2.02,9.01", "", "5.02", ""],
            "acceptanceDateTime": ["2024-05-02T20:05:00.000Z", "2024-05-09T21:00:00.000Z", "2024-04-01T12:00:00.000Z", "2024-05-03T12:00:00.000Z"],
            "filingDate": ["2024-05-02", "2024-05-09", "2024-04-01", "2024-05-03"],
        },
        "files": [{"name": "CIK0000000111-submissions-001.json", "filingFrom": "2015-01-01", "filingTo": "2023-12-31"}],
    }
}
OLDER = {"form": ["8-K"], "items": ["2.02"], "acceptanceDateTime": ["2023-05-04T12:30:00.000Z"], "filingDate": ["2023-05-04"]}


def test_release_times_set_when_the_news_was_known():
    times = earnings.releases(SUBMISSIONS, [OLDER])
    assert times == ["2023-05-04T12:30:00.000Z", "2024-05-02T20:05:00.000Z"]
    q = {"end": "2024-03-31", "filed": "2024-05-09"}
    assert earnings.known_for(q, times) == ("2024-05-03", "release")
    assert earnings.known_for({"end": "2023-03-31", "filed": "2023-05-10"}, times) == ("2023-05-04", "release")
    assert earnings.known_for({"end": "2023-06-30", "filed": "2023-08-09"}, times) == ("2023-08-10", "filing")


class Res:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeSec:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        if "EarningsPerShareDiluted" in url:
            return Res(404)
        if "EarningsPerShareBasic" in url:
            return Res(200, json.dumps(concept(FACTS)))
        if url.endswith("submissions-001.json"):
            return Res(200, json.dumps(OLDER))
        if "submissions/CIK" in url:
            return Res(200, json.dumps(SUBMISSIONS))
        return Res(404)


def seeded(cfg):
    conn = desk(cfg)
    with conn:
        buy(conn, "a1", 1, "SMOL", "2024-03-01")
        conn.execute("INSERT INTO alpaca_history VALUES ('SMOL', '2016-01-01', 10, 'x')")
        conn.executemany("INSERT INTO alpaca_bars VALUES ('SMOL', ?, 5, 5, 5, 5.0, 5.0, 1e6, 5)", [(d,) for d in sessions("2022-12-01", 400)])
    return conn


def test_fetch_falls_back_to_basic_eps_and_refreshes_monthly(cfg):
    conn = seeded(cfg)
    web = FakeSec()
    out = earnings.fetch(conn, web, "test agent", now=NOW, sleep=lambda _: None)
    assert out == {"companies": 1, "facts": 5, "releases": 2, "left": 0}
    assert sum("companyconcept" in u for u in web.urls) == 2 and sum("submissions" in u for u in web.urls) == 2
    again = earnings.fetch(conn, web, "test agent", now=NOW, sleep=lambda _: None)
    assert again["companies"] == 0
    conn.close()


def test_events_scale_the_year_over_year_change_by_the_prior_close(cfg):
    conn = seeded(cfg)
    earnings.fetch(conn, FakeSec(), "test agent", now=NOW, sleep=lambda _: None)
    assert earnings.build_events(conn) == 1
    row = dict(conn.execute("SELECT * FROM earnings_events").fetchone())
    assert row["period_end"] == "2024-03-31" and row["known"] == "2024-05-03" and row["source"] == "release"
    assert row["eps"] == 0.25 and row["eps_prior"] == 0.10 and row["surprise"] == pytest.approx(0.03)
    cov = earnings.coverage(conn)
    assert cov["clusters"] == 1 and cov["priced"] == 1 and cov["pending"] == 0 and cov["events"] == 1
    conn.close()


def test_job_skips_without_an_sec_agent_and_is_scheduled(cfg, monkeypatch):
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    monkeypatch.delenv("DESK_SEC_USER_AGENT", raising=False)
    conn = desk(cfg)
    assert earnings.run(conn, FakeSec(), now=NOW)["skipped_code"] == "no_sec_contact"
    conn.close()
    assert "earnings" in engine_main.JOBS and ("50 23 * * *", "python -m desk.engine earnings") in JOBS


# ---- Lab ----


SPEC = {
    "id": "pead",
    "version": 1,
    "title": "Post-earnings drift",
    "hypothesis": "Small caps with the biggest year-over-year EPS jumps keep drifting up for a quarter.",
    "predicted_effect": "+4 points a year",
    "universe": {"type": "small_caps"},
    "signals": [{"metric_id": "earnings.surprise", "window": "63d", "transform": "rank"}],
    "entry": {"top_n": 1, "min_signal": 0},
    "exit": "rebalance",
    "rebalance": "weekly",
    "sizing": "equal",
    "params": {},
    "success_criteria": {"excess_vs_plan_pts": 0.0},
    "horizons": [3],
}


def drift_lab(cfg):
    conn, days = lab_desk(cfg)
    with conn:
        conn.executemany(
            "INSERT INTO earnings_events VALUES (?, ?, '2023-12-31', ?, 'release', 1, 0.5, 10, ?)",
            [("SMOL", 111, "2024-02-06", 0.05), ("DULL", 222, "2024-02-06", -0.02)],
        )
    export(cfg, conn, {}, {})
    conn.close()
    return load(data_path(cfg))


def test_earnings_features_read_the_latest_news_inside_the_window(cfg):
    data = drift_lab(cfg)
    s, ev = data.series["SMOL"], data.earnings["SMOL"]
    assert features.value("earnings.surprise", s, s.index["2024-02-05"], 63, ev) is None
    assert features.value("earnings.surprise", s, s.index["2024-02-06"], 63, ev) == 0.05
    assert features.value("earnings.days_since", s, s.index["2024-02-09"], 63, ev) == 3.0
    assert features.value("earnings.surprise", s, s.index["2024-06-28"], 63, ev) is None
    assert {f["metric_id"]: f["kind"] for f in features.catalog()}["earnings.surprise"] == "earnings"
    assert json.loads(data.settings["earnings_coverage"])["events"] == 2


def test_a_drift_spec_buys_the_beat_after_the_news(cfg):
    data = drift_lab(cfg)
    spec = parse(SPEC, data, model="test")
    res = simulate(data, spec, resolve(spec, {}), "2024-01-02", "2024-04-30")
    buys = [(d, s) for d, s, side, *_ in res.trades if side == "buy"]
    assert buys and buys[0] == (buys[0][0], "SMOL") and buys[0][0] > "2024-02-06" and all(s == "SMOL" for _, s in buys)
