from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from desk.config import Config
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
    return fresh(profiles.active_profile(cfg).as_dict())


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
