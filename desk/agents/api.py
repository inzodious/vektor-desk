import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from desk.agents import console, store
from desk.agents.desks import DESKS
from desk.agents.status import crew
from desk.api.deps import get_cfg
from desk.config import Config

router = APIRouter(prefix="/api/agents", tags=["agents"])
CfgDep = Annotated[Config, Depends(get_cfg)]


class Switch(BaseModel):
    enabled: bool


class Question(BaseModel):
    desk: str
    question: str
    symbol: str | None = None
    run_now: bool = False


@router.get("/status")
def get_status(cfg: CfgDep) -> JSONResponse:
    return JSONResponse(crew(cfg), headers={"Cache-Control": "no-store"})


@router.put("/{desk}/enabled")
def put_enabled(desk: str, body: Switch, cfg: CfgDep) -> dict:
    if desk != store.ALL and desk not in DESKS:
        raise HTTPException(404, f"unknown desk {desk}")
    store.set_enabled(cfg, desk, body.enabled)
    return {"desk": desk, "enabled": body.enabled}


@router.get("/brief")
def get_brief(cfg: CfgDep) -> JSONResponse:
    return JSONResponse(store.latest_brief(cfg, "plan_keeper") or {"summary": None}, headers={"Cache-Control": "no-store"})


@router.get("/runs")
def get_runs(cfg: CfgDep, desk: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> JSONResponse:
    if desk is not None and desk not in DESKS:
        raise HTTPException(404, f"unknown desk {desk}")
    return JSONResponse(store.runs(cfg, desk, limit), headers={"Cache-Control": "no-store"})


@router.post("/console", status_code=201)
def post_console(body: Question, cfg: CfgDep) -> dict:
    try:
        rid = console.ask(cfg, body.desk, body.question, symbol=body.symbol, run_now=body.run_now)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return store.get_request(cfg, rid)


@router.get("/console")
def list_console(cfg: CfgDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> JSONResponse:
    return JSONResponse(store.requests(cfg, limit), headers={"Cache-Control": "no-store"})


@router.get("/console/{request_id}")
def get_console(request_id: int, cfg: CfgDep) -> JSONResponse:
    row = store.get_request(cfg, request_id)
    if row is None:
        raise HTTPException(404, "no such request")
    return JSONResponse(row, headers={"Cache-Control": "no-store"})


def _dossier(row: dict) -> dict:
    return {"symbol": row["symbol"], "run_id": row["run_id"], "created_at": row["created_at"], "dossier": json.loads(row["dossier"])}


@router.get("/dossiers")
def list_dossiers(cfg: CfgDep) -> JSONResponse:
    return JSONResponse([_dossier(r) for r in store.dossier_list(cfg)], headers={"Cache-Control": "no-store"})


@router.get("/dossiers/{symbol}")
def get_dossier(symbol: str, cfg: CfgDep) -> JSONResponse:
    row = store.latest_dossier(cfg, symbol.upper())
    if row is None:
        raise HTTPException(404, "no dossier yet")
    return JSONResponse(_dossier(row), headers={"Cache-Control": "no-store"})
