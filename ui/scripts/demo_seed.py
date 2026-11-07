import json
import random
from datetime import UTC, datetime, timedelta

from desk.config import Config
from desk.decisions import records
from desk.decisions.records import DecisionError

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

# ---------- research ----------
import math  # noqa: E402
import sqlite3  # noqa: E402
from datetime import date  # noqa: E402

EDGAR = "https://www.sec.gov/edgar/search/"
FRED = "https://fred.stlouisfed.org/series/"
rng = random.Random(6)  # noqa: S311

FILINGS = [
    ("ACME", "8-K", "2026-11-03", "2026-11-03", "Launch schedule update, synthetic"),
    ("ACME", "10-Q", "2026-10-30", "2026-09-30", "Quarterly report, Q3, synthetic"),
    ("ACME", "4", "2026-10-21", "2026-10-17", "Director sale under a 10b5-1 plan, synthetic"),
    ("ACME", "10-Q", "2026-07-31", "2026-06-30", "Quarterly report, Q2, synthetic"),
    ("ACME", "10-K", "2026-02-27", "2025-12-31", "Annual report, synthetic"),
    ("NOVA", "S-1/A", "2026-10-28", None, "Follow-on offering amendment, synthetic"),
    ("NOVA", "10-Q", "2026-10-24", "2026-09-30", "Quarterly report, Q3, synthetic"),
    ("FTEC", "NPORT-P", "2026-11-04", "2026-09-30", "Portfolio holdings, Sep 30, synthetic"),
    ("FTEC", "497K", "2026-09-26", None, "Summary prospectus, synthetic"),
    ("VXUS", "NPORT-P", "2026-10-29", "2026-09-30", "Portfolio holdings, Sep 30, synthetic"),
]
FACTS = []
for sym, base, margin, ops, shares in (("ACME", 410e6, 0.31, 0.06, 182e6), ("NOVA", 96e6, 0.18, -0.22, 74e6)):
    for k, fy in enumerate((2023, 2024, 2025)):
        rev = base * (1.24**k)
        FACTS += [
            (sym, "revenue", f"{fy}-01-01", f"{fy}-12-31", fy, "FY", "10-K", f"{fy + 1}-02-27", rev, "USD"),
            (sym, "gross_profit", f"{fy}-01-01", f"{fy}-12-31", fy, "FY", "10-K", f"{fy + 1}-02-27", rev * (margin + 0.02 * k), "USD"),
            (sym, "operating_income", f"{fy}-01-01", f"{fy}-12-31", fy, "FY", "10-K", f"{fy + 1}-02-27", rev * (ops + 0.03 * k), "USD"),
            (sym, "net_income", f"{fy}-01-01", f"{fy}-12-31", fy, "FY", "10-K", f"{fy + 1}-02-27", rev * (ops + 0.03 * k - 0.04), "USD"),
        ]
    for q, end in enumerate(("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30")):
        FACTS.append((sym, "shares_outstanding", None, end, 2025 + (q > 1), f"Q{q % 4 + 1}", "10-Q", end, shares * (1.012**q), "shares"))
EARNINGS = [
    ("ACME", "2026-11-12", "amc", 3, 2026, 0.21, None, 152e6, None),
    ("ACME", "2026-07-30", "amc", 2, 2026, 0.16, 0.19, 131e6, 136e6),
    ("ACME", "2026-04-29", "amc", 1, 2026, 0.12, 0.11, 118e6, 117e6),
    ("NOVA", "2026-11-18", "bmo", 3, 2026, -0.14, None, 33e6, None),
    ("NOVA", "2026-08-06", "bmo", 2, 2026, -0.18, -0.15, 29e6, 31e6),
]
INSIDERS = [
    ("ACME", "Synthetic Director A", "2026-10-21", "2026-10-17", "S", -12000, 88000, 3.14),
    ("ACME", "Synthetic Officer B", "2026-09-12", "2026-09-10", "P", 3000, 41000, 3.41),
    ("ACME", "Synthetic Officer C", "2026-08-20", "2026-08-18", "M", 5000, 60000, 0.95),
    ("NOVA", "Synthetic CEO", "2026-10-08", "2026-10-06", "P", 20000, 1250000, 31.2),
]

