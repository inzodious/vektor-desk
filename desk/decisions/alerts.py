from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.decisions.plan import upcoming_deposits
from desk.decisions.profile import active_profile
from desk.decisions.records import queue, unmatched
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

    # ---- Queue ----
    for d in queue(cfg, now=now)["items"]:
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
    return sent
