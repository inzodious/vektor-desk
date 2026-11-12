from desk.config import Config


def ready(cfg: Config) -> str | None:
    from desk.opportunities.build import build

    try:
        counts = build(cfg)["counts"]
    except Exception:  # noqa: BLE001
        return None
    total, buy = counts["total"], counts["buy"]
    if not total:
        return None
    line = f"{total} buying {'opportunity' if total == 1 else 'opportunities'}"
    return f"{line}, {buy} rated a buy" if buy else f"{line} to watch, none rated a buy yet"
