from datetime import timedelta

import pytest

from desk.decisions import approve, create_proposal, next_steps
from desk.decisions import steps as listing
from desk.decisions.plans import save_plan

PROFILE = """
deposits:
  - id: payday
    account: brokerage
    cadence: biweekly
    anchor: "2026-11-06"
    amount_usd: 500
rules:
  - id: no-margin-buys
    kind: no_margin_buys
  - id: drift-max
    kind: drift_max_pts
    params: {pts: 5}
"""
PLAN = {
    "role": "conviction",
    "thesis": "Made-up thesis for a test. A second sentence.",
    "steps": [
        {"id": "harvest", "kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "shares": 40, "lots": "highest_cost", "account": "Brokerage"},
        {"id": "repay", "kind": "repay", "due": "2026-11-18"},
        {"id": "add", "kind": "add", "when": "On a pullback below 20", "text": "Add on a pullback"},
        {"id": "far", "kind": "review", "due": "2027-06-01"},
    ],
}
ROW = {"status": "tested", "outdated": False, "tested_at": "2026-11-08T05:00:00+00:00"}
LIBRARY = {
    "lib-margin-paydown": ROW
    | {"title": "Pay the margin debit first", "verdict": "within_noise", "line": "Helped: ahead in 86% of 120 start months.", "backs": "yes"},
    "lib-harvest": ROW | {"title": "Tax-loss harvesting", "verdict": "held_up", "line": "Helped: ahead in 70% of 120 start months.", "backs": "yes"},
    "lib-deposit-steering": ROW
    | {"title": "Steer deposits to what is behind", "verdict": "within_noise", "line": "No clear edge: behind in 94%.", "backs": "no"},
    "lib-margin-dip": ROW
    | {"title": "Borrow on margin to buy a dip", "verdict": "fell_short", "line": "Hurt: behind in 80% of 120 start months.", "backs": "no"},
}


@pytest.fixture
def lab(monkeypatch):
    rows = dict(LIBRARY)
    monkeypatch.setattr(listing, "_library", lambda cfg, ids: {k: v for k, v in rows.items() if k in ids})
    return rows


@pytest.fixture
def home(cfg, lab):
    (cfg.data_dir / "desk.yaml").write_text(PROFILE)
    return cfg


def debit(conn, day, value):
    conn.execute(
        "INSERT OR REPLACE INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, n_obs, quality, engine_version) "
        "VALUES ('margin.debit', 'portfolio', 'all', 'now', ?, ?, 'usd', 1, 'ok', '1')",
        (day, value),
    )
    conn.commit()


def test_one_ordered_list_from_the_plan_the_deposits_and_the_rules(home, now):
    save_plan(home, "ABCD", PLAN, approve=True, now=now)
    out = next_steps(home, now=now)
    assert (out["as_of"], out["days"], out["count"]) == ("2026-11-09", 90, 2)
    assert [(r["id"], r["date"], r["until"]) for r in out["items"]] == [
        ("deposit:payday:2026-11-20", "2026-11-20", None),
        ("plan:ABCD:harvest", "2026-12-07", "2026-12-15"),
    ]
    pay, sale = out["items"]
    assert pay["text"] == "Deposit of $500 lands and pays the margin debit" and pay["source"] == "deposit" and pay["completes"] == "desk"
    assert pay["why"] == "The debit costs about 12% a year, more than a deposit usually earns on the same money."
    assert pay["basis"] == "Your ABCD plan, version 1, approved Nov 9." and pay["ref"]["step_id"] == "repay" and pay["ref"]["deposit_id"] == "payday"
    assert pay["changes_if"].startswith("Retires by itself once the margin debit reads zero.")
    assert pay["backed"] == "yes" and pay["evidence"] == [
        {
            "row": "lib-margin-paydown",
            "title": "Pay the margin debit first",
            "sentence": "Helped: ahead in 86% of 120 start months.",
            "verdict": "within_noise",
            "tested_at": "2026-11-08T05:00:00+00:00",
            "stance": "for",
            "reading": "yes",
            "words": "The lab's test backs this.",
        }
    ]
    assert sale["text"] == "Sell 40 ABCD to harvest the loss" and sale["detail"] == "From Brokerage. Lots: Specific Shares, highest-cost lots."
    assert (sale["symbol"], sale["status"], sale["completes"], sale["backed"]) == ("ABCD", "upcoming", "broker", "yes")
    assert sale["changes_if"] == "No longer worth doing if ABCD is back above your cost."
    standing = {r["id"]: r for r in out["standing"]}
    assert list(standing) == ["nobuy:ABCD", "rule:no-margin-buys", "plan:ABCD:add"]
    assert standing["nobuy:ABCD"]["text"] == "No ABCD buys in any account until 31 days after the sale"
    rule = standing["rule:no-margin-buys"]
    assert rule["text"] == "No new buys on margin" and rule["evidence"][0]["stance"] == "against" and rule["backed"] == "yes"
    assert standing["plan:ABCD:add"]["when"] == "On a pullback below 20" and standing["plan:ABCD:add"]["why"] == "Made-up thesis for a test."
    assert all(r["date"] is None and r["status"] in (None, "waiting") for r in out["standing"])
    assert set(out["readings"]) == {"yes", "no_edge", "no", "untested"}


def test_a_route_the_lab_does_not_back_says_so_and_an_agreed_note_claims_the_deposit(home, preflight, now, desk_db, proposal):
    route = create_proposal(
        home, proposal(kind="deposit_route", funding="deposit", title="Route $500 to WXYZ", expires="2099-01-01"), "plan_keeper", "r1", now=now
    )
    first = next_steps(home, now=now)["items"]
    assert [r["id"] for r in first] == ["deposit:payday:2026-11-20"]
    assert first[0]["text"] == "Deposit of $500 lands. The Plan keeper's route for it is waiting in your queue: Route $500 to WXYZ"
    assert (first[0]["backed"], first[0]["completes"], first[0]["ref"]["decision_id"]) == ("no", "you", route["id"])
    assert first[0]["evidence"][0]["words"] == "The lab's test does not back this."
    approve(home, route["id"], now=now)
    after = next_steps(home, now=now)["items"][0]
    assert after["text"] == "Deposit of $500 lands: Route $500 to WXYZ" and after["basis"] == "You approved this route on Nov 9."
    note = create_proposal(
        home,
        proposal(kind="hold_off", symbol=None, subject="margin", title="Margin loan: let deposits pay it off first", invalidation="The debit is paid off."),
        "plan_keeper",
        "r1",
        now=now,
    )
    approve(home, note["id"], now=now)
    out = next_steps(home, now=now)
    assert out["items"][0]["text"] == "Deposit of $500 lands and goes to the margin debit first"
    assert out["items"][0]["basis"] == "You agreed to this Plan keeper note on Nov 9." and out["items"][0]["backed"] == "yes"
    agreed = out["standing"][0]
    assert (agreed["id"], agreed["source"], agreed["text"]) == (f"agreed:{note['id']}", "agreed", "Margin loan: let deposits pay it off first")
    assert agreed["changes_if"] == "The debit is paid off." and agreed["until"] is None and agreed["backed"] == "yes"
    debit(desk_db, "2026-11-10", 0.0)
    later = next_steps(home, now=now + timedelta(days=2))
    assert later["items"][0]["text"] == "Deposit of $500 lands: Route $500 to WXYZ"
    assert [r["id"] for r in later["standing"]] == ["rule:no-margin-buys"]
    assert next_steps(home, now=now + timedelta(days=40))["standing"][0]["id"] == "rule:no-margin-buys"


def test_a_deposit_with_nothing_planned_shows_once_and_a_late_one_never(home, now):
    out = next_steps(home, now=now)
    assert [(r["id"], r["text"], r["basis"]) for r in out["items"]] == [
        ("deposit:payday:2026-11-20", "Deposit of $500 lands. Nothing is planned for it yet", "From your deposit schedule.")
    ]
    assert out["items"][0]["evidence"] == [] and out["items"][0]["backed"] is None
    assert next_steps(home, days=5, now=now)["items"] == []


@pytest.mark.parametrize(
    ("row", "backs"),
    [
        ({"verdict": "within_noise", "rule": {"share_better": 0.86, "share_worse": 0.1}}, "yes"),
        ({"verdict": "within_noise", "rule": {"share_better": 0.04, "share_worse": 0.94}}, "no"),
        ({"verdict": "within_noise", "rule": {"share_better": 0.4, "share_worse": 0.4}}, "no_edge"),
        ({"verdict": "held_up", "rule": None}, "yes"),
        ({"verdict": "fell_short", "rule": None}, "no"),
        ({"verdict": "inconclusive", "rule": None}, None),
        ({"verdict": "held_up", "rule": None, "outdated": True}, None),
        ({"verdict": None, "status": "waiting"}, None),
    ],
)
def test_which_results_count_as_backing(row, backs):
    assert listing._backs({"status": "tested", "outdated": False} | row) == backs


def test_a_missing_row_reads_untested_and_the_route_answers(home, lab, now, app_client):
    lab.clear()
    save_plan(home, "ABCD", PLAN, approve=True, now=now)
    body = app_client(packages=["decisions"]).get("/api/decisions/next-steps?days=366").json()
    assert set(body) == {"as_of", "days", "count", "items", "standing", "readings"} and body["days"] == 366
    cited = [r for r in body["items"] + body["standing"] if r["evidence"]]
    assert cited and all(r["backed"] == "untested" and r["evidence"][0]["words"] == "The lab has not judged this yet." for r in cited)
    assert set(body["items"][0]) == {
        "id",
        "symbol",
        "date",
        "until",
        "text",
        "detail",
        "why",
        "basis",
        "changes_if",
        "source",
        "ref",
        "status",
        "completes",
        "when",
        "evidence",
        "backed",
    }
