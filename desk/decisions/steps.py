from datetime import date, datetime, timedelta

from desk.config import Config
from desk.decisions.plan import AUTO, LAND_WINDOW_DAYS, _today, upcoming_deposits
from desk.decisions.plans import BUYS, LOT_TEXT, SELLS, approved_plans
from desk.decisions.profile import active_profile, margin_rate
from desk.decisions.records import _now, day_words, local_day, now_iso, tidy, to_dict
from desk.decisions.rules import active_rules
from desk.decisions.store import session

DAYS = 90
AGREED_DAYS = 30
WHY_MAX = 240
READINGS = {
    "yes": "The lab's test backs this.",
    "no_edge": "The lab's test shows no clear edge either way.",
    "no": "The lab's test does not back this.",
    "untested": "The lab has not judged this yet.",
}
EVIDENCE = {
    "repay": ("lib-margin-paydown", "for"),
    "harvest": ("lib-harvest", "for"),
    "route": ("lib-deposit-steering", "for"),
    "no_margin_buys": ("lib-margin-dip", "against"),
}
VERDICT_BACKS = {"held_up": "yes", "within_noise": "no_edge", "fell_short": "no"}
MARGIN_WHY = "The debit costs about {rate:g}% a year, more than a deposit usually earns on the same money."
KIND_WHY = {
    "repay": MARGIN_WHY,
    "harvest": "A sale below your cost books the loss against this year's taxes.",
}
KIND_CHANGES = {
    "repay": "Retires by itself once the margin debit reads zero.",
    "harvest": "No longer worth doing if {symbol} is back above your cost.",
}
PLAN_CHANGES = "Changes when you approve a new version of the {symbol} plan."
RULES = {
    "no_margin_buys": ("No new buys on margin", "Borrowed money costs about {rate:g}% a year whether or not the buy works out."),
    "no_new_single_stocks": ("No new single stocks", None),
}
RULE_CHANGES = "Changes only when you edit your rules in Settings."
DESK_NAMES = {
    "plan_keeper": "Plan keeper",
    "tax": "Tax desk",
    "risk": "Risk desk",
    "research": "Research desk",
    "scout": "Scout",
    "strategy": "Strategy desk",
}


# ---- Evidence ----


def _backs(row: dict) -> str | None:
    if row.get("status") != "tested" or row.get("outdated"):
        return None
    stats = row.get("rule") or {}
    if stats.get("share_better") is not None:
        if stats["share_better"] > 0.5:
            return "yes"
        if (stats.get("share_worse") or 0) > 0.5:
            return "no"
    return VERDICT_BACKS.get(row.get("verdict"))


def _library(cfg: Config, ids: list[str]) -> dict[str, dict]:
    try:
        from desk.engine.lab import shelf
    except ImportError:
        return {}
    try:
        lookup = getattr(shelf, "rows", None)
        if lookup:
            return dict(lookup(cfg, ids))
        return {r["id"]: r | {"backs": _backs(r)} for r in shelf.view(cfg)["rows"] if r["id"] in ids}
    except Exception:  # noqa: BLE001
        return {}


def _cite(rows: dict[str, dict], key: str) -> list[dict]:
    if key not in EVIDENCE:
        return []
    row_id, stance = EVIDENCE[key]
    r = rows.get(row_id) or {}
    backs = r.get("backs")
    if stance == "against" and backs in ("yes", "no"):
        backs = "no" if backs == "yes" else "yes"
    reading = backs or "untested"
    return [
        {
            "row": row_id,
            "title": r.get("title"),
            "sentence": r.get("line"),
            "verdict": r.get("verdict"),
            "tested_at": r.get("tested_at"),
            "stance": stance,
            "reading": reading,
            "words": READINGS[reading],
        }
    ]


# ---- Rows ----


def _row(rid: str, text: str, source: str, *, evidence: list[dict] | None = None, **more) -> dict:
    base = {"id": rid, "symbol": None, "date": None, "until": None, "text": text, "detail": None, "why": None, "basis": None}
    base |= {"changes_if": None, "source": source, "ref": None, "status": None, "completes": None, "when": None}
    evidence = evidence or []
    return base | more | {"evidence": evidence, "backed": evidence[0]["reading"] if evidence else None}


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    head = text.strip().split(". ")[0].strip()
    head = head if len(head) <= WHY_MAX else head[: WHY_MAX - 1].rstrip() + "…"
    return head if head.endswith((".", "!", "?", "…")) else head + "."


