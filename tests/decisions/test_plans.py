import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from desk.db import apply_schemas
from desk.decisions import alerts as alerting
from desk.decisions import calendar_events, plans
from desk.decisions.plans import PlanError, approve_plan, clean, discard_draft, get_plan, list_plans, mark_step, save_draft, save_plan
from desk.decisions.profile import DEFAULTS, active_profile

NOW = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
PLAN = {
    "role": "conviction",
    "thesis": "Made-up thesis: the network gets built and the shares re-rate.",
    "weight_band": {"min_pct": 0, "max_pct": 20},
    "add_rule": {"zone_low": 20, "zone_high": 26.5, "max_per_month_usd": 500, "deposits_only": True, "note": "Only from new deposits."},
    "trim_rule": {"above_pct": 20, "to_pct": 15, "zone_low": 60, "zone_high": 75, "note": None},
    "exit_conditions": ["The launch schedule slips a full year."],
    "tax_notes": "Loss lots are long term in March.",
    "catalysts": [{"text": "Q4 results", "date": "2027-02-24"}, {"text": "Next launch", "date": None}],
    "next_review": "2026-12-20",
    "steps": [
        {"id": "harvest", "kind": "harvest", "due": "2026-12-07", "until": "2026-12-15", "shares": 40, "lots": "highest_cost", "account": "Individual"},
        {"kind": "repay", "due": "2026-11-18"},
        {"kind": "add", "text": "Add on a pullback", "when": "Price is inside the add zone and a deposit has landed"},
        {"kind": "hold", "text": "Hold through the launch window"},
    ],
}
HARVEST = {
    "id": "harvest",
    "kind": "harvest",
    "text": "Sell 40 ABCD to harvest the loss",
    "due": "2026-12-07",
    "until": "2026-12-15",
    "when": None,
    "shares": 40,
    "amount_usd": None,
    "account": "Individual",
    "lots": "highest_cost",
    "no_buy_days": 31,
    "note": None,
    "by": "you",
    "symbol": "ABCD",
    "done_by": None,
    "filled_shares": None,
    "activity_ids": [],
    "status": "upcoming",
    "done_on": None,
    "no_buy_from": "2026-11-06",
    "rebuy_on": None,
    "no_buy_now": True,
}


def _metric(cfg, metric, scope, scope_id, value, as_of="2026-11-09"):
    apply_schemas(cfg, only=["engine"])
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(
        "INSERT INTO metric_values (metric_id, scope, scope_id, window, as_of, value, unit, quality, engine_version) "
        "VALUES (?, ?, ?, 'now', ?, ?, 'pct', 'ok', 'x')",
        (metric, scope, scope_id, as_of, value),
    )
    conn.commit()
    conn.close()


# ---- The record ----


