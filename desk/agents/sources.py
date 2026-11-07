import importlib
from dataclasses import dataclass
from typing import Protocol

from desk.config import Config


class NotReady(RuntimeError):
    pass


class Engine(Protocol):
    def desk_slice(self, cfg: Config, desk: str) -> dict: ...


class Decisions(Protocol):
    def profile(self, cfg: Config) -> tuple[str, dict]: ...

    def history(self, cfg: Config, desk: str, limit: int) -> list[dict]: ...

    def create(self, cfg: Config, proposal: dict, desk: str, run_id: str) -> dict: ...

    def reject(self, cfg: Config, proposal: dict, desk: str, reason: str, run_id: str) -> dict: ...

    def attach_skeptic(self, cfg: Config, decision_id: object, verdict: str | None, counter_case: str | None) -> object: ...


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and name.startswith(e.name):
            raise NotReady(f"{name} isn't built yet") from None
        raise


@dataclass
class RealEngine:
    def desk_slice(self, cfg: Config, desk: str) -> dict:
        brief = _module("desk.engine.brief")
        try:
            return brief.desk_slice(cfg, desk)
        except brief.NotReady as e:
            raise NotReady(str(e) or "no engine run yet") from None


@dataclass
class RealDecisions:
    def profile(self, cfg: Config) -> tuple[str, dict]:
        p = _module("desk.decisions.profile").active_profile(cfg)
        return str(p.version), dict(p.data)

    def history(self, cfg: Config, desk: str, limit: int) -> list[dict]:
        return list(_module("desk.decisions").desk_history(cfg, desk, limit=limit))

    def create(self, cfg: Config, proposal: dict, desk: str, run_id: str) -> dict:
        return _module("desk.decisions").create_proposal(cfg, proposal, desk, run_id=run_id)

    def reject(self, cfg: Config, proposal: dict, desk: str, reason: str, run_id: str) -> dict:
        return _module("desk.decisions").reject_proposal(cfg, proposal, desk, reason, run_id=run_id)

    def attach_skeptic(self, cfg: Config, decision_id: object, verdict: str | None, counter_case: str | None) -> object:
        return _module("desk.decisions").attach_skeptic(cfg, decision_id, verdict, counter_case)


@dataclass
class RealTriggers:
    def today(self, cfg: Config) -> list[dict]:
        return list(_module("desk.engine.triggers").today(cfg))
