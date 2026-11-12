import sqlite3
from datetime import timedelta

import pytest

from desk.decisions import cleared, create_proposal, desk_history, draft, get, journal, notes, queue, snooze, summary
from desk.decisions.__main__ import main, night, sync
from desk.decisions.plans import save_plan
from desk.decisions.records import subject_of
from desk.decisions.schema import SCHEMA
from desk.decisions.store import session

DAY = "2026-11-09"


def price(conn, symbol, day, close):
    conn.execute("INSERT OR REPLACE INTO prices_daily (symbol, date, close, adj_close, source) VALUES (?, ?, ?, ?, 'test')", (symbol, day, close, close))
    conn.commit()


def quote(conn, symbol, at, value):
    conn.execute(
        "INSERT OR REPLACE INTO quotes_live (symbol, at, price, prev_close, source, fetched_at) VALUES (?, ?, ?, NULL, 'finnhub', ?)", (symbol, at, value, at)
    )
    conn.commit()


def cash(conn, day, value, quality="ok"):
    conn.execute(
        "INSERT OR REPLACE INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, n_obs, quality, engine_version) "
        "VALUES ('cash.ready', 'portfolio', 'all', 'now', ?, ?, 'usd', 1, ?, '1')",
        (day, value, quality),
    )
    conn.commit()


def reason(cfg, d):
    return get(cfg, d["id"])["status_reason"]


# ---- Subject and as of ----


def test_subject_and_as_of_are_stored_or_derived(cfg, preflight, now, proposal):
    given = create_proposal(cfg, proposal(subject="  Next  Deposit ", as_of="2026-11-06"), "plan_keeper", run_id="r1", now=now)
    assert given["subject"] == "next deposit" and given["as_of"] == "2026-11-06"
    derived = create_proposal(cfg, proposal(kind="trim", symbol="wxyz"), "risk", run_id="r1", now=now)
    assert derived["subject"] == "sell:WXYZ" and derived["as_of"] == derived["created_at"]
    assert subject_of({"kind": "deposit_route", "symbol": "abcd"}) == "next-deposit"
    assert subject_of({"kind": "buy", "symbol": "abcd"}) == "buy:ABCD"
    assert subject_of({"kind": "hold_off", "symbol": None, "rule_served": "Margin stays at 0"}) == "hold_off:general"
    assert subject_of({"kind": "alert", "symbol": None, "rule_served": "Margin stays at 0"}) == "note:margin-stays-at"
    assert subject_of({"kind": "alert", "symbol": None, "title": "Tech is 3 points over"}) == "note:tech-is-points-over"
    assert subject_of({"kind": "memo", "symbol": None}) == "note:general"


@pytest.mark.parametrize("over", [{"as_of": "last week"}, {"price_min": 30, "price_max": 20}, {"needs_cash_usd": -5}])
def test_bad_rule_fields_are_rejected_not_queued(cfg, now, over, proposal):
    d = create_proposal(cfg, proposal(**over), "scout", run_id="r1", now=now)
    assert d["status"] == "rejected" and d["status_reason"].startswith("Malformed proposal")


# ---- Replace ----


def test_a_newer_proposal_replaces_the_older_one_on_its_subject(cfg, preflight, now, proposal):
    old = create_proposal(cfg, proposal(), "plan_keeper", run_id="r1", now=now)
    twin = create_proposal(cfg, proposal(symbol="WXYZ"), "plan_keeper", run_id="r1", now=now)
    other_desk = create_proposal(cfg, proposal(), "scout", run_id="s1", now=now)
    mine = draft(cfg, {"kind": "buy", "symbol": "ABCD", "amount_usd": 10, "thesis": "Mine"}, now=now)
    later = now + timedelta(days=1)
    new = create_proposal(cfg, proposal(amount_usd=400), "plan_keeper", run_id="r2", now=later)
    gone = get(cfg, old["id"])
    assert gone["status"] == "expired" and gone["replaced_by"] == new["id"]
    assert gone["status_reason"] == "A newer proposal on the same subject replaced this one on Nov 10."
    assert gone["events"][-1]["event"] == "replaced" and gone["events"][-1]["detail"] == {"by": new["id"]}
    assert {d["id"] for d in queue(cfg, now=later)["items"]} == {new["id"], twin["id"], other_desk["id"], mine["id"]}
    assert old["id"] in [i["id"] for day in journal(cfg, now=later)["days"] for i in day["items"]]


