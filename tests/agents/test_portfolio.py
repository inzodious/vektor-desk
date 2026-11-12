import json
from datetime import UTC, datetime, timedelta

import pytest

from desk.agents import __main__ as cli
from desk.agents import portfolio, store
from desk.agents.adapter import AgentError, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.jobs import JOBS
from desk.scheduler import package_jobs
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_advisor import FakeAdvisor
from tests.agents.test_plans import FakeBook, FakeFacts, Served, fact

ON = {"agents": {"enabled": True, "desks": {"research": True}}}
NIGHT = datetime(2026, 11, 12, 5, 30, tzinfo=UTC)


def analysis(**over) -> dict:
    dossier = {
        "symbol": "WRONG",
        "what_it_is": "A company that sells subscriptions to small firms. It earns a fee each month per seat.",
        "thesis": "Recurring revenue is still growing and it funds itself.",
        "bear_case": "Growth is slowing and a bigger rival is cutting prices.",
        "valuation_range": {"low": 34.0, "high": 52.0, "now": 41.2, "unit": "price", "basis": "Price per share at 4 to 6 times next year's sales."},
        "valuation_note": "About fair: it trades near the middle of its range.",
        "risks": ["A bigger rival is cutting prices.", "One customer is a fifth of sales."],
        "fit": "It sits inside its band and matches your plan to hold through earnings.",
        "identified": True,
        "verdict": "hold",
        "verdict_line": "Hold. Results were in line and it sits inside its band.",
        "what_would_change": "Two quarters of falling revenue, or a close below 34.",
        "changes_since_last": "Guidance was raised.",
        "sources": [{"url": "https://www.sec.gov/example-10q", "title": "Form 10-Q", "date": "2026-11-03"}],
    }
    return {"summary": "Held up; nothing to do.", "dossier": dossier | over}


def rows() -> list[dict]:
    return [
        fact("TICKA", kind="stock", band={"status": "inside", "weight_pct": 8.4}),
        fact("FUNDA", kind="fund", band={"status": "under", "weight_pct": 41.0}),
        fact("TICKB", kind="stock", band={"status": "over", "weight_pct": 12.5}),
        fact("CASHX", kind="cash", band={"status": "inside", "weight_pct": 3.0}),
    ]


def go(cfg, answer=None, held=None, profile=ON, now=NIGHT, advice=None, **kw):
    fake = answer if isinstance(answer, FakeAdapter) else Served({"research": answer if answer is not None else analysis()})
    report = portfolio.run_pass(
        cfg,
        facts=FakeFacts(held if held is not None else rows()),
        plans=FakeBook(),
        decisions=FakeDecisions(profile_data=profile),
        adapter=fake,
        advice=advice or FakeAdvisor(),
        now=now,
        **kw,
    )
    return report, fake


def saved(cfg, symbol) -> dict:
    return json.loads(store.latest_dossier(cfg, symbol)["dossier"])


def status(cfg, now=NIGHT, held=None, profile=ON) -> dict:
    return portfolio.status(cfg, facts=FakeFacts(held if held is not None else rows()), decisions=FakeDecisions(profile_data=profile), now=now)


# ---- The pass ----


def test_first_night_analyses_every_holding_biggest_first(cfg):
    report, fake = go(cfg)
    assert report.status == "ok" and report.analysed == ["FUNDA", "TICKB", "TICKA"] and report.held == 3
    assert [c["desk"] for c in fake.calls] == ["research"] * 3
    assert fake.calls[0]["system"].startswith("You are the Research desk") and fake.calls[0]["schema"] == portfolio.schema()
    payload = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert payload["today"] == "2026-11-12" and payload["reasons"] == ["new"] and payload["holding"]["symbol"] == "FUNDA"
    assert "lots" not in payload["holding"] and payload["previous_analysis"] is None and "risk_band" in payload["advisor"]
    got = saved(cfg, "TICKA")
    assert (got["symbol"], got["as_of"], got["verdict"], got["changes_since_last"]) == ("TICKA", "2026-11-12", "hold", None)
    assert got["risks"] == analysis()["dossier"]["risks"] and got["sources"][0]["url"].startswith("https://www.sec.gov")
    assert report.ready == {"ready": "All 3 holdings analysed"}


