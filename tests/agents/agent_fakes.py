from dataclasses import dataclass, field

from desk.agents.sources import NotReady


def m(metric_id, scope_id, window, value, unit="usd"):
    return {"metric_id": metric_id, "scope_id": scope_id, "window": window, "value": value, "unit": unit, "as_of": "2026-11-06", "quality": "ok"}


SLICE = {
    "as_of": "2026-11-06T22:00:00Z",
    "data_health": [{"check": "reconcile", "status": "ok"}],
    "sections": {
        "drift": [m("plan.drift", "FUNDA", "now", -4.2, "pts"), m("plan.drift", "FUNDB", "now", 3.1, "pts")],
        "cash": [m("cash.ready", "portfolio", "now", 1500.0)],
        "margin": [m("margin.debit", "portfolio", "now", 0.0)],
        "triggers": [{"as_of": "2026-11-06", "kind": "earnings", "scope_id": "TICKA", "detail": "{}"}],
    },
}


def proposal(**over):
    p = {
        "kind": "deposit_route",
        "title": "Send the ready cash to FUNDA",
        "symbol": "FUNDA",
        "account": "taxable",
        "amount_usd": 1500,
        "funding": "cash",
        "thesis": "FUNDA is the most underweight fund.",
        "bear_case": None,
        "rule_served": "drift band",
        "invalidation": "Drift on FUNDA back inside 1 point",
        "horizon": "30d",
        "numbers_used": [{"field": "plan.drift:FUNDA:now", "value": -4.2}, {"field": "cash.ready:portfolio:now", "value": "$1,500"}],
        "sources": [],
        "confidence": 0.6,
        "order_ticket": {"action": "buy", "symbol": "FUNDA", "amount_usd": 1500, "order_type": "market", "account": "taxable"},
    }
    return p | over


@dataclass
class FakeEngine:
    slice_: dict | None = None

    def desk_slice(self, cfg, desk):
        if self.slice_ is None:
            raise NotReady("no engine run yet")
        return self.slice_


@dataclass
class FakeDecisions:
    ready: bool = True
    profile_data: dict = field(default_factory=dict)
    created: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    skeptic: list = field(default_factory=list)

    def profile(self, cfg):
        return "v3", self.profile_data

    def history(self, cfg, desk, limit):
        return [{"kind": "alert", "decision": "dismissed", "reason": "seen it"}]

    def create(self, cfg, p, desk, run_id):
        if not self.ready:
            raise NotReady("desk.decisions isn't built yet")
        self.created.append((desk, run_id, p))
        return {"id": len(self.created), "status": "queued"}

    def attach_skeptic(self, cfg, decision_id, verdict, counter_case):
        self.skeptic.append((decision_id, verdict, counter_case))

    def reject(self, cfg, p, desk, reason, run_id):
        if not self.ready:
            raise NotReady("desk.decisions isn't built yet")
        self.rejected.append((desk, reason))
        return {"status": "rejected", "reason": reason}


def answer(*proposals, summary="Plan on track. FUNDA is 4.2 points under."):
    return {"summary": summary, "proposals": list(proposals)}
