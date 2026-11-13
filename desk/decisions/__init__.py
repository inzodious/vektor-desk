import importlib

# ---- Lazy exports: `python -m desk.decisions.<module>` must not find its module already imported ----

_EXPORTS = {
    "add_event": "plan",
    "calendar_events": "plan",
    "cleared": "records",
    "delete_event": "plan",
    "deposits_landed": "plan",
    "upcoming_deposits": "plan",
    "Profile": "profile",
    "active_profile": "profile",
    "active_rules": "rules",
    "DecisionError": "records",
    "approve": "records",
    "attach_skeptic": "records",
    "confirm_fills": "records",
    "create_proposal": "records",
    "desk_history": "records",
    "dismiss": "records",
    "draft": "records",
    "get": "records",
    "journal": "records",
    "log_trade": "records",
    "mark_placed": "records",
    "next_steps": "steps",
    "notes": "records",
    "pass_on": "records",
    "queue": "records",
    "reject_proposal": "records",
    "rerun_preflight": "records",
    "scoring_rows": "records",
    "snooze": "records",
    "summary": "records",
    "unmatched": "records",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted([*globals(), *_EXPORTS])