def _plan_rows(plans: list[dict], ahead: str, lib: dict, rate: float, tz: str) -> tuple[list[dict], list[dict], list[dict]]:
    dated, undated, windows = [], [], []
    for p in plans:
        sym = p["symbol"]
        basis = f"Your {sym} plan, version {p['version']}, approved {day_words(p['approved_at'], tz)}."
        held = False
        for s in p["steps"]:
            if s["no_buy_now"] and not held:
                held = True
                until = f"until {day_words(s['rebuy_on'], tz)}" if s["rebuy_on"] else f"until {s['no_buy_days']} days after the sale"
                windows.append(
                    _row(
                        f"nobuy:{sym}",
                        f"No {sym} buys in any account {until}",
                        "plan",
                        symbol=sym,
                        until=s["rebuy_on"],
                        why=f"A buy within {s['no_buy_days']} days of a loss sale cancels the tax loss (the wash-sale rule).",
                        basis=basis,
                        changes_if="Ends by itself.",
                        ref={"symbol": sym, "version": p["version"], "step_id": s["id"]},
                        completes="desk",
                    )
                )
            if s["status"] in ("done", "passed") or (s["status"] == "upcoming" and s["due"] > ahead):
                continue
            kind = s["kind"]
            parts = [f"From {s['account']}." if s["account"] else None, f"Lots: {LOT_TEXT[s['lots']]}." if s["lots"] else None]
            why = KIND_WHY.get(kind, "").format(rate=rate) or _first_sentence(p["thesis"])
            row = _row(
                f"plan:{sym}:{s['id']}",
                s["text"],
                "plan",
                symbol=sym,
                date=s["due"],
                until=s["until"] if s["until"] and s["until"] != s["due"] else None,
                detail=" ".join(x for x in parts if x) or None,
                why=_first_sentence(s["note"]) or why,
                basis=basis,
                changes_if=KIND_CHANGES.get(kind, PLAN_CHANGES).format(symbol=sym),
                ref={"symbol": sym, "version": p["version"], "step_id": s["id"], "kind": kind},
                status=s["status"],
                completes="broker" if kind in BUYS + SELLS else "desk" if kind == "repay" else "you",
                when=s["when"],
                evidence=_cite(lib, kind),
            )
            (dated if s["due"] else undated).append(row)
    return dated, undated, windows


