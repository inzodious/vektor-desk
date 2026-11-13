from datetime import date, datetime, timedelta

import pytest

from desk.decisions import approve, create_proposal, get, next_steps, pass_on
from desk.decisions import steps as listing
from desk.decisions.__main__ import night
from desk.decisions.plans import open_steps, save_plan
from desk.decisions.said import read_date
from desk.decisions.store import session

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
        "read",
        "undo",
    }


# ---- His own words ----

SAID = "I will sell enough to harvest tax losses after Dec 6"


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (SAID, ("2026-12-07", None, "after Dec 6")),
        ("Paying margin off on Nov 18", ("2026-11-18", None, "Nov 18")),
        ("Will do it by December 15th.", ("2026-11-12", "2026-12-15", "by December 15th")),
        ("before 12/31", ("2026-11-12", "2026-12-30", "before 12/31")),
        ("Revisit in January", ("2027-01-01", "2027-01-31", "in January")),
        ("Jan 15 is better", ("2027-01-15", None, "Jan 15")),
        ("after the 6th of December", ("2026-12-07", None, "after the 6th of December")),
        ("on 2026-12-01", ("2026-12-01", None, "2026-12-01")),
        ("next week", ("2026-11-16", "2026-11-20", "next week")),
        ("tomorrow morning", ("2026-11-13", None, "tomorrow")),
        ("in 2 weeks", ("2026-11-26", None, "in 2 weeks")),
        ("by year end", ("2026-11-12", "2026-12-31", "by year end")),
        ("Sell 1/2 now and the rest later", None),
        ("Already sold some on Nov 3", None),
        ("sell 10 may be later", None),
        ("Too expensive", None),
        ("", None),
    ],
)
def test_reading_a_date_from_his_words(text, found):
    read = read_date(text, date(2026, 11, 12))
    assert (read and (read["date"], read["until"], read["phrase"])) == found


def test_a_pass_reason_with_a_date_becomes_a_step_without_a_second_tap(home, preflight, now, proposal, monkeypatch, app_client):
    trim = create_proposal(home, proposal(kind="trim", title="Trim ABCD", shares=10, amount_usd=None, expires="2099-01-01"), "risk", "k1", now=now)
    passed = pass_on(home, trim["id"], SAID + ".", now=now)
    step = passed["step"]
    assert (step["source"], step["symbol"], step["text"], step["date"], step["until"]) == ("you", "ABCD", SAID + ".", "2026-12-07", "2026-12-31")
    assert step["read"] == {"date": "2026-12-07", "until": "2026-12-31", "phrase": "after Dec 6"}
    assert step["basis"] == "Your words on Nov 9, when you passed on “Trim ABCD”." and step["completes"] == "broker" and step["backed"] == "yes"
    assert step["changes_if"].startswith("Completes itself when the broker shows the sale, and leaves the list after Dec 31 if there is none.")
    assert step["undo"] == {"method": "DELETE", "path": f"/api/decisions/next-steps/{step['ref']['step_id']}"}
    assert [r["id"] for r in next_steps(home, now=now)["items"]] == ["deposit:payday:2026-11-20", step["id"]]
    seen = [s for s in open_steps(home, days=60, now=now) if s["symbol"] == "ABCD"]
    assert [(s["kind"], s["status"], s["due"], s["by"]) for s in seen] == [("harvest", "upcoming", "2026-12-07", "you")]
    assert seen[0]["line"] == f"ABCD: {SAID}. Window 2026-12-07 to 2026-12-31 (upcoming)."
    again = create_proposal(home, proposal(kind="trim", title="Trim ABCD again", shares=10, amount_usd=None, expires="2099-01-01"), "risk", "k2", now=now)
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now)
    night(home)
    assert get(home, again["id"])["status_reason"] == "Your plan already times this sale for Dec 7 to 31."
    client = app_client(packages=["decisions"])
    assert client.delete(step["undo"]["path"]).json() == {"removed": step["ref"]["step_id"]}
    assert client.delete(step["undo"]["path"]).status_code == 409 and client.delete("/api/decisions/next-steps/nope").status_code == 404
    assert [e["event"] for e in get(home, trim["id"])["events"]][-3:] == ["passed", "step_added", "step_removed"]
    assert [r["id"] for r in next_steps(home, now=now)["items"]] == ["deposit:payday:2026-11-20"]


