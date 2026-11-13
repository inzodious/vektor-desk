from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
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
SCHEDULED = ("schedule", "retry")
WEEK = timedelta(days=7)
SLACK = timedelta(hours=6)
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


# ---- Weekly room ----


def room(cfg: Config, desk: Desk, trigger: str, now: datetime | None = None) -> dict:
    now = now or limits.clock_now()
    lane, cap, span = None, desk.weekly_runs, WEEK
    if desk.kept:
        lane, cap, span = ("scheduled", desk.kept, WEEK - SLACK) if trigger in SCHEDULED else ("asked", max(desk.weekly_runs - desk.kept, 0), WEEK)
    starts = store.counted_starts(cfg, desk.name, now - span, lane)
    over = len(starts) >= cap
    frees = starts[len(starts) - cap] + span if over and cap > 0 else None
    return {"lane": lane, "runs": len(starts), "cap": cap, "over": over, "frees_at": frees, "now": now}


def free_words(cfg: Config, left: dict) -> str:
    if left["frees_at"] is None:
        return ""
    return f"The next one is free {limits.clock(left['frees_at'], left['now'], ZoneInfo(cfg.timezone))}."


def used_words(left: dict) -> str:
    many, extra = left["cap"] != 1, " extra" if left["lane"] == "asked" else ""
    return f"This week's {left['cap']}{extra} runs are used." if many else f"This week's{extra} run is used."


def refusal(cfg: Config, left: dict) -> str:
    said = {
        None: f"Weekly cap of {left['cap']} runs reached.",
        "scheduled": "This week's scheduled check has already run.",
        "asked": f"{used_words(left)} One run is kept for the scheduled check.",
    }[left["lane"]]
    return f"{said} {free_words(cfg, left)}".strip()


# ---- One run ----


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
    if capped and trigger in CAPPED:
        left = room(cfg, desk, trigger)
        if left["over"]:
            return skip("over_budget", refusal(cfg, left))
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
