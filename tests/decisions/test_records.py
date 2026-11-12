from datetime import timedelta

import pytest

from desk.decisions import (
    DecisionError,
    approve,
    attach_skeptic,
    confirm_fills,
    create_proposal,
    desk_history,
    dismiss,
    draft,
    get,
    journal,
    log_trade,
    mark_placed,
    pass_on,
    queue,
    reject_proposal,
    scoring_rows,
    snooze,
    summary,
    unmatched,
)
from desk.decisions.records import expiry, trading_days_after


def test_proposal_is_stored_with_profile_and_preflight(cfg, preflight, now, proposal):
    d = create_proposal(cfg, proposal(), "research", run_id=7, now=now)
    assert d["status"] == "proposed" and d["origin"] == "research" and d["run_id"] == "7"
    assert d["symbol"] == "ABCD" and d["title"] == "Buy $500 ABCD"
    assert d["profile_version"] == 1 and d["rules_version"] == 1
    assert d["preflight_status"] == "clear"
    assert d["expires_at"] == "2026-11-16T21:00:00+00:00"
    trade, ticket_id = preflight["calls"][0]
    assert ticket_id == d["id"]
    assert trade == {
        "kind": "buy",
        "symbol": "ABCD",
        "account": "Brokerage",
        "side": "buy",
        "amount_usd": 500.0,
        "shares": None,
        "funding": "cash",
        "lot_method": None,
        "order_type": "market",
        "limit": None,
    }
    assert [e["event"] for e in get(cfg, d["id"])["events"]] == ["proposed", "preflight"]


def test_preflight_status_is_derived_from_lights(cfg, preflight, now, proposal):
    preflight["result"]["value"] = {"lights": [{"check": "Funding", "status": "act"}], "tax": {"realized_st": 0}}
    d = create_proposal(cfg, proposal(funding="margin"), "research", now=now)
    assert d["preflight_status"] == "blocked"
    assert d["tax_impact"] == {"realized_st": 0}
    preflight["result"]["value"] = {"lights": [{"check": "Wash sales", "status": "watch"}]}
    assert create_proposal(cfg, proposal(), "research", now=now)["preflight_status"] == "flagged"


def test_preflight_pending_without_engine_and_error_is_kept(cfg, preflight, now, monkeypatch, proposal):
    from desk.decisions import records

    monkeypatch.setattr(records, "_checker", lambda: None)
    assert create_proposal(cfg, proposal(), "research", now=now)["preflight_status"] == "pending"
    monkeypatch.undo()
    preflight["result"]["value"] = RuntimeError("no prices")
    monkeypatch.setattr(records, "_checker", lambda: lambda c, t, ticket_id: (_ for _ in ()).throw(RuntimeError("no prices")))
    d = create_proposal(cfg, proposal(), "research", now=now)
    assert d["preflight_status"] == "error" and "no prices" in d["preflight"]["error"]


def test_memo_skips_preflight(cfg, preflight, now, proposal):
    d = create_proposal(cfg, {"kind": "hold_off", "title": "Hold off while the debit is open", "thesis": "All quiet."}, "risk", now=now)
    assert d["preflight_status"] == "pending" or preflight["calls"]
    assert approve(cfg, d["id"], now=now)["status"] == "done"
    note = create_proposal(cfg, {"kind": "memo", "title": "Weekly risk note", "thesis": "All quiet."}, "risk", now=now)
    assert note["preflight_status"] == "none" and note["status"] == "logged"


@pytest.mark.parametrize(
    "over, reason",
    [({"bear_case": None}, "bear case"), ({"sources": [{"url": "https://example.com"}]}, "two sources"), ({"kind": "trim", "thesis": ""}, "thesis")],
)
def test_contract_rejections_are_stored(cfg, preflight, now, over, reason, proposal):
    d = create_proposal(cfg, proposal(**over), "scout", now=now)
    assert d["status"] == "rejected" and reason in d["status_reason"]
    assert d["decided_at"] and d["expires_at"] is None
    assert preflight["calls"] == []
    assert queue(cfg, now=now)["count"] == 0


@pytest.mark.parametrize(
    "over, message",
    [
        ({"kind": "yolo"}, "kind must be one of"),
        ({"funding": "credit"}, "funding must be one of"),
        ({"symbol": None}, "needs a symbol"),
        ({"amount_usd": None}, "needs amount_usd or shares"),
        ({"amount_usd": -5}, "positive"),
        ({"confidence": 1.5}, "probability"),
        ({"sources": "x"}, "must be a list"),
        ({"expires": "soon"}, "expires must be"),
    ],
)
def test_malformed_proposals_raise_for_drafts_and_reject_for_desks(cfg, now, over, message, proposal):
    with pytest.raises(DecisionError, match=message):
        draft(cfg, proposal(**over), now=now)
    d = create_proposal(cfg, proposal(**over), "research", now=now)
    assert d["status"] == "rejected" and message in d["status_reason"] and d["status_reason"].startswith("Malformed proposal")


