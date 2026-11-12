import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from desk.agents import __main__ as cli
from desk.agents import briefs, debrief, store
from desk.agents.adapter import AgentError, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.jobs import JOBS
from desk.agents.sources import NotReady, RealReviews
from desk.agents.status import crew
from desk.engine.jobs import JOBS as ENGINE_JOBS
from desk.scheduler import package_jobs
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_advisor import FakeAdvisor

ON = {"agents": {"enabled": True, "desks": {"debrief": True}}}
ANSWER = {
    "headline": "A rough day: down 1.2%, a touch worse than the S&P 500",
    "what_happened": "The book fell 1.2% against 0.9% for the S&P 500. No deposits or trades.",
    "why": "Most of it was MSFT after its guidance cut.",
    "against_decisions": "",
    "watch": ["MSFT reports again on Jan 27"],
    "next_steps": [{"text": "Nothing to do today.", "symbol": None}, {"text": "Check the MSFT plan's add zone.", "symbol": "msft"}],
    "numbers_cited": ["change_pct", "vs.spy.pts", "contrib.MSFT.usd", "invented"],
}


def pack_row(kind="day", end="2026-11-10", closed=True, digest="d1", debrief_digest=None) -> dict:
    return {
        "kind": kind,
        "start": end if kind == "day" else "2026-11-02",
        "end": end,
        "closed": closed,
        "digest": digest,
        "debrief_digest": debrief_digest,
        "pack": {
            "as_of": end,
            "final": False,
            "numbers": {"change_pct": -1.2, "change_usd": -410.0, "vs.spy.pts": -0.3, "contrib.MSFT.usd": -260.0},
            "movers": {"up": [], "down": [{"symbol": "MSFT", "usd": -260.0}]},
            "risk": {"band": 4},
            "decisions": {"made": [], "matured": []},
            "events": [],
        },
    }


@dataclass
class FakeReviews:
    rows: list = field(default_factory=list)
    ready: bool = True
    refuse: set = field(default_factory=set)
    recorded: dict = field(default_factory=dict)
    shown: dict = field(default_factory=dict)

    def pending(self, cfg):
        if not self.ready:
            raise NotReady("no review run yet")
        return self.rows

    def record(self, cfg, kind, end, result):
        if (kind, end) in self.refuse:
            raise ValueError("pack_digest is not the current digest")
        self.recorded[(kind, end)] = result

    def view(self, cfg, kind, end=None):
        if not self.ready:
            raise NotReady("no review run yet")
        return self.shown


@dataclass
class FakePlans:
    rows: list = field(
        default_factory=lambda: [{"symbol": "MSFT", "status": "approved", "role": "core", "thesis": "long text", "steps": [{"text": "Add in zone"}]}]
    )

    def list_plans(self, cfg):
        return self.rows

    def steps_today(self, cfg):
        return ["MSFT: add up to 200 from the next deposit while it sits in the add zone."]


class Served(FakeAdapter):
    def run(self, desk, system, prompt, schema=None):
        out = super().run(desk, system, prompt, schema)
        out.model = "claude-opus-5-5"
        return out


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr("desk.agents.alerts.publish", lambda *a, **k: calls.append((a, k)) or True)
    return calls


def go(cfg, rows, profile=ON, answer=ANSWER, **kw):
    box = FakeReviews(rows)
    fake = Served({"debrief": answer})
    report = debrief.run_debrief_desk(
        cfg, reviews=box, decisions=FakeDecisions(profile_data=profile), adapter=fake, advice=FakeAdvisor(), plans=FakePlans(), **kw
    )
    return report, box, fake


def seed(cfg):
    run_id = store.start_run(cfg, "debrief", trigger="schedule", model="opus", effort="high")
    store.finish_run(cfg, run_id, "ok")
    store.save_brief(cfg, run_id, "debrief", "2026-11-09", "d0", "", "Earlier debrief", "{}")


# ---- Switches ----


def test_runs_under_the_first_run_guard_but_not_when_switched_off(cfg, sent):
    store.set_guard(cfg, True)
    report, box, _ = go(cfg, [pack_row()])
    assert report.status == "ok" and box.recorded
    tiles = {d["desk"]: d for d in crew(cfg)["desks"]}
    assert tiles["debrief"]["guarded"] is False and tiles["risk"]["guarded"] is True
    store.set_enabled(cfg, "debrief", False)
    report, _, fake = go(cfg, [pack_row(end="2026-11-11")])
    assert report.status == "disabled" and not fake.calls


