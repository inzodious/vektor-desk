from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.agents import limits, portfolio, store, switches
from desk.agents.desks import DESKS, Desk
from desk.agents.pipeline import ONCE_A_DAY
from desk.agents.runner import FIRST_RUN, UNGUARDED
from desk.agents.sources import Decisions, NotReady, PlanFacts, RealDecisions, RealPlanFacts
from desk.config import Config
from desk.runlock import running
from desk.scheduler import parse

HORIZON_DAYS = 35


def next_run(desk: Desk, now: datetime, zone: ZoneInfo) -> str | None:
    if not desk.schedules:
        return None
    jobs = parse("\n".join(f"{s} true" for s in desk.schedules))
    t = now.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = t + timedelta(days=HORIZON_DAYS)
    while t < end:
        if desk.due_on(t.date()) and any(j.due(t) for j in jobs):
            return t.isoformat()
        t += timedelta(minutes=1)
    return None


def _last(run: dict | None) -> dict | None:
    if run is None:
        return None
    keys = ("status", "trigger", "started_at", "finished_at", "turns", "duration_ms", "note")
    return {k: run[k] for k in keys} | {"tokens": run["input_tokens"] + run["output_tokens"] + run["cache_tokens"]}


def _profile(cfg: Config, decisions: Decisions | None) -> dict:
    try:
        return (decisions or RealDecisions()).profile(cfg)[1]
    except NotReady:
        return {}


def _held(cfg: Config, facts: PlanFacts | None) -> int | None:
    try:
        return len(portfolio.held_rows((facts or RealPlanFacts()).facts(cfg)))
    except NotReady:
        return None


def week_of(cfg: Config, desk: Desk, now: datetime, facts: PlanFacts | None = None) -> dict:
    week = store.week_usage(cfg, desk.name, now) | {"cap": desk.weekly_runs, "line": None, "parts": []}
    if desk.name == portfolio.NAME:
        nightly, asked = store.week_usage(cfg, desk.name, now, lane="pass")["runs"], store.week_usage(cfg, desk.name, now, lane="desk")["runs"]
        held = _held(cfg, facts)
        room = portfolio.desk_for(held).weekly_runs if held else max(nightly, 1)
        week["cap"] = desk.weekly_runs + room
        week["parts"] = [{"name": "Holdings pass", "runs": nightly, "cap": room}, {"name": "On request", "runs": asked, "cap": desk.weekly_runs}]
        week["line"] = f"Holdings pass {nightly} of {room} this week, one per holding. On request {asked} of {desk.weekly_runs}."
    elif desk.name in ONCE_A_DAY and week["runs"] >= desk.weekly_runs:
        week["line"] = "Over this week's allowance, so extra runs wait. The daily check still runs once a day."
    return week


def crew(cfg: Config, now: datetime | None = None, decisions: Decisions | None = None, facts: PlanFacts | None = None) -> dict:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(cfg.timezone)
    profile = _profile(cfg, decisions)
    master = switches.resolve(cfg, store.ALL, profile)
    on = master["enabled"]
    guard = store.guard_on(cfg)
    ready, why = switches.guard_ready(cfg, FIRST_RUN)
    busy = any(j["job"] == "agents" for j in running(cfg))
    held = limits.state(cfg, now)
    retries = {r["desk"]: r["due_at"] for r in held["retries"]}
    desks = []
    for d in sorted(DESKS.values(), key=lambda d: (d.priority, d.name)):
        switch = switches.resolve(cfg, d.name, profile)
        enabled = switch["enabled"]
        guarded = guard and d.name not in UNGUARDED
        week = week_of(cfg, d, now, facts)
        desks.append(
            {
                "desk": d.name,
                "title": d.title,
                "model": d.model,
                "effort": d.effort,
                "live": d.live,
                "enabled": enabled,
                "source": switch["source"],
                "app": switch["app"],
                "yaml": switch["yaml"],
                "guarded": guarded,
                "last_run": _last(store.last_run(cfg, d.name)),
                "next_run": next_run(d, now, zone) if d.live and enabled and on and not guarded else None,
                "week": week,
                "retry_at": retries.get(d.name),
            }
        )
    return {
        "enabled": on,
        "enabled_source": master["source"],
        "busy": busy,
        "guard": {"on": guard, "allowed": list(UNGUARDED), "ready": ready, "why": why},
        "limit": held,
        "desks": desks,
    }
