import sqlite3

from desk.config import Config
from desk.db import connect
from desk.engine import asof
from desk.engine.lots import current_lots
from desk.engine.tax import held_long

DESKS = ("plan_keeper", "tax", "risk", "research", "scout", "skeptic", "strategy")
SECTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "plan_keeper": {
        "value": ("value.market@portfolio", "value.market@account", "value.day_change", "value.gain", "flow.net_contrib", "income.dividends"),
        "cash": ("cash.*",),
        "drift": ("plan.weight", "plan.target", "plan.drift", "plan.drift_max", "plan.in_mix", "plan.next_deposit", "plan.adherence"),
        "rules": ("plan.rules", "plan.rule_breaks", "plan.single_stock"),
        "margin": ("margin.*",),
        "benchmarks": ("bm.plan_shadow", "bm.sp500_shadow", "bm.excess"),
    },
    "tax": {
        "tax": ("tax.*",),
        "holdings": ("value.market@holding", "value.weight@holding"),
        "cash": ("cash.ready", "cash.pending", "cash.pending_days"),
        "drift": ("plan.drift", "plan.next_deposit"),
    },
    "risk": {
        "risk": ("risk.*",),
        "margin": ("margin.*",),
        "concentration": ("value.weight@holding", "plan.single_stock", "plan.rules", "plan.rule_breaks"),
        "returns": ("ret.twr@portfolio", "value.day_change", "bm.excess"),
        "signals": ("sig.dilution", "sig.earnings_days", "sig.insider_net"),
        "macro": ("macro.*",),
    },
    "research": {
        "holdings": ("value.market@holding", "value.weight@holding"),
        "signals": ("sig.*",),
        "fundamentals": ("fund.*",),
        "returns": ("ret.twr@portfolio",),
        "room": ("plan.single_stock", "plan.rules"),
    },
    "scout": {
        "room": ("plan.single_stock", "plan.rules", "cash.ready", "cash.pending"),
        "holdings": ("value.weight@holding",),
    },
    "skeptic": {
        "value": ("value.market@portfolio", "cash.ready"),
        "drift": ("plan.drift", "plan.drift_max"),
        "margin": ("margin.debit", "margin.cost_month", "margin.call_drop"),
        "risk": ("risk.top1", "risk.eff_n", "risk.lookthrough@portfolio", "risk.scenario", "risk.var95", "plan.single_stock", "value.weight@holding"),
        "tax": ("tax.wash_window", "tax.marginal_rate"),
        "signals": ("sig.*", "fund.*"),
    },
    "strategy": {
        "returns": ("ret.*",),
        "benchmarks": ("bm.*",),
        "risk": ("risk.vol", "risk.mdd", "risk.dd_now", "risk.sharpe", "risk.sortino", "risk.beta@portfolio", "risk.downside_dev"),
        "macro": ("macro.*",),
    },
}
FILING_DESKS = ("research",)
FILING_FORMS = ("10-K", "10-Q", "8-K", "4", "S-1", "S-3", "DEF 14A", "SC 13D", "SC 13G", "424B5")
FILINGS_PER_SYMBOL = 8
LOT_DESKS = ("tax",)
WASH_DESKS = ("tax", "skeptic")


class NotReady(RuntimeError):
    pass


def _matches(pattern: str, metric_id: str, scope: str) -> bool:
    name, _, want_scope = pattern.partition("@")
    if want_scope and scope != want_scope:
        return False
    return metric_id.startswith(name[:-1]) if name.endswith("*") else metric_id == name


FLAG_MEANING = "A yes or no flag, not a count: 1 means the rule holds, 0 means it is broken. plan.rule_breaks counts what breaks it."


def _item(r: sqlite3.Row) -> dict:
    item = {
        "metric_id": r["metric_id"],
        "scope": r["scope"],
        "scope_id": r["scope_id"],
        "window": r["window"],
        "value": r["value"],
        "unit": r["unit"],
        "as_of": r["as_of"],
        "quality": r["quality"],
    }
    if r["unit"] == "flag" and r["value"] is not None:
        item |= {"state": "holds" if r["value"] == 1 else "broken", "meaning": FLAG_MEANING}
    return item


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None