def test_saved_plan_has_the_pinned_shape(cfg):
    out = save_plan(cfg, "abcd", PLAN, now=NOW)
    assert (out["changed"], out["skipped"]) == (True, None)
    p = out["plan"]
    assert set(p) == {
        "symbol",
        "version",
        "status",
        "author",
        "run_id",
        "model",
        "summary",
        "created_at",
        "approved_at",
        "role",
        "thesis",
        "weight_band",
        "band_source",
        "add_rule",
        "trim_rule",
        "exit_conditions",
        "tax_notes",
        "catalysts",
        "next_review",
        "steps",
        "next_step",
        "weight_pct",
        "weight_as_of",
        "band_status",
        "conviction",
        "review_due",
        "warnings",
        "approved",
        "versions",
    }
    assert (p["symbol"], p["version"], p["status"], p["author"], p["approved"], p["versions"]) == ("ABCD", 1, "draft", "you", None, 1)
    assert p["created_at"] == "2026-11-10T15:00:00+00:00" and p["approved_at"] is None
    assert p["weight_band"] == {"min_pct": 0, "max_pct": 20} and p["band_source"] == "plan"
    assert p["add_rule"] == {"zone_low": 20, "zone_high": 26.5, "max_per_month_usd": 500, "deposits_only": True, "note": "Only from new deposits."}
    assert p["trim_rule"] == {"above_pct": 20, "to_pct": 15, "zone_low": 60, "zone_high": 75, "note": None}
    assert p["catalysts"] == [{"text": "Q4 results", "date": "2027-02-24"}, {"text": "Next launch", "date": None}]
    assert (p["weight_pct"], p["weight_as_of"], p["band_status"], p["conviction"], p["review_due"]) == (None, None, None, None, False)
    assert p["warnings"] == ["ABCD has no conviction hold yet, so the single-stock cap still applies. Set one on the Plan screen."]
    assert p["steps"][0] == HARVEST
    assert [(s["id"], s["status"], s["text"]) for s in p["steps"][1:]] == [
        ("repay-2026-11-18", "upcoming", "Pay off the margin debit"),
        ("add", "waiting", "Add on a pullback"),
        ("hold", "standing", "Hold through the launch window"),
    ]
    assert p["next_step"]["id"] == "repay-2026-11-18"
    assert get_plan(cfg, "ABCD", now=NOW) == p and list_plans(cfg, now=NOW) == [p]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"role": "moonshot"}, "role must be one of core, conviction, satellite, exit"),
        ({"thesis": " "}, "thesis is required"),
        ({"weight_band": {"min_pct": 30, "max_pct": 20}}, "weight_band: min_pct is above max_pct"),
        ({"weight_band": {"min_pct": 0}}, "weight_band.max_pct is required"),
        ({"add_rule": {"margin": True}}, "add_rule: unknown field margin"),
        ({"add_rule": {"zone_low": 30, "zone_high": 20}}, "add_rule: zone_low is above zone_high"),
        ({"trim_rule": {"above_pct": 10, "to_pct": 15}}, "trim_rule: to_pct is above above_pct"),
        ({"next_review": "soon"}, "next_review must be a date like 2026-12-07"),
        ({"mood": "sunny"}, "unknown field mood"),
        ({"steps": [{"kind": "yolo"}]}, "steps[0].kind must be one of add, trim, hold, review, harvest, sell, repay, other"),
        ({"steps": [{"kind": "other"}]}, "steps[0].text is required"),
        ({"steps": [{"kind": "add", "shares": "all"}]}, "steps[0].shares can't be all for an add"),
        ({"steps": [{"kind": "review", "shares": 5}]}, "steps[0].shares is only for add, trim, harvest and sell"),
        ({"steps": [{"kind": "sell", "until": "2026-12-01"}]}, "steps[0].until needs a due date"),
        ({"steps": [{"kind": "sell", "due": "2026-12-09", "until": "2026-12-01"}]}, "steps[0]: due is above until"),
        (
            {"steps": [{"kind": "add", "lots": "fifo"}]},
            "steps[0].lots must be one of highest_cost, lowest_cost, fifo, lifo, tax_efficient, on a trim, harvest or sell",
        ),
        ({"steps": [{"id": "a", "kind": "review"}, {"id": "a", "kind": "review"}]}, "steps: id 'a' is used twice"),
    ],
)
def test_bad_plans_are_refused(change, message):
    with pytest.raises(PlanError, match=message.replace("[", r"\[").replace("]", r"\]")) as e:
        clean(PLAN | change)
    assert e.value.status == 422 and isinstance(e.value, ValueError)


def test_view_fields_are_dropped_so_a_plan_can_be_sent_back(cfg):
    first = save_plan(cfg, "ABCD", PLAN, now=NOW)["plan"]
    again = save_plan(cfg, "ABCD", first, now=NOW)
    assert (again["changed"], again["skipped"], again["plan"]["version"]) == (False, "unchanged", 1)
    with pytest.raises(PlanError, match="doesn't look like a ticker"):
        save_plan(cfg, "AB CD", PLAN)


# ---- Versions ----


