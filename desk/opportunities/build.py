import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import discounts, planfacts
from desk.engine.source import closes as mirror_closes
from desk.engine.source import open_mirror
from desk.opportunities import sizing
from desk.opportunities.sizing import day_words

MAX_ROWS = 12
MIN_ROWS = 3
SCOUT_DAYS = 45
ON_SALE_DROP = -10.0
ON_SALE_SWINGS = 1.5
CHEAP_PCTILE = 0.2
CHEAP_DROP = -5.0
NEAR_SWINGS = 0.75
EARNINGS_SOON = 14
TEXT_MAX = 320
OPEN_DECISIONS = ("open", "approved")
SELL_VERDICTS = ("trim", "sell", "reduce")
ORDER = {"buy": 0, "watch": 1, "screen": 1}
METHOD = "Ranked by how unusual the discount is for that name, lifted by a written buy case or a Scout idea. It is a sort, not a forecast."
NO_ENGINE = "No list yet: the engine has not run. It fills in after the next engine run."
NOTHING = "Nothing is on sale tonight: every name the desk tracks is within a normal swing of its high."
SOURCE_WORDS = {"scanner": "Discount scanner", "case": "written case", "scout": "Scout idea", "standing": "On sale by the numbers", "near": "Not on sale yet"}
BUY_WORDS = {"cash": "Worth buying now", "deposit": "Worth buying with the next deposit", "wait": "Worth buying once cash is free"}
SPLIT = "Today's close down to one monthly swing lower. Split the buy in two."
BELOW = "One to two monthly swings under today's close."