def test_one_run_never_replaces_its_own_proposals(cfg, preflight, now, proposal):
    a = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="margin"), "plan_keeper", run_id="r1", now=now)
    b = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="margin"), "plan_keeper", run_id="r1", now=now)
    assert {d["id"] for d in queue(cfg, now=now)["items"]} == {a["id"], b["id"]}


def test_a_named_subject_also_replaces_the_unnamed_one_it_stands_for(cfg, preflight, now, proposal):
    unnamed = create_proposal(cfg, proposal(kind="hold_off", symbol=None), "plan_keeper", run_id="r1", now=now)
    other = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="earnings-week"), "plan_keeper", run_id="r1", now=now)
    named = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="margin"), "plan_keeper", run_id="r2", now=now + timedelta(days=1))
    assert unnamed["subject"] == "hold_off:general" and get(cfg, unnamed["id"])["replaced_by"] == named["id"]
    assert {d["id"] for d in queue(cfg, now=now + timedelta(days=1))["items"]} == {other["id"], named["id"]}


def test_a_snooze_carries_over_to_the_replacement(cfg, preflight, now, proposal):
    old = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="margin"), "plan_keeper", run_id="r1", now=now)
    until = snooze(cfg, old["id"], days=7, now=now)["snoozed_until"]
    new = create_proposal(cfg, proposal(kind="hold_off", symbol=None, subject="margin"), "plan_keeper", run_id="r2", now=now + timedelta(days=1))
    assert new["status"] == "snoozed" and new["snoozed_until"] == until
    q = queue(cfg, now=now + timedelta(days=1))
    assert q["count"] == 0 and q["snoozed"] == 1


# ---- Notes ----


def test_heads_up_notes_skip_the_queue_and_show_latest_per_subject(cfg, preflight, now, proposal, app_client):
    note = {"kind": "alert", "title": "Tech is 3 points over its band", "thesis": "Steer the next deposit.", "subject": "rule:tech"}
    first = create_proposal(cfg, note, "plan_keeper", run_id="r1", now=now)
    second = create_proposal(cfg, {**note, "title": "Tech is 2 points over its band"}, "plan_keeper", run_id="r2", now=now + timedelta(days=1))
    memo = create_proposal(cfg, {"kind": "memo", "title": "Weekly note", "thesis": "Quiet."}, "risk", run_id="k1", now=now)
    mine = draft(cfg, {"kind": "memo", "title": "Note to self"}, now=now)
    later = now + timedelta(days=1, hours=1)
    assert first["status"] == second["status"] == memo["status"] == "logged"
    assert [d["id"] for d in queue(cfg, now=later)["items"]] == [mine["id"]]
    assert [d["id"] for d in notes(cfg, now=later)["items"]] == [second["id"], memo["id"]]
    assert notes(cfg, days=1, now=now + timedelta(days=3))["count"] == 0
    logged = [i["id"] for day in journal(cfg, status="logged", now=later)["days"] for i in day["items"] if i["kind"] != "rule_change"]
    assert set(logged) == {first["id"], second["id"], memo["id"]}
    body = app_client(packages=["decisions"]).get("/api/decisions/notes?days=30").json()
    assert set(body) == {"count", "days", "items"} and body["days"] == 30


# ---- Facts that changed ----


def test_price_outside_its_zone_expires_with_the_reason(cfg, preflight, now, desk_db, proposal):
    quote(desk_db, "ABCD", "2026-11-09T14:55:00+00:00", 20.0)
    inside = create_proposal(cfg, proposal(price_min=18, price_max=22, expires="2099-01-01"), "scout", run_id="s1", now=now)
    floor = create_proposal(cfg, proposal(symbol="WXYZ", price_min=50, expires="2099-01-01"), "scout", run_id="s1", now=now)
    unknown = create_proposal(cfg, proposal(symbol="NOPE", price_max=5, expires="2099-01-01"), "scout", run_id="s1", now=now)
    assert queue(cfg, now=now)["count"] == 3
    quote(desk_db, "ABCD", "2026-11-10T15:00:00+00:00", 23.5)
    price(desk_db, "WXYZ", "2026-11-10", 48.0)
    later = now + timedelta(days=1)
    assert [d["id"] for d in queue(cfg, now=later)["items"]] == [unknown["id"]]
    assert reason(cfg, inside) == "ABCD is at $23.50, above the $18.00 to $22.00 zone this was written for."
    assert reason(cfg, floor) == "WXYZ is at $48.00, below the $50.00 floor this was written for."
    last = get(cfg, inside["id"])["events"][-1]
    assert last["event"] == "expired" and last["detail"] == {"check": "price"}