def test_on_by_default_without_a_desk_yaml_key(cfg, sent):
    report, _, fake = go(cfg, [pack_row()], profile={})
    assert report.status == "ok" and len(fake.calls) == 1


# ---- The debrief ----


def test_day_debrief_is_recorded_with_digest_model_and_clean_numbers(cfg, sent):
    seed(cfg)
    report, box, fake = go(cfg, [pack_row()])
    assert report.status == "ok" and report.written == ["day 2026-11-10"]
    desk = get("debrief")
    assert (desk.model, desk.effort, desk.tools) == ("opus", "high", ())
    call = fake.calls[0]
    assert call["system"] == briefs.prompt_file("debrief") and call["schema"] == briefs.schema_file("debrief")
    payload = json.loads(call["prompt"].split("\n\n", 1)[1])
    assert payload["review"] == {"kind": "day", "start": "2026-11-10", "end": "2026-11-10", "closed": True}
    assert payload["pack"]["numbers"]["change_pct"] == -1.2 and payload["advisor"]["risk_band"]["band"] == 4
    assert payload["stock_plans"] == [{"symbol": "MSFT", "status": "approved", "role": "core", "steps": [{"text": "Add in zone"}]}]
    got = box.recorded[("day", "2026-11-10")]
    assert got["numbers_cited"] == ["change_pct", "vs.spy.pts", "contrib.MSFT.usd"] and report.dropped_numbers == 1
    assert (got["pack_digest"], got["model"]) == ("d1", "claude-opus-5-5") and got["written_at"].endswith("+00:00") and got["run_id"]
    assert got["next_steps"][1] == {"text": "Check the MSFT plan's add zone.", "symbol": "MSFT"}
    assert got["against_decisions"] == debrief.NO_DECISIONS and all(got[k] for k in debrief.TEXT)
    assert store.runs(cfg, "debrief")[0]["note"].startswith("day 2026-11-10: A rough day")


def test_phone_alert_carries_the_headline(cfg, sent):
    seed(cfg)
    go(cfg, [pack_row(), pack_row("week", "2026-11-13")])
    (args, kwargs), (wargs, wkwargs) = sent
    assert args[:3] == ("research", "Day review: 2026-11-10", ANSWER["headline"]) and args[3] == "low"
    assert kwargs["key"] == "agents:debrief:day:2026-11-10" and kwargs["click"] == "/results/day?end=2026-11-10"
    assert wargs[1] == "Week review: 2026-11-13" and wargs[3] == "default" and wkwargs["click"] == "/results/week?end=2026-11-13"


def test_long_text_is_trimmed_to_the_contract(cfg, sent):
    seed(cfg)
    long = ANSWER | {"headline": "h" * 300, "why": "w" * 2000, "watch": ["x" * 400] * 9, "next_steps": [{"text": "t" * 500, "symbol": None}] * 7}
    _, box, _ = go(cfg, [pack_row()], answer=long)
    got = box.recorded[("day", "2026-11-10")]
    assert len(got["headline"]) == 120 and len(got["why"]) == 700 and len(got["watch"]) == 4 and len(got["watch"][0]) == 160
    assert len(got["next_steps"]) == 3 and len(got["next_steps"][0]["text"]) == 200


# ---- Which periods ----


def test_open_week_month_and_year_wait_for_their_close(cfg, sent):
    seed(cfg)
    rows = [
        pack_row(),
        pack_row("week", "2026-11-13", closed=False),
        pack_row("month", "2026-11-30", closed=False),
        pack_row("year", "2026-12-31", closed=False),
    ]
    report, _, fake = go(cfg, rows)
    assert report.written == ["day 2026-11-10"] and len(fake.calls) == 1
    rows[1]["closed"] = rows[2]["closed"] = True
    report, _, _ = go(cfg, rows)
    assert report.written == ["day 2026-11-10", "week 2026-11-13", "month 2026-11-30"]