def test_older_passes_are_read_once_and_only_intent_without_a_date_stands(home, preflight, now, proposal):
    made = {}
    reasons = {"dated": SAID, "wait": "I'll wait for earnings first", "no": "Too expensive", "old": "Selling on Dec 1"}
    for i, (key, reason) in enumerate(reasons.items()):
        at = now - timedelta(days=90 if key == "old" else 3)
        d = create_proposal(home, proposal(kind="trim", symbol=f"AAA{i}", shares=5, amount_usd=None, expires="2099-01-01"), "risk", f"k{i}", now=at)
        made[key] = pass_on(home, d["id"], reason, now=at)
    with session(home) as conn:
        conn.execute("DELETE FROM loose_steps")
        conn.commit()
    out = next_steps(home, now=now)
    mine = {r["ref"]["decision_id"]: r for r in out["items"] + out["standing"] if r["source"] == "you"}
    assert set(mine) == {made["dated"]["id"], made["wait"]["id"]}
    assert mine[made["dated"]["id"]]["basis"].startswith("Your words on Nov 6") and mine[made["dated"]["id"]]["date"] == "2026-12-07"
    wait = mine[made["wait"]["id"]]
    assert (wait["date"], wait["read"], wait["text"], wait["changes_if"]) == (None, None, "I'll wait for earnings first", "Yours to take off the list.")
    assert wait in out["standing"]
    with session(home) as conn:
        counts = [tuple(r) for r in conn.execute("SELECT status, COUNT(*) FROM loose_steps GROUP BY status ORDER BY status")]
        assert counts == [("open", 1), ("skipped", 1), ("standing", 1)]
        conn.execute("UPDATE loose_steps SET status='removed' WHERE status='open'")
        conn.commit()
    assert [r["source"] for r in next_steps(home, now=now)["items"]] == ["deposit"]


def test_his_step_completes_from_the_fill_retires_after_its_window_and_hides_behind_a_plan(home, preflight, now, proposal, mirror):
    ids = {}
    for sym in ("ABCD", "WXYZ", "EFGH"):
        d = create_proposal(home, proposal(kind="trim", symbol=sym, shares=10, amount_usd=None, expires="2099-01-01"), "risk", f"k-{sym}", now=now)
        ids[sym] = pass_on(home, d["id"], SAID, now=now)["id"]
    save_plan(home, "EFGH", {"role": "core", "thesis": "Made-up.", "steps": [{"id": "trim", "kind": "trim", "due": "2026-12-10"}]}, approve=True, now=now)
    listed = [r["id"] for r in next_steps(home, now=now)["items"] if r["symbol"]]
    assert [i.split(":")[0] for i in listed] == ["you", "you", "plan"] and "plan:EFGH:trim" in listed
    assert [s["id"] for s in open_steps(home, days=60, now=now) if s["symbol"] == "EFGH"] == ["trim"]
    mirror("s1", date="2026-12-09", accountKey="individual-1", kind="sell", symbol="ABCD", quantity=-40, amount=800)
    later = datetime(2027, 1, 2, 15, 0, tzinfo=now.tzinfo)
    assert [r["symbol"] for r in next_steps(home, now=later)["items"] if r["source"] == "you"] == []
    done, gone = get(home, ids["ABCD"])["events"][-1], get(home, ids["WXYZ"])["events"][-1]
    assert (done["event"], done["reason"]) == ("step_done", "Sold 40 ABCD by Dec 9.")
    assert (gone["event"], gone["reason"]) == ("step_retired", "Its window ended on Dec 31 with no sale.")
