import json
from dataclasses import dataclass, field

from desk.agents import __main__ as cli
from desk.agents import moves, store
from desk.agents.adapter import AgentError, FakeAdapter
from desk.agents.jobs import JOBS, MOVES_JOB
from desk.agents.sources import NotReady
from desk.scheduler import package_jobs
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_advisor import FakeAdvisor

ON = {"agents": {"enabled": True, "desks": {"research": True}}}
ANSWER = {
    "verdict": "overreaction",
    "headline": "Fell after a share offering priced under yesterday's close",
    "why": "The company sold new shares at a discount this morning. Holders were diluted by about 4.0123%.",
    "overdone_case": "The cash funds launches already planned, so the plan did not change.",
    "real_case": "More offerings may follow before revenue arrives.",
    "watch": "The next launch date.",
    "plan_note": "This doesn't change your December sale.",
    "confidence": 0.6,
    "sources": [
        {"url": "https://example.com/offering", "title": "Pricing of offering", "date": "2026-11-16"},
        {"url": "ftp://bad", "title": "x", "date": None},
    ],
    "summary": "Offering.",
}


def live(state="after", rows=None, spy=(590.0, 595.0), day="2026-11-16"):
    rows = rows or [
        ("taxable", "TICKA", 300, 26.6, 30.0),
        ("hsa", "TICKA", 25, 26.6, 30.0),
        ("taxable", "FUNDA", 10, 99.0, 100.0),
        ("taxable", "TICKB", 5, 101.5, 100.0),
        ("taxable", "CORE", 500, 1.0, 1.0),
    ]
    out = []
    for account, symbol, shares, price, prev in rows:
        cash = symbol == "CORE"
        out.append(
            {
                "account": account,
                "symbol": symbol,
                "shares": shares,
                "price": price,
                "prev_close": prev,
                "value": round(shares * price, 2),
                "day_change": round(shares * (price - prev), 2),
                "source": "cash" if cash else "finnhub",
            }
        )
    return {
        "state": state,
        "day": day,
        "quote_day": day,
        "holdings_date": "2026-11-13",
        "rows": out,
        "benchmarks": {"SPY": {"price": spy[0], "prev_close": spy[1]}},
    }


@dataclass
class FakeMoves:
    raw: dict = field(default_factory=live)
    ready: bool = True

    def day(self, cfg):
        if not self.ready:
            raise NotReady("no live quotes yet")
        return self.raw

    def names(self, cfg):
        return {"TICKA": "Ticka Space Inc"}


@dataclass
class FakePlans:
    def list_plans(self, cfg):
        return [{"symbol": "TICKA", "thesis": "Held for the launch cadence", "steps": [{"id": "s1", "kind": "sell", "due": "2026-12-07", "shares": 105}]}]


def go(cfg, raw=None, answer=ANSWER, profile=ON, trigger="schedule", **kw):
    fake = FakeAdapter({"moves": answer})
    report = moves.run_moves(
        cfg,
        source=FakeMoves(raw or live()),
        decisions=FakeDecisions(profile_data=profile),
        plans=FakePlans(),
        adapter=fake,
        advice=FakeAdvisor(),
        trigger=trigger,
        **kw,
    )
    return report, fake


# ---- Which moves need explaining ----


def test_only_moves_past_the_market_are_researched():
    day = moves.gather(live())
    by = {r["symbol"]: r for r in day["rows"]}
    assert day["market"]["pct"] == -0.84 and day["day"] == "2026-11-16" and day["trading"] is False
    assert set(by) == {"TICKA", "FUNDA", "TICKB"}
    assert (by["TICKA"]["pct"], by["TICKA"]["label"], by["TICKA"]["change_usd"]) == (-11.33, "due", -1105.0)
    assert by["FUNDA"]["label"] == "market" and by["TICKB"]["label"] == "small"
    assert [r["symbol"] for r in day["rows"]][0] == "TICKA"
    assert moves.label(-4.0, -3.5) == "market" and moves.label(-4.0, None) == "due" and moves.label(2.5, 0.0) == "small"


def test_open_session_is_intraday_and_a_weekend_is_not():
    assert moves.gather(live(state="open"))["trading"] is True
    weekend = live(state="closed", day="2026-11-14") | {"quote_day": "2026-11-13"}
    assert moves.gather(weekend)["day"] == "2026-11-13" and moves.gather(weekend)["trading"] is False


# ---- The run ----


def test_after_close_run_explains_the_big_move_with_the_plan(cfg):
    report, fake = go(cfg)
    assert report.status == "ok" and report.explained == ["TICKA"] and report.verdicts == {"TICKA": "overreaction"}
    assert len(fake.calls) == 1 and fake.calls[0]["desk"] == "moves" and fake.calls[0]["schema"]["title"] == "Why it moved"
    prompt = json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])
    assert prompt["holding"] == {"symbol": "TICKA", "name": "Ticka Space Inc", "move_pct": -11.33, "price": 26.6, "prev_close": 30.0}
    assert prompt["market"]["holding_beyond_market_pts"] == -10.49 and prompt["current_plan"]["steps"][0]["due"] == "2026-12-07"
    assert "full day" in prompt["session"]
    row = moves.saved(cfg, "2026-11-16")["TICKA"]
    body = json.loads(row["body"])
    assert row["status"] == "ok" and row["after_close"] == 1 and body["verdict"] == "overreaction"
    assert len(body["sources"]) == 1 and "about 4%." in body["why"]
    assert report.last == {"ready": "Explained TICKA overreaction"}
    again, fake = go(cfg)
    assert not fake.calls and again.note == "Every big move today already has its explanation." and "skipped" in again.last


