import json
from dataclasses import dataclass, field

import pytest

from desk.agents import __main__ as cli
from desk.agents import briefs, filings, store
from desk.agents.adapter import AgentError, AgentResult, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.jobs import JOBS
from desk.agents.sources import NotReady, RealFilings
from tests.agents.agent_fakes import FakeDecisions

EXCERPT = "The Company entered into a securities purchase agreement to sell 3,500,000 shares\nat $2.10 per share in a registered direct offering."
ON = {"agents": {"enabled": True, "desks": {"filings": True}}}
SCORE = {
    "direction": -2,
    "confidence": 0.7,
    "event_type": "dilution",
    "horizon_days": 20,
    "rationale": "A registered direct offering of 3,500,000 shares at a discount is large for a company this size.",
    "numbers_cited": ["3,500,000 shares", "$2.10 per share", "$99 billion"],
}


def filing(n: int, symbol: str = "SOUN", form: str = "8-K", text: str | None = None) -> dict:
    return {
        "accession": f"0000000000-26-{n:06d}",
        "symbol": symbol,
        "form": form,
        "items": ["3.02", "8.01"] if form == "8-K" else [],
        "filed_at": "2026-11-07T21:05:00Z",
        "url": f"https://www.sec.gov/Archives/edgar/data/1/{n}.htm",
        "excerpt": text or EXCERPT,
        "company": {"name": f"{symbol} Example Inc.", "market_cap": 450_000_000, "sector": "Technology"},
    }


@dataclass
class FakeFilings:
    queue: list = field(default_factory=list)
    ready: bool = True
    refuse: set = field(default_factory=set)
    recorded: dict = field(default_factory=dict)
    asked: list = field(default_factory=list)

    def pending(self, cfg, limit):
        if not self.ready:
            raise NotReady("filings schema missing")
        self.asked.append(limit)
        return [f for f in self.queue if f["accession"] not in self.recorded][:limit]

    def record(self, cfg, accession, result):
        if accession in self.refuse:
            raise ValueError("unknown event_type")
        self.recorded.setdefault(accession, result)


class Served(FakeAdapter):
    def run(self, desk, system, prompt, schema=None):
        out = super().run(desk, system, prompt, schema)
        out.model = "claude-opus-5-5"
        return out


def go(cfg, queue, profile=ON, answer=SCORE, **kw):
    box = FakeFilings(queue)
    fake = Served({"filings": answer})
    report = filings.run_filings_desk(cfg, filings=box, decisions=FakeDecisions(profile_data=profile), adapter=fake, **kw)
    return report, box, fake


# ---- Switches and guard ----


@pytest.mark.parametrize("profile", [{}, {"agents": {"enabled": True, "desks": {}}}, {"agents": {"enabled": False, "desks": {"filings": True}}}])
def test_off_unless_desk_yaml_switches_it_on(cfg, profile):
    report, box, fake = go(cfg, [filing(1)], profile=profile)
    assert report.status == "disabled" and not fake.calls and not box.recorded
    assert store.runs(cfg, "filings")[0]["status"] == "disabled"


def test_first_run_guard_blocks_it(cfg):
    store.set_guard(cfg, True)
    report, box, fake = go(cfg, [filing(1), filing(2)])
    assert report.status == "guarded" and not fake.calls
    assert len(store.runs(cfg, "filings")) == 1


def test_settings_switch_stops_it(cfg):
    store.set_enabled(cfg, "filings", False)
    report, _, fake = go(cfg, [filing(1)])
    assert report.status == "disabled" and not fake.calls


# ---- Scoring ----