def _debit(conn) -> tuple[float, str] | None:
    try:
        r = conn.execute(
            "SELECT value, as_of FROM metric_values WHERE metric_id='margin.debit' AND scope='portfolio' AND value IS NOT NULL ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return (float(r["value"]), str(r["as_of"])[:10]) if r else None


def _about_margin(d: dict) -> bool:
    return d["subject"] == "margin" or "margin" in f"{d['title']} {d['rule_served'] or ''}".lower()


def _agreed(conn, since: str, debit: tuple[float, str] | None, tz: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM decisions WHERE status='done' AND kind='hold_off' AND origin != 'you' AND decided_at >= ? ORDER BY decided_at DESC, rowid DESC", (since,)
    ).fetchall()
    seen: set[tuple[str, str]] = set()
    out = []
    for r in rows:
        d = to_dict(r)
        key = (d["origin"], d["subject"] or d["title"])
        if key in seen:
            continue
        seen.add(key)
        d["margin"] = _about_margin(d)
        if d["margin"] and debit and debit[0] <= 1 and debit[1] >= local_day(d["decided_at"], tz):
            continue
        out.append(d)
    return out


def _agreed_row(d: dict, lib: dict, tz: str) -> dict:
    ends = (date.fromisoformat(local_day(d["decided_at"], tz)) + timedelta(days=AGREED_DAYS)).isoformat()
    fallback = "Ends by itself when the margin debit is paid off." if d["margin"] else f"Drops off this list on {day_words(ends, tz)}."
    return _row(
        f"agreed:{d['id']}",
        d["title"],
        "agreed",
        symbol=d["symbol"],
        until=None if d["margin"] else ends,
        why=_first_sentence(d["thesis"]),
        basis=f"You agreed to this {DESK_NAMES.get(d['origin'], 'desk')} note on {day_words(d['decided_at'], tz)}.",
        changes_if=d["invalidation"] or fallback,
        ref={"decision_id": d["id"]},
        completes="desk",
        evidence=_cite(lib, "repay") if d["margin"] else [],
    )


def _routes(conn) -> tuple[dict | None, dict | None]:
    approved = conn.execute("SELECT * FROM decisions WHERE status='approved' AND kind='deposit_route' ORDER BY decided_at DESC LIMIT 1").fetchone()
    waiting = conn.execute(
        "SELECT * FROM decisions WHERE status='proposed' AND kind='deposit_route' AND origin != 'you' ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return (to_dict(approved) if approved else None, to_dict(waiting) if waiting else None)


def _deposit_rows(deposits: list[dict], today: str, dated: list[dict], agreed: list[dict], routes: tuple, lib: dict, rate: float, tz: str) -> list[dict]:
    out = []
    repay = next((r for r in dated if r["ref"]["kind"] == "repay"), None)
    note = next((d for d in agreed if d["margin"]), None)
    approved, waiting = routes
    first = True
    for d in deposits:
        if d["status"] != "expected" or d["date"] < today:
            continue
        head = f"Deposit of ${d['amount_usd']:,.0f} lands" if d["amount_usd"] else "A deposit lands"
        more = {"date": d["date"], "status": "upcoming", "ref": {"deposit_id": d["id"]}, "detail": f"Into {d['account']}." if d["account"] else None}
        near = repay and d["date"] >= (date.fromisoformat(repay["date"]) - timedelta(days=LAND_WINDOW_DAYS)).isoformat()
        margin = {
            "why": MARGIN_WHY.format(rate=rate),
            "changes_if": "Retires by itself once the margin debit reads zero. If one deposit does not clear it, the next one picks this up.",
            "completes": "desk",
            "evidence": _cite(lib, "repay"),
        }
        if near:
            dated.remove(repay)
            row = _row(f"deposit:{d['id']}:{d['date']}", f"{head} and pays the margin debit", "deposit", **more, **margin, basis=repay["basis"])
            row["ref"] |= {k: repay["ref"][k] for k in ("symbol", "version", "step_id")}
            repay = None
        elif first and note and not repay:
            basis = f"You agreed to this {DESK_NAMES.get(note['origin'], 'desk')} note on {day_words(note['decided_at'], tz)}."
            row = _row(f"deposit:{d['id']}:{d['date']}", f"{head} and goes to the margin debit first", "deposit", **more, **margin, basis=basis)
            row["ref"]["decision_id"] = note["id"]
        elif first and (approved or waiting):
            route = approved or waiting
            words = f"{head}: {route['title']}" if approved else f"{head}. The Plan keeper's route for it is waiting in your queue: {route['title']}"
            basis = f"You approved this route on {day_words(route['decided_at'], tz)}." if approved else "Waiting on your decision."
            changes = "Changes if you pass on the route or approve a newer one." if approved else "Yours to approve, change or pass on."
            row = _row(
                f"deposit:{d['id']}:{d['date']}",
                words,
                "deposit",
                **more,
                why=_first_sentence(route["thesis"]),
                basis=basis,
                changes_if=changes,
                completes="broker" if approved else "you",
                evidence=_cite(lib, "route"),
            )
            row["ref"]["decision_id"] = route["id"]
        elif first:
            basis = "From the pattern of your past deposits." if d["mode"] == AUTO else "From your deposit schedule."
            row = _row(f"deposit:{d['id']}:{d['date']}", f"{head}. Nothing is planned for it yet", "deposit", **more, basis=basis, completes="desk")
        else:
            continue
        first = False
        out.append(row)
    return out


def _rule_rows(cfg: Config, lib: dict, rate: float) -> list[dict]:
    try:
        version, rules = active_rules(cfg)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rules:
        if r["kind"] not in RULES:
            continue
        text, why = RULES[r["kind"]]
        out.append(
            _row(
                f"rule:{r['id']}",
                text,
                "rule",
                why=why.format(rate=rate) if why else None,
                basis="One of your rules.",
                changes_if=RULE_CHANGES,
                ref={"rule_id": r["id"], "rules_version": version},
                evidence=_cite(lib, r["kind"]),
            )
        )
    return out


# ---- The list ----


def next_steps(cfg: Config, *, days: int = DAYS, now: datetime | None = None) -> dict:
    moment = _now(now)
    tz = cfg.timezone
    today = _today(cfg, moment)
    days = max(0, min(int(days), 366))
    ahead = (today + timedelta(days=days)).isoformat()
    rate = margin_rate(active_profile(cfg).data)["rate_pct"]
    lib = _library(cfg, sorted({row for row, _ in EVIDENCE.values()}))
    dated, undated, windows = _plan_rows(approved_plans(cfg, now=moment), ahead, lib, rate, tz)
    with session(cfg) as conn:
        tidy(cfg, conn, now_iso(moment))
        debit = _debit(conn)
        agreed = _agreed(conn, now_iso(moment - timedelta(days=AGREED_DAYS)), debit, tz)
        routes = _routes(conn)
    dated += _deposit_rows(upcoming_deposits(cfg, days=days, now=moment), today.isoformat(), dated, agreed, routes, lib, rate, tz)
    items = sorted(dated, key=lambda r: (r["date"], r["symbol"] or "", r["id"]))
    standing = [*windows, *(_agreed_row(d, lib, tz) for d in agreed), *_rule_rows(cfg, lib, rate), *undated]
    return {"as_of": today.isoformat(), "days": days, "count": len(items), "items": items, "standing": standing, "readings": READINGS}
