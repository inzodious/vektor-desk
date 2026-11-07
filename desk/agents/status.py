from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.agents import store
from desk.agents.desks import DESKS, Desk
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


def crew(cfg: Config, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(cfg.timezone)
    on = store.is_enabled(cfg, store.ALL)
    busy = any(j["job"] == "agents" for j in running(cfg))
    desks = []
    for d in sorted(DESKS.values(), key=lambda d: (d.priority, d.name)):
        enabled = store.is_enabled(cfg, d.name)
        week = store.week_usage(cfg, d.name, now)
        desks.append(
            {
                "desk": d.name,
                "title": d.title,
                "model": d.model,
                "effort": d.effort,
                "live": d.live,
                "enabled": enabled,
                "last_run": _last(store.last_run(cfg, d.name)),
                "next_run": next_run(d, now, zone) if d.live and enabled and on else None,
                "week": week | {"cap": d.weekly_runs},
            }
        )
    return {"enabled": on, "busy": busy, "desks": desks}
