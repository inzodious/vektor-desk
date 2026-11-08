import json
from dataclasses import dataclass, field
from datetime import date

from desk.agents import __main__ as cli
from desk.agents import store, strategy
from desk.agents.adapter import FakeAdapter
from desk.agents.sources import NotReady
from tests.agents.agent_fakes import FakeDecisions
from tests.agents.test_strategy import SPEC

GRAMMAR = {"universe": {"fund_list": "...", "screen": "...", "small_caps": "point-in-time small caps"}, "sizing": "equal"}
PRICE = [{"metric_id": "ret", "kind": "price"}]
INSIDER = [{"metric_id": "insider.buyers", "kind": "insider"}, {"metric_id": "insider.buy_usd", "kind": "insider"}]
DRIFT = [{"metric_id": "earnings.surprise", "kind": "earnings"}, {"metric_id": "earnings.days_since", "kind": "earnings"}]
ON = {"agents": {"enabled": True, "desks": {"strategy": True}}}


@dataclass
class NightLab:
    feats: list = field(default_factory=lambda: PRICE + INSIDER + DRIFT)
    gram: dict = field(default_factory=lambda: GRAMMAR)
    rows: list = field(default_factory=list)
    ready: bool = True

    def grammar(self):
        if not self.ready:
            raise NotReady("lab not built")
        return self.gram

    def features(self, cfg):
        if not self.ready:
            raise NotReady("lab not built")
        return self.feats

    def desk_view(self, cfg, sid):
        return {}

    def pending_reviews(self, cfg):
        return []

    def eligible(self, cfg):
        return []

    def strategies(self, cfg):
        return self.rows


def spec(sid="insider-cluster-3in30", **over):
    return SPEC | {"id": sid, "universe": {"type": "small_caps"}, "signals": [{"metric_id": "insider.buyers", "window": "30d", "transform": "raw"}]} | over


def exp_answer(grid=None, budget=12, sid="insider-cluster-3in30"):
    exp = {"spec": spec(sid), "grid": grid or {"top_n": [5, 10]}, "date_range": {"start": "2016-01-01", "end": "2025-12-31"}, "seed": 3, "trial_budget": budget}
    return {"summary": "New insider variant.", "memo": "Testing clusters of three buyers.", "action": "experiment", "experiment": exp}


def night(cfg, lab=None, answer=None, day=date(2026, 11, 9)):
    fake = FakeAdapter({"strategy": answer or exp_answer()})
    report = strategy.run_nightly(cfg, lab=lab or NightLab(), decisions=FakeDecisions(profile_data=ON), adapter=fake, day=day)
    return report, fake


# ---- Family choice ----


def test_only_families_the_lab_can_express_are_picked():
    lab = NightLab()
    assert strategy.available("insider", lab.feats, GRAMMAR, []) and strategy.available("drift", lab.feats, GRAMMAR, [])
    assert not strategy.available("filings", lab.feats, GRAMMAR, [])
    assert not strategy.available("insider", PRICE, GRAMMAR, [])
    assert not strategy.available("insider", INSIDER, {"universe": {"screen": "..."}}, [])
    lane = [{"id": "lane-filings", "kind": "lane"}]
    assert strategy.available("filings", PRICE, GRAMMAR | {"universe": GRAMMAR["universe"] | {"lane": "..."}}, lane)


def test_rotation_alternates_between_available_families():
    picks = {strategy.pick_family(date(2026, 11, d), PRICE + INSIDER + DRIFT, GRAMMAR, []) for d in range(1, 5)}
    assert picks == {"insider", "drift"}
    assert strategy.pick_family(date(2026, 11, 1), PRICE + DRIFT, GRAMMAR, []) == "drift"
    assert strategy.pick_family(date(2026, 11, 1), PRICE, GRAMMAR, []) is None


def test_no_family_yet_skips_without_a_call(cfg):
    report, fake = night(cfg, lab=NightLab(feats=PRICE))
    assert report.status == "not_ready" and not fake.calls and "can't express" in report.note


def test_lab_not_ready(cfg):
    report, fake = night(cfg, lab=NightLab(ready=False))
    assert report.status == "not_ready" and not fake.calls


