import sqlite3

from desk.agents.sources import Advisor, NotReady, RealAdvisor
from desk.config import Config

RISK_FIELDS = ("band", "equity_min_pct", "equity_max_pct", "speculative_max_pct", "single_stock_max_pct", "worst_year_loss_pct")
CATALOG_FIELDS = ("risk_rank", "worst_year_p10_pct", "p50_value_10y", "chance_fi", "sharpe", "max_drawdown_pct")
CATALOG_LABELS = ("id", "name", "fit", "proxy_note")
FAILS = (NotReady, ValueError, OSError, sqlite3.Error)
STEPS_AHEAD_DAYS = 60
STEP_FIELDS = ("symbol", "kind", "due", "until", "status", "purpose")


def gather(cfg: Config, source: Advisor | None = None) -> dict:
    source = source or RealAdvisor()
    view: dict = {"risk_profile": None, "catalog": [], "convictions": [], "planned_actions": [], "missing": []}
    for name, fn in (("risk_profile", source.risk), ("catalog", source.catalog), ("convictions", source.convictions), ("planned_actions", source.actions)):
        try:
            view[name] = fn(cfg) or view[name]
        except FAILS:
            view["missing"].append(name)
    if view["risk_profile"] is None and "risk_profile" not in view["missing"]:
        view["missing"].append("risk_profile")
    try:
        view["no_buy"] = dict(source.no_buy(cfg) or {}) if hasattr(source, "no_buy") else {}
    except FAILS:
        view["no_buy"] = {}
    try:
        rows = source.steps(cfg, STEPS_AHEAD_DAYS) if hasattr(source, "steps") else []
        view["plan_steps"] = [{k: s.get(k) for k in STEP_FIELDS} for s in rows or () if isinstance(s, dict)]
    except FAILS:
        view["plan_steps"] = []
    return view


def no_buy_until(view: dict, symbol: object, today: str) -> str | None:
    window = (view.get("no_buy") or {}).get(str(symbol or "").upper())
    if not isinstance(window, dict):
        return None
    start, until = str(window.get("from") or "")[:10], str(window.get("until") or "")[:10]
    if (start and start > today) or (until and until < today):
        return None
    return until or "the window ends"


def _item(metric_id: str, scope: str, scope_id: str, value: object, unit: str) -> dict:
    return {"metric_id": metric_id, "scope": scope, "scope_id": scope_id, "window": "now", "value": value, "unit": unit, "quality": "ok"}


def _unit(field: str) -> str:
    if field.endswith("_pct"):
        return "pct"
    if field.startswith("p50_value"):
        return "usd"
    return "ratio" if field in ("chance_fi", "sharpe") else "level"


def items(view: dict) -> list[dict]:
    out = []
    risk = view.get("risk_profile") or {}
    for f in RISK_FIELDS:
        if isinstance(risk.get(f), int | float) and not isinstance(risk.get(f), bool):
            out.append(_item(f"risk.{f}", "portfolio", "all", risk[f], _unit(f)))
    for row in view.get("catalog") or ():
        sid = str(row.get("id") or "")
        for f in CATALOG_FIELDS:
            v = row.get(f)
            if sid and isinstance(v, int | float) and not isinstance(v, bool):
                out.append(_item(f"catalog.{f}", "strategy", sid, v, _unit(f)))
    return out


def summary(view: dict) -> dict:
    risk = view.get("risk_profile")
    return {
        "risk_band": {k: risk.get(k) for k in ("band", "label", "limited_by", "tolerance_band", "capacity_band", "version", "answered_at") if k in risk}
        if risk
        else None,
        "catalog": [{k: r.get(k) for k in CATALOG_LABELS if k in r} for r in view.get("catalog") or ()],
        "convictions": view.get("convictions") or [],
        "planned_actions": view.get("planned_actions") or [],
        "upcoming_steps": view.get("plan_steps") or [],
        "no_buy": view.get("no_buy") or {},
        "missing": view.get("missing") or [],
    }


def attach(slice_: dict, view: dict) -> dict:
    sections = dict(slice_.get("sections") or {})
    sections["advisor"] = items(view)
    return slice_ | {"sections": sections}
