import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from desk.engine.filings import EVENT_TYPES, lane_start
from desk.engine.lab.paper import PAPER_DAYS
from desk.engine.market import ET, trading_day

STRATEGY_ID = "filings-lane"
VERSION = 1
CAPITAL = 1000.0
BENCHMARK = "IWM"
LIMITS = {"min_direction": (1, 2), "min_confidence": (0.5, 0.95), "hold_sessions": (5, 60), "max_names": (3, 20)}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")
MAX_VARIANTS = 12


@dataclass(frozen=True)
class LaneSpec:
    id: str = STRATEGY_ID
    version: int = VERSION
    title: str = "Filings lane: buy small caps Claude scores +1 or better"
    min_direction: int = 1
    min_confidence: float = 0.6
    hold_sessions: int = 20
    max_names: int = 10
    event_types: tuple[str, ...] = ()
    hypothesis: str | None = None
    registered_at: str | None = None

    def rule(self) -> str:
        kinds = f" on {', '.join(self.event_types)} filings" if self.event_types else ""
        return (
            f"Buy names scored at least +{self.min_direction} with confidence at least {self.min_confidence}{kinds} at the next open after scoring, "
            f"hold {self.hold_sessions} trading days, equal weight in {self.max_names} slots, cash otherwise. Benchmark {BENCHMARK}."
        )

    def params(self) -> dict:
        d = asdict(self)
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in d.items() if k in LIMITS or k == "event_types"}


DEFAULT = LaneSpec()
MIN_DIRECTION, MIN_CONFIDENCE, HOLD_SESSIONS, MAX_NAMES = DEFAULT.min_direction, DEFAULT.min_confidence, DEFAULT.hold_sessions, DEFAULT.max_names
TITLE, RULE = DEFAULT.title, DEFAULT.rule()


@dataclass
class Trade:
    symbol: str
    accession: str
    confidence: float
    entry: str
    exit: str
    entry_px: float | None = None
    exit_px: float | None = None
    shares: float = 0.0


@dataclass
class Lane:
    start: str | None
    trades: list[Trade] = field(default_factory=list)
    values: list[tuple[str, float]] = field(default_factory=list)
    bench: list[tuple[str, float]] = field(default_factory=list)


# ---- Calendar ----


def _stamp(text: str) -> datetime:
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def entry_session(known: datetime) -> date:
    t = known.astimezone(ET)
    d = t.date()
    if not (trading_day(d) and t < datetime.combine(d, time(9, 30), ET)):
        d += timedelta(days=1)
        while not trading_day(d):
            d += timedelta(days=1)
    return d