with sqlite3.connect(cfg.desk_db) as conn:
    conn.executemany(
        "INSERT OR REPLACE INTO filings (accession, symbol, cik, form, filed, report_date, description, url) VALUES (?,?,?,?,?,?,?,?)",
        [(f"0000000000-26-{k:06d}", s, 0, f, d, r, t, EDGAR) for k, (s, f, d, r, t) in enumerate(FILINGS)],
    )
    conn.executemany("INSERT INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?,?)", FACTS)
    conn.executemany("INSERT OR REPLACE INTO earnings VALUES (?,?,?,?,?,?,?,?,?)", EARNINGS)
    conn.executemany("INSERT OR IGNORE INTO insider_trades VALUES (?,?,?,?,?,?,?,?)", INSIDERS)
    conn.execute("INSERT OR REPLACE INTO market_symbols (symbol, role, priority, added_at) VALUES ('NOVA', 'watch', 5, '2026-10-02T14:00:00+00:00')")
    conn.executemany(
        "INSERT OR REPLACE INTO sym_profiles (symbol, name, industry, sector, fetched_at) VALUES (?,?,?,?,?)",
        [
            ("ACME", "Acme Orbital (synthetic)", "Aerospace", "Industrials", "2026-11-06"),
            ("NOVA", "Nova Fission (synthetic)", "Utilities", "Utilities", "2026-11-06"),
        ],
    )
    day, px, rows = date(2024, 11, 7), 14.0, []
    while day <= date(2026, 11, 6):
        if day.weekday() < 5:
            px *= math.exp(rng.gauss(0.0006, 0.032))
            rows.append(("NOVA", day.isoformat(), round(px, 2), round(px, 2), "seed"))
        day += timedelta(days=1)
    conn.executemany("INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?)", rows)
    macro = []
    for series, start, drift, vol in (
        ("DGS3MO", 4.6, -0.0012, 0.01),
        ("DGS2", 4.1, -0.0008, 0.03),
        ("DGS10", 4.3, -0.0002, 0.03),
        ("BAMLH0A0HYM2", 3.4, -0.0005, 0.04),
        ("VIXCLS", 17.0, 0, 0.6),
    ):
        day, v = date(2025, 11, 3), start
        while day <= date(2026, 11, 6):
            if day.weekday() < 5:
                v = max(0.1, v + drift + rng.gauss(0, vol) - (0.02 * (v - start) if series == "VIXCLS" else 0))
                macro.append((series, day.isoformat(), round(v, 2)))
            day += timedelta(days=1)
    for k in range(13):
        m = date(2025 + (10 + k) // 12, (10 + k) % 12 + 1, 1)
        macro.append(("CPIAUCSL", m.isoformat(), round(318.0 * (1.0025**k), 3)))
    conn.executemany("INSERT OR REPLACE INTO macro_daily VALUES (?,?,?)", macro)
print("research rows", len(FILINGS), len(FACTS), len(EARNINGS), len(INSIDERS), len(macro))

# ---------- dossiers and console ----------
DOSSIERS = [
    (
        "FTEC",
        "2026-11-05T06:12:00+00:00",
        {
            "symbol": "FTEC",
            "verdict": "hold",
            "thesis": (
                "FTEC is the plan's tech tilt at 20% of the mix. It tracks the broad US tech index for 0.084% a year, "
                "and the plan already caps it so one sector can't run the portfolio."
            ),
            "bear_case": (
                "The top three holdings are 45% of the fund. A bad quarter for any one of them moves FTEC far more than the S&P 500, "
                "and it overlaps a third with the core fund."
            ),
            "valuation_range": {"low": 24, "high": 35, "basis": "forward P/E of the fund", "now": 32},
            "what_would_change": "Top three weights pass 50%.\nForward P/E above 35x.\nThe plan drops the tech tilt.",
            "changes_since_last": "Top three weight is up 2 points since the June holdings.",
            "sources": [
                {"url": EDGAR, "title": "N-PORT holdings, Sep 30 (synthetic) · SEC EDGAR", "date": "2026-11-04"},
                {"url": f"{FRED}DGS10", "title": "10-year Treasury yield · FRED", "date": "2026-11-05"},
                {"url": "https://example.com/synthetic/sector-recap", "title": "Sector earnings recap (synthetic)", "date": "2026-11-02"},
                {"url": "note:2026-09-12", "title": "Your note: keep the tilt at 20%, no higher", "date": "2026-09-12"},
            ],
        },
    ),
    (
        "ACME",
        "2026-11-04T06:07:00+00:00",
        {
            "symbol": "ACME",
            "verdict": "avoid",
            "thesis": "ACME grew revenue 24% a year for three years and turned an operating profit in 2025. The launch backlog is two years deep.",
            "bear_case": (
                "It is a single stock outside the plan, share count is up 5% in a year, and a director sold under a 10b5-1 plan last month. "
                "One launch scrub resets the story."
            ),
            "valuation_range": {"low": 2.4, "high": 4.2, "basis": "price per share, $", "now": None},
            "what_would_change": "Two clean launches in a row.\nShare count stops growing.\nThe plan makes room for a satellite sleeve.",
            "changes_since_last": None,
            "sources": [
                {"url": EDGAR, "title": "10-Q, Q3 (synthetic) · SEC EDGAR", "date": "2026-10-30"},
                {"url": EDGAR, "title": "Form 4, director sale (synthetic) · SEC EDGAR", "date": "2026-10-21"},
                {"url": "https://example.com/synthetic/launch-tracker", "title": "Launch tracker (synthetic)", "date": "2026-11-03"},
            ],
        },
    ),
    (
        "NOVA",
        "2026-10-29T06:20:00+00:00",
        {
            "symbol": "NOVA",
            "verdict": "watch",
            "thesis": "NOVA is the watchlist's nuclear theme pick. The CEO bought $624K of stock in October and revenue grew 24% last year.",
            "bear_case": "It still loses money, a follow-on offering is on file, and it would be a new single stock, which the plan rules out.",
            "valuation_range": {"low": 28, "high": 44, "basis": "price per share, $", "now": None},
            "what_would_change": "Price under $28 with the offering done.\nFirst operating profit.",
            "changes_since_last": "New S-1/A on file since the last look.",
            "sources": [{"url": EDGAR, "title": "S-1/A (synthetic) · SEC EDGAR", "date": "2026-10-28"}],
        },
    ),
]

with store.db(cfg) as conn:
    research_run = conn.execute("SELECT id FROM agent_runs WHERE desk='research' ORDER BY id DESC LIMIT 1").fetchone()[0]
for sym, _created, body in DOSSIERS:
    store.save_dossier(cfg, sym, research_run, json.dumps(body, sort_keys=True))
with store.db(cfg) as conn:
    for sym, created, _ in DOSSIERS:
        conn.execute("UPDATE agent_dossiers SET created_at=? WHERE symbol=?", (created, sym))

ASKS = [
    (
        "tax",
        "Why is the tax desk quiet about ACME?",
        None,
        "done",
        "2026-11-06T01:04:00+00:00",
        "The ACME position is $79, too small to clear the $250 harvest threshold even at a full loss. The desk speaks up once a lot can clear it.",
    ),
    ("research", "Deep dive on NOVA for the nuclear theme", "NOVA", "queued", None, None),
]
for desk, q, sym, status, done_at, answer in ASKS:
    rid = store.add_request(cfg, desk, q, symbol=sym)
    if status == "done":
        store.finish_request(cfg, rid, "done", run_id=research_run, answer=answer)
        with store.db(cfg) as conn:
            conn.execute("UPDATE agent_requests SET created_at=?, started_at=?, finished_at=? WHERE id=?", ("2026-11-05T21:40:00+00:00", done_at, done_at, rid))
    else:
        with store.db(cfg) as conn:
            conn.execute("UPDATE agent_requests SET created_at=? WHERE id=?", ("2026-11-07T12:50:00+00:00", rid))
print("dossiers", len(DOSSIERS), "asks", len(ASKS))

# ---------- fund look-through ----------
MEGA = {
    "AAA": ("Synthetic Megacap A", "Technology"),
    "BBB": ("Synthetic Megacap B", "Technology"),
    "CCC": ("Synthetic Megacap C", "Technology"),
    "DDD": ("Synthetic Retail D", "Consumer Discretionary"),
    "EEE": ("Synthetic Bank E", "Financials"),
    "FFF": ("Synthetic Chips F", "Technology"),
    "GGG": ("Synthetic Global G", "Health Care"),
    "HHH": ("Synthetic Global H", "Industrials"),
    "JJJ": ("Synthetic Global J", "Consumer Staples"),
}
FUNDS = {
    "FXAIX": [("AAA", 7.1), ("BBB", 6.4), ("CCC", 5.9), ("DDD", 3.8), ("EEE", 2.1), ("FFF", 1.9), ("ACME", 0.05)],
    "FTEC": [("AAA", 17.8), ("BBB", 15.6), ("CCC", 11.2), ("FFF", 6.1)],
    "VXUS": [("GGG", 1.9), ("HHH", 1.6), ("JJJ", 1.3), ("CCC", 0.4)],
    "BND": [("UST1", 2.4), ("UST2", 2.1), ("UST3", 1.8)],
}
with sqlite3.connect(cfg.desk_db) as conn:
    for k, (fund, rows) in enumerate(FUNDS.items()):
        conn.execute("INSERT OR REPLACE INTO sec_funds VALUES (?,?,?,?,?)", (fund, 0, f"S{k:09d}", None, "2026-11-01T00:00:00+00:00"))
        conn.executemany(
            "INSERT OR REPLACE INTO fund_holdings VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    fund,
                    "2026-09-30",
                    sym,
                    MEGA[sym][0] if sym in MEGA else f"Synthetic Treasury {sym[-1]}" if fund == "BND" else "Acme Orbital (synthetic)",
                    None,
                    w,
                    "DBT" if fund == "BND" else "EC",
                    "US",
                    "synthetic",
                )
                for sym, w in rows
            ],
        )
    conn.executemany(
        "INSERT OR REPLACE INTO sym_profiles (symbol, name, industry, sector, fetched_at) VALUES (?,?,?,?,?)",
        [(s, n, None, sec, "2026-11-06") for s, (n, sec) in MEGA.items()],
    )