def test_unknown_desk_raises(cfg, now, proposal):
    with pytest.raises(DecisionError, match="desk must be one of"):
        create_proposal(cfg, proposal(), "oracle", now=now)


def test_runner_rejections_are_logged_even_when_malformed(cfg, now, proposal):
    d = reject_proposal(cfg, proposal(), "research", "numbers_used plan.drift:ABCD:now does not match the brief", run_id=3, now=now)
    assert d["status"] == "rejected" and d["symbol"] == "ABCD" and "does not match" in d["status_reason"]
    bad = reject_proposal(cfg, {"kind": "buy"}, "research", "", now=now)
    assert bad["status"] == "rejected" and bad["title"].startswith("Malformed proposal") and bad["status_reason"] == "Rejected by the runner"


def test_override_needs_a_reason(cfg, preflight, now, proposal):
    preflight["result"]["value"] = {"status": "blocked", "lights": []}
    d = create_proposal(cfg, proposal(funding="margin"), "research", now=now)
    with pytest.raises(DecisionError, match="one-line reason"):
        approve(cfg, d["id"], now=now)
    done = approve(cfg, d["id"], "Paying it off on payday", now=now)
    assert done["status"] == "approved" and done["override"] is True and done["override_reason"] == "Paying it off on payday"
    assert done["decision"] == "override"
    assert get(cfg, d["id"])["events"][-1]["event"] == "override"


def test_clean_approval_and_unchecked_approval(cfg, preflight, now, monkeypatch, proposal):
    d = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    a = approve(cfg, d["id"], now=now)
    assert a["status"] == "approved" and a["override"] is False and a["decision"] == "approved"
    with pytest.raises(DecisionError, match="already approved"):
        approve(cfg, d["id"], now=now)
    from desk.decisions import records

    monkeypatch.setattr(records, "_checker", lambda: None)
    u = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    approve(cfg, u["id"], now=now)
    assert get(cfg, u["id"])["events"][-1]["event"] == "approved_unchecked"


def test_expired_proposal_cannot_be_approved(cfg, preflight, now, proposal):
    d = create_proposal(cfg, proposal(expires="2026-11-10"), "tax", now=now)
    later = now + timedelta(days=2)
    with pytest.raises(DecisionError, match="expired"):
        approve(cfg, d["id"], now=later)
    assert get(cfg, d["id"])["status"] == "expired"


def test_queue_snooze_and_dismiss(cfg, preflight, now, proposal):
    a = create_proposal(cfg, proposal(expires="2026-11-12"), "tax", now=now)
    b = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    c = draft(cfg, {"kind": "deposit_route", "symbol": "WXYZ", "amount_usd": 200, "funding": "deposit"}, now=now)
    q = queue(cfg, now=now)
    assert [d["id"] for d in q["items"]] == [a["id"], b["id"], c["id"]]
    snooze(cfg, b["id"], 1, "After payday", now=now)
    assert [d["id"] for d in queue(cfg, now=now)["items"]] == [a["id"], c["id"]]
    assert queue(cfg, now=now)["snoozed"] == 1
    assert b["id"] in [d["id"] for d in queue(cfg, now=now + timedelta(days=1, minutes=1))["items"]]
    dismissed = dismiss(cfg, c["id"], "Not this month", now=now)
    assert dismissed["status"] == "dismissed" and dismissed["status_reason"] == "Not this month"
    with pytest.raises(DecisionError, match="between"):
        snooze(cfg, a["id"], 0, now=now)


def test_pass_needs_reason_and_works_after_approval(cfg, preflight, now, proposal):
    d = create_proposal(cfg, proposal(), "research", now=now)
    with pytest.raises(DecisionError, match="reason"):
        pass_on(cfg, d["id"], " ", now=now)
    approve(cfg, d["id"], now=now)
    passed = pass_on(cfg, d["id"], "Changed my mind before placing it", now=now)
    assert passed["status"] == "passed" and passed["decision"] == "passed"


def test_draft_needs_thesis_for_buy(cfg, preflight, now):
    with pytest.raises(DecisionError, match="thesis") as e:
        draft(cfg, {"kind": "buy", "symbol": "ABCD", "amount_usd": 100}, now=now)
    assert e.value.status == 422
    d = draft(cfg, {"kind": "buy", "symbol": "ABCD", "amount_usd": 100, "thesis": "Test"}, now=now)
    assert d["origin"] == "you" and d["status"] == "proposed" and d["preflight_status"] == "clear"


