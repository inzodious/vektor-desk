from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from desk.config import Config
from desk.decisions import plan, records, starter, targets, tickets
from desk.decisions import profile as profiles
from desk.decisions import rules as ruleset
from desk.decisions.store import session

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


def get_cfg(request: Request) -> Config:
    return getattr(request.app.state, "cfg", None) or Config.from_env()


Cfg = Annotated[Config, Depends(get_cfg)]


def fresh(body) -> JSONResponse:
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


# ---- Profile and rules ----


@router.get("/profile")
def get_profile(cfg: Cfg) -> JSONResponse:
    body = profiles.active_profile(cfg).as_dict()
    mode, series = plan.deposit_series(cfg)
    body["profile"] = {**body["profile"], "deposits": series}
    return fresh(body | {"deposits_mode": mode})


class PlanPreset(BaseModel):
    preset: str


@router.get("/plan")
def get_plan(cfg: Cfg) -> JSONResponse:
    mine = targets.profile_plan(profiles.active_profile(cfg))
    return fresh({"plan": mine, "source": "profile" if mine else None, "presets": sorted(targets.PRESETS), "actions": targets.planned_actions(cfg)})


@router.get("/actions")
def get_actions(cfg: Cfg) -> JSONResponse:
    items = targets.planned_actions(cfg)
    return fresh({"actions": items, "lines": targets.describe(items)})


@router.put("/profile/plan")
def put_profile_plan(body: PlanPreset, cfg: Cfg) -> JSONResponse:
    try:
        changed, message = targets.set_plan(profiles.profile_path(cfg), body.preset)
    except targets.TargetsError as e:
        raise HTTPException(422, str(e)) from e
    except profiles.ProfileError as e:
        raise HTTPException(409, f"desk.yaml doesn't validate right now ({e}); fix it first.") from e
    return fresh({"changed": changed, "message": message, "profile": profiles.active_profile(cfg).as_dict()})


@router.get("/profile/status")
def get_profile_status(cfg: Cfg) -> JSONResponse:
    return fresh(starter.status(cfg))


@router.get("/profile/versions")
def get_profile_versions(cfg: Cfg) -> JSONResponse:
    profiles.active_profile(cfg)
    with session(cfg) as conn:
        return fresh({"versions": profiles.versions(conn)})


@router.get("/profile/versions/{version}")
def get_profile_version(version: int, cfg: Cfg) -> JSONResponse:
    with session(cfg) as conn:
        found = profiles.get_version(conn, version)
    if found is None:
        raise HTTPException(404, "No such profile version")
    return fresh(found.as_dict())


@router.get("/rules")
def get_rules(cfg: Cfg) -> JSONResponse:
    version, active = ruleset.active_rules(cfg)
    return fresh({"version": version, "rules": [{**r, "label": ruleset.describe(r)} for r in active]})


@router.get("/rules/versions")
def get_rules_versions(cfg: Cfg) -> JSONResponse:
    profiles.active_profile(cfg)
    with session(cfg) as conn:
        return fresh({"versions": ruleset.versions(conn)})


# ---- Decisions ----


class Reason(BaseModel):
    reason: str | None = None


class Snooze(BaseModel):
    days: float = 1
    reason: str | None = None


class Placed(BaseModel):
    shares: float | None = None
    price: float | None = None


class Note(BaseModel):
    text: str


class LogTrade(BaseModel):
    thesis: str | None = None
    reason: str | None = None


class Draft(BaseModel):
    kind: str
    symbol: str | None = None
    account: str | None = None
    amount_usd: float | None = None
    shares: float | None = None
    funding: str | None = None
    title: str | None = None
    thesis: str | None = None
    bear_case: str | None = None
    invalidation: str | None = None
    horizon: str | None = None
    rule_served: str | None = None
    confidence: float | None = None
    expires: str | None = None
    order_ticket: dict | None = None


def act(fn, *args, **kwargs) -> JSONResponse:
    try:
        return fresh(fn(*args, **kwargs))
    except records.DecisionError as e:
        raise HTTPException(e.status, str(e)) from e


class Event(BaseModel):
    date: str
    title: str
    note: str | None = None
    kind: str = "note"