def test_draft_approve_and_discard(cfg):
    save_plan(cfg, "ABCD", PLAN, now=NOW)
    done = approve_plan(cfg, "abcd", now=NOW + timedelta(hours=1))
    assert done["changed"] is True and (done["plan"]["status"], done["plan"]["approved_at"]) == ("approved", "2026-11-10T16:00:00+00:00")
    assert approve_plan(cfg, "ABCD")["changed"] is False
    edited = save_plan(cfg, "ABCD", PLAN | {"thesis": "A sharper made-up thesis."}, now=NOW)["plan"]
    assert (edited["version"], edited["status"], edited["versions"]) == (2, "draft", 2)
    assert (edited["approved"]["version"], edited["approved"]["thesis"]) == (1, PLAN["thesis"])
    assert [p["version"] for p in plans.approved_plans(cfg, now=NOW)] == [1]
    back = discard_draft(cfg, "ABCD")["plan"]
    assert (back["version"], back["status"], back["approved"]) == (1, "approved", None)
    with pytest.raises(PlanError, match="no draft to discard") as e:
        discard_draft(cfg, "ABCD")
    assert e.value.status == 404
    one_go = save_plan(cfg, "ABCD", PLAN | {"thesis": "Third made-up thesis."}, approve=True, now=NOW)["plan"]
    assert (one_go["version"], one_go["status"], one_go["approved"]) == (3, "approved", None)
    assert [(h["version"], h["status"]) for h in plans.history(cfg, "ABCD")] == [(3, "approved"), (2, "discarded"), (1, "approved")]
    assert plans.get_version(cfg, "ABCD", 2, now=NOW)["thesis"] == "A sharper made-up thesis."
    with pytest.raises(PlanError, match="no plan yet"):
        approve_plan(cfg, "ZZZZ")
    with pytest.raises(PlanError, match="no version 9"):
        approve_plan(cfg, "ABCD", 9)


def test_desk_drafts_never_touch_his_work(cfg):
    desk = {k: PLAN[k] for k in ("role", "thesis")} | {
        "steps": [{"kind": "review", "due": "2026-12-01"}, {"id": "harvest", "kind": "sell", "text": "Sell it all"}]
    }
    first = save_draft(cfg, "ABCD", desk, run_id="run-1", model="some-model", summary="First pass", now=NOW)
    p = first["plan"]
    assert (first["changed"], p["status"], p["author"], p["run_id"], p["model"], p["summary"]) == (True, "draft", "desk", "run-1", "some-model", "First pass")
    assert [s["by"] for s in p["steps"]] == ["desk", "desk"]
    assert save_draft(cfg, "ABCD", desk, now=NOW)["skipped"] == "unchanged"
    mine = save_plan(cfg, "ABCD", PLAN, now=NOW)["plan"]
    assert (mine["version"], mine["author"]) == (2, "you")
    held = save_draft(cfg, "ABCD", desk, now=NOW)
    assert (held["changed"], held["skipped"], held["plan"]["version"]) == (False, "your_draft", 2)
    approve_plan(cfg, "ABCD", now=NOW)
    refreshed = save_draft(cfg, "ABCD", desk | {"thesis": "The desk's fresh made-up take."}, now=NOW)["plan"]
    assert (refreshed["version"], refreshed["status"], refreshed["approved"]["version"]) == (3, "draft", 2)
    steps = {s["id"]: s for s in refreshed["steps"]}
    assert list(steps) == ["review-2026-12-01", "harvest", "repay-2026-11-18", "add", "hold"]
    assert (steps["harvest"]["kind"], steps["harvest"]["shares"], steps["harvest"]["by"]) == ("harvest", 40, "you")
    assert steps["review-2026-12-01"]["by"] == "desk"
    assert plans.approved_plans(cfg, now=NOW)[0]["thesis"] == PLAN["thesis"]
    newer = save_draft(cfg, "ABCD", desk | {"thesis": "An even fresher made-up take."}, now=NOW)["plan"]
    assert newer["version"] == 4 and [h["status"] for h in plans.history(cfg, "ABCD")] == ["draft", "superseded", "approved", "superseded"]


# ---- Steps ----


