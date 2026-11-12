from datetime import UTC, datetime, timedelta

from desk.config import Config

NIGHT_HOURS = 18


def line(cfg: Config, *, now: datetime | None = None) -> str | None:
    from desk.opportunities.build import build
    from desk.opportunities.cases import written_tonight

    now = now or datetime.now(UTC)
    try:
        counts = build(cfg, now=now)["counts"]
    except Exception:  # noqa: BLE001
        return None
    buy, could, rest = counts["buy"], counts["could"], counts["not_now"]
    if not counts["total"]:
        return None
    n = buy + could
    if buy:
        text = f"{n} buying {'opportunity' if n == 1 else 'opportunities'}, {buy} rated a buy"
    elif could:
        text = f"{could} buying {'opportunity' if could == 1 else 'opportunities'} to watch, none rated a buy yet"
    else:
        text = f"No buying opportunities today: {rest} looked at, none for now"
    try:
        wrote = written_tonight(cfg, now)
    except Exception:  # noqa: BLE001
        wrote = 0
    return f"{text}; {wrote} {'case' if wrote == 1 else 'cases'} written overnight" if wrote else text


def ready(cfg: Config, *, now: datetime | None = None) -> str | None:
    from desk.opportunities.cases import parse
    from desk.opportunities.night import last_night

    now = now or datetime.now(UTC)
    night = last_night(cfg) or {}
    ran = parse(night.get("finished_at"))
    if night.get("ready") and ran is not None and timedelta(0) <= now - ran <= timedelta(hours=NIGHT_HOURS):
        return night["ready"]
    return line(cfg, now=now)