# ---- The run ----


def test_nightly_prompt_names_the_family_and_its_earlier_specs(cfg):
    rows = [
        {"id": "insider-cluster-2in14", "version": 2, "title": "Two buyers", "status": "lab", "hypothesis": "Two insiders in 14 days."},
        {"id": "drift-sue-top", "version": 1, "title": "Top surprise", "status": "lab", "hypothesis": "Biggest surprises drift."},
    ]
    day = next(date(2026, 11, d) for d in range(1, 9) if strategy.pick_family(date(2026, 11, d), PRICE + INSIDER + DRIFT, GRAMMAR, []) == "insider")
    report, fake = night(cfg, lab=NightLab(rows=rows), day=day)
    assert report.status == "ok" and report.queued is not None
    prompt = fake.calls[0]["prompt"]
    payload = json.loads(prompt.split("\n\n", 1)[1])
    assert payload["family"]["key"] == "insider" and payload["family"]["universe"] == "small_caps"
    assert [p["id"] for p in payload["family"]["prior"]] == ["insider-cluster-2in14"]
    assert "not a parameter sweep" in payload["question"] and '"insider-"' in payload["question"]
    assert store.runs(cfg, "strategy")[0]["trigger"] == "schedule"


def test_nightly_trial_budget_is_clamped(cfg):
    report, _ = night(cfg, answer=exp_answer(budget=150))
    body = json.loads(report.queued.read_text())
    assert body["trial_budget"] == strategy.NIGHTLY_TRIALS


def test_nightly_wide_grid_is_not_queued(cfg):
    report, _ = night(cfg, answer=exp_answer(grid={"top_n": [3, 5, 7, 10, 15], "window": [14, 30, 60, 90, 120]}))
    assert report.queued is None and "25 grid points" in report.note


def test_grid_points():
    assert strategy.grid_points(None) == 1
    assert strategy.grid_points({"a": [1, 2], "b": [1, 2, 3]}) == 6


def test_nightly_respects_the_weekly_cap_from_desk_yaml(cfg):
    profile = ON | {"usage": {"weekly_runs": {"strategy": 1}}}
    store.finish_run(cfg, store.start_run(cfg, "strategy", trigger="schedule", model="opus", effort="xhigh"), "ok")
    fake = FakeAdapter({"strategy": exp_answer()})
    report = strategy.run_nightly(cfg, lab=NightLab(), decisions=FakeDecisions(profile_data=profile), adapter=fake, day=date(2026, 11, 9))
    assert report.status == "over_budget" and not fake.calls


def test_console_runs_keep_the_full_trial_budget(cfg):
    fake = FakeAdapter({"strategy": exp_answer(budget=150, grid={"top_n": list(range(2, 30))})})
    report = strategy.run_strategy_desk(cfg, question="Try insider clusters", lab=NightLab(), decisions=FakeDecisions(profile_data=ON), adapter=fake)
    assert json.loads(report.queued.read_text())["trial_budget"] == 150


# ---- CLI ----


def test_cli_run_strategy_is_the_nightly_variant(cfg, monkeypatch, capsys):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(strategy, "RealLab", NightLab)
    monkeypatch.setattr(strategy, "RealDecisions", lambda: FakeDecisions(profile_data=ON))
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", lambda: FakeAdapter({"strategy": exp_answer()}))
    assert cli.main(["run", "strategy"]) == 0
    assert "Strategy desk: ok. Queued" in capsys.readouterr().out


def test_cli_dry_run_strategy_schedule_shows_the_nightly_prompt(cfg, monkeypatch, capsys):
    class NoCli:
        def run(self, *a, **k):
            raise AssertionError("dry-run must not call claude")

    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.setattr(cli, "RealLab", NightLab)
    monkeypatch.setattr("desk.agents.runner.ClaudeCli", NoCli)
    assert cli.main(["dry-run", "strategy", "--trigger", "schedule"]) == 0
    out = capsys.readouterr().out
    assert "nightly family" in out and "Nightly variant" in out and "small_caps" in out
