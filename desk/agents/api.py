from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from desk.agents import store
from desk.agents.desks import DESKS
from desk.agents.status import crew
from desk.api.deps import get_cfg
from desk.config import Config

router = APIRouter(prefix="/api/agents", tags=["agents"])
CfgDep = Annotated[Config, Depends(get_cfg)]


class Switch(BaseModel):
    enabled: bool


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
