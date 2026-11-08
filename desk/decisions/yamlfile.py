import shutil
from pathlib import Path


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


def write_with_backup(path: Path, text: str) -> Path:
    backup = path.with_name(path.name + ".bak")
    shutil.copy2(path, backup)
    path.write_text(text)
    return backup
