import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import asof as desk_day
from desk.engine import discounts, planfacts
from desk.engine.market import ET
from desk.engine.source import closes as mirror_closes
from desk.engine.source import open_mirror
from desk.opportunities import sizing
from desk.opportunities.sizing import day_words, usd

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
SELL_VERDICTS = ("trim", "avoid", "sell", "reduce")
ORDER = {"buy": 0, "watch": 1, "screen": 1}
METHOD = "Ranked by how unusual the discount is for that name, lifted by a written buy case or a Scout idea. It is a sort, not a forecast."
NO_ENGINE = "No list yet: the engine has not run. It fills in after the next engine run."
NOTHING = "Nothing is on sale tonight: every name the desk tracks is within a normal swing of its high."
SOURCE_WORDS = {"scanner": "Discount scanner", "case": "written case", "scout": "Scout idea", "standing": "On sale by the numbers", "near": "Not on sale yet"}
BUY_WORDS = {"cash": "Worth buying now", "deposit": "Worth buying with the next deposit", "wait": "Worth buying once cash is free"}
SPLIT = "The latest price down to one monthly swing lower. Split the buy in two."
BELOW = "One to two monthly swings under the latest price."
KEEP_CLOSES = 80
OLDER = "The desk has no newer price for it than {day}: live quotes cover what you hold, and its next close lands overnight."
FUNDING_REASONS = ("A margin debit", "It needs $")
HOLD_REASONS = ("A standing note says to hold off",)
WINDOW_WORDS = "wash-sale window"
ANALYSIS_WORDS = {"case": "The written case is", "scout": "Scout's idea is", "scanner": "The scanner hit is"}


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


def _turned_back(cfg: Config, today: date) -> list[dict]:
    try:
        from desk import decisions

        cut = (today - timedelta(days=SCOUT_DAYS)).isoformat()
        found = decisions.journal(cfg, origin="scout", kind="buy", status="rejected", since=cut, limit=50)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for d in (item for day in found.get("days") or () for item in day.get("items") or ()):
        why = str(d.get("status_reason") or "")
        if not d.get("symbol"):
            continue
        if why.startswith(FUNDING_REASONS):
            out.append(d | {"turned_back": {"kind": "funding", "reason": why}})
        elif why.startswith(HOLD_REASONS) or WINDOW_WORDS in why:
            out.append(d | {"turned_back": {"kind": "window" if WINDOW_WORDS in why else "hold", "reason": why}})
    return out


def _et_day(at: object) -> str | None:
    try:
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(ET).date().isoformat()


def _marks(conn: sqlite3.Connection) -> dict[str, dict[str, tuple[float, str, str | None]]]:
    out: dict[str, dict[str, tuple[float, str, str | None]]] = {}
    if _has(conn, "quotes_live"):
        newest = "SELECT symbol, max(fetched_at) f FROM quotes_live WHERE source='finnhub' GROUP BY symbol"
        for r in conn.execute(f"SELECT q.symbol, q.at, q.price FROM quotes_live q JOIN ({newest}) m ON m.symbol=q.symbol AND m.f=q.fetched_at"):
            day = _et_day(r["at"])
            if day and r["price"]:
                out.setdefault(r["symbol"], {})[day] = (float(r["price"]), "quote", r["at"])
    if _has(conn, "closes_provisional"):
        for r in conn.execute("SELECT symbol, date, close, quote_at FROM closes_provisional"):
            if r["close"]:
                out.setdefault(r["symbol"], {})[r["date"]] = (float(r["close"]), "provisional", r["quote_at"])
    return out


def _scale(conn: sqlite3.Connection, symbol: str) -> float:
    if not _has(conn, "price_bars"):
        return 1.0
    r = conn.execute("SELECT adj_close, close FROM price_bars WHERE symbol=? ORDER BY date DESC LIMIT 1", (symbol,)).fetchone()
    return float(r[0]) / float(r[1]) if r and r[0] and r[1] else 1.0


def _day_view(conn: sqlite3.Connection | None, now: datetime) -> dict:
    try:
        return desk_day.view(conn, now=now)
    except Exception:  # noqa: BLE001
        return desk_day.view(None, now=now)


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