def test_the_day_a_week_closes_refreshes_month_and_year_so_far(cfg, sent):
    seed(cfg)
    rows = [
        pack_row(end="2026-11-13"),
        pack_row("week", "2026-11-13"),
        pack_row("month", "2026-11-30", closed=False),
        pack_row("year", "2026-12-31", closed=False),
    ]
    report, _, _ = go(cfg, rows)
    assert report.written == ["day 2026-11-13", "week 2026-11-13", "month 2026-11-30", "year 2026-12-31"]
    rows[0] = pack_row(end="2026-11-16")
    rows[1] = pack_row("week", "2026-11-20", closed=False)
    report, _, _ = go(cfg, rows)
    assert report.written == ["day 2026-11-16"]


def test_first_ever_run_debriefs_every_period_so_far(cfg, sent):
    rows = [
        pack_row(),
        pack_row("week", "2026-11-13", closed=False),
        pack_row("month", "2026-11-30", closed=False),
        pack_row("year", "2026-12-31", closed=False),
    ]
    report, _, fake = go(cfg, rows, kinds=("day", "month", "year"))
    assert len(report.written) == 4 and len(fake.calls) == 4
    report, _, fake = go(cfg, rows, kinds=("day", "month", "year"))
    assert report.written == ["day 2026-11-10"]


def test_kinds_and_so_far_pick_periods(cfg, sent):
    seed(cfg)
    rows = [pack_row(), pack_row("week", "2026-11-13", closed=True), pack_row("month", "2026-11-30", closed=False)]
    report, _, _ = go(cfg, rows, kinds=("week",))
    assert report.written == ["week 2026-11-13"]
    report, _, _ = go(cfg, rows, kinds=("month",), so_far=True)
    assert report.written == ["month 2026-11-30"]
    assert debrief.parse_kinds("day, week") == ("day", "week") and debrief.parse_kinds(None) is None
    with pytest.raises(ValueError):
        debrief.parse_kinds("decade")


def test_unchanged_pack_makes_no_call_and_no_run(cfg, sent):
    seed(cfg)
    before = len(store.runs(cfg, "debrief"))
    report, _, fake = go(cfg, [pack_row(digest="d1", debrief_digest="d1")])
    assert report.status == "ok" and report.unchanged == ["day 2026-11-10"] and not fake.calls
    assert len(store.runs(cfg, "debrief")) == before and not sent
    report, _, fake = go(cfg, [])
    assert report.note == "No new period pack to debrief." and not fake.calls


def test_missing_pack_skips_as_not_ready(cfg):
    box = FakeReviews(ready=False)
    report = debrief.run_debrief_desk(cfg, reviews=box, decisions=FakeDecisions(profile_data=ON), adapter=Served(), advice=FakeAdvisor(), plans=FakePlans())
    assert report.status == "not_ready" and "no review run yet" in report.note
    with pytest.raises(NotReady):
        RealReviews().pending(cfg)


def test_stock_plans_are_optional(cfg, sent):
    class NoPlans:
        def list_plans(self, cfg):
            raise NotReady("plans not built")

    seed(cfg)
    box, fake = FakeReviews([pack_row()]), Served({"debrief": ANSWER})
    report = debrief.run_debrief_desk(cfg, reviews=box, decisions=FakeDecisions(profile_data=ON), adapter=fake, advice=FakeAdvisor(), plans=NoPlans())
    assert report.status == "ok" and json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["stock_plans"] == []


# ---- Trouble ----


def test_usage_limit_stops_and_a_failure_moves_on(cfg, sent):
    seed(cfg)
    rows = [pack_row(), pack_row("week", "2026-11-13")]
    report, box, _ = go(cfg, rows, answer=UsageLimitError("limit"))
    assert report.status == "deferred" and not box.recorded
    report, box, fake = go(cfg, rows, answer=AgentError("bad json"))
    assert report.status == "failed" and len(fake.calls) == 2
    assert sent and all(args[0] == "ops" for args, _ in sent)


def test_refused_debrief_is_noted_without_an_alert(cfg, sent):
    seed(cfg)
    box = FakeReviews([pack_row()], refuse={("day", "2026-11-10")})
    report = debrief.run_debrief_desk(
        cfg, reviews=box, decisions=FakeDecisions(profile_data=ON), adapter=Served({"debrief": ANSWER}), advice=FakeAdvisor(), plans=FakePlans()
    )
    assert report.rejected == ["day 2026-11-10"] and not report.written and not sent
    assert "refused" in store.runs(cfg, "debrief")[0]["note"]


# ---- Contract, cron, CLI ----