def test_step_status_follows_the_calendar_fills_and_his_taps(cfg, mirror):
    save_plan(cfg, "ABCD", PLAN, approve=True, now=NOW)
    in_window = datetime(2026, 12, 8, 15, 0, tzinfo=UTC)
    harvest = get_plan(cfg, "ABCD", now=in_window)["steps"][0]
    assert (harvest["status"], harvest["no_buy_now"]) == ("open", True)
    mirror("s1", date="2026-12-08", accountKey="individual-1", kind="sell", symbol="ABCD", quantity=-15, amount=300)
    harvest = get_plan(cfg, "ABCD", now=in_window)["steps"][0]
    assert (harvest["status"], harvest["filled_shares"], harvest["activity_ids"]) == ("partial", 15, ["s1"])
    mirror("s2", date="2026-12-09", accountKey="individual-1", kind="sell", symbol="ABCD", quantity=-25, amount=500)
    harvest = get_plan(cfg, "ABCD", now=in_window + timedelta(days=2))["steps"][0]
    assert (harvest["status"], harvest["done_on"], harvest["done_by"], harvest["rebuy_on"], harvest["no_buy_now"]) == (
        "done",
        "2026-12-09",
        "broker",
        "2027-01-09",
        True,
    )
    assert get_plan(cfg, "ABCD", now=datetime(2027, 1, 9, 15, 0, tzinfo=UTC))["steps"][0]["no_buy_now"] is False
    late = get_plan(cfg, "ABCD", now=datetime(2026, 11, 25, 15, 0, tzinfo=UTC))["steps"][1]
    assert late["status"] == "passed"
    _metric(cfg, "margin.debit", "portfolio", "all", 0.0, "2026-11-19")
    repaid = get_plan(cfg, "ABCD", now=datetime(2026, 11, 25, 15, 0, tzinfo=UTC))["steps"][1]
    assert (repaid["status"], repaid["done_on"], repaid["done_by"]) == ("done", "2026-11-19", "desk")
    tapped = mark_step(cfg, "abcd", "hold", on="2026-11-12", now=NOW)["plan"]
    assert [(s["status"], s["done_on"], s["done_by"]) for s in tapped["steps"] if s["id"] == "hold"] == [("done", "2026-11-12", "you")]
    undone = mark_step(cfg, "ABCD", "hold", undo=True, now=NOW)["plan"]
    assert [s["status"] for s in undone["steps"] if s["id"] == "hold"] == ["standing"]
    with pytest.raises(PlanError, match="no step 'nope'") as e:
        mark_step(cfg, "ABCD", "nope")
    assert e.value.status == 404


def test_only_approved_plans_reach_the_brief_calendar_and_alerts(cfg, monkeypatch):
    save_plan(cfg, "ABCD", PLAN, now=NOW)
    assert plans.steps_today(cfg, now=NOW) == [] and plans.no_buy(cfg, now=NOW) == {}
    assert not [e for e in calendar_events(cfg, "2026-11-01", "2027-03-01", now=NOW) if e["source"] == "plan"]
    approve_plan(cfg, "ABCD", now=NOW)
    assert plans.steps_today(cfg, now=NOW) == [
        "ABCD: Sell 40 ABCD to harvest the loss. Window 2026-12-07 to 2026-12-15 (upcoming). From Individual. "
        "Lots: Specific Shares, highest-cost lots. No ABCD buys in any account until 31 days after the sale."
    ]
    assert plans.no_buy(cfg, now=NOW) == {"ABCD": {"from": "2026-11-06", "until": None, "step_id": "harvest", "reason": "Sell 40 ABCD to harvest the loss"}}
    assert [s["id"] for s in plans.open_steps(cfg, days=10, now=NOW)] == ["repay-2026-11-18", "harvest"]
    events = [(e["date"], e["title"]) for e in calendar_events(cfg, "2026-11-01", "2027-03-01", now=NOW) if e["source"] == "plan"]
    assert events == [
        ("2026-11-18", "ABCD: Pay off the margin debit"),
        ("2026-12-07", "ABCD: Sell 40 ABCD to harvest the loss: window opens (Specific Shares, highest-cost lots)"),
        ("2026-12-15", "ABCD: Sell 40 ABCD to harvest the loss: window closes"),
        ("2026-12-20", "Review the ABCD plan"),
        ("2027-02-24", "ABCD: Q4 results"),
    ]
    sent = []
    monkeypatch.setattr(alerting, "publish", lambda topic, title, body="", priority="default", **kw: sent.append({"title": title, "body": body, **kw}) or True)
    keys = [k for k in alerting.send_alerts(cfg, now=datetime(2026, 12, 7, 15, 0, tzinfo=UTC)) if k.startswith("plan-")]
    assert keys == ["plan-step-ABCD-harvest-2026-12-07"]
    assert (
        sent[-1]["title"] == "ABCD: Sell 40 ABCD to harvest the loss" and sent[-1]["body"] == "Open until 2026-12-15. Lots: Specific Shares, highest-cost lots."
    )
    keys = [k for k in alerting.send_alerts(cfg, now=datetime(2026, 12, 20, 15, 0, tzinfo=UTC)) if k.startswith("plan-")]
    assert keys == ["plan-review-ABCD-2026-12-20"]