print("look-through funds", len(FUNDS))

# ---------- flight record history ----------
rng = random.Random(41)  # noqa: S311
HISTORY = [
    ("plan_keeper", "deposit_route", ("FXAIX", "VXUS", "BND", "FTEC"), (150, 400), "deposit", 26, 0.92),
    ("plan_keeper", "trim", ("FTEC", "FXAIX"), (100, 300), "sale_proceeds", 8, 0.75),
    ("plan_keeper", "rebalance", ("VXUS", "BND"), (80, 250), "cash", 6, 0.7),
    ("scout", "buy", ("NOVA", "ACME", "FTEC"), (200, 600), "cash", 14, 0.45),
    ("risk", "hold_off", ("ACME", "NOVA"), (300, 800), "cash", 9, 0.6),
    ("tax", "harvest", ("VXUS", "ACME"), (200, 900), "sale_proceeds", 5, 0.8),
    ("you", "buy", ("ACME", "NOVA", "FTEC"), (200, 700), "cash", 12, 1.0),
]
start = datetime(2025, 11, 10, 14, 5, tzinfo=UTC)
span = (datetime(2026, 9, 25, 14, 5, tzinfo=UTC) - start).days
made = 0
for desk, kind, symbols, (lo, hi), funding, n, take in HISTORY:
    for _k in range(n):
        when = start + timedelta(days=rng.randrange(span))
        if when.weekday() > 4:
            when -= timedelta(days=when.weekday() - 4)
        sym = rng.choice(symbols)
        amount = round(rng.uniform(lo, hi) / 10) * 10
        body = {
            "kind": kind,
            "symbol": sym,
            "account": "individual-0001",
            "amount_usd": amount,
            "funding": funding,
            "thesis": f"Synthetic {kind.replace('_', ' ')} on {sym} for the flight record.",
            "confidence": round(min(0.95, max(0.2, rng.gauss(take - 0.1, 0.15))), 2),
            "horizon": "3 months",
        }
        if kind == "buy":
            body |= {"bear_case": "A small name can halve on one bad quarter.", "sources": SRC}
        if kind == "harvest":
            body["tax_impact"] = {"realized": -round(rng.uniform(80, 600), 2)}
        d = records.draft(cfg, body, now=when) if desk == "you" else records.create_proposal(cfg, body, desk, run_id=f"r-hist-{made}", now=when)
        if d["status"] != "proposed":
            continue
        later = when + timedelta(hours=3)
        if rng.random() < take:
            try:
                ok = records.approve(cfg, d["id"], None, now=later)
            except DecisionError:
                ok = records.approve(cfg, d["id"], "Going ahead on purpose", now=later)
            if ok["status"] == "approved":
                records.mark_placed(cfg, d["id"], now=later + timedelta(hours=1))
        else:
            records.dismiss(cfg, d["id"], rng.choice(["Not this month", "Too small to bother with", "Waiting for the deposit"]), now=later)
        made += 1
print(json.dumps({"history": made}))
