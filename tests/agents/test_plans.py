import json
from dataclasses import dataclass, field
from datetime import date

import pytest

from desk.agents import __main__ as cli
from desk.agents import advisor, briefs, console, plans, store
from desk.agents.adapter import AgentError, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.jobs import JOBS
from desk.agents.pipeline import no_buy_problem, prepare
from desk.agents.sources import NotReady, RealAdvisor, RealPlanFacts, RealPlans
from desk.agents.status import crew
from desk.scheduler import package_jobs
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine
from tests.agents.test_advisor import FakeAdvisor

ON = {"agents": {"enabled": True, "desks": {"plans": True}}}
WED = date(2026, 11, 11)
SAT = date(2026, 11, 14)
PINS = {
    "steps": [
        {"id": "harvest-2026", "kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "shares": 40, "lots": "highest_cost", "no_buy_days": 31},
        {"id": "margin-repay", "kind": "repay", "due": "2026-11-18", "note": "The deposit pays off the margin debit."},
    ]
}


def fact(symbol="TICKA", **over) -> dict:
    row = {
        "symbol": symbol,
        "name": f"{symbol} Corp",
        "as_of": "2026-11-10",
        "numbers": {"weight_pct": 8.4, "price": 41.2, "unrealized_usd": -310.0, "drop_from_high_pct": -18.0},
        "lots": [{"acquired": "2025-12-01", "shares": 10, "long_term_on": "2026-12-02"}],
        "wash_windows": [],
        "zones": {"add": {"low": 36.5, "high": 39.0}, "trim": {"low": 52.0, "high": 55.5}},
        "discount": {"active": False, "signal_id": None},
        "next_earnings": "2026-11-20",
        "filing_signals": [],
        "valuation": None,
        "band": {"status": "inside"},
    }
    return row | over


def draft(**over) -> dict:
    plan = {
        "role": "satellite",
        "thesis": "A small position in a company growing its recurring revenue. It has to keep growing without new debt.",
        "weight_band": {"min_pct": 4, "max_pct": 10},
        "add_rule": {"zone_low": 36.5, "zone_high": 39.0, "max_per_month_usd": 300, "deposits_only": True, "note": "Only from new deposits."},
        "trim_rule": {"above_pct": 10, "to_pct": 8, "zone_low": 52.0, "zone_high": 61.0, "note": ""},
        "exit_conditions": ["Revenue growth turns negative for two quarters."],
        "tax_notes": "One lot turns long-term on 2026-12-02.",
        "catalysts": [{"text": "Earnings", "date": "2026-11-20"}],
        "next_review": "2026-11-21",
        "steps": [
            {"text": "Hold; nothing to do before earnings.", "kind": "hold", "due": None, "when": None},
            {"text": "Add 200 with margin if it dips.", "kind": "add", "due": None, "when": "price in the add zone"},
            {"text": "Add up to 300 from the next deposit while in the add zone.", "kind": "add", "due": None, "when": "price in the add zone"},
        ],
    }
    return {"action": "draft", "summary": "A small satellite; hold into earnings.", "numbers_cited": ["weight_pct", "made_up"], "plan": plan | over}


KEEP = {"action": "keep", "summary": "Still fits.", "numbers_cited": []}


def saved(symbol="TICKA", **over) -> dict:
    row = {"symbol": symbol, "status": "approved", "author": "desk", "band_status": "inside", "review_due": False} | draft()["plan"]
    row["steps"] = [{"id": "hold", "kind": "hold", "text": "Hold.", "by": "desk", "status": "standing"}]
    return row | over


@dataclass
class FakeFacts:
    rows: list = field(default_factory=lambda: [fact()])
    ready: bool = True

    def facts(self, cfg, symbol=None):
        if not self.ready:
            raise NotReady("the engine has not run yet")
        return self.rows


@dataclass
class FakeBook:
    rows: list = field(default_factory=list)
    refuse: set = field(default_factory=set)
    skip: dict = field(default_factory=dict)
    drafts: list = field(default_factory=list)

    def list_plans(self, cfg):
        return self.rows

    def save_draft(self, cfg, symbol, plan, *, run_id, model, summary):
        if symbol in self.refuse:
            raise ValueError("thesis is too long")
        self.drafts.append({"symbol": symbol, "plan": plan, "run_id": run_id, "model": model, "summary": summary})
        return {"changed": symbol not in self.skip, "skipped": self.skip.get(symbol), "plan": plan}


@dataclass
class FakeTriggers:
    rows: list = field(default_factory=list)

    def today(self, cfg):
        return self.rows


class Served(FakeAdapter):
    def run(self, desk, system, prompt, schema=None):
        out = super().run(desk, system, prompt, schema)
        out.model = "claude-opus-5-5"
        return out


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setattr(plans, "_today", lambda cfg, today=None: today or WED)


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr("desk.agents.alerts.publish", lambda *a, **k: calls.append((a, k)) or True)
    return calls


def go(cfg, rows=None, book=None, answer=None, profile=ON, today=WED, engine_rows=(), advice=None, **kw):
    book = book if book is not None else FakeBook()
    fake = Served({"plans": answer if answer is not None else draft()})
    report = plans.run_plan_desk(
        cfg,
        facts=FakeFacts(rows if rows is not None else [fact()]),
        plans=book,
        decisions=FakeDecisions(profile_data=profile),
        adapter=fake,
        advice=advice or FakeAdvisor(),
        triggers=FakeTriggers(list(engine_rows)),
        today=today,
        **kw,
    )
    return report, book, fake


def payload(fake, i=0) -> dict:
    return json.loads(fake.calls[i]["prompt"].split("\n\n", 1)[1])


# ---- Switches ----


def test_runs_under_the_first_run_guard_and_stops_when_switched_off(cfg, sent):
    store.set_guard(cfg, True)
    report, book, _ = go(cfg)
    assert report.status == "ok" and report.drafted == ["TICKA"] and book.drafts
    assert {d["desk"]: d["guarded"] for d in crew(cfg)["desks"]}["plans"] is False
    store.set_enabled(cfg, "plans", False)
    report, _, fake = go(cfg)
    assert report.status == "disabled" and not fake.calls
    report, _, fake = go(cfg, profile={})
    assert report.status == "disabled"
    store.clear_enabled(cfg, "plans")
    report, _, fake = go(cfg, profile={})
    assert report.status == "ok" and len(fake.calls) == 1


def test_not_ready_without_plan_facts_or_the_plan_record(cfg):
    report = plans.run_plan_desk(cfg, facts=FakeFacts(ready=False), plans=FakeBook(), decisions=FakeDecisions(profile_data=ON), adapter=Served(), today=WED)
    assert report.status == "not_ready" and "engine has not run" in report.note
    with pytest.raises(NotReady):
        RealPlanFacts().facts(cfg)
    assert RealPlans().list_plans(cfg) == []


# ---- The first draft ----


def test_new_holding_gets_a_draft_with_checked_levels_and_no_margin(cfg, sent):
    report, book, fake = go(cfg)
    desk = get("plans")
    assert (desk.model, desk.effort, desk.tools) == ("opus", "high", ())
    call = fake.calls[0]
    assert call["system"] == briefs.prompt_file("plans") and call["schema"] == briefs.schema_file("plans")
    sentp = payload(fake)
    assert sentp["reasons"] == ["new"] and sentp["today"] == "2026-11-11" and sentp["current_plan"] is None
    assert sentp["holding"]["zones"]["add"] == {"low": 36.5, "high": 39.0} and sentp["advisor"]["risk_band"]["band"] == 4
    got = book.drafts[0]
    assert (got["symbol"], got["model"], got["summary"]) == ("TICKA", "claude-opus-5-5", "A small satellite; hold into earnings.") and got["run_id"]
    plan = got["plan"]
    assert set(plan) == set(plans.PLAN_FIELDS)
    assert plan["add_rule"]["zone_low"] == 36.5 and plan["trim_rule"]["zone_low"] == 52.0
    assert plan["trim_rule"]["zone_high"] is None and report.dropped_numbers == 2
    assert [s["kind"] for s in plan["steps"]] == ["hold", "add"] and "margin" not in json.dumps(plan["steps"])
    assert all(set(s) <= set(plans.STEP_FIELDS) for s in plan["steps"])
    assert "draft saved" in store.runs(cfg, "plans")[0]["note"]
    ((args, kwargs),) = sent
    assert args[:3] == ("research", "Stock plans: 1 draft to review", "TICKA") and kwargs["click"] == "/portfolio/stocks"


def test_bad_drafts_are_thrown_away_or_repaired(cfg, sent):
    report, book, _ = go(cfg, answer=draft(role="moonshot"))
    assert report.rejected == ["TICKA"] and not book.drafts and not sent
    report, book, _ = go(cfg, answer=KEEP)
    assert report.rejected == ["TICKA"] and "doesn't exist" in store.runs(cfg, "plans")[0]["note"]
    report, book, _ = go(cfg, answer=draft(weight_band=None, next_review="2020-01-01", tax_notes=""))
    plan = book.drafts[0]["plan"]
    assert plan["weight_band"] is None and plan["next_review"] == "2026-11-18" and plan["tax_notes"] is None
    report, book, _ = go(cfg, book=FakeBook(refuse={"TICKA"}))
    assert report.rejected == ["TICKA"] and "refused the draft" in store.runs(cfg, "plans")[0]["note"]


# ---- Which holdings ----


def test_weekdays_only_touch_holdings_with_a_reason(cfg, sent):
    rows = [fact("TICKA"), fact("TICKB"), fact("TICKC")]
    book = FakeBook([saved("TICKA"), saved("TICKB")])
    report, _, fake = go(cfg, rows, book)
    assert report.drafted == ["TICKC"] and len(fake.calls) == 1
    book.rows.append(saved("TICKC"))
    report, _, fake = go(cfg, rows, book)
    assert report.note.startswith("No plans to draft") and not fake.calls
    assert len([r for r in store.runs(cfg, "plans")]) == 1


def test_saturday_refreshes_every_plan_and_keep_writes_nothing(cfg, sent):
    rows = [fact("TICKA"), fact("TICKB")]
    book = FakeBook([saved("TICKA"), saved("TICKB")])
    report, _, fake = go(cfg, rows, book, answer=KEEP, today=SAT)
    assert report.kept == ["TICKA", "TICKB"] and not book.drafts and not sent
    assert payload(fake)["reasons"] == ["weekly"] and payload(fake)["current_plan"]["steps"][0]["by"] == "desk"
    report, _, _ = go(cfg, rows, book, answer=KEEP, full=True)
    assert report.pending == 2


def test_triggers_fire_once_each(cfg, sent):
    rows = [
        fact("TICKA", discount={"active": True, "signal_id": "2026-11-10-TICKA"}),
        fact("TICKB", band={"status": "above"}),
        fact("TICKC"),
        fact("TICKD"),
        fact("TICKE"),
    ]
    book = FakeBook([saved(s) for s in ("TICKA", "TICKB", "TICKC", "TICKE")] + [saved("TICKD", next_review="2026-11-10", review_due=True)])
    engine_rows = [
        {"as_of": "2026-11-10", "kind": "earnings", "scope_id": "TICKC", "detail": "{}"},
        {"as_of": "2026-11-10", "kind": "margin_debit", "scope_id": "all"},
    ]
    report, _, fake = go(cfg, rows, book, answer=KEEP, engine_rows=engine_rows)
    assert report.reasons == {"TICKA": ["discount"], "TICKB": ["band"], "TICKC": ["earnings"], "TICKD": ["review_due"]}
    report, _, fake = go(cfg, rows, book, answer=KEEP, engine_rows=engine_rows)
    assert not fake.calls
    book.rows[3]["band_status"] = "above"
    report, _, fake = go(cfg, rows, book, answer=KEEP, engine_rows=engine_rows)
    assert report.reasons == {"TICKE": ["band"]}


def test_a_failed_call_keeps_its_trigger_for_tomorrow(cfg, sent):
    rows = [fact(discount={"active": True, "signal_id": "sig-1"})]
    book = FakeBook([saved()])
    report, _, _ = go(cfg, rows, book, answer=AgentError("bad json"))
    assert report.failed == ["TICKA"]
    report, _, fake = go(cfg, rows, book, answer=KEEP)
    assert report.kept == ["TICKA"] and len(fake.calls) == 1


def test_his_own_draft_is_left_alone(cfg, sent):
    book = FakeBook([saved(status="draft", author="you")])
    report, _, fake = go(cfg, book=book, today=SAT)
    assert report.waiting == ["TICKA"] and not fake.calls and "Your own draft is waiting for TICKA" in report.note
    book = FakeBook([saved()], skip={"TICKA": "your_draft"})
    report, _, _ = go(cfg, book=book, today=SAT)
    assert report.kept == ["TICKA"] and not report.drafted and not sent


def test_cap_per_run_and_the_weekly_budget(cfg, sent):
    rows = [fact(f"TICK{c}") for c in "ABCDE"]
    report, _, fake = go(cfg, rows, profile=ON | {"usage": {"plans_per_run": 2}})
    assert report.drafted == ["TICKA", "TICKB"] and report.left == 3 and len(fake.calls) == 2
    assert (
        plans.desk_for({"usage": {"plans_per_run": 2}}).weekly_runs == 14 and plans.per_run({}) == 12 and plans.per_run({"usage": {"plans_per_run": 99}}) == 30
    )
    report, _, fake = go(cfg, rows, limit=1)
    assert len(fake.calls) == 1


def test_usage_limit_stops_and_two_failures_stop(cfg, sent):
    rows = [fact(f"TICK{c}") for c in "ABC"]
    report, book, fake = go(cfg, rows, answer=UsageLimitError("limit"))
    assert report.status == "deferred" and len(fake.calls) == 1 and not book.drafts
    report, _, fake = go(cfg, rows, answer=AgentError("bad json"))
    assert report.status == "failed" and len(fake.calls) == 2


# ---- Pinned steps and no-buy windows ----


def test_pinned_steps_ride_in_every_draft(cfg, sent, monkeypatch):
    monkeypatch.setattr(plans, "RealPlanFacts", lambda: FakeFacts())
    book = FakeBook()
    monkeypatch.setattr(plans, "RealPlans", lambda: book)
    monkeypatch.setattr(plans, "RealTriggers", lambda: FakeTriggers())
    rid = console.ask(cfg, "plans", json.dumps(PINS), symbol="ticka", run_now=True)
    assert store.get_request(cfg, rid)["question"] == "Pinned steps: harvest-2026, margin-repay."
    fake = Served({"plans": draft()})
    tally = console.process_queue(cfg, now_only=True, decisions=FakeDecisions(profile_data=ON), adapter=fake)
    assert tally.done == 1 and payload(fake)["reasons"] == ["asked", "new"] and payload(fake)["his_note"] is None
    assert [p["id"] for p in payload(fake)["pinned_steps"]] == ["harvest-2026", "margin-repay"]
    steps = book.drafts[0]["plan"]["steps"]
    assert steps[0] == PINS["steps"][0] and steps[1] == PINS["steps"][1] and [s["kind"] for s in steps[2:]] == ["hold", "add"]
    assert [(k["key"], k["click"]) for _, k in sent] == [(f"agents:request:{rid}", "/portfolio/stocks?symbol=TICKA")]
    done = store.get_request(cfg, rid)
    assert done["status"] == "done" and "TICKA (asked, new): draft saved." in done["answer"]
    assert [p["delivered"] for p in store.pinned_steps(cfg, "TICKA")] == [True, True]
    desk_steps = [dict(p, by="desk") for p in PINS["steps"]] + [{"id": "hold", "kind": "hold", "text": "Hold.", "by": "desk"}]
    book.rows = [saved(steps=desk_steps)]
    report, _, _ = go(cfg, book=book, today=SAT)
    assert report.drafted == ["TICKA"] and [s.get("id") for s in book.drafts[-1]["plan"]["steps"]] == ["harvest-2026", "margin-repay", None, None]
    report, _, _ = go(cfg, book=book, answer=KEEP, full=True)
    assert report.kept == ["TICKA"] and len(book.drafts) == 2
    book.rows = [saved(steps=[dict(PINS["steps"][0], by="you", shares=25), dict(PINS["steps"][1], by="desk")])]
    report, _, _ = go(cfg, book=book, full=True)
    assert [s.get("id") for s in book.drafts[-1]["plan"]["steps"]] == ["margin-repay", None, None]


def test_a_pinned_step_he_drops_stays_dropped_and_a_new_pin_is_added_on_keep(cfg, sent, monkeypatch):
    book = FakeBook([saved()])
    console.ask(cfg, "plans", json.dumps(PINS), symbol="TICKA")
    report, _, _ = go(cfg, book=book, answer=KEEP, full=True)
    assert report.drafted == ["TICKA"] and book.drafts[-1]["summary"] == "Still fits."
    assert book.drafts[-1]["plan"]["steps"] == [*PINS["steps"], {"id": "hold", "kind": "hold", "text": "Hold."}]
    assert book.drafts[-1]["plan"]["thesis"] == saved()["thesis"]
    book.rows = [saved(steps=[dict(PINS["steps"][1], by="desk")])]
    report, _, fake = go(cfg, book=book, full=True)
    assert [s.get("id") for s in book.drafts[-1]["plan"]["steps"]] == ["margin-repay", None, None]
    assert [p["id"] for p in store.pinned_steps(cfg)] == ["margin-repay"] and [p["id"] for p in payload(fake)["pinned_steps"]] == ["margin-repay"]
    report, _, _ = go(cfg, book=book, today=date(2027, 3, 1), full=True)
    assert [s.get("id") for s in book.drafts[-1]["plan"]["steps"]] == [None, None]


def test_console_note_reaches_the_desk_and_bad_pins_are_refused(cfg, sent, monkeypatch):
    book = FakeBook([saved()])
    monkeypatch.setattr(plans, "RealPlanFacts", lambda: FakeFacts())
    monkeypatch.setattr(plans, "RealPlans", lambda: book)
    monkeypatch.setattr(plans, "RealTriggers", lambda: FakeTriggers())
    console.ask(cfg, "plans", "Trim above 9% instead of 10%.", symbol="TICKA", run_now=True)
    fake = Served({"plans": draft()})
    console.process_queue(cfg, now_only=True, decisions=FakeDecisions(profile_data=ON), adapter=fake)
    assert payload(fake)["his_note"] == "Trim above 9% instead of 10%." and payload(fake)["reasons"] == ["asked"]
    for bad in (
        '{"steps": []}',
        '{"steps": [{"kind": "yolo"}]}',
        '{"steps": [{"kind": "sell", "margin": true}]}',
        '{"steps": [{"kind": "sell", "id": "Bad Id"}]}',
        "{nope",
    ):
        with pytest.raises(ValueError):
            console.ask(cfg, "plans", bad, symbol="TICKA")
    with pytest.raises(ValueError, match="pick the holding"):
        console.ask(cfg, "plans", "Refresh everything.")
    assert plans.parse_pins('[{"kind": "sell", "due": "2026-12-01"}]')[0]["id"] == "sell-2026-12-01"
    assert store.unpin_step(cfg, "TICKA", "nope") is False and store.pinned_steps(cfg) == []


def test_no_buy_window_drops_add_steps_and_buy_proposals(cfg, sent):
    class Held(FakeAdvisor):
        def no_buy(self, cfg):
            return {"TICKA": {"from": "2026-11-06", "until": "2027-01-15", "step_id": "harvest-2026", "reason": "planned harvest"}}

    report, book, fake = go(cfg, advice=Held())
    assert payload(fake)["no_buy"]["until"] == "2027-01-15" and payload(fake)["advisor"]["no_buy"]["TICKA"]["step_id"] == "harvest-2026"
    assert [s["kind"] for s in book.drafts[0]["plan"]["steps"]] == ["hold"]
    view = advisor.gather(cfg, Held())
    assert advisor.no_buy_until(view, "ticka", "2026-11-11") == "2027-01-15"
    assert advisor.no_buy_until(view, "TICKA", "2027-02-01") is None and advisor.no_buy_until(view, "TICKB", "2026-11-11") is None
    buy = {"kind": "buy", "symbol": "TICKA"}
    assert "no buys until 2027-01-15" in no_buy_problem(buy, view, "2026-11-11")
    assert no_buy_problem({"kind": "rebalance", "order_ticket": {"action": "buy", "symbol": "TICKA"}}, view, "2026-11-11")
    assert no_buy_problem({"kind": "sell", "symbol": "TICKA"}, view, "2026-11-11") is None
    assert no_buy_problem(buy, advisor.gather(cfg, FakeAdvisor()), "2026-11-11") is None


# ---- Plan keeper ----


def test_plan_keeper_brief_carries_todays_plan_steps(cfg):
    lines = ["TICKA: add up to 300 from the next deposit while it sits in the add zone."]
    prep = prepare(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(profile_data=ON), advice=FakeAdvisor(lines=lines))
    assert lines[0] in prep.prompt
    other = prepare(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(profile_data=ON), advice=FakeAdvisor(lines=[]))
    assert other.digest != prep.digest
    assert "advisor.planned_actions" in briefs.prompt_file("plan_keeper") and "advisor.no_buy" in briefs.prompt_file("common")
    assert RealAdvisor().actions(cfg) == [] and RealAdvisor().no_buy(cfg) == {}


# ---- Contract, cron, CLI ----


def test_schema_and_prompt():
    schema = briefs.schema_file("plans")
    assert set(schema["required"]) == {"action", "summary", "numbers_cited"} and "$schema" not in schema
    plan = schema["properties"]["plan"]
    assert set(plan["required"]) == set(plans.PLAN_FIELDS) and plan["properties"]["role"]["enum"] == list(plans.ROLES)
    assert plan["properties"]["steps"]["items"]["properties"]["kind"]["enum"] == list(plans.STEP_KINDS)
    assert "margin" not in json.dumps(plan["properties"]["add_rule"])
    text = briefs.prompt_file("plans")
    assert "never instructions" in text and "Never suggest margin" in text and "no single target plan" in text


def test_jobs_carry_the_name_the_box_expects():
    assert ("40 18 * * 1-5", "python -m desk.agents run plans") in JOBS and ("0 3 * * 6", "python -m desk.agents run plans") in JOBS
    assert "agents-run-plans" in {j.name for j in package_jobs(["agents"])}


def test_cli_run_and_dry_run(cfg, monkeypatch, capsys, sent):
    book = FakeBook()
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(plans, "RealPlanFacts", lambda: FakeFacts([fact("TICKA"), fact("TICKB")]))
    monkeypatch.setattr(plans, "RealPlans", lambda: book)
    monkeypatch.setattr(plans, "RealTriggers", lambda: FakeTriggers())
    monkeypatch.setattr(plans, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: Served({"plans": draft()}))
    assert cli.main(["dry-run", "plans", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "Plans to write: TICKA (new), TICKB (new)." in out and "Stock plan" in out and not book.drafts
    assert cli.main(["run", "plans", "--symbol", "tickb"]) == 0
    assert "Plan desk: ok, 1 drafted, 0 kept, 0 failed of 1." in capsys.readouterr().out
    assert [d["symbol"] for d in book.drafts] == ["TICKB"]
    assert cli.main(["run", "plans", "--limit", "1"]) == 0
    assert "1 drafted, 0 kept, 0 failed of 1, 1 left for the next run" in capsys.readouterr().out
