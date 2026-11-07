import importlib
import importlib.util
import pkgutil
from types import ModuleType

import desk

CORE = frozenset({"api"})


def packages() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(desk.__path__) if m.ispkg and m.name not in CORE)


def seam(pkg: str, module: str) -> ModuleType | None:
    name = f"desk.{pkg}.{module}"
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def seams(module: str, only: list[str] | None = None) -> dict[str, ModuleType]:
    found = {}
    for pkg in packages() if only is None else only:
        mod = seam(pkg, module)
        if mod is not None:
            found[pkg] = mod
    return found