def test_skeptic_and_history(cfg, preflight, now, proposal):
    d = create_proposal(cfg, proposal(), "research", now=now)
    attach_skeptic(cfg, d["id"], "flag", "Priced in.", now=now)
    assert get(cfg, d["id"])["skeptic"]["verdict"] == "flag"
    with pytest.raises(DecisionError):
        attach_skeptic(cfg, d["id"], "maybe", "", now=now)
    dismiss(cfg, d["id"], "Skeptic is right", now=now)
    create_proposal(cfg, proposal(bear_case=None), "research", now=now)
    history = desk_history(cfg, "research")
    assert [h["decision"] for h in history] == ["rejected", "dismissed"]
    assert history[1]["reason"] == "Skeptic is right"
    assert desk_history(cfg, "tax") == []


def test_placed_then_confirmed_by_mirror(cfg, preflight, now, mirror, proposal):
    d = create_proposal(cfg, proposal(amount_usd=500), "plan_keeper", now=now)
    with pytest.raises(DecisionError, match="Only an approved"):
        mark_placed(cfg, d["id"], now=now)
    approve(cfg, d["id"], now=now)
    placed = mark_placed(cfg, d["id"], shares=10, now=now)
    assert placed["status"] == "placed" and placed["fill"] == {"placed": {"shares": 10.0}}
    mirror("a-old", date="2026-10-01", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=10, price=50, amount=-500)
    mirror("a-other", date="2026-11-10", accountKey="brokerage-9", kind="buy", symbol="ZZZZ", quantity=10, price=50, amount=-500)
    mirror("a-hit", date="2026-11-10", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=9.9, price=50.4, amount=-498.96)
    assert confirm_fills(cfg, now=now) == [d["id"]]
    f = get(cfg, d["id"])
    assert f["status"] == "filled" and f["filled_at"] == "2026-11-10" and f["activity_id"] == "a-hit"
    assert f["fill"]["price"] == 50.4 and f["fill"]["placed"] == {"shares": 10.0}
    assert confirm_fills(cfg, now=now) == []


def test_fill_matching_respects_side_size_and_account(cfg, preflight, now, mirror, proposal):
    d = create_proposal(cfg, proposal(kind="harvest", shares=20, amount_usd=None, account="HSA"), "tax", now=now)
    approve(cfg, d["id"], now=now)
    mark_placed(cfg, d["id"], now=now)
    mirror("wrong-side", date="2026-11-10", accountKey="hsa-1", kind="buy", symbol="ABCD", quantity=20, amount=-300)
    mirror("wrong-size", date="2026-11-10", accountKey="hsa-1", kind="sell", symbol="ABCD", quantity=12, amount=180)
    mirror("wrong-account", date="2026-11-10", accountKey="brokerage-9", kind="sell", symbol="ABCD", quantity=20, amount=300)
    assert confirm_fills(cfg, now=now) == []
    mirror("right", date="2026-11-11", accountKey="hsa-1", kind="sell", symbol="ABCD", quantity=-20, amount=300)
    assert confirm_fills(cfg, now=now) == [d["id"]]


def test_unmatched_trades_coverage_and_streak(cfg, preflight, now, mirror):
    mirror("t1", date="2026-11-02", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=5, amount=-250)
    mirror("t2", date="2026-11-03", accountKey="brokerage-9", kind="sell", symbol="QRST", quantity=2, amount=90)
    mirror("core", date="2026-11-03", accountKey="brokerage-9", kind="buy", symbol="CASHX", amount=-90, core=True)
    mirror("div", date="2026-11-03", accountKey="brokerage-9", kind="dividend", symbol="ABCD", amount=3)
    mirror("old", date="2026-01-03", accountKey="brokerage-9", kind="buy", symbol="ABCD", amount=-3)
    assert [t["activity_id"] for t in unmatched(cfg, now=now)] == ["t2", "t1"]
    s = summary(cfg, now=now)
    assert s["unmatched"] == 2 and s["coverage"] == 0 and s["streak_days"] == 6
    logged = log_trade(cfg, "t1", thesis="Bought on a hunch", reason="Forgot to log it", now=now)
    assert logged["status"] == "filled" and logged["origin"] == "you" and logged["kind"] == "buy" and logged["amount_usd"] == 250
    with pytest.raises(DecisionError, match="already has"):
        log_trade(cfg, "t1", now=now)
    with pytest.raises(DecisionError, match="isn't in the mirror"):
        log_trade(cfg, "nope", now=now)
    s = summary(cfg, now=now)
    assert s["unmatched"] == 1 and s["logged_after"] == 1 and s["coverage"] == 0 and s["streak_days"] == 6


