from dataclasses import dataclass
from typing import Protocol

from desk.agents import alerts, store
from desk.agents.adapter import Adapter
from desk.agents.pipeline import run_proposal_desk
from desk.agents.sources import Decisions, Engine, Lab, NotReady, RealTriggers
from desk.agents.strategy import run_strategy_desk
from desk.config import Config

ASKABLE = ("plan_keeper", "tax", "risk", "research", "strategy")
TRIGGER_DESKS = {
    "margin_debit": ("risk", True),
    "daily_move": ("risk", True),
    "concentration": ("risk", True),
    "lot_export": ("tax", True),
    "earnings": ("research", False),
    "rule_breach": ("plan_keeper", True),
    "deposit_landed": ("plan_keeper", False),
}
DONE = {"ok": "done", "not_ready": "done", "disabled": "done", "unchanged": "done", "over_budget": "done"}
MAX_PER_PASS = 10


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
    return store.add_request(cfg, desk, question, symbol=(symbol or "").strip().upper() or None, run_now=run_now)


def _answer(report) -> str:
    parts = [report.summary] if report.summary else []
    if getattr(report, "memo", ""):
        parts.append(report.memo)
    if getattr(report, "queued", None):
        parts.append(f"Sent to the lab as {report.queued.name}.")
    if getattr(report, "created", None):
        parts.append(f"{len(report.created)} proposal(s) added to the queue.")
    if getattr(report, "rejected", None):
        parts.append(f"{len(report.rejected)} proposal(s) rejected by the number check.")
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
) -> Pass:
    tally = Pass()
    while tally.ran < limit:
        req = store.next_request(cfg, now_only=now_only)
        if req is None:
            break
        tally.ran += 1
        if req["desk"] == "strategy":
            report = run_strategy_desk(
                cfg, question=req["question"], strategy_id=req["symbol"], lab=lab, decisions=decisions, adapter=adapter, trigger=req["source"], wait=300
            )
        else:
            report = run_proposal_desk(
                cfg,
                req["desk"],
                engine=engine,
                decisions=decisions,
                adapter=adapter,
                trigger=req["source"],
                wait=300,
                question=req["question"],
                symbol=req["symbol"],
                lab=lab,
            )
        status = report.status
        if status in DONE:
            answer = _answer(report)
            store.finish_request(cfg, req["id"], "done", run_id=report.outcome.run_id, answer=answer, note=report.note)
            if status == "ok":
                alerts.answer_ready(cfg, req, answer)
            tally.done += 1
        elif status in ("busy", "deferred") and req["source"] != "retry" and "deferred once" not in (req["note"] or ""):
            store.requeue(cfg, req["id"], f"{status}; deferred once to tonight")
            tally.requeued += 1
            if status == "busy":
                break
        else:
            store.finish_request(cfg, req["id"], "failed", run_id=report.outcome.run_id, note=report.note)
            if status in ("busy", "deferred"):
                alerts.run_failed(cfg, req["desk"], status, report.outcome.run_id, report.note)
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
    return store.add_request(cfg, desk, "Retry of a scheduled run that hit the usage limit.", source="retry")