def test_pass_desk_is_opus_high_with_web_and_its_own_cap(cfg):
    desk = portfolio.desk_for(14)
    assert (desk.name, desk.model, desk.effort, desk.max_turns, desk.weekly_runs) == ("research", "opus", "high", 30, 34)
    assert "WebSearch" in desk.tools and get("research").effort == "xhigh"
    shape = portfolio.schema()
    assert "$schema" not in shape and shape["properties"]["dossier"]["properties"]["verdict"] == {"enum": ["add", "hold", "trim", "watch"]}
    assert {"what_it_is", "risks", "fit", "verdict", "verdict_line"} <= set(shape["properties"]["dossier"]["required"])


def test_a_second_start_the_same_night_skips_what_is_done(cfg):
    go(cfg, limit=2)
    report, fake = go(cfg, now=NIGHT + timedelta(minutes=40))
    assert report.analysed == ["TICKA"] and len(fake.calls) == 1 and report.ready == {"ready": "All 3 holdings analysed"}
    report, fake = go(cfg, now=NIGHT + timedelta(minutes=50))
    assert report.status == "ok" and not fake.calls and report.note == "Every holding's analysis is current."
    assert report.ready == {"ready": "All 3 holdings analysed"}


def test_later_nights_refresh_only_what_has_a_reason(cfg):
    go(cfg)
    next_night = NIGHT + timedelta(days=1)
    quiet, fake = go(cfg, now=next_night)
    assert not fake.calls and quiet.ready == {"skipped": "All 3 holdings already have a current analysis."}
    held = rows()
    held[0] = held[0] | {"filing_signals": [{"filed_at": "2026-11-12T16:30:00", "form": "8-K"}]}
    held[1] = held[1] | {"discount": {"active": True, "as_of": "2026-11-12", "reason": "drop"}}
    report, fake = go(cfg, held=held, now=next_night)
    assert report.analysed == ["FUNDA", "TICKA"]
    payload = json.loads(fake.calls[1]["prompt"].split("\n\n", 1)[1])
    assert payload["reasons"] == ["filing"] and payload["previous_analysis"]["verdict"] == "hold"
    assert saved(cfg, "TICKA")["changes_since_last"] == "Guidance was raised."
    assert report.ready == {"ready": "2 holdings refreshed, all 3 current"}
    week, fake = go(cfg, now=NIGHT + timedelta(days=9))
    assert week.analysed == ["FUNDA", "TICKB", "TICKA"]
    assert json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["reasons"] == ["weekly"]


def test_an_add_is_held_back_above_the_band_and_inside_a_no_buy_window(cfg):
    advice = FakeAdvisor()
    advice.windows = {"TICKA": {"until": "2027-01-15", "reason": "planned sale"}}
    advice.no_buy = lambda cfg: advice.windows
    go(cfg, analysis(verdict="add", verdict_line="Add. It is cheap."), advice=advice)
    assert saved(cfg, "FUNDA")["verdict"] == "add" and saved(cfg, "FUNDA")["verdict_line"] == "Add. It is cheap."
    over, window = saved(cfg, "TICKB"), saved(cfg, "TICKA")
    assert over["verdict"] == "hold" and "above its band" in over["verdict_line"]
    assert window["verdict"] == "hold" and "2027-01-15" in window["verdict_line"]


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"verdict": "avoid"}, "gave no verdict"),
        ({"fit": " "}, "left out fit"),
        ({"sources": [{"url": "notes", "title": "x", "date": "2026"}]}, "cited no dated source"),
    ],
)
def test_an_incomplete_answer_is_refused_and_said_plainly(cfg, over, why):
    stock = [fact("TICKB", kind="stock", band={"status": "over", "weight_pct": 12.5})]
    report, _ = go(cfg, analysis(**over), held=stock)
    assert report.rejected == ["TICKB"] and store.latest_dossier(cfg, "TICKB") is None
    row = status(cfg, held=stock)["rows"][0]
    assert row["status"] == "failed" and why in row["status_line"] and row["attempt"]["status"] == "refused"
    assert report.ready == {"skipped": "No holding was analysed: 1 failed."}