def measure(conn: sqlite3.Connection, mirror_series: dict, symbol: str, marks: dict | None = None) -> dict | None:
    px = list(planfacts.prices(conn, mirror_series, symbol))
    source, at = "close", None
    later = (marks or {}).get(symbol) or {}
    if px and later:
        scale = _scale(conn, symbol)
        for day in sorted(d for d in later if d > px[-1][0]):
            price, source, at = later[day]
            px.append((day, price * scale))
    s = planfacts.stats(px)
    if not s:
        return None
    out = dict(s) | {"price_as_of": px[-1][0], "price_source": source, "price_at": at, "closes": px[-KEEP_CLOSES:], "valuation": None, "swings": None}
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
        lead += f" Off below {_money(floor)}, {'three' if steps == 3 else 'two'} monthly swings under that price."
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


def analysis_day(m: dict, c: dict) -> tuple[str | None, str]:
    case, idea, hit = c.get("case"), c.get("scout"), c.get("hit")
    if hit and (case or not idea):
        return str(hit["as_of"])[:10], "case" if case else "scanner"
    if idea:
        seen = str(idea.get("as_of") or "")
        return (seen if len(seen) == 10 else _et_day(idea.get("created_at"))), "scout"
    return m.get("price_as_of"), "numbers"


def timing(m: dict, c: dict, book_day: str) -> dict:
    day, source, at = m.get("price_as_of") or book_day, m.get("price_source") or "close", m.get("price_at")
    seen, kind = analysis_day(m, c)
    seen = seen or day
    if source == "quote" and at:
        words = f"Priced at {desk_day.day_words(day)}, {desk_day.time_words(datetime.fromisoformat(str(at).replace('Z', '+00:00')))}."
    elif source == "provisional":
        words = f"Priced at the {desk_day.day_words(day)} close, provisional until the official close lands."
    else:
        words = f"Priced at the {desk_day.day_words(day)} close."
    since = None
    if seen < day and m.get("price"):
        base = next((p for d, p in reversed(m.get("closes") or ()) if d <= seen), None)
        since = round((m["price"] / base - 1) * 100, 2) if base else None
    lead = ANALYSIS_WORDS.get(kind)
    if lead and seen >= day:
        words += f" {lead} from the same day."
    elif lead:
        moved = (
            ""
            if since is None
            else ("; the price is about where it was" if abs(since) < 0.05 else f"; the price is {abs(since):.1f}% {'lower' if since < 0 else 'higher'} since")
        )
        words += f" {lead} from {desk_day.day_words(seen)}{moved}."
    else:
        words += " The numbers here are worked out from that price."
    return {
        "price_as_of": day,
        "price_source": source,
        "price_at": at,
        "price_behind": False,
        "analysis_as_of": min(seen, day),
        "since_analysis_pct": since,
        "as_of_words": words,
    }


def not_queued(c: dict, label: str, book: sizing.Book | None) -> str | None:
    idea = c.get("scout")
    back = (idea or {}).get("turned_back")
    if back and back["kind"] != "funding":
        return back["reason"]
    if label != "buy" or (idea and not back):
        return None
    funding = c["size"]["funding"]
    if funding != "cash" and book is not None:
        if book.debit > 0:
            tail = f" The {day_words(book.deposit_on)} deposit clears it and covers this." if funding == "deposit" else ""
            return f"Pay the margin debit first: {usd(book.debit)} is open, so no buy goes to the queue.{tail}"
        if funding == "deposit":
            return f"Needs more ready cash than there is: {usd(book.free)} today. It waits for the {day_words(book.deposit_on)} deposit."
        if str(c["size"].get("note") or "").startswith(sizing.SHORT):
            return "Needs more ready cash than the buying account holds today."
        return f"Needs more ready cash than there is: {usd(book.free)} is ready today."
    if back:
        return f"Scout's idea was turned back on {day_words(_et_day(idea.get('created_at')))}: {back['reason']} Nothing has proposed it again since."
    return None


def stance(c: dict) -> tuple[str, str]:
    blocked, case, idea = c["size"].get("blocked"), c.get("case"), c.get("scout")
    back = (idea or {}).get("turned_back")
    if back and back["kind"] != "funding" and not blocked:
        return "watch", "Watch: inside a no-buy window" if back["kind"] == "window" else "Watch: a standing note says hold off"
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


def headline(rows: list[dict], note: str | None, debit: bool = False) -> str:
    if not rows:
        return note or NOTHING
    top = rows[0]
    drop = next((f for f in top["facts"] if "under its 52-week high" in f), None)
    lead = f"Top: {top['symbol']}" + (f", {drop.replace(' its 52-week high', ' its high')}." if drop else ".")
    buy = sum(r["stance"] == "buy" for r in rows)
    rest = len(rows) - buy
    if buy:
        funded = any(r["stance"] == "buy" and r["size"]["funding"] == "cash" for r in rows)
        words = f"{buy} worth buying now" if funded else f"{buy} worth buying once {'the margin debit is paid' if debit else 'cash is free'}"
        return f"{words}, {rest} to watch. {lead}" if rest else f"{words}. {lead}"
    return f"Nothing rated a buy yet. {len(rows)} to watch. {lead}"