def test_weight_band_and_conviction_hold(cfg):
    (cfg.data_dir / "desk.yaml").write_text(
        "rules:\n  - id: conviction-abcd\n    kind: conviction_hold\n    symbols: [ABCD]\n    params: {band_min_pct: 0, band_max_pct: 25}\n"
    )
    _metric(cfg, "value.weight", "holding", "ABCD", 31.4)
    _metric(cfg, "value.weight", "holding", "WXYZ", 4.0)
    p = save_plan(cfg, "ABCD", PLAN, now=NOW)["plan"]
    assert (p["weight_pct"], p["weight_as_of"], p["band_status"], p["conviction"]["band_max_pct"]) == (31.4, "2026-11-09", "above", 25)
    assert p["warnings"] == ["The plan's band differs from the conviction hold (0 to 25%), and the hold is what the desk enforces."]
    bare = save_plan(cfg, "ABCD", PLAN | {"weight_band": None}, now=NOW)["plan"]
    assert (bare["weight_band"], bare["band_source"], bare["band_status"], bare["warnings"]) == ({"min_pct": 0, "max_pct": 25}, "conviction", "above", [])
    gone = save_plan(cfg, "QRST", PLAN | {"role": "core", "weight_band": {"max_pct": 10}}, now=NOW)["plan"]
    assert (gone["weight_pct"], gone["band_status"], gone["warnings"]) == (0.0, "inside", [])


def test_new_desks_default_on_behind_the_master_switch(cfg):
    assert (DEFAULTS["agents"]["desks"]["debrief"], DEFAULTS["agents"]["desks"]["plans"], DEFAULTS["agents"]["desks"]["research"]) == (True, True, False)
    assert DEFAULTS["agents"]["enabled"] is False
    (cfg.data_dir / "desk.yaml").write_text("agents:\n  enabled: true\n  desks:\n    tax: true\n")
    profile = active_profile(cfg)
    assert profile.desk_enabled("plans") and profile.desk_enabled("debrief") and not profile.desk_enabled("scout")


# ---- API ----


def test_plan_endpoints(cfg, app_client):
    client = app_client(packages=["decisions"])
    empty = client.get("/api/decisions/plans").json()
    assert empty["items"] == [] and empty["roles"] == ["core", "conviction", "satellite", "exit"] and "harvest" in empty["step_templates"]
    assert client.get("/api/decisions/plans/ABCD").status_code == 404
    assert client.put("/api/decisions/plans/ABCD", json={"plan": PLAN | {"role": "moonshot"}}).status_code == 422
    put = client.put("/api/decisions/plans/abcd", json={"plan": PLAN}).json()
    assert (put["changed"], put["plan"]["symbol"], put["plan"]["status"], put["plan"]["author"]) == (True, "ABCD", "draft", "you")
    assert client.get("/api/decisions/plan-steps").json() == {"items": [], "no_buy": {}}
    ok = client.post("/api/decisions/plans/ABCD/approve", json={}).json()
    assert ok["changed"] is True and ok["plan"]["status"] == "approved"
    read = client.get("/api/decisions/plans/ABCD").json()
    assert read["plan"]["version"] == 1 and [h["version"] for h in read["history"]] == [1]
    assert client.get("/api/decisions/plans/ABCD/versions/1").json()["plan"]["thesis"] == PLAN["thesis"]
    assert client.get("/api/decisions/plans/ABCD/versions/7").status_code == 404
    done = client.post("/api/decisions/plans/ABCD/steps/hold/done", json={"on": "2026-11-12"}).json()
    assert [s["done_on"] for s in done["plan"]["steps"] if s["id"] == "hold"] == ["2026-11-12"]
    assert client.post("/api/decisions/plans/ABCD/steps/nope/done", json={}).status_code == 404
    client.put("/api/decisions/plans/ABCD", json={"plan": PLAN | {"thesis": "Edited made-up thesis."}})
    assert client.get("/api/decisions/plans").json()["items"][0]["approved"]["version"] == 1
    assert client.post("/api/decisions/plans/ABCD/discard").json()["plan"]["version"] == 1
    assert client.post("/api/decisions/plans/ABCD/discard").status_code == 404
    saved = client.put("/api/decisions/plans/ABCD", json={"plan": PLAN | {"thesis": "Edited again."}, "approve": True}).json()
    assert (saved["plan"]["version"], saved["plan"]["status"]) == (3, "approved")
    steps = client.get("/api/decisions/plan-steps?days=30").json()
    assert set(steps) == {"items", "no_buy"} and all("line" in s for s in steps["items"])
    assert client.get("/api/decisions/plan-steps?days=9999").status_code == 422