def _lots(conn: sqlite3.Connection, as_of: str) -> list[dict]:
    if not _has(conn, "holdings_daily"):
        return []
    closes = {r["symbol"]: r["close"] for r in conn.execute("SELECT symbol, max(close) AS close FROM holdings_daily WHERE date=? GROUP BY symbol", (as_of,))}
    out = []
    for lot in current_lots(conn):
        price = closes.get(lot["symbol"])
        value = round(lot["shares"] * price, 2) if price is not None else lot["value"]
        gain = round(value - lot["cost"], 2) if value is not None and lot["cost"] is not None else None
        out.append(
            {
                "account": lot["account"],
                "symbol": lot["symbol"],
                "acquired": lot["acquired"],
                "shares": lot["shares"],
                "cost": lot["cost"],
                "value": value,
                "gain": gain,
                "term": "long" if held_long(lot["acquired"], as_of) else "short",
            }
        )
    return out


def _filings(conn: sqlite3.Connection) -> list[dict]:
    out, seen = [], {}
    marks = ",".join("?" * len(FILING_FORMS))
    for r in conn.execute(
        f"SELECT symbol, form, filed, report_date, description, url FROM filings WHERE form IN ({marks}) ORDER BY symbol, filed DESC", FILING_FORMS
    ):
        seen[r["symbol"]] = seen.get(r["symbol"], 0) + 1
        if seen[r["symbol"]] <= FILINGS_PER_SYMBOL:
            out.append(dict(r))
    return out


def desk_slice(cfg: Config, desk: str) -> dict:
    if desk not in SECTIONS:
        raise ValueError(f"unknown desk {desk!r}")
    if not cfg.desk_db.exists():
        raise NotReady("no engine run yet")
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if not _has(conn, "metric_values"):
            raise NotReady("no engine run yet")
        as_of = conn.execute("SELECT max(as_of) FROM metric_values").fetchone()[0]
        if not as_of:
            raise NotReady("no engine run yet")
        rows = conn.execute('SELECT * FROM metric_values WHERE as_of=? ORDER BY metric_id, scope, scope_id, "window"', (as_of,)).fetchall()
        sections = {}
        for name, patterns in SECTIONS[desk].items():
            sections[name] = [_item(r) for r in rows if any(_matches(p, r["metric_id"], r["scope"]) for p in patterns)]
        if desk in LOT_DESKS:
            sections["lots"] = _lots(conn, as_of)
        if desk in FILING_DESKS and _has(conn, "filings"):
            sections["filings"] = _filings(conn)
        if desk in WASH_DESKS and _has(conn, "wash_windows"):
            sections["wash_windows"] = [dict(r) for r in conn.execute("SELECT symbol, kind, date, clears, account FROM wash_windows ORDER BY clears, symbol")]
        sections["triggers"] = (
            [dict(r) for r in conn.execute("SELECT as_of, kind, scope_id, detail FROM triggers WHERE as_of=? ORDER BY kind, scope_id", (as_of,))]
            if _has(conn, "triggers")
            else []
        )
        health = [
            {"check": r["check_name"], "status": r["status"], "detail": r["detail"]}
            for r in conn.execute("SELECT check_name, status, detail FROM data_health WHERE as_of=? ORDER BY check_name", (as_of,))
        ]
        run = conn.execute("SELECT finished_at FROM engine_runs WHERE job='core' AND ok=1 ORDER BY id DESC LIMIT 1").fetchone()
        book = asof.view(conn)
    finally:
        conn.close()
    day = {k: book[k] for k in ("day", "provisional", "words", "previous_day", "prices")}
    return {"desk": desk, "as_of": (run["finished_at"] if run else None) or as_of, "data_as_of": as_of, "day": day, "data_health": health, "sections": sections}
