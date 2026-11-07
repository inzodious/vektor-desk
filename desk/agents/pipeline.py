import json
from dataclasses import dataclass, field, replace

from desk.agents import briefs, store
from desk.agents.adapter import Adapter
from desk.agents.desks import get
from desk.agents.runner import Outcome, run_desk
from desk.agents.sources import Decisions, Engine, NotReady, RealDecisions, RealEngine
from desk.config import Config

SKIP_UNCHANGED = {"plan_keeper"}


@dataclass
class Report:
    outcome: Outcome
    summary: str = ""
    created: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    note: str | None = None

    @property
    def status(self) -> str:
        return self.outcome.status


def _log_skip(cfg: Config, name: str, status: str, note: str, trigger: str) -> Report:
    desk = get(name)
    run_id = store.start_run(cfg, name, trigger=trigger, model=desk.model, effort=desk.effort, status=status, note=note)
    return Report(Outcome(status, run_id, note=note), note=note)


def _profile(cfg: Config, decisions: Decisions) -> tuple[str, dict]:
    try:
        return decisions.profile(cfg)
    except NotReady:
        return "none", {}


def run_proposal_desk(
    cfg: Config,
    name: str,
    *,
    engine: Engine | None = None,
    decisions: Decisions | None = None,
    adapter: Adapter | None = None,
    trigger: str = "schedule",
    wait: float = 0.0,
) -> Report:
    engine = engine or RealEngine()
    decisions = decisions or RealDecisions()
    desk = get(name)
    version, profile = _profile(cfg, decisions)
    agents = profile.get("agents") or {}
    if agents.get("enabled", True) is False or (agents.get("desks") or {}).get(name, True) is False:
        return _log_skip(cfg, name, "disabled", "Switched off in desk.yaml.", trigger)
    cap = ((profile.get("usage") or {}).get("weekly_runs") or {}).get(name)
    if isinstance(cap, int):
        desk = replace(desk, weekly_runs=cap)
    try:
        slice_ = engine.desk_slice(cfg, name)
    except NotReady as e:
        return _log_skip(cfg, name, "not_ready", f"Engine brief not ready: {e}", trigger)
    digest = briefs.digest(slice_)
    if name in SKIP_UNCHANGED and trigger == "schedule" and store.last_digest(cfg, name) == digest:
        return _log_skip(cfg, name, "unchanged", "Nothing in the brief changed since the last run.", trigger)
    try:
        history = decisions.history(cfg, name, briefs.HISTORY_LIMIT)
    except NotReady:
        history = []
    prompt = briefs.build_prompt(name, slice_, {"version": version} | profile, history)
    outcome = run_desk(desk, briefs.system_prompt(name), prompt, cfg=cfg, schema=briefs.schema_file("proposal"), adapter=adapter, trigger=trigger, wait=wait)
    if not outcome.ok:
        return Report(outcome, note=outcome.note)
    answer = outcome.result.structured or {}
    summary = str(answer.get("summary") or "")
    proposals = [p for p in answer.get("proposals") or () if isinstance(p, dict)]
    store.save_brief(cfg, outcome.run_id, name, slice_.get("as_of"), digest, version, summary, json.dumps(answer, sort_keys=True))
    report = Report(outcome, summary)
    idx = briefs.index(slice_)
    run_id = str(outcome.run_id)
    try:
        for p in proposals:
            problems = briefs.number_problems(p, idx)
            if problems:
                report.rejected.append(decisions.reject(cfg, p, name, "Numbers don't match the brief: " + "; ".join(problems), run_id))
            else:
                report.created.append(decisions.create(cfg, p, name, run_id))
    except NotReady as e:
        report.note = f"Decision records not built yet ({e}); {len(proposals)} proposals kept in the run log."
    return report