def test_without_a_zone_a_desk_trade_expires_after_a_big_move(cfg, preflight, now, desk_db, proposal):
    quote(desk_db, "ABCD", "2026-11-09T14:55:00+00:00", 20.0)
    quote(desk_db, "WXYZ", "2026-11-09T14:55:00+00:00", 100.0)
    moved = create_proposal(cfg, proposal(expires="2099-01-01"), "research", run_id="a1", now=now)
    steady = create_proposal(cfg, proposal(symbol="WXYZ", expires="2099-01-01"), "research", run_id="a1", now=now)
    mine = draft(cfg, {"kind": "buy", "symbol": "ABCD", "amount_usd": 10, "thesis": "Mine", "expires": "2099-01-01"}, now=now)
    assert moved["valid"] == {"price_at": 20.0}
    quote(desk_db, "ABCD", "2026-11-11T15:00:00+00:00", 17.5)
    quote(desk_db, "WXYZ", "2026-11-11T15:00:00+00:00", 105.0)
    later = now + timedelta(days=2)
    assert [h["decision"] for h in desk_history(cfg, "research", now=later)] == ["open", "expired"]
    assert {d["id"] for d in queue(cfg, now=later)["items"]} == {steady["id"], mine["id"]}
    assert reason(cfg, moved) == "ABCD is down 12% since this was written on Nov 9 ($20.00 then, $17.50 now), so its numbers no longer hold."


def test_ready_cash_gone_expires_a_cash_funded_buy(cfg, preflight, now, desk_db, proposal):
    cash(desk_db, "2026-11-06", 900.0)
    buy = create_proposal(cfg, proposal(expires="2099-01-01"), "plan_keeper", run_id="r1", now=now)
    route = create_proposal(cfg, proposal(kind="deposit_route", symbol="WXYZ", funding="deposit", expires="2099-01-01"), "plan_keeper", run_id="r1", now=now)
    explicit = create_proposal(cfg, proposal(symbol="EFGH", funding=None, needs_cash_usd=800, expires="2099-01-01"), "scout", run_id="s1", now=now)
    fresh = create_proposal(cfg, proposal(symbol="IJKL", as_of="2026-11-10", expires="2099-01-01"), "research", run_id="a1", now=now)
    assert queue(cfg, now=now)["count"] == 4
    for unsure in ("mismatch", "stale", "insufficient_history"):
        cash(desk_db, "2026-11-10", 120.4, unsure)
        assert queue(cfg, now=now + timedelta(days=1))["count"] == 4
    desk_db.execute(
        "INSERT INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, n_obs, quality, engine_version) "
        "VALUES ('cash.ready', 'account', 'Brokerage', 'now', '2026-11-11', 0, 'usd', 1, 'ok', '1')"
    )
    cash(desk_db, "2026-11-10", 0.0, "pro_forma")
    later = now + timedelta(days=1)
    assert {d["id"] for d in queue(cfg, now=later)["items"]} == {route["id"], fresh["id"]}
    assert reason(cfg, buy) == "Ready cash is $0 as of Nov 10 (estimated), less than the $500 this needs."
    assert reason(cfg, explicit) == "Ready cash is $0 as of Nov 10 (estimated), less than the $800 this needs."


def test_a_closed_window_says_when_it_closed(cfg, preflight, now, proposal):
    d = create_proposal(cfg, proposal(expires="2026-11-10"), "tax", run_id="t1", now=now)
    assert summary(cfg, now=now + timedelta(days=3))["waiting"] == 0
    assert reason(cfg, d) == "Its window closed on Nov 10."


# ---- One pass over what is already there ----