# ---- Inputs ----


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _universe(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return discounts.universe(conn)
    except sqlite3.Error:
        return dict.fromkeys(discounts.QUALITY, "quality")


def _signals(conn: sqlite3.Connection) -> tuple[dict, dict[str, dict]]:
    try:
        view = discounts.view(conn, days=discounts.PENDING_DAYS)
    except sqlite3.Error:
        view = discounts.view(None)
    latest: dict[str, dict] = {}
    for row in view["rows"]:
        seen = latest.get(row["symbol"])
        if seen is None:
            latest[row["symbol"]] = dict(row)
        elif seen.get("case") is None and row.get("case"):
            seen["case"] = row["case"]
    return view, latest


def _last_case_at(conn: sqlite3.Connection) -> str | None:
    if not _has(conn, "discount_cases"):
        return None
    return conn.execute("SELECT max(written_at) FROM discount_cases").fetchone()[0]


def _scout(cfg: Config, today: date) -> list[dict]:
    try:
        from desk import decisions

        cut = (today - timedelta(days=SCOUT_DAYS)).isoformat()
        out = []
        for h in decisions.desk_history(cfg, "scout", 20):
            if h["kind"] != "buy" or h["decision"] not in OPEN_DECISIONS or not h["symbol"] or str(h["created_at"])[:10] < cut:
                continue
            out.append(decisions.get(cfg, h["id"]))
        return out
    except Exception:  # noqa: BLE001
        return []


def _last_ok(cfg: Config, desk: str) -> str | None:
    try:
        from desk.agents import store

        for run in store.runs(cfg, desk, 20):
            if run["status"] == "ok":
                return run["finished_at"] or run["started_at"]
    except Exception:  # noqa: BLE001
        return None
    return None


def _research(cfg: Config) -> dict[str, str]:
    try:
        from desk.agents import store

        rows = store.dossier_list(cfg)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for row in rows:
        try:
            verdict = json.loads(row["dossier"]).get("verdict")
        except (TypeError, ValueError, AttributeError):
            continue
        if isinstance(verdict, str) and verdict.strip():
            out[str(row["symbol"]).upper()] = verdict.strip().lower()
    return out


def _earnings(conn: sqlite3.Connection, symbol: str, as_of: str) -> dict | None:
    if not _has(conn, "earnings"):
        return None
    r = conn.execute("SELECT date FROM earnings WHERE symbol=? AND date >= ? ORDER BY date LIMIT 1", (symbol, as_of)).fetchone()
    return {"date": r["date"], "days": (date.fromisoformat(r["date"]) - date.fromisoformat(as_of)).days} if r else None


# ---- Measures ----


def measure(conn: sqlite3.Connection, mirror_series: dict, symbol: str) -> dict | None:
    px = planfacts.prices(conn, mirror_series, symbol)
    s = planfacts.stats(px)
    if not s:
        return None
    out = dict(s) | {"price_as_of": px[-1][0], "valuation": None, "swings": None}
    if "sigma_month_pct" in s:
        out["valuation"] = discounts.valuation(conn, symbol, px)
        if s["sigma_month_pct"] > 0:
            out["swings"] = abs(min(s["drop_from_high_pct"], 0.0)) / s["sigma_month_pct"]
    return out


def on_sale(m: dict) -> bool:
    drop, swings, val = m.get("drop_from_high_pct"), m.get("swings"), m.get("valuation") or {}
    if drop is None or swings is None:
        return False
    if drop <= ON_SALE_DROP and swings >= ON_SALE_SWINGS:
        return True
    return val.get("metric") == "pe_annual" and val.get("pctile_own") is not None and val["pctile_own"] <= CHEAP_PCTILE and drop <= CHEAP_DROP


def score(m: dict, c: dict) -> int:
    pts = min(m.get("swings") or 0.0, 4.0) / 4 * 40
    pctile = (m.get("valuation") or {}).get("pctile_own")
    if pctile is not None:
        pts += (0.5 - pctile) * 30
    trend = m.get("vs_sma_200_pct")
    if trend is not None:
        pts += 8 if trend >= 0 else max(-8.0, 8 + trend * 0.8)
    if c.get("hit"):
        pts += 10
    case = c.get("case")
    if case:
        pts += 25 * case["confidence"] if case["verdict"] == "buy" else -5
    idea = c.get("scout")
    if idea:
        pts += 20 * (idea.get("confidence") or 0.6)
        if ((idea.get("skeptic") or {}).get("verdict")) == "flag":
            pts -= 15
    if c["size"].get("blocked"):
        pts -= 25
    soon = c.get("next_earnings")
    if soon and soon["days"] <= 5:
        pts -= 5
    return round(max(0.0, min(100.0, pts)))


# ---- Words ----


def _clip(text: object, limit: int = TEXT_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _money(v: float) -> str:
    return f"${v:,.2f}"


def hit_line(hit: dict) -> str:
    when, why = day_words(hit["as_of"]), str(hit.get("reason") or "")
    if why.startswith("crossed_"):
        return f"First close {why.split('_')[1]}% under its 52-week high on {when}"
    move, z = (hit.get("numbers") or {}).get("day_move_pct"), hit.get("move_z")
    if move is not None and z is not None:
        return f"Fell {abs(move):.1f}% on {when}, a {abs(z):.1f}-sigma day for it"
    return f"An unusually big down day on {when}"


def facts(m: dict, c: dict) -> list[str]:
    out = []
    drop = m.get("drop_from_high_pct")
    if drop is not None and drop < -0.05:
        out.append(f"{abs(drop):.1f}% under its 52-week high")
    if c.get("hit"):
        out.append(hit_line(c["hit"]))
    val = m.get("valuation") or {}
    if val.get("metric") == "pe_annual" and val.get("pctile_own") is not None:
        out.append(f"Cheaper than {round((1 - val['pctile_own']) * 100)}% of its last 5 years on earnings")
    elif val.get("metric") == "price_vs_5y_avg" and val.get("value") is not None and abs(val["value"]) >= 0.005:
        out.append(f"{abs(val['value']) * 100:.0f}% {'under' if val['value'] < 0 else 'above'} its 5-year average price")
    trend = m.get("vs_sma_200_pct")
    if trend is not None:
        out.append(f"{abs(trend):.1f}% {'above' if trend >= 0 else 'under'} its 200-day average")
    if c["held"]:
        out.append(f"You hold {c['weight_pct']:.1f}% of the portfolio")
    idea = c.get("scout")
    if idea and idea.get("confidence") is not None:
        out.append(f"Scout confidence {round(idea['confidence'] * 100)}%")
    return out[:4]


def why_now(m: dict, c: dict) -> str:
    case, idea, hit = c.get("case"), c.get("scout"), c.get("hit")
    if case:
        return _clip(case["case"])
    if idea:
        return _clip("Scout: " + str(idea.get("thesis") or idea.get("title") or "an idea inside your focus."))
    drop, swings, trend = m.get("drop_from_high_pct"), m.get("swings"), m.get("vs_sma_200_pct")
    if c["tier"] == "near":
        zone = c["entry"]
        where = f" It gets interesting between {_money(zone['low'])} and {_money(zone['high'])}." if zone.get("low") else ""
        return f"Not on sale yet: {abs(drop):.1f}% under its high is a normal swing for it.{where}"
    tail = ""
    if trend is not None:
        tail = ", and still above its 200-day average" if trend >= 0 else ", and under its 200-day average, so the slide may not be over"
    size = f"about {swings:.1f} of its usual monthly swings" if swings and swings <= 6 else "well beyond its usual monthly swings"
    if drop is None or not swings:
        return f"{hit_line(hit)}." if hit else "Flagged by the discount scanner."
    if hit:
        return f"{hit_line(hit)}. It now sits {abs(drop):.1f}% under that high, {size}{tail}."
    return f"{abs(drop):.1f}% under its 52-week high, {size}{tail}."


def wrong_if(m: dict, c: dict) -> tuple[str, float | None]:
    case, idea = c.get("case"), c.get("scout")
    if case:
        lead = _clip(case["risks"], 240)
    elif idea:
        skeptic = idea.get("skeptic") or {}
        if skeptic.get("verdict") == "flag" and skeptic.get("counter_case"):
            lead = _clip("Skeptic: " + skeptic["counter_case"], 240)
        else:
            lead = _clip(idea.get("bear_case") or idea.get("invalidation") or "Scout wrote no bear case.", 240)
    elif c["tier"] == "near":
        lead = "It is not cheap yet, so buying now pays a normal price."
    else:
        lead = "No written case yet, so nobody has checked why it fell."
    lead = lead if lead.endswith((".", "!", "?", "…")) else lead + "."
    sigma, price = m.get("sigma_month_pct"), m.get("price")
    floor = None
    if sigma and price:
        steps = 3 if c["tier"] == "near" else 2
        floor = round(price * (1 - steps * sigma / 100), 2)
        lead += f" Off below {_money(floor)}, {'three' if steps == 3 else 'two'} monthly swings under today."
    soon = c.get("next_earnings")
    if soon and soon["days"] <= EARNINGS_SOON:
        lead += f" Earnings on {day_words(soon['date'])} can move it either way."
    return lead, floor


def entry(m: dict, tier: str) -> dict:
    price, sigma = m.get("price"), m.get("sigma_month_pct")
    if not price or not sigma:
        return {"low": None, "high": round(price, 2) if price else None, "price": price, "in_zone": True, "basis": "Not enough price history for a zone yet."}
    s = sigma / 100
    if tier == "near":
        return {"low": round(price * (1 - 2 * s), 2), "high": round(price * (1 - s), 2), "price": round(price, 4), "in_zone": False, "basis": BELOW}
    return {"low": round(price * (1 - s), 2), "high": round(price, 2), "price": round(price, 4), "in_zone": True, "basis": SPLIT}


def stance(c: dict) -> tuple[str, str]:
    blocked, case, idea = c["size"].get("blocked"), c.get("case"), c.get("scout")
    if blocked:
        limit = c["size"].get("limited_by")
        if limit == "no-buy window":
            return "watch", "Watch: inside a no-buy window"
        return "watch", "Watch: no room under your cap" if limit and limit != "plan rules" else "Watch: your rules block it"
    if c.get("research_verdict") in SELL_VERDICTS:
        return "watch", f"Watch: your research note says {c['research_verdict']}"
    if case:
        return ("buy", BUY_WORDS[c["size"]["funding"]]) if case["verdict"] == "buy" else ("watch", "Watch: the written case says wait")
    if idea:
        if (idea.get("skeptic") or {}).get("verdict") == "flag":
            return "watch", "Watch: Skeptic disagreed"
        return "buy", BUY_WORDS[c["size"]["funding"]]
    if c["tier"] == "near":
        return "watch", "Watch: not on sale yet"
    return "screen", "Cheap by the numbers, no written case yet"


def source_label(sources: list[str]) -> str:
    words = [SOURCE_WORDS[s] for s in sources if s in SOURCE_WORDS]
    return " + ".join(words) if words else "Desk screen"


def headline(rows: list[dict], note: str | None) -> str:
    if not rows:
        return note or NOTHING
    top = rows[0]
    drop = next((f for f in top["facts"] if "under its 52-week high" in f), None)
    lead = f"Top: {top['symbol']}" + (f", {drop.replace(' its 52-week high', ' its high')}." if drop else ".")
    buy = sum(r["stance"] == "buy" for r in rows)
    rest = len(rows) - buy
    if buy:
        funded = any(r["stance"] == "buy" and r["size"]["funding"] == "cash" for r in rows)
        words = f"{buy} worth buying now" if funded else f"{buy} worth buying once cash is free"
        return f"{words}, {rest} to watch. {lead}" if rest else f"{words}. {lead}"
    return f"Nothing rated a buy yet. {len(rows)} to watch. {lead}"


# ---- The list ----


def _empty(now: datetime, note: str, profile: dict, cash: dict, freshness: dict) -> dict:
    return {
        "as_of": None,
        "built_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "advice_only": True,
        "freshness": freshness,
        "headline": headline([], note),
        "counts": dict.fromkeys(("total", "buy", "watch", "screen", "held", "outside", "with_case"), 0),
        "note": note,
        "profile": profile,
        "cash": cash,
        "method": METHOD,
        "rows": [],
        "passed": [],
    }


def _freshness(cfg: Config, conn: sqlite3.Connection | None, view: dict | None) -> dict:
    from desk.opportunities.night import last_night

    night = last_night(cfg) or {}
    return {
        "scanner_as_of": (view or {}).get("as_of"),
        "last_case_at": _last_case_at(conn) if conn is not None else None,
        "last_scout_at": _last_ok(cfg, "scout"),
        "night_run_at": night.get("finished_at"),
        "night_status": night.get("status"),
        "note": None,
    }


def build(cfg: Config, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    profile = sizing.profile(cfg)
    if not cfg.desk_db.exists():
        return _empty(now, NO_ENGINE, profile, sizing.cash_view(None), _freshness(cfg, None, None))
    conn = connect(cfg.desk_db, readonly=True)
    mirror = open_mirror(cfg)
    try:
        return _build(cfg, conn, mirror, now, profile)
    except Exception as e:  # noqa: BLE001
        note = _clip(f"The list could not be built this time ({type(e).__name__}: {e}). The numbers behind it are untouched.", 240)
        return _empty(now, note, profile, sizing.cash_view(None), _freshness(cfg, None, None))
    finally:
        conn.close()
        if mirror is not None:
            mirror.close()


def _build(cfg: Config, conn: sqlite3.Connection, mirror: sqlite3.Connection | None, now: datetime, profile: dict) -> dict:
    try:
        as_of, held, total = planfacts.held(conn)
    except sqlite3.Error:
        as_of, held, total = None, {}, 0.0
    view, signals = _signals(conn)
    if as_of is None:
        return _empty(now, NO_ENGINE, profile, sizing.cash_view(None), _freshness(cfg, conn, view))
    ideas = {str(d["symbol"]).upper(): d for d in reversed(_scout(cfg, date.fromisoformat(as_of)))}
    lists = _universe(conn)
    symbols = sorted(set(lists) | set(signals) | set(ideas))
    mirror_series = mirror_closes(mirror) if mirror is not None else {}
    measures = {s: m for s in symbols if (m := measure(conn, mirror_series, s)) is not None}
    kinds = planfacts.kinds_of(mirror, conn, set(symbols))
    titles = planfacts.names(conn)
    book = sizing.load(cfg, mirror, conn, kinds, now=now)
    verdicts = _research(cfg)
    picked, near, passed = [], [], []
    for sym in symbols:
        m = measures.get(sym) or {}
        hit, idea = signals.get(sym), ideas.get(sym)
        case = (hit or {}).get("case")
        name = titles.get(sym) or (hit or {}).get("name")
        if case and case["verdict"] == "avoid" and not idea:
            passed.append({"symbol": sym, "name": name, "reason": _clip("Written case says avoid: " + case["case"], 200)})
            continue
        sale = bool(m) and on_sale(m)
        tier = "live" if (hit or idea or sale) else "near"
        if tier == "near" and not ((m.get("swings") or 0) >= NEAR_SWINGS and lists.get(sym) in ("held", "quality")):
            continue
        sources = [s for s, on in (("scanner", hit), ("case", case), ("scout", idea), ("standing", sale and not hit and not idea)) if on]
        c = {
            "symbol": sym,
            "name": name,
            "kind": kinds.get(sym, "unknown"),
            "held": sym in held,
            "weight_pct": round(held[sym]["value"] / total * 100, 2) if sym in held and total else 0.0,
            "tier": tier,
            "sources": sources or ["near"],
            "hit": hit,
            "case": case,
            "scout": idea,
            "next_earnings": _earnings(conn, sym, as_of),
            "research_verdict": verdicts.get(sym) if sym in held else None,
        }
        c["entry"] = entry(m, tier)
        c["size"] = sizing.size(book, sym, c["kind"], m.get("price"))
        c["score"] = score(m, c)
        c["m"] = m
        (near if tier == "near" else picked).append(c)
    near.sort(key=lambda c: (-c["score"], c["symbol"]))
    picked += near[: max(0, MIN_ROWS - len(picked))]
    rows = [_row(c, as_of) for c in picked]
    rows.sort(key=lambda r: (ORDER[r["stance"]], -r["score"], r["symbol"]))
    rows = rows[:MAX_ROWS]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    counts = {
        "total": len(rows),
        **{k: sum(r["stance"] == k for r in rows) for k in ("buy", "watch", "screen")},
        "held": sum(r["held"] for r in rows),
        "outside": sum(not r["held"] for r in rows),
        "with_case": sum(r["case"] is not None for r in rows),
    }
    note = None if rows else NOTHING
    fresh = _freshness(cfg, conn, view)
    if counts["screen"]:
        n = counts["screen"]
        fresh["note"] = f"{n} of these {'has' if n == 1 else 'have'} no written case yet. The numbers stand on their own; the cases are written overnight."
    return {
        "as_of": as_of,
        "built_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "advice_only": True,
        "freshness": fresh,
        "headline": headline(rows, note),
        "counts": counts,
        "note": note,
        "profile": profile,
        "cash": sizing.cash_view(book),
        "method": METHOD,
        "rows": rows,
        "passed": sorted(passed, key=lambda p: p["symbol"]),
    }


def _row(c: dict, as_of: str) -> dict:
    m, case, idea = c["m"], c["case"], c["scout"]
    label, words = stance(c)
    wrong, floor = wrong_if(m, c)
    return {
        "rank": 0,
        "symbol": c["symbol"],
        "name": c["name"],
        "kind": c["kind"],
        "held": c["held"],
        "weight_pct": c["weight_pct"],
        "sources": c["sources"],
        "source_label": source_label(c["sources"]),
        "stance": label,
        "stance_label": words,
        "why_now": why_now(m, c),
        "facts": facts(m, c),
        "entry": c["entry"],
        "size": c["size"],
        "wrong_if": wrong,
        "invalid_below": floor,
        "case": {k: case[k] for k in ("verdict", "confidence", "horizon_days", "written_at")} if case else None,
        "decision_id": idea["id"] if idea else None,
        "research_verdict": c["research_verdict"],
        "next_earnings": c["next_earnings"],
        "as_of": m.get("price_as_of") or as_of,
        "score": c["score"],
    }
