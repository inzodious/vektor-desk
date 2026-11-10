import json
from dataclasses import dataclass, field

from desk.agents import advisor, briefs
from desk.agents.adapter import FakeAdapter
from desk.agents.pipeline import prepare, run_proposal_desk
from desk.agents.sources import NotReady
from tests.agents.agent_fakes import SLICE, FakeDecisions, FakeEngine, answer, proposal

RISK = {
    "version": 2,
    "band": 4,
    "label": "Growth",
    "equity_min_pct": 70,
    "equity_max_pct": 95,
    "speculative_max_pct": 15,
    "single_stock_max_pct": 10,
    "worst_year_loss_pct": 35,
    "limited_by": "capacity",
    "tolerance_band": 5,
    "capacity_band": 4,
    "answered_at": "2026-11-08T12:00:00Z",
}
CATALOG = [
    {"id": "safe-mix", "name": "Safe mix", "risk_rank": 2, "fit": "fits", "worst_year_p10_pct": -22.5, "chance_fi": 0.61, "proxy_note": "FXAIX as IVV"},
    {"id": "tech-tilt", "name": "Aggressive tech tilt", "risk_rank": 5, "fit": "above", "worst_year_p10_pct": -41.0, "chance_fi": 0.68},
]


@dataclass
class FakeAdvisor:
    risk_row: dict | None = field(default_factory=lambda: RISK)
    rows: list = field(default_factory=lambda: CATALOG)
    held: list = field(default_factory=lambda: [{"symbol": "TICKA", "band_min": 5, "band_max": 12}])
    lines: list = field(default_factory=lambda: ["Sell 10 TICKA. Window 2026-12-07 to 2026-12-15 (upcoming)."])
    broken: set = field(default_factory=set)

    def _maybe(self, name, value):
        if name in self.broken:
            raise NotReady(f"{name} isn't built yet")
        return value

    def risk(self, cfg):
        return self._maybe("risk_profile", self.risk_row)

    def catalog(self, cfg):
        return self._maybe("catalog", self.rows)

    def convictions(self, cfg):
        return self._maybe("convictions", self.held)

    def actions(self, cfg):
        return self._maybe("planned_actions", self.lines)


def test_gather_tolerates_missing_pieces(cfg):
    view = advisor.gather(cfg, FakeAdvisor(broken={"catalog", "convictions", "planned_actions"}, risk_row=None))
    assert view["risk_profile"] is None and view["catalog"] == []
    assert set(view["missing"]) == {"risk_profile", "catalog", "convictions", "planned_actions"}


def test_real_advisor_is_not_ready_without_the_modules(cfg):
    view = advisor.gather(cfg)
    assert view["risk_profile"] is None and "catalog" in view["missing"]


def test_risk_and_catalog_numbers_become_brief_keys(cfg):
    view = advisor.gather(cfg, FakeAdvisor())
    idx = briefs.index(advisor.attach(SLICE, view))
    assert idx["risk.equity_max_pct:all:now"] == 95 and idx["risk.band:all:now"] == 4
    assert idx["catalog.worst_year_p10_pct:tech-tilt:now"] == -41.0
    assert "catalog.sharpe:safe-mix:now" not in idx
    assert "advisor" not in SLICE["sections"]


def test_plan_keeper_prompt_carries_band_catalog_and_actions(cfg):
    prep = prepare(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(), advice=FakeAdvisor())
    payload = json.loads(prep.prompt.split("\n\n", 1)[1])
    assert payload["advisor"]["risk_band"] == {
        "band": 4,
        "label": "Growth",
        "limited_by": "capacity",
        "tolerance_band": 5,
        "capacity_band": 4,
        "version": 2,
        "answered_at": "2026-11-08T12:00:00Z",
    }
    assert [c["fit"] for c in payload["advisor"]["catalog"]] == ["fits", "above"]
    assert payload["advisor"]["planned_actions"][0].startswith("Sell 10 TICKA")
    assert any(i["key"] == "risk.single_stock_max_pct:all:now" for i in payload["brief"]["sections"]["advisor"])


def test_skeptic_and_strategy_get_no_advisor_block(cfg):
    prep = prepare(cfg, "skeptic", engine=FakeEngine(SLICE), decisions=FakeDecisions(), advice=FakeAdvisor())
    assert "advisor" not in json.loads(prep.prompt.split("\n\n", 1)[1])


def test_proposals_may_cite_band_numbers(cfg):
    p = proposal(numbers_used=[{"field": "risk.equity_max_pct:all:now", "value": 95}, {"field": "cash.ready:all:now", "value": 1500}])
    decisions = FakeDecisions()
    report = run_proposal_desk(
        cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=decisions, adapter=FakeAdapter({"plan_keeper": answer(p)}), advice=FakeAdvisor()
    )
    assert report.status == "ok" and len(decisions.created) == 1 and not decisions.rejected


def test_band_change_counts_as_a_brief_change(cfg):
    a = prepare(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(), advice=FakeAdvisor())
    b = prepare(cfg, "plan_keeper", engine=FakeEngine(SLICE), decisions=FakeDecisions(), advice=FakeAdvisor(risk_row=RISK | {"band": 3}))
    assert a.digest != b.digest


def test_prompts_drop_v3_as_the_target():
    common = briefs.prompt_file("common")
    assert "no single target plan" in common and "suggestion only" in common and "plan-mix baseline" not in common
    assert "risk band" in briefs.prompt_file("plan_keeper") and "not as the target" in briefs.prompt_file("plan_keeper")
    assert "plan-mix" not in briefs.prompt_file("skeptic")


def test_module_not_ready_is_translated(cfg, monkeypatch):
    import sys
    import types

    from desk.agents.sources import RealAdvisor

    fake = types.ModuleType("desk.engine.bands")

    class BandsNotReady(RuntimeError):
        pass

    def catalog(cfg):
        raise BandsNotReady("bands not built")

    fake.NotReady, fake.catalog = BandsNotReady, catalog
    monkeypatch.setitem(sys.modules, "desk.engine.bands", fake)
    view = advisor.gather(cfg, RealAdvisor())
    assert "catalog" in view["missing"] and view["catalog"] == []