def add_sessions(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if trading_day(d):
            n -= 1
    return d


# ---- Signals into trades ----


def signals(conn: sqlite3.Connection, spec: LaneSpec = DEFAULT) -> list[dict]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='filing_signals'").fetchone() is None:
        return []
    rows = conn.execute(
        "SELECT accession, symbol, filed_at, scored_at, direction, confidence, event_type FROM filing_signals "
        "WHERE direction >= ? AND confidence >= ? ORDER BY scored_at",
        (spec.min_direction, spec.min_confidence),
    ).fetchall()
    return [dict(r) for r in rows if not spec.event_types or r["event_type"] in spec.event_types]


def start_day(conn: sqlite3.Connection, spec: LaneSpec = DEFAULT) -> date | None:
    first = lane_start(conn)
    if not first:
        return None
    begin = entry_session(_stamp(first))
    if spec.registered_at:
        begin = max(begin, entry_session(_stamp(spec.registered_at)))
    return begin


def plan(rows: list[dict], through: date, spec: LaneSpec = DEFAULT, start: date | None = None) -> list[Trade]:
    cands = []
    for r in rows:
        known = max(_stamp(r["scored_at"]), _stamp(r["filed_at"])) if r["filed_at"] else _stamp(r["scored_at"])
        begin = entry_session(known)
        if spec.registered_at and known < _stamp(spec.registered_at):
            continue
        if begin <= through and (start is None or begin >= start):
            cands.append((begin, -r["confidence"], r["accession"], r))
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    taken: list[Trade] = []
    for begin, _, acc, r in cands:
        day = begin.isoformat()
        live = [t for t in taken if t.entry <= day < t.exit]
        if len(live) >= spec.max_names or any(t.symbol == r["symbol"] for t in live):
            continue
        taken.append(Trade(r["symbol"], acc, r["confidence"], day, add_sessions(begin, spec.hold_sessions).isoformat()))
    return taken


def targets(conn: sqlite3.Connection, now: datetime | None = None, spec: LaneSpec = DEFAULT) -> dict[str, Trade]:
    now = now or datetime.now(UTC)
    today = entry_session(now)
    begin = start_day(conn, spec)
    if begin is None:
        return {}
    return {t.symbol: t for t in plan(signals(conn, spec), today, spec, begin) if t.entry <= today.isoformat() < t.exit}


# ---- Variants ----


def _clean(params: dict) -> dict:
    out = {}
    for key, (lo, hi) in LIMITS.items():
        if key not in params:
            continue
        v = params[key]
        if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        out[key] = int(v) if key != "min_confidence" else float(v)
    kinds = params.get("event_types") or []
    if not isinstance(kinds, list) or any(k not in EVENT_TYPES for k in kinds):
        raise ValueError(f"event_types must be a list drawn from {', '.join(EVENT_TYPES)}")
    out["event_types"] = tuple(sorted(set(kinds)))
    unknown = set(params) - set(LIMITS) - {"event_types"}
    if unknown:
        raise ValueError(f"unknown lane params: {', '.join(sorted(unknown))}")
    return out


def register(conn: sqlite3.Connection, strategy_id: str, title: str, params: dict, *, hypothesis: str | None = None, now: datetime | None = None) -> LaneSpec:
    if not ID_RE.match(strategy_id or "") or strategy_id == STRATEGY_ID:
        raise ValueError("id must be 3-32 lowercase letters, digits or dashes, and not filings-lane")
    if not title or len(title) > 120:
        raise ValueError("title must be 1-120 characters")
    clean = _clean(params)
    spec = LaneSpec(**(asdict(DEFAULT) | clean | {"id": strategy_id, "title": title, "hypothesis": (hypothesis or "")[:400] or None}))
    if any(v.params() == spec.params() for v in variants(conn) if v.id != strategy_id):
        raise ValueError("a lane with the same params already runs")
    live = [v for v in variants(conn) if v.registered_at]
    prior = conn.execute("SELECT max(version) FROM lane_variants WHERE id=?", (strategy_id,)).fetchone()[0]
    if prior is None and len(live) >= MAX_VARIANTS:
        raise ValueError(f"at most {MAX_VARIANTS} lane variants run at once")
    version = (prior or 0) + 1
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    spec = LaneSpec(**(asdict(spec) | {"version": version, "registered_at": stamp}))
    with conn:
        conn.execute(
            "INSERT INTO lane_variants (id, version, title, params, hypothesis, registered_at) VALUES (?, ?, ?, ?, ?, ?)",
            (spec.id, spec.version, spec.title, json.dumps(spec.params()), spec.hypothesis, stamp),
        )
    return spec


def register_variant(cfg, strategy_id: str, title: str, params: dict, *, hypothesis: str | None = None) -> dict:
    from desk.db import connect
    from desk.engine import schema

    conn = connect(cfg.desk_db)
    try:
        schema.apply(conn)
        spec = register(conn, strategy_id, title, params, hypothesis=hypothesis)
    finally:
        conn.close()
    return {"id": spec.id, "version": spec.version, "registered_at": spec.registered_at, "rule": spec.rule(), "params": spec.params()}


def variants(conn: sqlite3.Connection) -> list[LaneSpec]:
    out = [DEFAULT]
    if not _has(conn, "lane_variants"):
        return out
    latest: dict[str, sqlite3.Row] = {}
    for r in conn.execute("SELECT * FROM lane_variants ORDER BY id, version"):
        latest[r["id"]] = r
    for r in latest.values():
        p = json.loads(r["params"])
        p["event_types"] = tuple(p.get("event_types") or ())
        out.append(
            LaneSpec(
                **(
                    asdict(DEFAULT)
                    | p
                    | {"id": r["id"], "version": r["version"], "title": r["title"], "hypothesis": r["hypothesis"], "registered_at": r["registered_at"]}
                )
            )
        )
    return out


# ---- Forward paper record ----


def _bars(conn: sqlite3.Connection, symbol: str) -> dict[str, tuple[float, float]]:
    out = {}
    for r in conn.execute("SELECT date, open, close, adj_close FROM alpaca_bars WHERE symbol=? ORDER BY date", (symbol,)):
        factor = (r["adj_close"] / r["close"]) if r["adj_close"] and r["close"] else 1.0
        out[r["date"]] = ((r["open"] or r["close"]) * factor, (r["adj_close"] or r["close"]))
    return out


def _at_or_after(bars: dict[str, tuple[float, float]], day: str) -> tuple[str, float] | None:
    for d in sorted(bars):
        if d >= day:
            return d, bars[d][0]
    return None


def simulate(conn: sqlite3.Connection, spec: LaneSpec = DEFAULT) -> Lane:
    begin = start_day(conn, spec)
    last = conn.execute("SELECT max(date) FROM alpaca_bars").fetchone()[0] if _has(conn, "alpaca_bars") else None
    if not begin or not last:
        return Lane(start=None)
    start = begin.isoformat()
    lane = Lane(start=start, trades=plan(signals(conn, spec), date.fromisoformat(last), spec, begin))
    bench = _bars(conn, BENCHMARK)
    days = sorted(d for d in bench if start <= d <= last)
    if not days:
        return lane
    slot = CAPITAL / spec.max_names
    cash = CAPITAL
    prices = {t.symbol: _bars(conn, t.symbol) for t in lane.trades}
    for day in days:
        for t in lane.trades:
            if t.entry_px is not None and t.exit_px is None and t.exit <= day:
                hit = _at_or_after(prices[t.symbol], t.exit)
                if hit and hit[0] <= day:
                    t.exit_px = hit[1]
                    cash += t.shares * t.exit_px
            if t.entry_px is None and t.entry <= day < t.exit:
                hit = _at_or_after(prices[t.symbol], t.entry)
                if hit and hit[0] <= day and hit[1]:
                    t.entry_px = hit[1]
                    t.shares = slot / t.entry_px
                    cash -= slot
        held = sum(t.shares * _close(prices[t.symbol], day) for t in lane.trades if t.entry_px is not None and t.exit_px is None)
        lane.values.append((day, round(cash + held, 2)))
        lane.bench.append((day, bench[day][1] / bench[days[0]][1]))
    return lane


def _close(bars: dict[str, tuple[float, float]], day: str) -> float:
    seen = [d for d in bars if d <= day]
    return bars[max(seen)][1] if seen else 0.0


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def drawdown_pct(values: list[float]) -> float:
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1)
    return round(worst * 100, 4)