def test_summary_counts_overrides_and_clean(cfg, preflight, now, proposal):
    clean = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    approve(cfg, clean["id"], now=now)
    preflight["result"]["value"] = {"status": "flagged", "lights": []}
    flagged = create_proposal(cfg, proposal(), "research", now=now)
    approve(cfg, flagged["id"], "Small size", now=now)
    create_proposal(cfg, proposal(), "risk", now=now)
    s = summary(cfg, now=now)
    assert (s["clean"], s["overrides"], s["waiting"], s["unmatched"], s["coverage"]) == (1, 1, 1, 0, None)


def test_journal_groups_by_day_and_reads_scores(cfg, preflight, now, desk_db, proposal):
    a = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    approve(cfg, a["id"], now=now)
    b = create_proposal(cfg, proposal(symbol="WXYZ"), "tax", now=now)
    dismiss(cfg, b["id"], now=now + timedelta(days=1))
    create_proposal(cfg, proposal(), "risk", now=now)
    desk_db.execute("CREATE TABLE IF NOT EXISTS metric_values (metric_id, scope, scope_id, window, as_of, value, unit, n_obs, quality, engine_version)")
    desk_db.execute("INSERT INTO metric_values VALUES ('dec.score_30', 'decision', ?, '30d', '2026-12-10', 12.5, 'usd', 1, 'ok', '1')", (a["id"],))
    desk_db.commit()
    later = now + timedelta(days=1, hours=1)
    j = journal(cfg, now=later)
    assert [d["day"] for d in j["days"] if any(i["kind"] != "rule_change" for i in d["items"])] == ["2026-11-10", "2026-11-09"]
    items = [i for day in j["days"] for i in day["items"] if i["kind"] != "rule_change"]
    assert [i["id"] for i in items] == [b["id"], a["id"]]
    assert items[1]["scores"] == {"30d": 12.5}
    assert [i["id"] for day in journal(cfg, origin="tax", now=later)["days"] for i in day["items"]] == [b["id"]]
    assert journal(cfg, symbol="wxyz", now=later)["count"] == 1
    tomorrow = [i for day in journal(cfg, since="2026-11-10T00:00:00+00:00", now=later)["days"] for i in day["items"] if i["kind"] != "rule_change"]
    assert [i["id"] for i in tomorrow] == [b["id"]]


def test_scoring_rows_skip_open_and_rule_changes(cfg, preflight, now, proposal):
    a = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    approve(cfg, a["id"], now=now)
    create_proposal(cfg, proposal(), "risk", now=now)
    rows = scoring_rows(cfg)
    assert [r["id"] for r in rows] == [a["id"]]
    assert rows[0]["override"] is False and rows[0]["amount_usd"] == 500


def test_expiry_counts_trading_days(cfg, now):
    assert trading_days_after(now.date(), 5).isoformat() == "2026-11-16"
    assert expiry("2026-11-20", now, cfg.timezone) == "2026-11-20T21:00:00+00:00"
    assert expiry("2026-11-20T10:00:00", now, cfg.timezone) == "2026-11-20T15:00:00+00:00"
    assert expiry("2026-11-20T10:00:00Z", now, cfg.timezone) == "2026-11-20T10:00:00+00:00"


def test_demo_mirror_trades_show_as_unmatched(demo_cfg, monkeypatch):
    monkeypatch.setenv("DESK_PROFILE", str(demo_cfg.data_dir / "desk.yaml"))
    trades = unmatched(demo_cfg, days=3650)
    assert trades and all(t["kind"] in ("buy", "sell") and t["symbol"] for t in trades)
    logged = log_trade(demo_cfg, trades[0]["activity_id"], reason="Demo")
    assert logged["status"] == "filled" and logged["activity_id"] == trades[0]["activity_id"]
    assert len(unmatched(demo_cfg, days=3650)) == len(trades) - 1


def test_coverage_counts_only_trades_decided_first(cfg, preflight, now, mirror, proposal):
    d = create_proposal(cfg, proposal(), "plan_keeper", now=now)
    approve(cfg, d["id"], now=now)
    mark_placed(cfg, d["id"], now=now)
    mirror("fill", date="2026-11-10", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=10, amount=-500)
    mirror("loose", date="2026-11-10", accountKey="brokerage-9", kind="sell", symbol="QRST", quantity=1, amount=40)
    confirm_fills(cfg, now=now)
    s = summary(cfg, now=now + timedelta(days=1))
    assert (s["coverage"], s["unmatched"], s["logged_after"]) == (0.5, 1, 0)
    assert s["streak_days"] == 0