def test_schedule_waits_for_the_close_but_an_ask_runs_intraday_and_redoes_after(cfg):
    report, fake = go(cfg, raw=live(state="open"))
    assert not fake.calls and "still open" in report.note
    report, fake = go(cfg, raw=live(state="open"), trigger="console")
    assert report.explained == ["TICKA"] and moves.saved(cfg, "2026-11-16")["TICKA"]["after_close"] == 0
    assert "so far today" in json.loads(fake.calls[0]["prompt"].split("\n\n", 1)[1])["session"]
    report, fake = go(cfg)
    assert report.explained == ["TICKA"] and moves.saved(cfg, "2026-11-16")["TICKA"]["after_close"] == 1
    _, fake = go(cfg)
    assert not fake.calls


def test_quiet_days_switched_off_and_not_ready(cfg):
    calm = live(rows=[("taxable", "FUNDA", 10, 99.0, 100.0)])
    report, fake = go(cfg, raw=calm)
    assert not fake.calls and report.note == moves.NOTHING
    report, fake = go(cfg, profile={"agents": {"desks": {"research": False}}})
    assert report.status == "disabled" and not fake.calls
    store.set_enabled(cfg, "moves", False)
    assert go(cfg)[0].status == "disabled"
    store.set_enabled(cfg, "moves", True)
    report = moves.run_moves(cfg, source=FakeMoves(ready=False), decisions=FakeDecisions(profile_data=ON), adapter=FakeAdapter())
    assert report.status == "not_ready"


def test_bad_answers_fail_and_retry_once(cfg):
    report, _ = go(cfg, answer=ANSWER | {"sources": []})
    assert report.failed == ["TICKA"] and moves.saved(cfg, "2026-11-16")["TICKA"]["note"] == "the answer cited no dated source"
    report, _ = go(cfg, answer=AgentError("boom"))
    assert report.failed == ["TICKA"]
    _, fake = go(cfg)
    assert not fake.calls
    assert moves.clean(ANSWER | {"verdict": "unclear", "sources": []})[0]["verdict"] == "unclear"
    assert moves.clean(ANSWER | {"verdict": "buy"})[1] == "the answer gave no verdict"
    assert moves.clean(ANSWER | {"why": ""})[1] == "the answer left out why"


def test_at_most_three_names_a_day_biggest_first(cfg):
    rows = [("taxable", s, 10, 100.0 - n, 100.0) for n, s in zip((5, 9, 7, 6), ("A", "B", "C", "D"), strict=True)]
    report, fake = go(cfg, raw=live(rows=rows, spy=(100.0, 100.0)))
    assert report.explained == ["B", "C", "D"] and len(fake.calls) == 3


# ---- Asking from the app ----


def test_ask_queues_once_and_the_minute_queue_runs_it(cfg, monkeypatch):
    src = FakeMoves(live(state="open"))
    monkeypatch.setattr(moves, "RealMoves", lambda: src)
    monkeypatch.setattr(moves, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    board = moves.view(cfg)
    assert board["can_ask"] is True and board["rows"][0]["status"] == "waiting" and board["next"]
    assert moves.ask(cfg)["status"] == "queued"
    board = moves.view(cfg)
    assert board["can_ask"] is False and board["ask"]["status"] == "queued"
    fake = FakeAdapter({"moves": ANSWER})
    report = moves.process_ask(cfg, adapter=fake, plans=FakePlans(), advice=FakeAdvisor())
    assert report.explained == ["TICKA"] and moves.last_ask(cfg, "2026-11-16")["status"] == "done"
    assert moves.process_ask(cfg, adapter=fake) is None
    board = moves.view(cfg)
    row = board["rows"][0]
    assert (row["status"], row["verdict"], row["after_close"]) == ("explained", "overreaction", False)
    assert row["detail"]["headline"].startswith("Fell") and board["explained"] == 1 and board["can_ask"] is False
    assert [r["status"] for r in board["rows"][1:]] == ["small", "market"]


def test_api_reads_and_asks(cfg, app_client, monkeypatch):
    src = FakeMoves(live(rows=[("taxable", "FUNDA", 10, 99.0, 100.0)]))
    monkeypatch.setattr(moves, "RealMoves", lambda: src)
    monkeypatch.setattr(moves, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    client = app_client(packages=["agents"])
    body = client.get("/api/agents/moves").json()
    assert body["due"] == 0 and body["rows"][0]["label"] == "market" and body["next"] is None
    refused = client.post("/api/agents/moves/ask")
    assert refused.status_code == 422 and refused.json()["detail"] == moves.NOTHING
    src.raw = live()
    assert client.post("/api/agents/moves/ask").json()["ask"]["status"] == "queued"
    monkeypatch.setattr(moves, "RealDecisions", lambda: FakeDecisions(profile_data={"agents": {"desks": {"research": False}}}))
    assert client.post("/api/agents/moves/ask").status_code == 409
    src.ready = False
    assert client.get("/api/agents/moves").json()["note"].startswith("Live prices not ready")


# ---- Job and CLI ----


def test_job_runs_after_the_close_on_weekdays(cfg, monkeypatch):
    mine = [j for j in JOBS if isinstance(j, dict) and j["name"] == "run-moves"]
    assert mine == [MOVES_JOB] and mine[0]["schedule"] == "25 16 * * 1-5"
    assert "agents-run-moves" in [j.name for j in package_jobs(["agents"])]
    seen = {}
    monkeypatch.setattr(cli.moves, "run_moves", lambda cfg, wait: seen.setdefault("r", moves.MoveReport("ok", "2026-11-16", note=moves.NOTHING)))
    assert cli.main(["moves"]) == 0 and seen["r"].last == {"skipped": moves.NOTHING}
