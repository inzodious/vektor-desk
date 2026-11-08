import importlib
from dataclasses import dataclass
from typing import Protocol

from desk.config import Config


class NotReady(RuntimeError):
    pass


class Engine(Protocol):
    def desk_slice(self, cfg: Config, desk: str) -> dict: ...


class Lab(Protocol):
    def grammar(self) -> dict: ...

    def features(self, cfg: Config) -> list[dict]: ...

    def desk_view(self, cfg: Config, strategy_id: str) -> dict: ...

    def pending_reviews(self, cfg: Config) -> list[dict]: ...

    def eligible(self, cfg: Config) -> list[dict]: ...


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


def _fn(name: str, attr: str):
    fn = getattr(_module(name), attr, None)
    if fn is None:
        raise NotReady(f"{name}.{attr} isn't built yet")
    return fn


@dataclass
class RealEngine:
    def desk_slice(self, cfg: Config, desk: str) -> dict:
        brief = _module("desk.engine.brief")
        if not hasattr(brief, "desk_slice"):
            raise NotReady("desk.engine.brief.desk_slice isn't built yet")
        try:
            return brief.desk_slice(cfg, desk)
        except brief.NotReady as e:
            raise NotReady(str(e) or "no engine run yet") from None


@dataclass
class RealDecisions:
    def profile(self, cfg: Config) -> tuple[str, dict]:
        p = _fn("desk.decisions.profile", "active_profile")(cfg)
        return str(p.version), dict(p.data)

    def history(self, cfg: Config, desk: str, limit: int) -> list[dict]:
        return list(_fn("desk.decisions", "desk_history")(cfg, desk, limit=limit))

    def create(self, cfg: Config, proposal: dict, desk: str, run_id: str) -> dict:
        return _fn("desk.decisions", "create_proposal")(cfg, proposal, desk, run_id=run_id)

    def reject(self, cfg: Config, proposal: dict, desk: str, reason: str, run_id: str) -> dict:
        return _fn("desk.decisions", "reject_proposal")(cfg, proposal, desk, reason, run_id=run_id)

    def attach_skeptic(self, cfg: Config, decision_id: object, verdict: str | None, counter_case: str | None) -> object:
        return _fn("desk.decisions", "attach_skeptic")(cfg, decision_id, verdict, counter_case)


@dataclass
class RealTriggers:
    def today(self, cfg: Config) -> list[dict]:
        return list(_fn("desk.engine.triggers", "today")(cfg))


@dataclass
class RealLab:
    def _lab(self):
        mod = _module("desk.engine.lab")
        return mod, getattr(mod, "NotReady", None) or getattr(_module("desk.engine.brief"), "NotReady", NotReady)

    def _call(self, fn: str, *args):
        mod, not_ready = self._lab()
        if not hasattr(mod, fn):
            raise NotReady(f"desk.engine.lab.{fn} isn't built yet")
        try:
            return getattr(mod, fn)(*args)
        except not_ready as e:
            raise NotReady(str(e) or "lab not ready") from None

    def grammar(self) -> dict:
        return dict(self._call("grammar"))

    def features(self, cfg: Config) -> list[dict]:
        return list(self._call("features", cfg))

    def desk_view(self, cfg: Config, strategy_id: str) -> dict:
        return dict(self._call("desk_view", cfg, strategy_id))

    def pending_reviews(self, cfg: Config) -> list[dict]:
        return list(self._call("pending_reviews", cfg))

    def eligible(self, cfg: Config) -> list[dict]:
        return list(self._call("eligible", cfg))


class Filings(Protocol):
    def pending(self, cfg: Config, limit: int) -> list[dict]: ...

    def record(self, cfg: Config, accession: str, result: dict) -> object: ...


@dataclass
class RealFilings:
    def _call(self, fn: str, *args):
        mod = _module("desk.engine.filings")
        if not hasattr(mod, fn):
            raise NotReady(f"desk.engine.filings.{fn} isn't built yet")
        not_ready = getattr(mod, "NotReady", NotReady)
        try:
            return getattr(mod, fn)(*args)
        except not_ready as e:
            raise NotReady(str(e) or "filings not ready") from None

    def pending(self, cfg: Config, limit: int) -> list[dict]:
        return list(self._call("pending", cfg, limit))

    def record(self, cfg: Config, accession: str, result: dict) -> object:
        return self._call("record", cfg, accession, result)
