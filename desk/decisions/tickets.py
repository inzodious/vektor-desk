from desk.decisions.records import SELL_KINDS, TRADE_KINDS, side_of

STAMPS = {"proposed": "DRAFT", "snoozed": "DRAFT", "approved": "READY", "placed": "PLACED", "filled": "FILLED"}
LOT_LABELS = {
    "highest_cost": "Specific shares: highest cost first",
    "lowest_cost": "Specific shares: lowest cost first",
    "fifo": "First in, first out",
    "lifo": "Last in, first out",
    "tax_efficient": "Tax efficient",
}


def _money(value) -> str:
    return f"${value:,.2f}"


def ticket(d: dict, lot_method: str | None = None) -> dict:
    if d["kind"] not in TRADE_KINDS:
        return {"stamp": None, "fields": [], "text": ""}
    t = d.get("order_ticket") or {}
    side = side_of(d) or "buy"
    action = str(t.get("action") or ("Sell" if side == "sell" else "Buy")).capitalize()
    quantity = t.get("quantity", d["shares"])
    order_type = str(t.get("order_type") or ("limit" if t.get("limit") is not None else "market")).capitalize()
    fields = [
        ("Account", t.get("account") or d["account"] or "Choose at the broker"),
        ("Action", action),
        ("Symbol", t.get("symbol") or d["symbol"]),
        ("Quantity", f"{quantity:g} shares" if quantity else _money(d["amount_usd"]) if d["amount_usd"] is not None else ""),
        ("Order type", order_type),
    ]
    if t.get("limit") is not None:
        fields.append(("Limit price", _money(float(t["limit"]))))
    if d["kind"] in SELL_KINDS or side == "sell":
        method = t.get("lot_method") or lot_method
        if method:
            fields.append(("Lots", LOT_LABELS.get(method, str(method))))
    fields.append(("Time in force", str(t.get("time_in_force") or "Day").capitalize()))
    rows = [{"label": k, "value": str(v)} for k, v in fields if v not in (None, "")]
    return {"stamp": STAMPS.get(d["status"]), "fields": rows, "text": "\n".join(f"{r['label']}: {r['value']}" for r in rows)}
