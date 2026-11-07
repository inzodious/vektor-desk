import json
from datetime import UTC, datetime

from desk.config import Config
from desk.decisions import records

cfg = Config.from_env()

SRC = [
    {"url": "https://example.com/synthetic/fund-factsheet", "title": "Synthetic fund factsheet", "date": "2026-11-02"},
    {"url": "https://example.com/synthetic/index-weights", "title": "Synthetic index weights", "date": "2026-11-05"},
]


def at(day, hour):
    return datetime(2026, 11, day, hour, 5, tzinfo=UTC)


route = records.create_proposal(
    cfg,
    {
        "kind": "deposit_route",
        "symbol": "VXUS",
        "account": "individual-0001",
        "amount_usd": 180,
        "funding": "deposit",
        "thesis": "VXUS is the most under target. Routing part of the next deposit there pulls it back without selling anything.",
        "rule_served": "drift-max",
        "horizon": "next deposit",
        "confidence": 0.8,
        "numbers_used": [{"metric_id": "plan.drift", "scope_id": "VXUS", "value": -1.3, "unit": "pts"}],
        "sources": [],
    },
    "plan_keeper",
    run_id="r-seed-1",
    now=at(9, 13),
)

trim = records.create_proposal(
    cfg,
    {
        "kind": "trim",
        "symbol": "FTEC",
        "account": "individual-0001",
        "amount_usd": 150,
        "funding": "sale_proceeds",
        "title": "Trim $150 FTEC",
        "thesis": "FTEC is 1.2 pts over target after a strong month. A small trim keeps the tech tilt inside the plan.",
        "bear_case": "Momentum could carry on for months, and a trim gives up some of that upside.",
        "invalidation": "Drift falls back under 1 pt on its own before the next deposit.",
        "rule_served": "drift-max",
        "horizon": "1 month",
        "confidence": 0.6,
        "numbers_used": [{"metric_id": "plan.drift", "scope_id": "FTEC", "value": 1.2, "unit": "pts"}],
        "sources": SRC,
    },
    "plan_keeper",
    run_id="r-seed-1",
    now=at(9, 13),
)
records.attach_skeptic(
    cfg, trim["id"], "flag", "1.2 pts is well inside the 5 pt band. Routing deposits away from FTEC does the same thing with no sale and no tax.", now=at(9, 13)
)

margin = records.create_proposal(
    cfg,
    {
        "kind": "buy",
        "symbol": "ACME",
        "account": "individual-0001",
        "amount_usd": 400,
        "funding": "margin",
        "thesis": "ACME reports next week and the synthetic launch schedule looks strong.",
        "bear_case": "Single-name launch risk; one scrub resets the timeline and the price.",
        "invalidation": "A launch slips past the quarter.",
        "horizon": "3 months",
        "confidence": 0.35,
        "numbers_used": [{"metric_id": "plan.single_stock", "scope_id": "all", "value": 0.5, "unit": "pct"}],
        "sources": SRC,
    },
    "research",
    run_id="r-seed-2",
    now=at(9, 14),
)
records.attach_skeptic(cfg, margin["id"], "flag", "Borrowing at margin rates for a single-name earnings bet breaks two of your own rules.", now=at(9, 14))
records.attach_skeptic(cfg, route["id"], "pass", "Deposit routing with no sale and no tax. Nothing to argue with.", now=at(9, 13))

hold = records.create_proposal(
    cfg,
    {
        "kind": "hold_off",
        "symbol": "BND",
        "title": "Hold off on new BND until the rate decision",
        "thesis": "BND is on target. Nothing to add before the synthetic rate decision on Nov 18.",
        "horizon": "2 weeks",
        "confidence": 0.7,
        "sources": [],
    },
    "risk",
    run_id="r-seed-3",
    now=at(9, 14),
)

old = records.create_proposal(
    cfg,
    {
        "kind": "deposit_route",
        "symbol": "FXAIX",
        "account": "individual-0001",
        "amount_usd": 300,
        "funding": "deposit",
        "thesis": "Core fund gets its share of the monthly deposit.",
        "rule_served": "drift-max",
        "confidence": 0.9,
    },
    "plan_keeper",
    run_id="r-seed-0",
    now=at(2, 13),
)
records.approve(cfg, old["id"], "Monthly routine", now=at(2, 14))
records.mark_placed(cfg, old["id"], shares=1.445713, price=207.51, now=at(2, 15))

