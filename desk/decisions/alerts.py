from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.decisions.plan import upcoming_deposits
from desk.decisions.plans import LOT_TEXT, approved_plans
from desk.decisions.profile import active_profile
from desk.decisions.records import notes, queue, unmatched
from desk.decisions.risk import convictions
from desk.decisions.store import loads, session
from desk.notify import PRIORITIES, publish

ONCE = 24 * 400
URGENT_DESKS = ("tax", "risk")
DESK_NAMES = {
    "plan_keeper": "Plan keeper",
    "tax": "Tax desk",
    "risk": "Risk desk",
    "research": "Research desk",
    "skeptic": "Skeptic",
    "scout": "Scout",
    "strategy": "Strategy desk",
    "you": "Your draft",
}
RECENT_TRADE_DAYS = 3
TRADE_BATCH = 3


def item_priority(d: dict, now: datetime) -> str:
    if d["kind"] in ("memo", "alert"):
        return "low"
    soon = d["expires_at"] and datetime.fromisoformat(d["expires_at"]) - now <= timedelta(hours=24)
    if d["preflight_status"] in ("flagged", "blocked") or d["origin"] in URGENT_DESKS or soon:
        return "high"
    return "default"


def _send(sent: list[str], cfg: Config, floor: int, topic: str, title: str, body: str, priority: str, click: str, key: str, tags=()) -> None:
    if PRIORITIES[priority] < floor:
        return
    if publish(topic, title, body, priority, tags=tags, click=click, key=key, dedupe_hours=ONCE, cfg=cfg):
        sent.append(key)


def send_alerts(cfg: Config, *, now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    today = now.astimezone(ZoneInfo(cfg.timezone)).date()
    floor = PRIORITIES[active_profile(cfg).get("alerts", "min_priority", default="default")]
    sent: list[str] = []

    # ---- Queue and notes ----
    for d in [*queue(cfg, now=now)["items"], *notes(cfg, days=1, now=now)["items"]]:
        if d["origin"] == "you":
            continue
        priority = item_priority(d, now)
        lit = {"blocked": " Preflight lit up.", "flagged": " Preflight has a heads-up."}.get(d["preflight_status"], "")
        _send(
            sent,
            cfg,
            floor,
            "research",
            f"{DESK_NAMES.get(d['origin'], d['origin'])}: {d['title']}",
            (d["thesis"] or "") + lit,
            priority,
            f"/decisions?d={d['id']}",
            f"proposal-{d['id']}",
            ("inbox_tray",),
        )

    # ---- Deposits ----
    for d in upcoming_deposits(cfg, days=0, now=now):
        if d["status"] == "late":
            _send(
                sent,
                cfg,
                floor,
                "alerts",
                f"Deposit {d['id']} hasn't shown up yet",
                f"It usually lands around {d['date']} in {d['account'] or 'the account'}. If you changed it on purpose, there's nothing to do.",
                "default",
                "/plan",
                f"deposit-late-{d['id']}-{d['date']}",
                ("hourglass",),
            )

    # ---- Unmatched trades ----
    since = (today - timedelta(days=RECENT_TRADE_DAYS)).isoformat()
    fresh = [t for t in unmatched(cfg, days=RECENT_TRADE_DAYS, now=now) if str(t["date"]) >= since]
    if 0 < len(fresh) <= TRADE_BATCH:
        for t in fresh:
            _send(
                sent,
                cfg,
                floor,
                "alerts",
                f"{t['kind'].capitalize()} {t['symbol']} has no decision record",
                f"Seen at the broker on {t['date']}. Log it from the Journal so the scorecard counts it.",
                "default",
                "/decisions/journal",
                f"unmatched-{t['activity_id']}",
                ("memo",),
            )
    elif fresh:
        ids = ",".join(sorted(t["activity_id"] for t in fresh))
        _send(
            sent,
            cfg,
            floor,
            "alerts",
            f"{len(fresh)} trades have no decision record",
            "Log them from the Journal so the scorecard counts them.",
            "default",
            "/decisions/journal",
            f"unmatched-batch-{ids}",
            ("memo",),
        )

    # ---- Wash-sale windows ----
    with session(cfg) as conn:
        rows = conn.execute(
            "SELECT id, symbol, tax_impact FROM decisions WHERE status IN ('approved', 'placed', 'filled') AND tax_impact IS NOT NULL"
        ).fetchall()
    for r in rows:
        clear = str((loads(r["tax_impact"]) or {}).get("wash_clear_date") or "")[:10]
        if clear == today.isoformat():
            _send(
                sent,
                cfg,
                floor,
                "alerts",
                f"{r['symbol']} wash-sale window clears today",
                f"Buying {r['symbol']} again no longer disallows the loss.",
                "default",
                "/plan",
                f"wash-{r['id']}-{clear}",
                ("calendar",),
            )

    # ---- Stock plans ----
    for p in approved_plans(cfg, now=now):
        if p["next_review"] == today.isoformat():
            _send(
                sent,
                cfg,
                floor,
                "alerts",
                f"{p['symbol']} plan is up for review",
                "Give the thesis a fresh look.",
                "default",
                "/plan",
                f"plan-review-{p['symbol']}-{p['next_review']}",
                ("calendar",),
            )
        for s in p["steps"]:
            if s["due"] == today.isoformat() and s["status"] == "open":
                window = f"Open until {s['until']}." if s["until"] and s["until"] != s["due"] else "Due today."
                body = " ".join(x for x in (window, f"Lots: {LOT_TEXT[s['lots']]}." if s["lots"] else "", s["note"] or "") if x)
                _send(
                    sent,
                    cfg,
                    floor,
                    "alerts",
                    f"{p['symbol']}: {s['text']}",
                    body,
                    "default",
                    "/plan",
                    f"plan-step-{p['symbol']}-{s['id']}-{s['due']}",
                    ("calendar",),
                )
            if s["rebuy_on"] == today.isoformat():
                body = f"{s['no_buy_days']} days have passed since the sale on {s['done_on']}."
                _send(
                    sent,
                    cfg,
                    floor,
                    "alerts",
                    f"{p['symbol']} buys are fine again",
                    body,
                    "default",
                    "/plan",
                    f"plan-rebuy-{p['symbol']}-{s['id']}-{s['rebuy_on']}",
                    ("calendar",),
                )

    # ---- Conviction holds ----
    week = "{}-W{:02d}".format(*today.isocalendar()[:2])
    for c in convictions(cfg):
        if c["enabled"] and c["status"] == "above":
            _send(
                sent,
                cfg,
                floor,
                "alerts",
                f"{c['symbol']} is above its band",
                f"{c['symbol']} is {c['weight_pct']:g}% of the portfolio, past your {c['band_max_pct']:g}% ceiling. No rush: trimming back is an option, "
                "and the desk won't suggest adding until it's back inside.",
                "default",
                "/plan",
                f"conviction-{c['symbol']}-{week}",
                ("balance_scale",),
            )
    return sent