def rebuild_one(conn: sqlite3.Connection, spec: LaneSpec = DEFAULT) -> dict:
    lane = simulate(conn, spec)
    sid, ver = spec.id, spec.version
    if not lane.start or not lane.values:
        return {"strategy_id": sid, "version": ver, "status": "not_started", "start": lane.start}
    as_of = lane.values[-1][0]
    days = (date.fromisoformat(as_of) - date.fromisoformat(lane.start)).days
    own = (lane.values[-1][1] / CAPITAL - 1) * 100
    bench = (lane.bench[-1][1] - 1) * 100
    excess = own - bench
    status = "paper" if days < PAPER_DAYS else ("eligible" if excess >= 0 else "retired")
    opened = [t for t in lane.trades if t.entry_px is not None]
    still = [t for t in opened if t.exit_px is None]
    summary = {
        "kind": "lane",
        "rule": spec.rule(),
        "params": spec.params(),
        "hypothesis": spec.hypothesis,
        "forward_only": True,
        "signals": len(lane.trades),
        "opened": len(opened),
        "open_now": len(still),
        "closed": len(opened) - len(still),
        "trades": len(opened) + len(opened) - len(still),
        "hit_rate": round(sum(1 for t in opened if t.exit_px and t.exit_px > t.entry_px) / max(1, len(opened) - len(still)), 4),
        "benchmark": BENCHMARK,
        "benchmark_return_pct": round(bench, 4),
        "mdd_pct": drawdown_pct([v for _, v in lane.values]),
        "days_to_eligible": max(0, PAPER_DAYS - days),
    }
    with conn:
        conn.execute("DELETE FROM paper_trades WHERE strategy_id=? AND version=?", (sid, ver))
        trades = []
        for t in opened:
            trades.append((sid, ver, t.entry, t.symbol, "buy", round(t.shares, 6), round(t.entry_px, 4), round(t.shares * t.entry_px, 2)))
            if t.exit_px is not None:
                trades.append((sid, ver, t.exit, t.symbol, "sell", round(t.shares, 6), round(t.exit_px, 4), round(t.shares * t.exit_px, 2)))
        conn.executemany("INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)", trades)
        conn.execute("DELETE FROM paper_positions WHERE strategy_id=? AND version=?", (sid, ver))
        conn.executemany(
            "INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?)",
            [(sid, ver, as_of, t.symbol, round(t.shares, 6), round(t.shares * _close(_bars(conn, t.symbol), as_of), 2)) for t in still],
        )
        conn.execute(
            "INSERT OR REPLACE INTO paper_portfolios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, ver, spec.title, lane.start, as_of, days, lane.values[-1][1], round(own, 4), round(excess, 4), status, json.dumps(summary)),
        )
    return {"strategy_id": sid, "version": ver, "status": status, "start": lane.start, "as_of": as_of, "open_now": len(still), "return_pct": round(own, 4)}


def rebuild(conn: sqlite3.Connection) -> dict:
    results = [rebuild_one(conn, spec) for spec in variants(conn)]
    return results[0] | {"variants": results[1:]}


def is_lane(conn: sqlite3.Connection, strategy_id: str) -> bool:
    return any(v.id == strategy_id for v in variants(conn))
