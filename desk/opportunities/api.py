from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from desk.api.deps import get_cfg
from desk.config import Config
from desk.opportunities.build import build

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])
CfgDep = Annotated[Config, Depends(get_cfg)]


@router.get("")
def get_opportunities(cfg: CfgDep) -> JSONResponse:
    return JSONResponse(build(cfg), headers={"Cache-Control": "no-store"})
