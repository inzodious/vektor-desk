from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from desk.config import Config
from desk.decisions import plan, plans, records, risk, starter, tickets, yamlfile
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
    return fresh(body | {"deposits_mode": mode, "editable": list(yamlfile.EDITABLE)})


class ProfilePatch(BaseModel):
    changes: dict


@router.patch("/profile")
def patch_profile(body: ProfilePatch, cfg: Cfg) -> JSONResponse:
    try:
        result = yamlfile.edit_profile(cfg, body.changes)
    except yamlfile.EditError as e:
        raise HTTPException(e.status, str(e)) from e
    return fresh(result | {"status": starter.status(cfg)})


class Answers(BaseModel):
    answers: dict


@router.get("/risk")
def get_risk(cfg: Cfg) -> JSONResponse:
    return fresh({"questions": risk.questions(cfg), "current": risk.current(cfg), "bands": risk.BANDS, "inputs": risk.inputs(cfg)})


@router.put("/risk")
def put_risk(body: Answers, cfg: Cfg) -> JSONResponse:
    try:
        saved, changed = risk.save(cfg, body.answers)
    except risk.RiskError as e:
        raise HTTPException(422, str(e)) from e
    return fresh({"changed": changed, "result": saved, "current": risk.current(cfg)})


class Band(BaseModel):
    band_min_pct: float | None = None
    band_max_pct: float | None = None
    note: str | None = None


@router.get("/convictions")
def get_convictions(cfg: Cfg) -> JSONResponse:
    return fresh({"items": risk.convictions(cfg), "suggested": risk.suggested_band(cfg)})


@router.put("/convictions/{symbol}")
def put_conviction(symbol: str, body: Band, cfg: Cfg) -> JSONResponse:
    try:
        result = risk.set_conviction(cfg, symbol, band_min_pct=body.band_min_pct, band_max_pct=body.band_max_pct, note=body.note)
    except risk.RiskError as e:
        raise HTTPException(422, str(e)) from e
    except yamlfile.EditError as e:
        raise HTTPException(e.status, str(e)) from e
    return fresh(result | {"suggested": risk.suggested_band(cfg)})


@router.delete("/convictions/{symbol}")
def delete_conviction(symbol: str, cfg: Cfg) -> JSONResponse:
    try:
        result = risk.drop_conviction(cfg, symbol)
    except risk.RiskError as e:
        raise HTTPException(404, str(e)) from e
    except yamlfile.EditError as e:
        raise HTTPException(e.status, str(e)) from e
    return fresh(result)


# ---- Stock plans ----


class PlanBody(BaseModel):
    plan: dict
    approve: bool = False
    summary: str | None = None


class Approve(BaseModel):
    version: int | None = None


class StepDone(BaseModel):
    on: str | None = None
    undo: bool = False


def _planned(fn, *args, **kwargs) -> JSONResponse:
    try:
        return fresh(fn(*args, **kwargs))
    except plans.PlanError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/plans")
def get_plans(cfg: Cfg) -> JSONResponse:
    return fresh(
        {
            "items": plans.list_plans(cfg),
            "roles": plans.ROLES,
            "step_kinds": plans.STEP_KINDS,
            "lot_methods": plans.LOT_TEXT,
            "step_templates": plans.STEP_TEMPLATES,
        }
    )


@router.get("/plan-steps")
def get_plan_steps(cfg: Cfg, days: int = Query(0, ge=0, le=366)) -> JSONResponse:
    return fresh({"items": plans.open_steps(cfg, days=days), "no_buy": plans.no_buy(cfg)})


@router.get("/plans/{symbol}")
def get_plan(symbol: str, cfg: Cfg) -> JSONResponse:
    def read():
        found = plans.get_plan(cfg, symbol)
        if found is None:
            raise plans.PlanError(f"{symbol.upper()} has no plan yet", 404)
        return {"plan": found, "history": plans.history(cfg, symbol)}

    return _planned(read)


@router.get("/plans/{symbol}/versions/{version}")
def get_plan_version(symbol: str, version: int, cfg: Cfg) -> JSONResponse:
    def read():
        found = plans.get_version(cfg, symbol, version)
        if found is None:
            raise plans.PlanError(f"{symbol.upper()} has no version {version}", 404)
        return {"plan": found}

    return _planned(read)


@router.put("/plans/{symbol}")
def put_plan(symbol: str, body: PlanBody, cfg: Cfg) -> JSONResponse:
    return _planned(plans.save_plan, cfg, symbol, body.plan, approve=body.approve, summary=body.summary)


@router.post("/plans/{symbol}/approve")
def post_plan_approve(symbol: str, body: Approve, cfg: Cfg) -> JSONResponse:
    return _planned(plans.approve_plan, cfg, symbol, body.version)


@router.post("/plans/{symbol}/discard")
def post_plan_discard(symbol: str, cfg: Cfg) -> JSONResponse:
    return _planned(plans.discard_draft, cfg, symbol)


@router.post("/plans/{symbol}/steps/{step_id}/done")
def post_plan_step_done(symbol: str, step_id: str, body: StepDone, cfg: Cfg) -> JSONResponse:
    return _planned(plans.mark_step, cfg, symbol, step_id, on=body.on, undo=body.undo)


@router.get("/risk/versions")
def get_risk_versions(cfg: Cfg) -> JSONResponse:
    return fresh({"versions": risk.history(cfg)})


@router.post("/profile/init")
def post_profile_init(cfg: Cfg) -> JSONResponse:
    try:
        path, _ = starter.init(cfg)
    except starter.StarterError as e:
        raise HTTPException(409 if "already exists" in str(e) else 422, str(e)) from e
    message = f"Wrote {path}. The next page load picks it up as a new profile version."
    return fresh({"changed": True, "path": str(path), "message": message, "status": starter.status(cfg)})


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


@router.get("/notes")
def get_notes(cfg: Cfg, days: Annotated[int, Query(ge=1, le=90)] = records.NOTE_DAYS) -> JSONResponse:
    return act(records.notes, cfg, days=days)


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
