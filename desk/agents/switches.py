from desk.agents import store
from desk.agents.desks import DESKS
from desk.config import Config

DEFAULT_OFF = ("filings",)
NOTES = {
    "app": "Switched off in Settings.",
    "desk.yaml": "Switched off in desk.yaml.",
    "default": "Off until you switch it on.",
}


def _yaml(profile: dict, desk: str) -> bool | None:
    agents = profile.get("agents") or {}
    value = agents.get("enabled") if desk == store.ALL else (agents.get("desks") or {}).get(desk)
    return value if isinstance(value, bool) else None


def resolve(cfg: Config, desk: str, profile: dict) -> dict:
    app = store.app_switch(cfg, desk)
    yaml = _yaml(profile, desk)
    if app is not None:
        on, source = app, "app"
    elif yaml is not None:
        on, source = yaml, "desk.yaml"
    else:
        on, source = desk not in DEFAULT_OFF, "default"
    return {"enabled": on, "source": source, "app": app, "yaml": yaml}


def blocked(cfg: Config, desk: str, profile: dict) -> str | None:
    master = resolve(cfg, store.ALL, profile)
    if not master["enabled"]:
        return "All desks are " + NOTES[master["source"]][0].lower() + NOTES[master["source"]][1:]
    mine = resolve(cfg, desk, profile)
    if not mine["enabled"]:
        return NOTES[mine["source"]]
    return None


def guard_ready(cfg: Config, first_run: tuple[str, ...]) -> tuple[bool, str | None]:
    missing = [d for d, n in store.ok_runs(cfg, first_run).items() if n == 0]
    if not missing:
        return True, None
    names = " and the ".join(DESKS[d].title if d in DESKS else d for d in missing)
    return False, f"The {names} {'has' if len(missing) == 1 else 'have'}n't finished a run yet."
