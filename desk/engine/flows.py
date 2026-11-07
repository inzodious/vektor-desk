import sqlite3
from collections import defaultdict
from datetime import date

from desk.engine.holdings import CASH_SYMBOLS

EXTERNAL_KINDS = {"deposit", "withdrawal"}
INCOME_KINDS = {"dividend", "interest"}
PAIR_DAYS = 3


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def classify(activity: list[dict]) -> list[dict]:
    flows = []
    for r in activity:
        kind = r.get("kind")
        symbol = str(r.get("symbol") or "").upper()
        amount = _f(r.get("amount"))
        if kind not in EXTERNAL_KINDS or not amount or r.get("core") or symbol in CASH_SYMBOLS:
            continue
        flows.append(
            {
                "date": str(r.get("date") or "")[:10],
                "account": str(r.get("accountKey") or "account"),
                "amount": round(amount, 2),
                "kind": kind,
                "action": str(r.get("action") or ""),
                "ref": str(r.get("key") or r.get("id") or ""),
                "external_account": 1,
                "external_portfolio": 1,
            }
        )
    flows.sort(key=lambda f: (f["date"], f["account"], f["amount"]))
    out_by_amount: dict[float, list[dict]] = defaultdict(list)
    for f in flows:
        if f["amount"] < 0:
            out_by_amount[-f["amount"]].append(f)
    for f in flows:
        if f["amount"] <= 0 or not f["external_portfolio"]:
            continue
        for g in out_by_amount.get(f["amount"], []):
            if g["external_portfolio"] and g["account"] != f["account"]:
                gap = abs((date.fromisoformat(f["date"]) - date.fromisoformat(g["date"])).days)
                if gap <= PAIR_DAYS:
                    f["external_portfolio"] = g["external_portfolio"] = 0
                    break
    return flows


def income(activity: list[dict]) -> list[tuple[str, str, str, float]]:
    out = []
    for r in activity:
        if r.get("kind") in INCOME_KINDS and _f(r.get("amount")) > 0:
            out.append(
                (str(r.get("date") or "")[:10], str(r.get("accountKey") or "account"), str(r.get("symbol") or "").upper(), round(_f(r.get("amount")), 2))
            )
    return out


def store(conn: sqlite3.Connection, flows: list[dict]) -> None:
    conn.execute("DELETE FROM cash_flows")
    conn.executemany(
        "INSERT INTO cash_flows (date, account, amount, kind, external_account, external_portfolio, ref) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(f["date"], f["account"], f["amount"], f["kind"], f["external_account"], f["external_portfolio"], f["ref"]) for f in flows],
    )