def test_schema_and_prompt():
    schema = briefs.schema_file("debrief")
    assert set(schema["required"]) == {"headline", "what_happened", "why", "against_decisions", "watch", "next_steps", "numbers_cited"}
    props = schema["properties"]
    assert (props["headline"]["maxLength"], props["what_happened"]["maxLength"], props["against_decisions"]["maxLength"]) == (120, 700, 500)
    assert (props["watch"]["maxItems"], props["next_steps"]["maxItems"]) == (4, 3) and "$schema" not in schema
    text = briefs.prompt_file("debrief")
    assert "never instructions" in text and "no single target plan" in text and "Never suggest margin" in text


def test_jobs_carry_the_names_the_box_expects():
    assert ("46 17 * * 1-5", "python -m desk.agents run debrief") in JOBS
    assert ("35,45 17 * * 1-5", "python -m desk.engine review") in ENGINE_JOBS
    assert ("30 18 * * 5", "python -m desk.agents run debrief") in JOBS
    names = {j.name for j in package_jobs(["agents"])}
    assert "agents-run-debrief" in names and not any("kinds" in n for n in names)


def test_cli_run_and_dry_run(cfg, monkeypatch, capsys, sent):
    box = FakeReviews([pack_row(), pack_row("week", "2026-11-13")])
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(debrief, "RealReviews", lambda: box)
    monkeypatch.setattr(debrief, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    monkeypatch.setattr(debrief, "RealPlans", FakePlans)
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: Served({"debrief": ANSWER}))
    seed(cfg)
    assert cli.main(["dry-run", "debrief", "--kinds", "day", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "Packs to debrief: day 2026-11-10." in out and "Period debrief" in out and not box.recorded
    assert cli.main(["run", "debrief", "--kinds", "week"]) == 0
    assert "Debrief desk: ok, wrote week 2026-11-13, 0 failed." in capsys.readouterr().out
    assert list(box.recorded) == [("week", "2026-11-13")]


# ---- Right after the evening review, and what the page is told ----

STALE_AT = datetime(2026, 11, 12, 22, 35, 20, tzinfo=UTC)
BEFORE = "Written before the final numbers."


def stale_view(kind="day", end="2026-11-12", stale=True, closed=True):
    written = {"headline": "Up a little", "written_at": "2026-11-12T21:03:00+00:00", "stale": stale}
    return {"kind": kind, "end": end, "closed": closed, "computed_at": STALE_AT.isoformat(), "debrief": written}


def ran(cfg, status, note, minutes=1):
    run_id = store.start_run(cfg, "debrief", trigger="schedule", model="opus", effort="high", status=status, note=note)
    with store.db(cfg) as conn:
        conn.execute("UPDATE agent_runs SET started_at=? WHERE id=?", ((STALE_AT + timedelta(minutes=minutes)).isoformat(), run_id))


def told(cfg, minutes, view=None, rows=None, profile=ON):
    view = view or stale_view()
    rows = [pack_row(end="2026-11-12", digest="d2", debrief_digest="d1")] if rows is None else rows
    box = FakeReviews(rows, shown=view)
    return debrief.rewrite(cfg, view["kind"], reviews=box, decisions=FakeDecisions(profile_data=profile), now=STALE_AT + timedelta(minutes=minutes))


def test_the_scheduled_run_waits_for_the_review_to_finish(cfg, monkeypatch):
    seen, naps = [[{"job": "engine-review"}], [{"job": "engine-daily"}], [{"job": "agents"}]], []
    assert debrief.settle(cfg, busy=lambda cfg: seen.pop(0), sleep=naps.append) and naps == [debrief.REVIEW_POLL] * 2
    assert not debrief.settle(cfg, 0, busy=lambda cfg: [{"job": "engine-review"}], sleep=naps.append)
    order = []
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(cli, "settle", lambda cfg: order.append("settle"))
    monkeypatch.setattr(cli, "run_debrief_desk", lambda cfg, **kw: order.append(kw["trigger"]) or debrief.DebriefReport("ok"))
    assert cli.main(["run", "debrief"]) == 0 and cli.main(["run", "debrief", "--trigger", "manual"]) == 0
    assert order == ["settle", "schedule", "manual"]


def test_a_fresh_debrief_has_nothing_to_tell_the_page(cfg):
    assert told(cfg, 1, stale_view(stale=False)) == {"kind": "day", "end": "2026-11-12", "stale": False, "rewrite": None}
    assert debrief.rewrite(cfg, "day", reviews=FakeReviews(ready=False)) == {"kind": "day", "end": None, "stale": False, "rewrite": None}


def test_a_stale_debrief_is_due_then_late_after_an_hour(cfg):
    due = told(cfg, 0)
    assert due == {"kind": "day", "end": "2026-11-12", "stale": True, "rewrite": {"state": "due", "due_at": "2026-11-12T17:46:00-05:00", "words": None}}
    assert told(cfg, 59)["rewrite"] == {"state": "due", "due_at": "2026-11-13T01:40:00-05:00", "words": None}
    late = told(cfg, 61)["rewrite"]
    assert late["state"] == "late" and late["words"] == f"{BEFORE} The rewrite is running late; the next try is tomorrow at 1:40 AM."


def test_a_rewrite_that_did_not_finish_says_when_the_next_try_is(cfg):
    ran(cfg, "failed", "week 2026-11-13: timed out")
    assert told(cfg, 3)["rewrite"]["state"] == "due"
    ran(cfg, "failed", "day 2026-11-12: timed out")
    failed = told(cfg, 3)["rewrite"]
    assert failed == {
        "state": "failed",
        "due_at": "2026-11-12T17:46:00-05:00",
        "words": f"{BEFORE} The rewrite did not finish; the desk tries again at 5:46 PM.",
    }
    assert told(cfg, 3, stale_view() | {"computed_at": (STALE_AT + timedelta(minutes=2)).isoformat()})["rewrite"]["state"] == "due"


def test_a_desk_that_declined_counts_as_a_failed_rewrite(cfg):
    ran(cfg, "busy", "Another desk was running.")
    assert told(cfg, 3)["rewrite"]["state"] == "due"
    ran(cfg, "over_budget", "Weekly cap reached.")
    assert told(cfg, 3)["rewrite"]["state"] == "failed"


def test_no_rewrite_is_coming_when_the_desk_is_off_or_the_period_is_old(cfg):
    off = told(cfg, 1, profile={"agents": {"enabled": True, "desks": {"debrief": False}}})["rewrite"]
    assert off == {"state": "late", "due_at": None, "words": f"{BEFORE} The Debrief desk is switched off, so it stays as written."}
    old = told(cfg, 1, stale_view(end="2026-11-10"))["rewrite"]
    assert old == {"state": "late", "due_at": None, "words": f"{BEFORE} The numbers were revised after it was written."}
    week = told(cfg, 1, stale_view("week", "2026-11-13", closed=False), rows=[pack_row("week", "2026-11-13", closed=False, debrief_digest="d0")])
    assert week["rewrite"]["state"] == "late" and week["rewrite"]["due_at"] is None


def test_the_next_try_is_named_by_day_when_it_is_not_today(cfg):
    saturday = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    view = stale_view(end="2026-11-13") | {"computed_at": (saturday - timedelta(hours=2)).isoformat()}
    box = FakeReviews([pack_row(end="2026-11-13", digest="d2", debrief_digest="d1")], shown=view)
    out = debrief.rewrite(cfg, "day", reviews=box, decisions=FakeDecisions(profile_data=ON), now=saturday)["rewrite"]
    assert out["due_at"] == "2026-11-16T17:46:00-05:00" and out["words"].endswith("the next try is on Monday at 5:46 PM.")


def test_the_page_can_ask_for_the_rewrite_state(cfg, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from desk.agents.api import router
    from desk.api.deps import get_cfg

    box = FakeReviews([pack_row(end="2026-11-12", digest="d2", debrief_digest="d1")], shown=stale_view() | {"computed_at": datetime.now(UTC).isoformat()})
    monkeypatch.setattr(debrief, "RealReviews", lambda: box)
    monkeypatch.setattr(debrief, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_cfg] = lambda: cfg
    client = TestClient(app)
    body = client.get("/api/agents/debrief").json()
    assert (body["kind"], body["end"], body["stale"], body["rewrite"]["state"], body["rewrite"]["words"]) == ("day", "2026-11-12", True, "due", None)
    assert client.get("/api/agents/debrief?kind=decade").status_code == 404


def test_the_real_review_view_is_read_without_writing(cfg):
    assert RealReviews().view(cfg, "day")["debrief"] is None
    assert debrief.rewrite(cfg, "day", decisions=FakeDecisions(profile_data=ON)) == {"kind": "day", "end": None, "stale": False, "rewrite": None}
