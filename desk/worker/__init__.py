from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from desk.config import Config
from desk.packages import seams
from desk.runlock import run_dir

ASLEEP_AFTER = 120
BEAT_EVERY = 30
MAX_ATTEMPTS = 3
RESULT_MAX = 64 * 2**20


@dataclass(frozen=True)
class Kind:
    name: str
    title: str
    run: Callable[[dict, dict[str, Path]], object]
    accept: Callable[[Config, dict, Path], str | None]


def registry(only: list[str] | None = None) -> dict[str, Kind]:
    found: dict[str, Kind] = {}
    for mod in seams("kinds", only).values():
        for kind in getattr(mod, "KINDS", []):
            found[kind.name] = kind
    return found


def home(cfg: Config) -> Path:
    return run_dir(cfg) / "worker"


def offer(cfg: Config, kind: str, inputs: dict, copies: tuple[str, ...] = ("lab",), key: str | None = None, again: bool = False) -> dict:
    from desk.worker import snapshots, store

    snapshots.allowed(cfg, copies)
    taken = [snapshots.take(cfg, name) for name in copies]
    return store.enqueue(cfg, kind, inputs, taken, key, again)


def online(cfg: Config, now: datetime | None = None) -> bool:
    from desk.worker import store

    return any(w["state"] == "online" for w in store.workers(cfg, now))