def test_a_failed_holding_is_retried_once_then_left_for_tomorrow(cfg):
    class Flaky(Served):
        def run(self, desk, system, prompt, schema=None):
            if '"symbol": "TICKB"' in prompt:
                self.calls.append({"desk": desk.name, "prompt": prompt})
                raise AgentError("the CLI exited with an error")
            return super().run(desk, system, prompt, schema)

    report, fake = go(cfg, Flaky({"research": analysis()}))
    assert report.status == "ok" and report.failed == ["TICKB"] and report.analysed == ["FUNDA", "TICKA"]
    assert report.ready == {"ready": "2 of 3 holdings analysed, 1 failed"}
    board = status(cfg)
    row = next(r for r in board["rows"] if r["symbol"] == "TICKB")
    assert row["status"] == "failed" and "didn't finish: the CLI exited with an error." in row["status_line"]
    assert (board["held"], board["analysed"], board["failed"]) == (3, 2, 1) and "1 didn't finish on the last try" in board["line"]
    again, fake = go(cfg, Flaky({"research": analysis()}), now=NIGHT + timedelta(minutes=30))
    assert again.failed == ["TICKB"] and len(fake.calls) == 1
    third, fake = go(cfg, Flaky({"research": analysis()}), now=NIGHT + timedelta(minutes=60))
    assert not fake.calls
    fixed, _ = go(cfg, now=NIGHT + timedelta(days=1))
    assert fixed.analysed == ["TICKB"]
    assert next(r for r in status(cfg, now=NIGHT + timedelta(days=1))["rows"] if r["symbol"] == "TICKB")["status"] == "today"


def test_usage_limit_stops_the_pass_and_says_so(cfg):
    report, fake = go(cfg, Served({"research": UsageLimitError("usage limit reached, resets 9am")}))
    assert report.status == "deferred" and len(fake.calls) == 1 and report.left == 3
    row = status(cfg)["rows"][0]
    assert row["status"] == "failed" and "usage limit was reached" in row["status_line"]
    assert "skipped" in report.ready


def test_three_failures_in_a_row_stop_the_pass(cfg):
    report, fake = go(cfg, Served({"research": AgentError("boom")}))
    assert report.status == "failed" and len(fake.calls) == 3 and "3 failures in a row" in report.note


def test_no_new_call_after_six_in_the_morning_on_schedule(cfg):
    morning = datetime(2026, 11, 12, 11, 5, tzinfo=UTC)
    report, fake = go(cfg, now=morning)
    assert not fake.calls and report.left == 3 and "6:00 AM" in report.note
    report, fake = go(cfg, now=morning, trigger="console", limit=1)
    assert len(fake.calls) == 1
    report, fake = go(cfg, now=morning + timedelta(hours=3))
    assert len(fake.calls) == 2 and report.left == 0


def test_switched_off_guarded_and_not_ready(cfg):
    report, fake = go(cfg, profile={"agents": {"desks": {"research": False}}})
    assert report.status == "disabled" and not fake.calls and report.ready == {"skipped": "Switched off in desk.yaml."}
    board = status(cfg, profile={"agents": {"desks": {"research": False}}})
    assert board["line"] == "Holdings aren't being analysed yet. Switched off in desk.yaml." and board["pass"]["next"] is None
    store.clear_enabled(cfg, store.GUARD)
    report, fake = go(cfg)
    assert report.status == "guarded" and not fake.calls
    assert "First-run guard" in status(cfg)["line"]
    store.set_guard(cfg, False)
    report = portfolio.run_pass(cfg, facts=FakeFacts(ready=False), plans=FakeBook(), decisions=FakeDecisions(profile_data=ON), adapter=Served({}))
    assert report.status == "not_ready" and "skipped" in report.ready
    assert status(cfg, held=[])["line"] == portfolio.NO_HOLDINGS


def test_asking_for_one_holding_runs_it_even_when_current(cfg):
    go(cfg)
    report, fake = go(cfg, symbols=("ticka",), trigger="console", now=NIGHT + timedelta(minutes=5))
    assert report.analysed == ["TICKA"] and json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["reasons"] == ["asked"]
    report, fake = go(cfg, symbols=("NOPE",), trigger="console")
    assert not fake.calls and report.note == "NOPE isn't a holding today."


# ---- What the app reads ----


