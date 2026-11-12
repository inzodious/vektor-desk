import os
import sqlite3
from collections import defaultdict

from desk.config import Config

RATE_ERRORS = (sqlite3.Error, TypeError, KeyError, ValueError, OSError, AttributeError)


def picture(rows: list[dict]) -> dict:
    net: dict[str, float] = defaultdict(float)
    modelled = False
    for h in rows:
        if h["is_cash"]:
            net[h["account"]] += h["value"]
            modelled = modelled or h.get("quality") == "modelled"
    ready = {a: round(v, 2) for a, v in sorted(net.items()) if v > 0}
    debit = {a: round(-v, 2) for a, v in sorted(net.items()) if v < 0}
    return {
        "ready": round(sum(ready.values()), 2),
        "debit": round(sum(debit.values()), 2),
        "ready_by_account": ready,
        "debit_by_account": debit,
        "accounts": sorted(net),
        "modelled": modelled,
    }


def margin_rate(cfg: Config | None) -> tuple[float | None, str]:
    raw = os.environ.get("DESK_MARGIN_RATE_PCT", "").strip()
    try:
        if raw:
            return float(raw), "env"
    except ValueError:
        pass
    if cfg is None:
        return None, "none"
    try:
        from desk.decisions import profile

        read = getattr(profile, "margin_rate", None)
        got = read(profile.active_profile(cfg).data) if read else None
    except RATE_ERRORS:
        return None, "none"
    if isinstance(got, dict) and isinstance(got.get("rate_pct"), int | float):
        return float(got["rate_pct"]), str(got.get("source") or "profile")
    return None, "none"