@router.get("/deposits")
def get_deposits(cfg: Cfg, days: int = 60) -> JSONResponse:
    return act(lambda: {"deposits": plan.upcoming_deposits(cfg, days=max(0, min(days, 400)))})


@router.get("/calendar")
def get_calendar(
    cfg: Cfg,
    since: Annotated[str | None, Query(alias="from")] = None,
    until: Annotated[str | None, Query(alias="to")] = None,
) -> JSONResponse:
    return act(lambda: {"events": plan.calendar_events(cfg, since, until)})


@router.post("/calendar")
def post_event(body: Event, cfg: Cfg) -> JSONResponse:
    return act(plan.add_event, cfg, body.date, body.title, body.note, body.kind)


@router.delete("/calendar/{event_id}")
def delete_event(event_id: str, cfg: Cfg) -> JSONResponse:
    return act(plan.delete_event, cfg, event_id)


@router.get("/queue")
def get_queue(cfg: Cfg) -> JSONResponse:
    return act(records.queue, cfg)


@router.get("/summary")
def get_summary(cfg: Cfg) -> JSONResponse:
    return act(records.summary, cfg)


@router.get("/journal")
def get_journal(
    cfg: Cfg,
    origin: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    since: Annotated[str | None, Query(alias="from")] = None,
    until: Annotated[str | None, Query(alias="to")] = None,
    limit: int = 100,
) -> JSONResponse:
    return act(records.journal, cfg, origin=origin, kind=kind, status=status, symbol=symbol, since=since, until=until, limit=limit)


@router.get("/unmatched")
def get_unmatched(cfg: Cfg, days: int = records.UNMATCHED_DAYS) -> JSONResponse:
    return act(lambda: {"trades": records.unmatched(cfg, days=days)})


@router.post("/unmatched/{activity_id}/log")
def post_log_trade(activity_id: str, body: LogTrade, cfg: Cfg) -> JSONResponse:
    return act(records.log_trade, cfg, activity_id, thesis=body.thesis, reason=body.reason)


@router.post("")
def post_draft(body: Draft, cfg: Cfg) -> JSONResponse:
    return act(records.draft, cfg, body.model_dump(exclude_none=True))


@router.get("/{decision_id}")
def get_decision(decision_id: str, cfg: Cfg) -> JSONResponse:
    return act(records.get, cfg, decision_id)


@router.get("/{decision_id}/ticket")
def get_ticket(decision_id: str, cfg: Cfg) -> JSONResponse:
    def build():
        d = records.get(cfg, decision_id)
        return tickets.ticket(d, profiles.active_profile(cfg).get("tax", "lot_method"))

    return act(build)


@router.post("/{decision_id}/approve")
def post_approve(decision_id: str, body: Reason, cfg: Cfg) -> JSONResponse:
    return act(records.approve, cfg, decision_id, body.reason)


@router.post("/{decision_id}/dismiss")
def post_dismiss(decision_id: str, body: Reason, cfg: Cfg) -> JSONResponse:
    return act(records.dismiss, cfg, decision_id, body.reason)


@router.post("/{decision_id}/snooze")
def post_snooze(decision_id: str, body: Snooze, cfg: Cfg) -> JSONResponse:
    return act(records.snooze, cfg, decision_id, body.days, body.reason)


@router.post("/{decision_id}/pass")
def post_pass(decision_id: str, body: Reason, cfg: Cfg) -> JSONResponse:
    return act(records.pass_on, cfg, decision_id, body.reason or "")


@router.post("/{decision_id}/placed")
def post_placed(decision_id: str, body: Placed, cfg: Cfg) -> JSONResponse:
    return act(records.mark_placed, cfg, decision_id, body.shares, body.price)


@router.post("/{decision_id}/note")
def post_note(decision_id: str, body: Note, cfg: Cfg) -> JSONResponse:
    return act(records.add_note, cfg, decision_id, body.text)


@router.post("/{decision_id}/preflight")
def post_preflight(decision_id: str, cfg: Cfg) -> JSONResponse:
    return act(records.rerun_preflight, cfg, decision_id)