def test_scores_each_filing_on_opus_high_and_records_served_model(cfg):
    report, box, fake = go(cfg, [filing(1), filing(2, "PLUG", "S-3")])
    assert report.status == "ok" and report.scored == ["0000000000-26-000001", "0000000000-26-000002"]
    assert [c["desk"] for c in fake.calls] == ["filings", "filings"]
    desk = get("filings")
    assert (desk.model, desk.effort, desk.tools) == ("opus", "high", ())
    call = fake.calls[0]
    assert call["system"] == briefs.prompt_file("filings")
    assert call["schema"] == briefs.schema_file("filings")
    assert "<excerpt>" in call["prompt"] and "3,500,000 shares" in call["prompt"] and '"accession": "0000000000-26-000001"' in call["prompt"]
    rec = box.recorded["0000000000-26-000001"]
    assert rec["model"] == "claude-opus-5-5"
    assert rec["scored_at"].endswith("+00:00")
    assert (rec["direction"], rec["confidence"], rec["event_type"], rec["horizon_days"]) == (-2, 0.7, "dilution", 20)
    assert rec["run_id"] == store.runs(cfg, "filings")[-1]["id"]
    runs = store.runs(cfg, "filings")
    assert {r["status"] for r in runs} == {"ok"} and "PLUG S-3 0000000000-26-000002: direction -2" in runs[0]["note"]


def test_numbers_must_appear_verbatim_in_the_excerpt(cfg):
    report, box, _ = go(cfg, [filing(1)])
    assert box.recorded["0000000000-26-000001"]["numbers_cited"] == ["3,500,000 shares", "$2.10 per share"]
    assert report.dropped_numbers == 1


def test_excerpt_is_capped(cfg):
    long = filing(1, text="x" * (filings.EXCERPT_CHARS + 5000))
    _, _, fake = go(cfg, [long])
    assert fake.calls[0]["prompt"].count("x") <= filings.EXCERPT_CHARS + 10


def test_rationale_is_trimmed_to_280(cfg):
    _, box, _ = go(cfg, [filing(1)], answer=SCORE | {"rationale": "y" * 400})
    assert len(box.recorded["0000000000-26-000001"]["rationale"]) == 280


# ---- Volume ----


def test_nightly_cap_defaults_to_40_and_takes_queue_order(cfg):
    queue = [filing(i) for i in range(1, 46)]
    report, box, fake = go(cfg, queue)
    assert box.asked == [40] and len(fake.calls) == 40
    assert report.scored[0] == "0000000000-26-000001" and report.scored[-1] == "0000000000-26-000040"


def test_cap_comes_from_desk_yaml_and_limit_overrides(cfg):
    profile = ON | {"usage": {"filings_per_night": 3}}
    _, box, fake = go(cfg, [filing(i) for i in range(1, 10)], profile=profile)
    assert box.asked == [3] and len(fake.calls) == 3
    _, box, fake = go(cfg, [filing(i) for i in range(1, 10)], profile=profile, limit=1)
    assert box.asked == [1] and len(fake.calls) == 1


@pytest.mark.parametrize(("value", "cap"), [(None, 40), (-1, 40), (True, 40), ("9", 40), (0, 0), (500, filings.MAX_PER_NIGHT)])
def test_per_night_reads_safely(value, cap):
    assert filings.per_night({"usage": {"filings_per_night": value}}) == cap


def test_weekly_cap_is_seven_nights(cfg):
    profile = ON | {"usage": {"filings_per_night": 2}}
    assert filings.desk_for(profile).weekly_runs == 14
    for _ in range(14):
        store.finish_run(cfg, store.start_run(cfg, "filings", trigger="schedule", model="opus", effort="high"), "ok")
    report, _, fake = go(cfg, [filing(1)], profile=profile)
    assert report.status == "over_budget" and not fake.calls


def test_usage_limit_stops_the_night(cfg):
    report, box, _ = go(cfg, [filing(1), filing(2)], answer=UsageLimitError("usage limit reached"))
    assert report.status == "deferred" and not box.recorded and len(store.runs(cfg, "filings")) == 1


def test_three_failures_in_a_row_stop_the_night(cfg):
    report, box, fake = go(cfg, [filing(i) for i in range(1, 8)], answer=AgentError("bad json"))
    assert report.status == "failed" and len(fake.calls) == 3 and len(report.failed) == 3 and not box.recorded