def test_the_first_read_cleans_a_queue_written_before_the_rule(cfg, preflight, now, desk_db, proposal, monkeypatch, capsys):
    with session(cfg) as conn:
        conn.execute("UPDATE decisions SET status='dismissed' WHERE status IN ('proposed', 'snoozed')")
        conn.commit()
    quote(desk_db, "EFGH", "2026-11-05T15:00:00+00:00", 40.0)
    made = {}
    for i, day in enumerate((4, 3, 2)):
        at = now - timedelta(days=day)
        run = f"r{i}"
        made[f"hold{i}"] = create_proposal(
            cfg, proposal(kind="hold_off", symbol=None, rule_served="margin", expires="2099-01-01"), "plan_keeper", run_id=run, now=at
        )
        made[f"route{i}"] = create_proposal(cfg, proposal(kind="deposit_route", funding="deposit", expires="2099-01-01"), "plan_keeper", run_id=run, now=at)
        made[f"alert{i}"] = create_proposal(cfg, {"kind": "alert", "title": f"Tech is {i} points over", "thesis": "Steer."}, "plan_keeper", run_id=run, now=at)
    made["stale"] = create_proposal(cfg, proposal(symbol="EFGH", funding="deposit", expires="2099-01-01"), "scout", run_id="s1", now=now - timedelta(days=4))
    made["good"] = create_proposal(cfg, proposal(symbol="WXYZ", funding="deposit", expires="2099-01-01"), "scout", run_id="s1", now=now - timedelta(days=4))
    with session(cfg) as conn:
        conn.execute("UPDATE decisions SET status='proposed', status_reason=NULL, decided_at=NULL, replaced_by=NULL, subject=NULL, valid=NULL")
        conn.execute("UPDATE decisions SET status='logged' WHERE kind='rule_change'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE status='proposed'").fetchone()[0] == 11
    price(desk_db, "EFGH", "2026-11-05", 40.0)
    quote(desk_db, "EFGH", "2026-11-09T14:00:00+00:00", 46.0)
    monkeypatch.setattr("desk.decisions.__main__.Config.from_env", lambda: cfg)
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now)
    assert main(["tidy"]) == 0
    assert capsys.readouterr().out.strip() == '{"ready": "3 decisions waiting; 8 out-of-date items moved to the journal with the reason"}'
    assert {d["id"] for d in queue(cfg, now=now)["items"]} == {made["hold2"]["id"], made["route2"]["id"], made["good"]["id"]}
    assert night(cfg) == {"ready": "3 decisions waiting, all current"}
    seen = {k: get(cfg, d["id"]) for k, d in made.items()}
    assert all(d["status_reason"] for k, d in seen.items() if k not in ("hold2", "route2", "good"))
    assert seen["hold0"]["replaced_by"] == made["hold2"]["id"] and seen["route1"]["status"] == "expired"
    assert seen["alert2"]["status"] == "logged" and "kept in the journal" in seen["alert2"]["status_reason"]
    assert seen["stale"]["status_reason"].startswith("EFGH is up 15% since this was written on Nov 5")
    assert [d["id"] for d in notes(cfg, days=30, now=now)["items"]] == [made["alert2"]["id"]]


def test_an_empty_queue_says_so(cfg, monkeypatch, now):
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now)
    assert night(cfg) == {"skipped": "Nothing is waiting on a decision."}


def test_an_older_database_gains_the_new_columns(cfg):
    old = SCHEMA
    for column in ("subject", "as_of", "valid", "replaced_by"):
        old = old.replace(f"  {column} TEXT,\n", "")
    conn = sqlite3.connect(cfg.desk_db)
    conn.executescript(old)
    conn.execute(
        "INSERT INTO decisions (id, created_at, updated_at, origin, kind, status) VALUES ('d_old', '2026-11-01T00:00:00+00:00', 'x', 'you', 'memo', 'done')"
    )
    conn.commit()
    conn.close()
    with session(cfg) as conn:
        assert {"subject", "as_of", "valid", "replaced_by"} <= {r[1] for r in conn.execute("PRAGMA table_info(decisions)")}
    assert get(cfg, "d_old")["as_of"] == "2026-11-01T00:00:00+00:00"


# ---- Items that pull against his plan ----