skip = records.create_proposal(
    cfg,
    {
        "kind": "rebalance",
        "symbol": "BND",
        "account": "hsa-0002",
        "amount_usd": 40,
        "funding": "cash",
        "thesis": "Top up BND in the HSA.",
        "confidence": 0.5,
    },
    "plan_keeper",
    run_id="r-seed-0",
    now=at(4, 13),
)
records.dismiss(cfg, skip["id"], "Too small to bother with", now=at(4, 16))

print(json.dumps({k: v["id"] for k, v in {"route": route, "trim": trim, "margin": margin, "hold": hold, "old": old, "skip": skip}.items()}))
for d in (route, trim, margin, hold):
    print(d["id"], d["status"], d.get("status_reason"), d["preflight_status"])

ready = records.create_proposal(
    cfg,
    {
        "kind": "deposit_route",
        "symbol": "BND",
        "account": "hsa-0002",
        "amount_usd": 25,
        "funding": "deposit",
        "thesis": "BND gets its slice of the HSA deposit.",
        "rule_served": "drift-max",
        "confidence": 0.8,
    },
    "plan_keeper",
    run_id="r-seed-4",
    now=at(6, 13),
)
records.approve(cfg, ready["id"], None, now=at(6, 14))
print("ready", ready["id"])

# ---------- agent runs and the brief ----------
from desk.agents import store  # noqa: E402

RUNS = [
    ("plan_keeper", "schedule", "timeout", "2026-11-04T22:30:00+00:00", 600000, 14, 61000, "Stopped at the 10 minute limit"),
    ("plan_keeper", "schedule", "ok", "2026-11-05T22:30:00+00:00", 212000, 6, 38400, None),
    ("research", "schedule", "ok", "2026-11-04T06:00:00+00:00", 431000, 11, 94200, "Dossier: ACME"),
    ("skeptic", "after_proposal", "ok", "2026-11-04T06:08:00+00:00", 64000, 2, 12800, None),
    ("risk", "schedule", "not_ready", "2026-11-01T07:00:00+00:00", 0, 0, 0, "Waiting on 30 days of history"),
    ("tax", "schedule", "unchanged", "2026-11-07T07:00:00+00:00", 0, 0, 0, "Nothing changed since the last run"),
    ("plan_keeper", "schedule", "ok", "2026-11-06T22:30:00+00:00", 198000, 5, 36100, None),
]
BRIEF = "\n".join(
    [
        "You are $883 behind the plan shadow this year, mostly from the tech tilt.",
        "Largest drift is VXUS at -1.3 pts, well inside the 5 pt band.",
        "$142 cash is ready and a $500 deposit is modelled for next week.",
        "Nothing needs you today. The VXUS deposit route is the one to look at.",
    ]
)

with store.db(cfg) as conn:
    last = None
    for desk, trigger, status, started, ms, turns, tokens, note in RUNS:
        end = datetime.fromisoformat(started).timestamp() + ms / 1000
        cur = conn.execute(
            "INSERT INTO agent_runs (desk, trigger, status, started_at, finished_at, model, effort, turns, "
            "input_tokens, output_tokens, cache_tokens, duration_ms, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                desk,
                trigger,
                status,
                started,
                datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds"),
                "opus",
                "high",
                turns,
                tokens // 2,
                tokens // 4,
                tokens - tokens // 2 - tokens // 4,
                ms,
                note,
            ),
        )
        if desk == "plan_keeper" and status == "ok":
            last = cur.lastrowid
    conn.execute(
        "INSERT OR REPLACE INTO agent_briefs (run_id, desk, as_of, digest, profile_version, summary, answer, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (last, "plan_keeper", "2026-11-06", "seed", "1", BRIEF, "{}", "2026-11-06T22:33:18+00:00"),
    )
print("brief run", last)
