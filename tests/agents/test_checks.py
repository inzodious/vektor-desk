from dataclasses import dataclass, field

from desk.agents import advisor, checks, wording
from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import run_proposal_desk
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer, proposal
from tests.agents.test_advisor import FakeAdvisor

TODAY = "2026-11-12"
STEPS = [
    {"symbol": "TICKA", "kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "status": "upcoming", "purpose": "Sell 10 TICKA to harvest the loss"},
    {"symbol": "TICKA", "kind": "repay", "due": "2026-11-18", "until": None, "status": "upcoming", "purpose": "The deposit pays off the margin debit."},
]


def trim(**over) -> dict:
    p = proposal(
        kind="trim",
        title="Trim TICKA",
        symbol="TICKA",
        thesis="It is above its band.",
        rule_served="single-stock band",
        horizon="now",
        funding=None,
        order_ticket={"action": "sell", "symbol": "TICKA", "shares": 10, "order_type": "market", "account": "taxable"},
    )
    return p | over


def hold_off(**over) -> dict:
    return (
        proposal(kind="hold_off", title="Hold off: no new buys until the margin debit is paid", symbol=None, rule_served="no margin", order_ticket=None) | over
    )


# ---- One function: a proposal against the plan ----


def test_a_sale_ahead_of_its_planned_window_is_refused_unless_it_names_the_window():
    assert checks.queue_problem(trim(), steps=STEPS, today=TODAY) == "Your plan already times this sale for Dec 7 to 15."
    for horizon in ("Dec 7 to Dec 15", "December 7 through 15", "2026-12-07 to 2026-12-15", "Dec. 07", "12/7 to 12/15"):
        assert checks.queue_problem(trim(horizon=horizon), steps=STEPS, today=TODAY) is None
    assert checks.queue_problem(trim(horizon="Dec 17"), steps=STEPS, today=TODAY) == "Your plan already times this sale for Dec 7 to 15."
    assert checks.queue_problem(trim(), steps=STEPS, today="2026-12-08") is None
    assert checks.queue_problem(trim(symbol="TICKB"), steps=STEPS, today=TODAY) is None
    assert checks.queue_problem(proposal(), steps=STEPS, today=TODAY) is None
    assert checks.queue_problem(trim(), steps=[STEPS[0] | {"status": "done"}], today=TODAY) is None
    assert checks.queue_problem(trim(), steps=[], today=TODAY) is None


def test_a_sale_to_pay_margin_is_refused_while_a_repay_step_is_planned():
    said = trim(symbol="TICKB", thesis="Selling some would clear the margin debit and ease concentration.")
    assert checks.queue_problem(said, steps=STEPS, today=TODAY) == "Your plan already pays the margin debit down on Nov 18, so no sale is needed for it."
    assert checks.queue_problem(said, steps=STEPS[:1], today=TODAY) is None
    assert (
        checks.queue_problem(trim(symbol="TICKB", thesis="The margin debit is already covered, this is about concentration."), steps=STEPS, today=TODAY) is None
    )
    window = trim(horizon="Dec 7 to Dec 15", thesis="Sell in your planned window; it also pays down margin.")
    assert checks.queue_problem(window, steps=STEPS, today=TODAY).startswith("Your plan already pays the margin debit down")


def test_plain_dates():
    assert checks.plain_window("2026-12-07", "2026-12-15") == "Dec 7 to 15" and checks.plain_window("2026-12-28", "2027-01-04") == "Dec 28 to Jan 4"
    assert checks.plain_window("2026-11-18", None) == "Nov 18" and checks.plain_window("2026-11-18", "2026-11-18") == "Nov 18"
    assert not checks.names_day("sell by dec 70", "2026-12-07") and checks.names_day("in the dec 7 window", "2026-12-07")


def test_one_margin_hold_off_across_desks():
    keeper = {
        "id": 4,
        "origin": "plan_keeper",
        "kind": "hold_off",
        "symbol": None,
        "subject": "margin",
        "title": "Hold off: let deposits pay off the margin loan first",
    }
    other = {
        "id": 7,
        "origin": "risk",
        "kind": "hold_off",
        "symbol": None,
        "subject": "hold_off:general",
        "title": "No new brokerage buys until the margin debit is paid",
    }
    single = {
        "id": 5,
        "origin": "risk",
        "kind": "hold_off",
        "symbol": "TICKB",
        "subject": "hold_off:TICKB",
        "title": "Hold off TICKB: above the single-stock line",
    }
    said = "Already covered by a standing note: Hold off: let deposits pay off the margin loan first."
    assert checks.queue_problem(hold_off(), today=TODAY, desk="risk", standing=[keeper, single]) == said
    assert checks.queue_problem(other, today=TODAY, standing=[keeper, other, single]) == said
    assert checks.queue_problem(keeper, today=TODAY, standing=[keeper, other, single]) is None
    assert checks.queue_problem(hold_off(), today=TODAY, desk="plan_keeper", standing=[other]) is None
    assert checks.queue_problem(hold_off(), today=TODAY, desk="risk", standing=[other]) is None
    assert checks.queue_problem(single, today=TODAY, standing=[keeper, other, single]) is None
    tax = other | {"id": 9, "origin": "tax"}
    assert (
        checks.queue_problem(tax, today=TODAY, standing=[other, tax]).startswith("Already covered")
        and checks.queue_problem(other, today=TODAY, standing=[other, tax]) is None
    )
    assert wording.subject_for("risk", hold_off()) == "margin" and wording.subject_for("plan_keeper", hold_off()) == "margin"
    assert wording.subject_for("risk", hold_off(symbol="TICKB", title="Hold off TICKB while margin is open")) == "hold_off:TICKB"


# ---- In the desks ----


@dataclass
class Planned(FakeAdvisor):
    plan: list = field(
        default_factory=lambda: [s | {"due": s["due"].replace("2026", "2099"), "until": s["until"] and s["until"].replace("2026", "2099")} for s in STEPS]
    )

    def steps(self, cfg, days):
        assert days == advisor.STEPS_AHEAD_DAYS
        return [s | {"shares": 10, "account": "Individual-0001"} for s in self.plan]


@dataclass
class Queue(FakeDecisions):
    waiting: list = field(default_factory=list)

    def standing(self, cfg):
        return self.waiting


def test_desks_get_the_plan_steps_and_the_whole_queue_and_conflicts_never_reach_it(cfg):
    import json

    keeper = {"origin": "plan_keeper", "kind": "hold_off", "symbol": None, "subject": "margin", "title": "Hold off: let deposits pay off the margin loan first"}
    decisions = Queue(waiting=[keeper])
    early, timed, twice = trim(), trim(title="Trim TICKA in your December window", horizon="Dec 7 to Dec 15"), hold_off()
    fake = FakeAdapter({"risk": answer(early, timed, twice)})
    report = run_proposal_desk(cfg, "risk", engine=FakeEngine(SLICE), decisions=decisions, adapter=fake, advice=Planned(), trigger="console")
    assert report.status == "ok"
    assert [p["title"] for _, _, p in decisions.created] == ["Trim TICKA in your December window"]
    assert [r[1] for r in decisions.rejected] == [
        "Your plan already times this sale for Dec 7 to 15.",
        "Already covered by a standing note: Hold off: let deposits pay off the margin loan first.",
    ]
    payload = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert payload["standing"] == [keeper]
    steps = payload["advisor"]["upcoming_steps"]
    assert [(s["symbol"], s["kind"], s["due"]) for s in steps] == [("TICKA", "harvest", "2099-12-07"), ("TICKA", "repay", "2099-11-18")]
    assert all(set(s) == {"symbol", "kind", "due", "until", "status", "purpose"} for s in steps) and "Individual-0001" not in fake.calls[0]["prompt"]
    assert "`advisor.upcoming_steps`" in fake.calls[0]["system"] and "`standing`" in fake.calls[0]["system"]


def test_advisor_without_plan_steps_changes_nothing(cfg):
    view = advisor.gather(cfg, FakeAdvisor())
    assert view["plan_steps"] == [] and advisor.summary(view)["upcoming_steps"] == []
    broken = Planned()
    broken.steps = lambda cfg, days: (_ for _ in ()).throw(ValueError("bad plan row"))
    assert advisor.gather(cfg, broken)["plan_steps"] == []
