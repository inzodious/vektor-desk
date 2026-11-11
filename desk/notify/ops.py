from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

from desk.config import Config
from desk.notify import publish
from desk.status import status

MIRROR_TITLES = {
    "stale": "Mirror is stale",
    "failing": "Mirror is failing",
    "error": "Mirror has no good pull yet",
}
REVIEW_TITLES = {
    "stale": "Today's review hasn't run",
    "failing": "Today's review didn't finish",
}


def ops_check(cfg: Config | None = None, now: datetime | None = None, session: requests.Session | None = None) -> list[str]:
    cfg = cfg or Config.from_env()
    if cfg.demo:
        return []
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(cfg.timezone)).date()
    report = status(cfg, now)
    sent: list[str] = []

    mirror = report["mirror"]
    if mirror["state"] in MIRROR_TITLES:
        age = mirror.get("age_hours")
        body = f"Last good pull {age:g} hours ago." if age is not None else "No pull has finished yet."
        if publish(
            "ops",
            MIRROR_TITLES[mirror["state"]],
            body + " Numbers on the desk may be behind. Open Settings, Box and tap Status.",
            "high",
            tags=["satellite"],
            click="/settings/box",
            key=f"mirror-{mirror['state']}-{local.isoformat()}",
            cfg=cfg,
            session=session,
        ):
            sent.append(f"mirror-{mirror['state']}")

    reviews = report["reviews"]
    if reviews["state"] in REVIEW_TITLES:
        if publish(
            "ops",
            REVIEW_TITLES[reviews["state"]],
            "The day, week, month and year results aren't in yet. Open Settings, Box and tap Run now on Review.",
            "default",
            tags=["bar_chart"],
            click="/settings/box",
            key=f"reviews-{reviews['state']}-{local.isoformat()}",
            cfg=cfg,
            session=session,
        ):
            sent.append(f"reviews-{reviews['state']}")

    token = report["claude_token"]
    if token["state"] in ("renew", "expired"):
        week = "{}-W{:02d}".format(*local.isocalendar()[:2])
        expired = token["state"] == "expired"
        if publish(
            "ops",
            "Claude token expired" if expired else "Claude token expires soon",
            "Agents are paused until it's renewed." if expired else f"{token['days_left']} days left. Run claude setup-token, then paste it in Settings, Data.",
            "high" if expired else "default",
            tags=["key"],
            click="/settings/data",
            key=f"token-{token['state']}-{week}",
            dedupe_hours=24 * 6.5,
            cfg=cfg,
            session=session,
        ):
            sent.append(f"token-{token['state']}")
    return sent