PLAN = {
    "role": "conviction",
    "thesis": "Made-up thesis for a test.",
    "steps": [
        {"id": "harvest", "kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "shares": 40, "lots": "highest_cost", "account": "Brokerage"},
        {"id": "repay", "kind": "repay", "due": "2026-11-18"},
    ],
}


def test_the_night_job_clears_items_that_pull_against_his_plan(cfg, preflight, now, proposal, monkeypatch, app_client):
    save_plan(cfg, "ABCD", PLAN, approve=True, now=now)
    margin = {"kind": "hold_off", "symbol": None, "subject": "margin", "thesis": "Made-up.", "expires": "2099-01-01"}
    keeper = create_proposal(cfg, proposal(**margin, title="Hold off on new buys until the margin debit is paid"), "plan_keeper", run_id="r1", now=now)
    trim = create_proposal(
        cfg, proposal(kind="trim", title="Trim ABCD to clear the margin debit", shares=10, amount_usd=None, expires="2099-01-01"), "risk", run_id="k1", now=now
    )
    second = create_proposal(cfg, proposal(**margin, title="No new buys while margin is open"), "risk", run_id="k1", now=now)
    other = create_proposal(cfg, proposal(kind="hold_off", symbol="EFGH", title="Hold off on EFGH", expires="2099-01-01"), "risk", run_id="k1", now=now)
    mine = draft(cfg, {"kind": "trim", "symbol": "ABCD", "shares": 5, "thesis": "Mine: trim to pay the margin down", "expires": "2099-01-01"}, now=now)
    assert queue(cfg, now=now)["count"] == 5
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now)
    assert night(cfg) == {"ready": "3 decisions waiting; 2 out-of-date items moved to the journal with the reason"}
    assert {d["id"] for d in queue(cfg, now=now)["items"]} == {keeper["id"], other["id"], mine["id"]}
    assert reason(cfg, trim) == "Your plan already times this sale for Dec 7 to 15."
    assert reason(cfg, second) == "Already covered by a standing note: Hold off on new buys until the margin debit is paid."
    last = get(cfg, trim["id"])["events"][-1]
    assert last["event"] == "cleared" and last["detail"] == {"check": "plan"}
    seen = cleared(cfg, now=now)
    assert {d["id"]: d["check"] for d in seen["items"]} == {trim["id"]: "plan", second["id"]: "plan"}
    assert all(d["cleared_at"] and d["status_reason"] for d in seen["items"])
    assert night(cfg) == {"ready": "3 decisions waiting, all current"}
    body = app_client(packages=["decisions"]).get("/api/decisions/cleared?days=30").json()
    assert set(body) == {"count", "days", "items"} and body["days"] == 30


def test_a_plain_read_does_not_run_the_plan_check_and_a_broken_check_clears_nothing(cfg, preflight, now, proposal, monkeypatch):
    save_plan(cfg, "ABCD", PLAN, approve=True, now=now)
    trim = create_proposal(cfg, proposal(kind="trim", shares=10, amount_usd=None, expires="2099-01-01"), "risk", run_id="k1", now=now)
    stale = create_proposal(cfg, proposal(symbol="WXYZ", expires="2026-11-10"), "tax", run_id="t1", now=now)
    assert [d["id"] for d in queue(cfg, now=now + timedelta(days=2))["items"]] == [trim["id"]]
    assert {d["id"]: d["check"] for d in cleared(cfg, now=now + timedelta(days=2))["items"]} == {stale["id"]: "window"}

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("desk.decisions.records._desk_check", lambda: broken)
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now + timedelta(days=2))
    assert night(cfg) == {"ready": "1 decision waiting, all current"}
    monkeypatch.setattr("desk.decisions.records._desk_check", lambda: None)
    assert night(cfg) == {"ready": "1 decision waiting, all current"}


def test_the_sync_job_runs_the_plan_check_too(cfg, preflight, now, proposal, monkeypatch):
    save_plan(cfg, "ABCD", PLAN, approve=True, now=now)
    trim = create_proposal(cfg, proposal(kind="trim", shares=10, amount_usd=None, expires="2099-01-01"), "risk", run_id="k1", now=now)
    keep = create_proposal(cfg, proposal(symbol="WXYZ", funding="deposit", expires="2099-01-01"), "scout", run_id="s1", now=now)
    monkeypatch.setattr("desk.decisions.records._now", lambda _=None: now)
    result = sync(cfg)
    assert result["cleared"] == 1 and result["expired"] == 0
    assert reason(cfg, trim) == "Your plan already times this sale for Dec 7 to 15."
    assert [d["id"] for d in queue(cfg, now=now)["items"]] == [keep["id"]]
    assert sync(cfg)["cleared"] == 0
