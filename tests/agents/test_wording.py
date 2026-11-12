import json

import pytest

from desk.agents import debrief, wording
from desk.agents.adapter import FakeAdapter
from desk.agents.briefs import prompt_file, system_prompt
from desk.agents.pipeline import run_proposal_desk
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, proposal


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Equity share is 81.2345% against a band of 60.0% to 80%.", "Equity share is 81.2% against a band of 60% to 80%."),
        ("Cash ready to invest is $1,234.5678; the debit is $2800.5.", "Cash ready to invest is $1,235; the debit is $2,800."),
        ("It trades at $30.12, inside the $28.5 to $31.25 zone.", "It trades at $30.12, inside the $28.5 to $31.25 zone."),
        ("Drift is -4.2567 pts and 12.00 points; ratio 0.84531.", "Drift is -4.3 pts and 12 points; ratio 0.85."),
        ("Up 1,234.5678% since 2026-11-06, build 1.2.3.", "Up 1,234.6% since 2026-11-06, build 1.2.3."),
        ("Nothing to round here: 8.4% and $300.", "Nothing to round here: 8.4% and $300."),
    ],
)
def test_tidy_rounds_what_he_reads(text, want):
    assert wording.tidy(text) == want and wording.tidy(want) == want
    assert wording.tidy(None) is None and wording.tidy("") == ""


@pytest.mark.parametrize(
    ("desk", "p", "want"),
    [
        ("plan_keeper", {"kind": "deposit_route", "symbol": "FUNDA"}, "next-deposit"),
        ("plan_keeper", {"kind": "hold_off", "title": "Margin debit: pay it down first", "symbol": None}, "margin"),
        ("plan_keeper", {"kind": "alert", "rule_served": "Single-stock max 10%", "symbol": "TICKA"}, "rule:single-stock-max"),
        ("plan_keeper", {"kind": "alert", "rule_served": "Single-stock max 12.5%"}, "rule:single-stock-max"),
        ("research", {"kind": "buy", "symbol": "ticka"}, "buy:TICKA"),
        ("scout", {"kind": "deposit_route", "symbol": "FUNDB"}, "buy:FUNDB"),
        ("tax", {"kind": "harvest", "symbol": "TICKA"}, "sell:TICKA"),
        ("risk", {"kind": "trim", "symbol": "TICKA"}, "sell:TICKA"),
        ("risk", {"kind": "rebalance", "symbol": "FUNDA"}, "rebalance:FUNDA"),
        ("risk", {"kind": "hold_off", "symbol": "TICKA", "title": "Hold off adding"}, "hold_off:TICKA"),
        ("risk", {"kind": "memo", "title": "Equity share is 81.2% today"}, "memo:equity-share-is-today"),
        ("risk", {"kind": "memo"}, "memo:general"),
    ],
)
def test_subject_is_stable_and_carries_no_numbers(desk, p, want):
    assert wording.subject_for(desk, p) == want
    assert not any(c.isdigit() for c in want)


def test_proposals_reach_the_record_with_subject_as_of_and_rounded_prose(cfg):
    slice_ = SLICE | {"data_as_of": "2026-11-06"}
    answer = {
        "summary": "Equity share is 81.2345% of the book.\nCash ready to invest is $1,500.0000.",
        "proposals": [proposal(title="Send $1,500.00 to FUNDA, now -4.2000 pts under", thesis="FUNDA is 4.2000% under its weight.")],
    }
    decisions = FakeDecisions()
    report = run_proposal_desk(cfg, "plan_keeper", engine=FakeEngine(slice_), decisions=decisions, adapter=FakeAdapter({"plan_keeper": answer}))
    assert report.status == "ok" and len(report.created) == 1
    sent = decisions.created[0][2]
    assert (sent["subject"], sent["as_of"]) == ("next-deposit", "2026-11-06")
    assert sent["title"] == "Send $1,500 to FUNDA, now -4.2 pts under" and sent["thesis"] == "FUNDA is 4.2% under its weight."
    assert sent["numbers_used"] == proposal()["numbers_used"]
    assert report.summary == "Equity share is 81.2% of the book.\nCash ready to invest is $1,500."


def test_debrief_text_is_rounded_but_cited_numbers_are_not():
    row = {"digest": "d", "pack": {"numbers": {"twr_pct": 1.23456}}}
    answer = {
        "headline": "Up 1.23456% on the day",
        "what_happened": "Up 1.23456%.",
        "why": "The market.",
        "against_decisions": "",
        "numbers_cited": ["twr_pct"],
    }
    out, dropped = debrief.result_for(answer, row, "opus", 1)
    assert out["headline"] == "Up 1.2% on the day" and out["what_happened"] == "Up 1.2%." and dropped == 0


def test_prompts_ask_for_plain_rounded_text_and_one_cash_figure():
    common = system_prompt("plan_keeper")
    for words in (
        "one decimal at most",
        "One cash figure",
        "Never show the machinery",
        "Don't raise the same thing twice",
        "the same words every day",
        "`day.provisional`",
        "never a count",
    ):
        assert words in common
    assert "say so in `summary` instead of working it out" not in common
    for name in ("debrief", "plans"):
        assert "one decimal at most" in prompt_file(name) and "Never show the machinery" in prompt_file(name)
    assert json.dumps(wording.stamp({"kind": "memo", "title": "x"}, "risk", {})) == json.dumps({"kind": "memo", "title": "x", "subject": "memo:x"})
