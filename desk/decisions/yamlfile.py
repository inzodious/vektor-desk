import shutil
from pathlib import Path

import yaml

from desk.config import Config
from desk.decisions.profile import DEFAULTS, ProfileError, active_profile, merge, parse, profile_path

EDITABLE = tuple(k for k in DEFAULTS if k != "risk_level")


class EditError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ---- Text edits ----


def top_level(line: str) -> bool:
    return bool(line) and not line[0].isspace() and line[0] not in "#-"


def replace_section(text: str, key: str, block: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if top_level(line) and line.split(":")[0].strip() == key), None)
    new_block = block.rstrip("\n").splitlines()
    if start is None:
        return "\n".join([*lines, "", *new_block]) + "\n"
    end = next((j for j in range(start + 1, len(lines)) if top_level(lines[j])), len(lines))
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
        end -= 1
    return "\n".join([*lines[:start], *new_block, *lines[end:]]) + "\n"


def dump_section(key: str, value) -> str:
    return yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False, allow_unicode=True, width=200)


def write_with_backup(path: Path, text: str) -> Path:
    backup = path.with_name(path.name + ".bak")
    shutil.copy2(path, backup)
    path.write_text(text)
    return backup


# ---- Profile edits ----


def check_changes(changes) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise EditError("changes must map profile sections to their new values")
    if "risk_level" in changes:
        raise EditError("risk_level comes from the risk questions now; answer them on the Risk screen instead")
    unknown = sorted(k for k in changes if k not in EDITABLE)
    if unknown:
        raise EditError(f"unknown section {', '.join(unknown)}; editable sections are {', '.join(EDITABLE)}")
    return changes


def apply(text: str, changes: dict) -> tuple[str, dict]:
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise EditError("desk.yaml must be a mapping at the top level")
    wanted = {}
    for key, value in changes.items():
        current = raw.get(key)
        new = merge(current, value) if isinstance(current, dict) and isinstance(value, dict) and key != "rules" else value
        wanted[key] = new
        if current != new:
            text = replace_section(text, key, dump_section(key, new))
    return text, wanted


def edit_profile(cfg: Config, changes) -> dict:
    changes = check_changes(changes)
    path = profile_path(cfg)
    if not path.exists():
        raise EditError("There's no desk.yaml yet. Create one first with Set up profile (POST /api/decisions/profile/init).", 409)
    text = path.read_text()
    try:
        parse(text)
    except ProfileError as e:
        raise EditError(f"desk.yaml doesn't load right now ({e}); fix it before editing here", 409) from e
    out, wanted = apply(text, changes)
    if out == text:
        return {"changed": False, "path": str(path), "backup": None, "sections": sorted(changes), "version": active_profile(cfg).version}
    try:
        parse(out)
    except ProfileError as e:
        raise EditError(f"That change doesn't validate, so nothing was written: {e}") from e
    reread = yaml.safe_load(out) or {}
    if any(reread.get(k) != v for k, v in wanted.items()):
        raise EditError("Couldn't place the change cleanly in desk.yaml, so nothing was written", 409)
    backup = write_with_backup(path, out)
    return {"changed": True, "path": str(path), "backup": str(backup), "sections": sorted(changes), "version": active_profile(cfg).version}