# ---- The list ----


def _asof(view: dict) -> dict:
    return {k: view.get(k) for k in ("day", "words", "status", "provisional", "expected_day", "behind")}


def _prices(rows: list[dict], book_day: str | None = None) -> dict:
    if not rows:
        return {"day": None, "words": None, "older": []}
    day = max([r["price_as_of"] for r in rows] + ([book_day] if book_day else []))
    older = [{"symbol": r["symbol"], "price_as_of": r["price_as_of"], "held": r["held"]} for r in rows if r["price_as_of"] < day]
    for r in rows:
        if r["price_as_of"] < day:
            r["price_behind"] = True
            r["as_of_words"] += " " + OLDER.format(day=desk_day.day_words(r["price_as_of"]))
    if not older:
        return {"day": day, "words": f"Every price here is from {desk_day.day_words(day)}.", "older": []}
    names = ", ".join(o["symbol"] for o in older)
    verb = "is" if len(older) == 1 else "are"
    words = (
        f"Prices run to {desk_day.day_words(day)}. {names} {verb} still at an earlier close: live quotes cover what you hold, and other closes land overnight."
    )
    return {"day": day, "words": words, "older": older}


def _empty(now: datetime, note: str, profile: dict, cash: dict, freshness: dict, view: dict | None = None) -> dict:
    return {
        "as_of": None,
        "asof": _asof(view or desk_day.view(None, now=now)),
        "prices": _prices([]),
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
    desk_view = _day_view(conn, now)
    if as_of is None:
        return _empty(now, NO_ENGINE, profile, sizing.cash_view(None), _freshness(cfg, conn, view), desk_view)
    book_day = desk_view.get("day") or as_of
    marks = _marks(conn)
    today = max([book_day, as_of, *(d for days in marks.values() for d in days)])
    ideas = {str(d["symbol"]).upper(): d for d in reversed(_turned_back(cfg, date.fromisoformat(today)))}
    ideas |= {str(d["symbol"]).upper(): d for d in reversed(_scout(cfg, date.fromisoformat(today)))}
    lists = _universe(conn)
    symbols = sorted(set(lists) | set(signals) | set(ideas))
    mirror_series = mirror_closes(mirror) if mirror is not None else {}
    measures = {s: m for s in symbols if (m := measure(conn, mirror_series, s, marks)) is not None}
    kinds = planfacts.kinds_of(mirror, conn, set(symbols))
    titles = planfacts.names(conn)
    book = sizing.load(cfg, mirror, conn, kinds, now=now, numbers=desk_view.get("numbers"))
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
            "next_earnings": _earnings(conn, sym, m.get("price_as_of") or book_day),
            "research_verdict": verdicts.get(sym) if sym in held else None,
        }
        c["entry"] = entry(m, tier)
        c["size"] = sizing.size(book, sym, c["kind"], m.get("price"))
        c["score"] = score(m, c)
        c["m"] = m
        (near if tier == "near" else picked).append(c)
    near.sort(key=lambda c: (-c["score"], c["symbol"]))
    picked += near[: max(0, MIN_ROWS - len(picked))]
    rows = [_row(c, book_day, book) for c in picked]
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
        "as_of": book_day,
        "asof": _asof(desk_view),
        "prices": _prices(rows, book_day),
        "built_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "advice_only": True,
        "freshness": fresh,
        "headline": headline(rows, note, debit=book is not None and book.debit > 0),
        "counts": counts,
        "note": note,
        "profile": profile,
        "cash": sizing.cash_view(book),
        "method": METHOD,
        "rows": rows,
        "passed": sorted(passed, key=lambda p: p["symbol"]),
    }


def _row(c: dict, book_day: str, book: sizing.Book | None) -> dict:
    m, case, idea = c["m"], c["case"], c["scout"]
    label, words = stance(c)
    wrong, floor = wrong_if(m, c)
    when = timing(m, c, book_day)
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
        "queued": bool(idea) and not idea.get("turned_back"),
        "not_queued": not_queued(c, label, book),
        "research_verdict": c["research_verdict"],
        "next_earnings": c["next_earnings"],
        "as_of": when["price_as_of"],
        **when,
        "score": c["score"],
    }
