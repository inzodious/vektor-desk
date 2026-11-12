from datetime import UTC, datetime

from desk.config import Config


def ready(cfg: Config, *, now: datetime | None = None) -> str | None:
    from desk.opportunities.build import build
    from desk.opportunities.cases import written_tonight

    try:
        counts = build(cfg)["counts"]
    except Exception:  # noqa: BLE001
        return None
    total, buy = counts["total"], counts["buy"]
    if not total:
        return None
    line = f"{total} buying {'opportunity' if total == 1 else 'opportunities'}"
    line = f"{line}, {buy} rated a buy" if buy else f"{line} to watch, none rated a buy yet"
    try:
        wrote = written_tonight(cfg, now or datetime.now(UTC))
    except Exception:  # noqa: BLE001
        wrote = 0
    return f"{line}; {wrote} {'case' if wrote == 1 else 'cases'} written overnight" if wrote else line
