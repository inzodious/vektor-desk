from dataclasses import dataclass
from typing import Protocol

from desk.agents import alerts, plans, store
from desk.agents.adapter import Adapter
from desk.agents.pipeline import run_proposal_desk
from desk.agents.sources import Decisions, Engine, Lab, NotReady, RealTriggers
from desk.agents.strategy import run_strategy_desk
from desk.config import Config

ASKABLE = ("plan_keeper", "tax", "risk", "research", "strategy", "plans")
TRIGGER_DESKS = {
    "margin_debit": ("risk", True),
    "daily_move": ("risk", True),
    "concentration": ("risk", True),
    "lot_export": ("tax", True),
    "earnings": ("research", False),
    "rule_breach": ("plan_keeper", True),
    "deposit_landed": ("plan_keeper", False),
}
DONE = {"ok": "done", "not_ready": "done", "disabled": "done", "unchanged": "done", "over_budget": "done", "unhealthy": "done", "guarded": "done"}
MAX_PER_PASS = 10
LOCK_WAIT = 300


class Triggers(Protocol):
    def today(self, cfg: Config) -> list[dict]: ...


@dataclass
class Pass:
    ran: int = 0
    done: int = 0
    failed: int = 0
    requeued: int = 0


def ask(cfg: Config, desk: str, question: str, *, symbol: str | None = None, run_now: bool = False) -> int:
    if desk not in ASKABLE:
        raise ValueError(f"{desk} can't take Console questions")
    question = question.strip()
    if not question or len(question) > 2000:
        raise ValueError("questions are 1 to 2000 characters")
    symbol = (symbol or "").strip().upper() or None
    if desk == "plans":
        if not symbol:
            raise ValueError("pick the holding whose plan this is about")
        pins = plans.parse_pins(question)
        if pins is not None:
            plans.check_pins(symbol, pins)
            store.pin_steps(cfg, symbol, pins)
            question = f"{plans.PIN_NOTE} {', '.join(str(p['id']) for p in pins)}."
    return store.add_request(cfg, desk, question, symbol=symbol, run_now=run_now)


def _run_id(report) -> int | None:
    return report.run_id if isinstance(report, plans.PlanReport) else report.outcome.run_id


def _answer(report) -> str:
    if isinstance(report, plans.PlanReport):
        return report.answer
    parts = [report.summary] if report.summary else []
    if getattr(report, "memo", ""):
        parts.append(report.memo)
    if getattr(report, "queued", None):
        parts.append(f"Sent to the lab as {report.queued.name}.")
    if getattr(report, "waiting", None):
        parts.append(f"{len(report.waiting)} proposal(s) added to the queue.")
    if getattr(report, "notes", None):
        parts.append(f"{len(report.notes)} note(s) filed under Notes.")
    if getattr(report, "snoozed", None):
        parts.append(f"{len(report.snoozed)} proposal(s) kept the snooze of the one replaced.")
    if getattr(report, "late", None):
        parts.append(f"{len(report.late)} proposal(s) out of date on arrival, listed under Cleared.")
    if getattr(report, "refused", None):
        parts.append(f"{len(report.refused)} proposal(s) turned down by the desk's checks.")
    return "\n".join(parts) or (report.note or "")


def process_queue(
    cfg: Config,
    *,
    now_only: bool,
    engine: Engine | None = None,
    decisions: Decisions | None = None,
    adapter: Adapter | None = None,
    lab: Lab | None = None,
    limit: int = MAX_PER_PASS,
    wait: float = LOCK_WAIT,
) -> Pass:
    tally = Pass()
    while tally.ran < limit:
        req = store.next_request(cfg, now_only=now_only)
        if req is None:
            break
        tally.ran += 1
        if req["desk"] == "plans":
            note = None if req["question"].startswith(plans.PIN_NOTE) else req["question"]
            report = plans.run_plan_desk(cfg, symbols=(req["symbol"],), note=note, decisions=decisions, adapter=adapter, trigger=req["source"], wait=wait)
        elif req["desk"] == "strategy":
            report = run_strategy_desk(
                cfg, question=req["question"], strategy_id=req["symbol"], lab=lab, decisions=decisions, adapter=adapter, trigger=req["source"], wait=wait
            )
        else:
            report = run_proposal_desk(
                cfg,
                req["desk"],
                engine=engine,
                decisions=decisions,
                adapter=adapter,
                trigger=req["source"],
                wait=wait,
                question=req["question"],
                symbol=req["symbol"],
                lab=lab,
            )
        status = report.status
        if status in DONE:
            answer = _answer(report)
            store.finish_request(cfg, req["id"], "done", run_id=_run_id(report), answer=answer, note=report.note)
            if status == "ok":
                alerts.answer_ready(cfg, req, answer)
            tally.done += 1
        elif status == "busy":
            store.release(cfg, req["id"])
            tally.requeued += 1
            break
        elif status == "deferred" and req["source"] != "retry" and "deferred once" not in (req["note"] or ""):
            store.requeue(cfg, req["id"], f"{status}; deferred once to tonight")
            tally.requeued += 1
            break
        else:
            store.finish_request(cfg, req["id"], "failed", run_id=_run_id(report), note=report.note)
            if status == "deferred":
                alerts.run_failed(cfg, req["desk"], status, _run_id(report), report.note)
            tally.failed += 1
    return tally


def process_triggers(cfg: Config, triggers: Triggers | None = None) -> list[int]:
    triggers = triggers or RealTriggers()
    try:
        rows = triggers.today(cfg)
    except NotReady:
        return []
    made = []
    for row in rows:
        kind, scope = str(row.get("kind") or ""), str(row.get("scope_id") or "")
        if kind not in TRIGGER_DESKS or not store.mark_trigger(cfg, str(row.get("as_of") or ""), kind, scope):
            continue
        desk, now = TRIGGER_DESKS[kind]
        question = f"Engine trigger: {kind.replace('_', ' ')} on {scope}. Details: {row.get('detail') or 'none'}"
        rid = store.add_request(cfg, desk, question, symbol=scope if desk == "research" else None, run_now=now, source="trigger")
        store.link_trigger(cfg, str(row.get("as_of") or ""), kind, scope, rid)
        made.append(rid)
    return made


def queue_retry(cfg: Config, desk: str) -> int:
    return store.add_request(cfg, desk, "Retry of a scheduled run that hit the usage limit or found another desk running.", source="retry")
