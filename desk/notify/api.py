from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from desk.api.deps import get_cfg
from desk.config import Config
from desk.notify import TOPICS, muted, recent, set_enabled, subscribe_url, topic_name

router = APIRouter(prefix="/api/notify", tags=["notify"])
CfgDep = Annotated[Config, Depends(get_cfg)]


class Switch(BaseModel):
    enabled: bool


@router.get("/topics")
def get_topics(cfg: CfgDep) -> dict:
    off = muted(cfg)
    return {
        "server": f"{cfg.public_url}:8443",
        "on": bool(cfg.ntfy_url) and not cfg.demo,
        "topics": [
            {"topic": t, "name": topic_name(t), "about": about, "enabled": t not in off, "subscribe": subscribe_url(cfg, t)} for t, about in TOPICS.items()
        ],
    }


@router.put("/topics/{topic}")
def put_topic(topic: str, body: Switch, cfg: CfgDep) -> dict:
    if topic not in TOPICS:
        raise HTTPException(404, f"unknown topic {topic}")
    set_enabled(cfg, topic, body.enabled)
    return {"topic": topic, "enabled": body.enabled}


@router.get("/recent")
def get_recent(cfg: CfgDep, limit: Annotated[int, Query(ge=1, le=200)] = 30, topic: str | None = None) -> dict:
    return {"alerts": recent(cfg, limit, topic if topic in TOPICS else None)}
