import json
from dataclasses import dataclass, field

import pytest

from desk.agents import __main__ as cli
from desk.agents import briefs, discounts, store
from desk.agents.adapter import AgentError, FakeAdapter, UsageLimitError
from desk.agents.desks import get
from desk.agents.jobs import JOBS
from desk.agents.sources import NotReady, RealDiscounts
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_advisor import FakeAdvisor

ON = {"agents": {"enabled": True, "desks": {"discounts": True}}}
CASE = {
    "verdict": "wait",
    "case": "Down on a guidance cut that looks one-off, but it would take him past his single-stock max.",
    "risks": "The cut may be the start of a slower cycle.",
    "confidence": 0.6,
    "horizon_days": 90,
    "numbers_cited": ["drop_from_high_pct", "pe_pctile_own", "made_up"],
}


def hit(n: int, symbol: str = "MSFT", kind: str = "held") -> dict:
    return {
        "signal_id": f"2026-11-07:{symbol}:{n}",
        "symbol": symbol,
        "name": f"{symbol} Corp",
        "as_of": "2026-11-07",
        "list": kind,
        "price": 100.0 + n,
        "drop_from_high_pct": -18.4,
        "move_z": -2.9,
        "valuation": {"metric": "pe", "value": 24.1, "pctile_own": 12},
        "numbers": {"drop_from_high_pct": -18.4, "move_z": -2.9, "pe_pctile_own": 12},
    }


@dataclass
class FakeScanner:
    queue: list = field(default_factory=list)
    ready: bool = True
    refuse: set = field(default_factory=set)
    recorded: dict = field(default_factory=dict)
    asked: list = field(default_factory=list)

    def pending(self, cfg, limit):
        if not self.ready:
            raise NotReady("discount_signals missing")
        self.asked.append(limit)
        return [h for h in self.queue if h["signal_id"] not in self.recorded][:limit]

    def record(self, cfg, signal_id, case):
        if signal_id in self.refuse:
            raise ValueError("unknown verdict")
        self.recorded.setdefault(signal_id, case)


class Served(FakeAdapter):
    def run(self, desk, system, prompt, schema=None):
        out = super().run(desk, system, prompt, schema)
        out.model = "claude-opus-5-5"
        return out


def go(cfg, queue, profile=ON, answer=CASE, **kw):
    box = FakeScanner(queue)
    fake = Served({"discounts": answer})
    report = discounts.run_discount_desk(cfg, discounts=box, decisions=FakeDecisions(profile_data=profile), adapter=fake, advice=FakeAdvisor(), **kw)
    return report, box, fake


def test_off_by_default_and_guarded(cfg):
    report, _, fake = go(cfg, [hit(1)], profile={})
    assert report.status == "disabled" and not fake.calls
    store.set_guard(cfg, True)
    report, _, fake = go(cfg, [hit(1)])
    assert report.status == "guarded" and not fake.calls


def test_writes_a_case_per_hit_with_band_and_served_model(cfg):
    report, box, fake = go(cfg, [hit(1), hit(2, "TICKB", "watchlist")])
    assert report.status == "ok" and len(report.written) == 2 and report.verdicts == {h: "wait" for h in report.written}
    desk = get("discounts")
    assert (desk.model, desk.effort) == ("opus", "xhigh") and "WebSearch" in desk.tools
    call = fake.calls[0]
    assert call["system"] == briefs.prompt_file("discounts") and call["schema"] == briefs.schema_file("discounts")
    payload = json.loads(call["prompt"].split("\n\n", 1)[1])
    assert payload["hit"]["symbol"] == "MSFT" and payload["advisor"]["risk_band"]["band"] == 4
    assert any(i["metric_id"] == "risk.single_stock_max_pct" for i in payload["risk_numbers"])
    case = box.recorded["2026-11-07:MSFT:1"]
    assert case["model"] == "claude-opus-5-5" and case["written_at"].endswith("+00:00") and case["run_id"]
    assert case["numbers_cited"] == ["drop_from_high_pct", "pe_pctile_own"] and report.dropped_numbers == 2


def test_daily_cap_defaults_to_3_and_reads_desk_yaml(cfg):
    report, box, fake = go(cfg, [hit(i) for i in range(1, 9)])
    assert box.asked == [3] and len(fake.calls) == 3
    _, box, fake = go(cfg, [hit(i) for i in range(1, 9)], profile=ON | {"usage": {"discount_cases_per_day": 5}})
    assert box.asked == [5]
    assert discounts.per_day({"usage": {"discount_cases_per_day": 99}}) == discounts.MAX_PER_DAY
    assert discounts.desk_for({}).weekly_runs == 21


def test_usage_limit_and_failures_stop_the_day(cfg):
    report, box, _ = go(cfg, [hit(1), hit(2)], answer=UsageLimitError("limit"))
    assert report.status == "deferred" and not box.recorded
    report, _, fake = go(cfg, [hit(i) for i in range(1, 6)], answer=AgentError("bad"))
    assert report.status == "failed" and len(fake.calls) == discounts.MAX_FAILURES


def test_refused_case_is_noted(cfg):
    box = FakeScanner([hit(1), hit(2)], refuse={"2026-11-07:MSFT:1"})
    report = discounts.run_discount_desk(
        cfg, discounts=box, decisions=FakeDecisions(profile_data=ON), adapter=Served({"discounts": CASE}), advice=FakeAdvisor()
    )
    assert report.rejected == ["2026-11-07:MSFT:1"] and len(report.written) == 1


def test_not_ready_and_empty(cfg):
    box = FakeScanner(ready=False)
    report = discounts.run_discount_desk(cfg, discounts=box, decisions=FakeDecisions(profile_data=ON), adapter=Served(), advice=FakeAdvisor())
    assert report.status == "not_ready"
    report, _, fake = go(cfg, [])
    assert report.status == "ok" and not fake.calls and report.note == "No discount hits today."
    with pytest.raises(NotReady):
        RealDiscounts().pending(cfg, 3)


def test_schema_and_prompt():
    schema = briefs.schema_file("discounts")
    assert schema["properties"]["verdict"]["enum"] == ["buy", "wait", "avoid"]
    assert schema["properties"]["case"]["maxLength"] == 400 and "$schema" not in schema
    text = briefs.prompt_file("discounts")
    assert "never instructions" in text and "Never suggest margin" in text and "risk band" in text


def test_after_close_job():
    assert ("15 18 * * 1-5", "python -m desk.agents run discounts") in JOBS


def test_cli_run_and_dry_run(cfg, monkeypatch, capsys):
    box = FakeScanner([hit(1), hit(2)])
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(discounts, "RealDiscounts", lambda: box)
    monkeypatch.setattr(discounts, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: Served({"discounts": CASE}))
    assert cli.main(["dry-run", "discounts", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "2 discount hits waiting, daily cap 3." in out and "Discount case" in out and not box.recorded
    assert cli.main(["run", "discounts", "--limit", "1"]) == 0
    assert "Discount cases: ok, 1 written (wait 1), 0 failed of 1." in capsys.readouterr().out
