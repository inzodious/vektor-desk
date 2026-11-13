from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

from desk.agents import alerts, limits, store
from desk.agents.adapter import Adapter, AgentError, AgentResult, AgentTimeout, ClaudeCli, UsageLimitError
from desk.agents.desks import DESKS, Desk
from desk.config import Config
from desk.runlock import Busy, job_lock

LOCK = "agents"
FIRST_RUN = store.GUARD_UNTIL
UNGUARDED = (*FIRST_RUN, "debrief", "plans")
CAPPED = ("schedule", "trigger", "retry", "lab")
GUARD_NOTE = "First-run guard: the other desks start once the Plan keeper and the Tax desk have each finished a run. It lifts itself then."


@dataclass
class Outcome:
    status: str
    run_id: int
    result: AgentResult | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _usage(result: AgentResult) -> dict:
    keep = ("turns", "input_tokens", "output_tokens", "cache_tokens", "duration_ms", "cost_estimate")
    return {k: v for k, v in asdict(result).items() if k in keep}


def run_desk(
    desk: Desk,
    system: str,
    prompt: str,
    *,
    cfg: Config,
    schema: dict | None = None,
    adapter: Adapter | None = None,
    trigger: str = "schedule",
    wait: float = 0.0,
    capped: bool = True,
) -> Outcome:
    def skip(status: str, note: str) -> Outcome:
        return Outcome(status, store.start_run(cfg, desk.name, trigger=trigger, model=desk.model, effort=desk.effort, status=status, note=note), note=note)

    if not store.is_enabled(cfg, desk.name):
        return skip("disabled", "Switched off in Settings.")
    if desk.name in DESKS and desk.name not in UNGUARDED and store.guard_on(cfg):
        return skip("guarded", GUARD_NOTE)
    if capped and trigger in CAPPED and store.week_usage(cfg, desk.name)["runs"] >= desk.weekly_runs:
        return skip("over_budget", f"Weekly cap of {desk.weekly_runs} runs reached.")
    held = limits.paused_until(cfg) if trigger in CAPPED else None
    if held:
        now = limits.clock_now()
        until = limits.clock(held, now, ZoneInfo(cfg.timezone)).removeprefix("at ").removeprefix("on ")
        note = f"Claude's limit is used up until {until}, so this run waits. {limits.plan(cfg, desk.name, trigger, held, now=now)}".strip()
        return skip("deferred", note)
    adapter = adapter or ClaudeCli()
    try:
        with job_lock(LOCK, wait=wait, cfg=cfg):
            run_id = store.start_run(cfg, desk.name, trigger=trigger, model=desk.model, effort=desk.effort)
            try:
                result = adapter.run(desk, system, prompt, schema)
            except UsageLimitError as e:
                note = f"{e} {limits.plan(cfg, desk.name, trigger, limits.saw_limit(cfg, str(e), run_id), run_id)}".strip()
                store.finish_run(cfg, run_id, "deferred", note=note)
                return Outcome("deferred", run_id, note=note)
            except AgentTimeout as e:
                store.finish_run(cfg, run_id, "timeout", note=str(e))
                alerts.run_failed(cfg, desk.name, "timeout", run_id, str(e))
                return Outcome("timeout", run_id, note=str(e))
            except AgentError as e:
                store.finish_run(cfg, run_id, "failed", note=str(e))
                alerts.run_failed(cfg, desk.name, "failed", run_id, str(e))
                return Outcome("failed", run_id, note=str(e))
            if schema is not None and result.structured is None:
                note = "No structured answer came back."
                store.finish_run(cfg, run_id, "failed", usage=_usage(result), note=note)
                alerts.run_failed(cfg, desk.name, "failed", run_id, note)
                return Outcome("failed", run_id, result, note)
            store.finish_run(cfg, run_id, "ok", usage=_usage(result))
            return Outcome("ok", run_id, result)
    except Busy:
        return skip("busy", "Another desk or a heavy engine job was running.")