def test_status_rows_and_door_line(cfg, app_client, monkeypatch):
    board = status(cfg)
    assert [r["status"] for r in board["rows"]] == ["none"] * 3 and board["analysed"] == 0 and board["fresh_at"] is None
    assert board["line"] == "0 of 3 holdings analysed." and board["pass"]["due"] == 3 and board["pass"]["next"]
    go(cfg, limit=2)
    board = status(cfg)
    assert [(r["symbol"], r["status"], r["verdict"]) for r in board["rows"]] == [
        ("FUNDA", "today", "hold"),
        ("TICKB", "today", "hold"),
        ("TICKA", "none", None),
    ]
    assert board["rows"][0]["status_line"] == "Analysed today" and board["rows"][0]["verdict_line"].startswith("Hold.")
    assert (board["today"], board["analysed"], board["waiting"]) == (2, 2, 0) and board["line"] == "2 of 3 holdings analysed today."
    later = status(cfg, now=NIGHT + timedelta(days=2))
    assert later["rows"][0]["status"] == "older" and later["rows"][0]["status_line"] == "Analysed Nov 12" and later["today"] == 0
    monkeypatch.setattr(portfolio, "running", lambda cfg: [{"job": "agents-run-research"}])
    store.start_try(cfg, "TICKA", (NIGHT - timedelta(minutes=1)).isoformat())
    live = status(cfg)
    assert live["running"] == "TICKA" and live["rows"][2]["status_line"] == "Being analysed now." and live["pass"]["active"] is True
    monkeypatch.setattr(portfolio, "running", lambda cfg: [])
    assert "the box restarted mid-run" in status(cfg)["rows"][2]["status_line"]
    monkeypatch.setattr(portfolio, "RealPlanFacts", lambda: FakeFacts(rows()))
    monkeypatch.setattr(portfolio, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    client = app_client(packages=["agents"])
    body = client.get("/api/agents/holdings").json()
    assert body["held"] == 3 and {r["symbol"] for r in body["rows"]} == {"FUNDA", "TICKA", "TICKB"}
    assert client.get("/api/agents/dossiers/FUNDA").json()["dossier"]["what_it_is"].startswith("A company")


def test_waiting_rows_while_the_pass_runs(cfg, monkeypatch):
    go(cfg, limit=1)
    monkeypatch.setattr(portfolio, "running", lambda cfg: [{"job": "agents-run-research"}])
    board = status(cfg)
    assert [r["status"] for r in board["rows"]] == ["today", "waiting", "waiting"] and board["waiting"] == 2


# ---- Job and CLI ----


def test_job_is_named_for_the_night_order_and_resumes(cfg):
    mine = [j for j in JOBS if isinstance(j, dict)]
    assert [j["schedule"] for j in mine] == ["5 0 * * *", "5 2 * * *", "5 4 * * *"] and [j.get("overnight") for j in mine] == [200, None, None]
    assert {j["command"] for j in mine} == {"python -m desk.agents run research"} and {j["title"] for j in mine} == {"Analyse every holding"}
    assert [j.name for j in package_jobs(["agents"])].count("agents-run-research") == 3


def test_cli_prints_the_ready_line_last(cfg, monkeypatch, capsys):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(portfolio, "RealPlanFacts", lambda: FakeFacts(rows()))
    monkeypatch.setattr(portfolio, "RealPlans", FakeBook)
    monkeypatch.setattr(portfolio, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: Served({"research": analysis()}))
    monkeypatch.setattr(portfolio, "closed", lambda *a: False)
    assert cli.main(["portfolio"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0].startswith("Portfolio pass: ok, 3 analysed, 0 failed of 3.") and json.loads(out[-1]) == {"ready": "All 3 holdings analysed"}
    assert cli.main(["run", "research"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"ready": "All 3 holdings analysed"}
    assert cli.main(["dry-run", "research", "--trigger", "schedule", "--symbol", "TICKA"]) == 0
    assert "3 holdings, 1 due: TICKA (asked)." in capsys.readouterr().out


# ---- Against the real plan facts ----


def test_real_plan_facts_feed_the_pass(cfg, monkeypatch):
    from desk.agents.sources import RealPlanFacts
    from tests.engine.test_planfacts import seeded

    seeded(cfg, monkeypatch)
    report = portfolio.run_pass(
        cfg,
        facts=RealPlanFacts(),
        plans=FakeBook(),
        decisions=FakeDecisions(profile_data=ON),
        adapter=Served({"research": analysis()}),
        advice=FakeAdvisor(),
        now=NIGHT,
    )
    assert report.status == "ok" and report.analysed == ["IVV", "ACME", "SOLO"] and report.held == 3
    board = portfolio.status(cfg, facts=RealPlanFacts(), decisions=FakeDecisions(profile_data=ON), now=NIGHT)
    assert [(r["symbol"], r["kind"], r["status"]) for r in board["rows"]] == [("IVV", "fund", "today"), ("ACME", "stock", "today"), ("SOLO", "stock", "today")]
    assert board["rows"][1]["name"] == "Acme Corp" and board["rows"][0]["weight_pct"] > board["rows"][1]["weight_pct"] > 0
    assert board["line"] == "All 3 holdings analysed today."


# ---- Valuation unit, plain text, old dossiers, plan funds ----

LONG_BASIS = (
    "Forward P/E on the Nasdaq ADR (price / next-year consensus EPS). Low 22x = the recent trough reading; high 33x = the five-year average forward P/E. "
    "Now 24.57x from a quote page at the Nov 11, 2026 close of $1,538.72."
)


def test_range_carries_a_unit_and_the_method_is_a_sentence(cfg):
    span = {"low": 22, "high": 33, "now": 24.57, "unit": "multiple", "basis": LONG_BASIS}
    go(cfg, analysis(valuation_range=span, valuation_note="", thesis="Margins of 52.8296% gross; you owe (-2182.12)."), limit=1)
    got = saved(cfg, "FUNDA")
    assert got["valuation_range"] == {"low": 22.0, "high": 33.0, "now": 24.57, "unit": "multiple", "basis": "Forward P/E on the Nasdaq ADR"}
    assert got["valuation_note"].startswith("Forward P/E on the Nasdaq ADR (price / next-year consensus EPS). Low 22x") and "$1,539" in got["valuation_note"]
    assert got["thesis"] == "Margins of 52.8% gross; you owe (-$2,182)."
    go(cfg, analysis(valuation_range={"low": None, "high": None, "basis": "Not a single business", "unit": "furlongs"}), held=[fact("FUNDB", kind="fund")])
    assert saved(cfg, "FUNDB")["valuation_range"] == {"low": None, "high": None, "now": None, "unit": None, "basis": "Not a single business"}
    shape = portfolio.schema()["properties"]["dossier"]["properties"]["valuation_range"]
    assert "unit" in shape["required"] and shape["properties"]["unit"] == {"enum": ["price", "multiple", "percent", None]}
    assert shape["properties"]["basis"]["maxLength"] == 120


def test_a_dossier_in_the_old_format_is_analysed_again_tonight(cfg):
    old = {
        "symbol": "TICKA",
        "thesis": "Old thesis.",
        "bear_case": "Old bear.",
        "valuation_range": {"low": 22, "high": 33, "basis": LONG_BASIS},
        "verdict": "hold",
    }
    run_id = store.start_run(cfg, "research", trigger="console", model="opus", effort="xhigh", status="ok")
    store.save_dossier(cfg, "TICKA", run_id, json.dumps(old), (NIGHT - timedelta(hours=8)).isoformat())
    board = status(cfg)
    assert board["pass"]["due"] == 3 and next(r for r in board["rows"] if r["symbol"] == "TICKA")["verdict"] == "hold"
    report, fake = go(cfg)
    assert sorted(report.analysed) == ["FUNDA", "TICKA", "TICKB"] and report.ready == {"ready": "All 3 holdings analysed"}
    payload = json.loads(fake.calls[-1]["prompt"].split("\n\n", 1)[1])
    assert payload["holding"]["symbol"] == "TICKA" and payload["reasons"] == ["new"] and payload["previous_analysis"]["thesis"] == "Old thesis."
    assert saved(cfg, "TICKA")["what_it_is"] and saved(cfg, "TICKA")["changes_since_last"] == "Guidance was raised."


def test_a_plan_fund_known_only_by_its_id_still_gets_an_analysis(cfg):
    funds = [
        fact("31617E745", name=None, kind="fund", held=False, numbers={"value": 2400.0, "weight_pct": 6.0}, band={"status": "inside", "weight_pct": 6.0}),
        fact("TICKA", kind="stock", band={"status": "inside", "weight_pct": 5.0}),
        fact("WATCH", kind="stock", held=False, numbers={"price": 10.0}),
    ]
    report, fake = go(cfg, analysis(sources=[], verdict="watch", verdict_line="Watch. Check the fund's name and fee in the plan."), held=funds)
    assert report.analysed == ["31617E745"] and report.rejected == ["TICKA"]
    assert saved(cfg, "31617E745")["sources"] == [] and saved(cfg, "31617E745")["verdict"] == "watch"
    assert "plan id" in fake.calls[0]["system"]


# ---- Names from the book, holdings the desk could not identify ----

PLACEHOLDER = {
    "symbol": "PLAN01",
    "what_it_is": "This is a placeholder: the fund behind this plan id could not be found.",
    "thesis": "Placeholder.",
    "bear_case": "Unknown.",
    "fit": "Unknown.",
    "verdict": "watch",
    "verdict_line": "Watch. Check the fund's name in the plan.",
    "what_would_change": "The fund's name.",
    "sources": [],
}


def plan_fund(**over) -> dict:
    return fact("PLAN01", kind="fund", held=False, numbers={"value": 2400.0, "weight_pct": 6.0}, band={"status": "inside", "weight_pct": 6.0}, **over)


def test_book_names_come_from_the_latest_snapshot_without_account_numbers():
    from desk.agents.sources import book_names

    accounts = [{"key": "plan-0003", "kind": "401k", "name": "Synthetic Retirement Plan", "last4": "0003"}]
    snaps = {1: {"id": 1, "asOf": "2026-11-01T16:00", "accounts": accounts}, 2: {"id": 2, "asOf": "2026-11-08T16:00", "accounts": accounts}}
    positions = [
        {"snapshotId": 2, "accountKey": "plan-0003", "symbol": "plan01", "description": "  Synthetic 500   Index Fund Inv ", "isCash": False},
        {"snapshotId": 1, "accountKey": "plan-0003", "symbol": "PLAN01", "description": "Old Name", "isCash": False},
        {"snapshotId": 1, "accountKey": "gone-0009", "symbol": "PLAN01", "description": "Old Name", "isCash": False},
        {"snapshotId": 2, "accountKey": "plan-0003", "symbol": "CASHX", "description": "Synthetic Money Market", "isCash": True},
        {"snapshotId": 2, "accountKey": "plan-0003", "symbol": "", "description": "No symbol"},
    ]
    got = book_names(snaps, positions)
    assert got == {"PLAN01": {"name": "Synthetic 500 Index Fund Inv", "held_in": [{"name": "Synthetic Retirement Plan", "kind": "401k"}]}}
    assert "0003" not in json.dumps(got)


def test_real_plan_facts_fill_a_missing_name_from_the_book(demo_cfg, monkeypatch):
    from desk.agents.sources import RealPlanFacts
    from desk.engine import planfacts

    rows = [{"symbol": "ACME", "name": None, "kind": "unknown"}, {"symbol": "FXAIX", "name": "Kept Name", "kind": "fund"}, {"symbol": "NOPE", "name": None}]
    monkeypatch.setattr(planfacts, "facts", lambda cfg, symbol=None: rows)
    got = {r["symbol"]: r for r in RealPlanFacts().facts(demo_cfg)}
    assert got["ACME"]["name"] == "Acme Rockets Inc" and got["FXAIX"]["name"] == "Kept Name" and got["NOPE"]["name"] is None
    assert got["ACME"]["held_in"] and all(set(a) <= {"name", "kind"} for a in got["ACME"]["held_in"]) and "held_in" not in got["NOPE"]
    assert rows[0]["name"] is None


def test_real_plan_facts_work_without_a_mirror(cfg, monkeypatch):
    from desk.agents.sources import RealPlanFacts
    from desk.engine import planfacts

    monkeypatch.setattr(planfacts, "facts", lambda cfg, symbol=None: [{"symbol": "ACME", "name": None}])
    assert RealPlanFacts().book(cfg) == {} and RealPlanFacts().facts(cfg) == [{"symbol": "ACME", "name": None}]


def test_the_desk_gets_the_name_and_accounts_and_speaks_to_you(cfg):
    held_in = [{"name": "Synthetic Retirement Plan", "kind": "401k"}]
    report, fake = go(cfg, held=[plan_fund(name="Synthetic 500 Index Fund Inv", held_in=held_in)])
    payload = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert payload["holding"]["name"] == "Synthetic 500 Index Fund Inv" and payload["holding"]["held_in"] == held_in
    system = fake.calls[0]["system"]
    assert '"you" and "your"' in system and "`holding.name`" in system and "`identified`" in system
    assert report.analysed == ["PLAN01"] and saved(cfg, "PLAN01")["identified"] is True
    assert status(cfg, held=[plan_fund(name="Synthetic 500 Index Fund Inv")])["rows"][0]["name"] == "Synthetic 500 Index Fund Inv"
    shape = portfolio.schema()["properties"]["dossier"]
    assert "identified" in shape["required"] and shape["properties"]["identified"] == {"type": "boolean"}


def test_an_analysis_that_could_not_identify_the_holding_is_not_kept(cfg):
    held = [plan_fund(name=None)]
    report, _ = go(cfg, analysis(identified=False, sources=[]), held=held)
    assert report.rejected == ["PLAN01"] and not report.analysed and store.latest_dossier(cfg, "PLAN01") is None
    assert report.lines == ["PLAN01: not analysed (the desk could not tell what this holding is)"]
    board = status(cfg, held=held)
    assert board["analysed"] == 0 and board["rows"][0]["status"] == "failed" and "could not tell what this holding is" in board["rows"][0]["status_line"]
    again, fake = go(cfg, analysis(identified=False), held=held, now=NIGHT + timedelta(hours=2))
    assert len(fake.calls) == 1 and again.rejected == ["PLAN01"]
    third, fake = go(cfg, held=held, now=NIGHT + timedelta(hours=4))
    assert not fake.calls


def test_a_placeholder_from_an_earlier_night_is_redone_and_only_that_one(cfg):
    held = [plan_fund(name="Synthetic 500 Index Fund Inv"), fact("TICKA", kind="stock", band={"status": "inside", "weight_pct": 5.0})]
    first, _ = go(cfg, held=held)
    assert sorted(first.analysed) == ["PLAN01", "TICKA"]
    run_id = store.start_run(cfg, "research", trigger="schedule", model="opus", effort="high", status="ok")
    wrote = NIGHT + timedelta(minutes=10)
    store.save_dossier(cfg, "PLAN01", run_id, json.dumps(PLACEHOLDER), wrote.isoformat())
    board = status(cfg, held=held, now=wrote + timedelta(minutes=5))
    row = next(r for r in board["rows"] if r["symbol"] == "PLAN01")
    assert (board["analysed"], board["pass"]["due"]) == (1, 1) and row["status"] == "none" and row["verdict"] is None and row["analysed_at"] is None
    assert board["line"] == "1 of 2 holdings analysed today."
    report, fake = go(cfg, held=held, now=NIGHT + timedelta(hours=2))
    assert report.analysed == ["PLAN01"] and len(fake.calls) == 1 and report.ready == {"ready": "All 2 holdings analysed"}
    payload = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert payload["reasons"] == ["new"] and payload["previous_analysis"] is None
    assert saved(cfg, "PLAN01")["identified"] is True and status(cfg, held=held, now=NIGHT + timedelta(hours=3))["analysed"] == 2


def test_a_holding_that_worked_since_its_misses_starts_the_count_again(cfg):
    held = [plan_fund(name=None)]
    for minutes in (0, 20):
        go(cfg, analysis(verdict="buy"), held=held, now=NIGHT + timedelta(minutes=minutes))
    since = (NIGHT - timedelta(hours=1)).isoformat(timespec="seconds")
    assert store.misses_since(cfg, since) == {"PLAN01": 2}
    done = store.start_try(cfg, "PLAN01", (NIGHT + timedelta(minutes=40)).isoformat(timespec="seconds"))
    store.finish_try(cfg, done, "ok", None, None, (NIGHT + timedelta(minutes=41)).isoformat(timespec="seconds"))
    assert store.misses_since(cfg, since) == {}
    go(cfg, analysis(verdict="buy"), held=held, now=NIGHT + timedelta(minutes=60))
    assert store.misses_since(cfg, since) == {"PLAN01": 1}


def test_another_desk_over_its_cap_does_not_stop_the_pass(cfg):
    from desk.agents.runner import run_desk

    risk = get("risk")
    for _ in range(risk.weekly_runs):
        run_desk(risk, "s", "p", cfg=cfg, adapter=FakeAdapter())
    assert run_desk(risk, "s", "p", cfg=cfg, adapter=FakeAdapter()).status == "over_budget"
    report, _ = go(cfg)
    assert report.status == "ok" and len(report.analysed) == 3