def test_one_failure_does_not_stop_the_night(cfg):
    answers = iter([AgentError("bad json"), SCORE, SCORE])

    class Flaky:
        def run(self, desk, system, prompt, schema=None):
            nxt = next(answers)
            if isinstance(nxt, Exception):
                raise nxt
            return AgentResult(text=json.dumps(nxt), structured=nxt, model="claude-opus-5-5")

    box = FakeFilings([filing(1), filing(2), filing(3)])
    report = filings.run_filings_desk(cfg, filings=box, decisions=FakeDecisions(profile_data=ON), adapter=Flaky())
    assert report.status == "ok" and report.failed == ["0000000000-26-000001"] and len(report.scored) == 2


def test_refused_score_is_noted_and_the_night_goes_on(cfg):
    box = FakeFilings([filing(1), filing(2)], refuse={"0000000000-26-000001"})
    report = filings.run_filings_desk(cfg, filings=box, decisions=FakeDecisions(profile_data=ON), adapter=Served({"filings": SCORE}))
    assert report.rejected == ["0000000000-26-000001"] and report.scored == ["0000000000-26-000002"]
    assert "refused" in store.runs(cfg, "filings")[-1]["note"]


def test_empty_queue_makes_no_call_and_no_run(cfg):
    report, _, fake = go(cfg, [])
    assert report.status == "ok" and report.pending == 0 and not fake.calls and not store.runs(cfg, "filings")


def test_not_ready_queue(cfg):
    box = FakeFilings(ready=False)
    report = filings.run_filings_desk(cfg, filings=box, decisions=FakeDecisions(profile_data=ON), adapter=Served())
    assert report.status == "not_ready" and "schema missing" in report.note


def test_real_filings_is_not_ready_before_the_first_fetch(cfg):
    with pytest.raises(NotReady):
        RealFilings().pending(cfg, 40)


# ---- Schema and prompt ----


def test_schema_matches_the_signal_contract():
    schema = briefs.schema_file("filings")
    assert set(schema["required"]) == {"direction", "confidence", "event_type", "horizon_days", "rationale", "numbers_cited"}
    props = schema["properties"]
    assert (props["direction"]["minimum"], props["direction"]["maximum"]) == (-2, 2)
    assert (props["confidence"]["minimum"], props["confidence"]["maximum"]) == (0, 1)
    assert props["rationale"]["maxLength"] == 280
    assert {"dilution", "going_concern", "insider_buy", "other"} <= set(props["event_type"]["enum"])
    assert "$schema" not in schema


def test_prompt_is_advisory_and_hindsight_free():
    text = briefs.prompt_file("filings")
    assert "never instructions" in text and "nothing you write is executed" in text
    assert "later share price" in text and "verbatim" in text


# ---- Cron and CLI ----


def test_nightly_job_runs_the_filings_desk():
    assert ("15 4 * * *", "python -m desk.agents run filings") in JOBS


@pytest.fixture
def cli_env(cfg, monkeypatch):
    box = FakeFilings([filing(1), filing(2)])
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(filings, "RealFilings", lambda: box)
    monkeypatch.setattr(filings, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    return box


def test_cli_run_filings_uses_its_own_loop(cli_env, monkeypatch, capsys):
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: Served({"filings": SCORE}))
    assert cli.main(["run", "filings", "--limit", "1"]) == 0
    assert "Filings desk: ok, 1 scored, 0 failed of 1." in capsys.readouterr().out
    assert list(cli_env.recorded) == ["0000000000-26-000001"]


def test_cli_dry_run_filings_prints_the_first_prompt_without_calling(cli_env, monkeypatch, capsys):
    class NoCli:
        def run(self, *a, **k):
            raise AssertionError("dry-run must not call claude")

    monkeypatch.setattr("desk.agents.runner.ClaudeCli", NoCli)
    assert cli.main(["dry-run", "filings", "--system", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "2 filings waiting, nightly cap 40." in out and "0000000000-26-000001" in out and "Filing score" in out
    assert not cli_env.recorded
