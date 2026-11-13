import hashlib
import json
import os
import sqlite3
from array import array
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from desk.config import Config
from desk.db import connect
from desk.engine.market import BENCHMARKS, LIBRARY_FUNDS, QUALITY

SMALLCAP_BENCHMARK = "IWM"
PUBLIC_FUNDS = frozenset((*BENCHMARKS, *LIBRARY_FUNDS, SMALLCAP_BENCHMARK))

FUND_KINDS = ("fund", "etf")
LISTED_FUNDS = ("IVV", "VOO", "FTEC", "SMH", "SCHD", "GRID", "ICLN", "NLR", "UFO", "DIA", "MDY")
BARS_SCHEMA = """
CREATE TABLE bars (
  symbol TEXT NOT NULL, date TEXT NOT NULL, open REAL, close REAL NOT NULL, adj_close REAL, volume REAL, PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE symbols (symbol TEXT PRIMARY KEY, kind TEXT NOT NULL, role TEXT, first TEXT, last TEXT) WITHOUT ROWID;
"""
EXPORT_SCHEMA = (
    BARS_SCHEMA
    + """
CREATE TABLE macro (series TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series, date)) WITHOUT ROWID;
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE factors (series TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series, date)) WITHOUT ROWID;
CREATE TABLE french (set_name TEXT NOT NULL, name TEXT NOT NULL, date TEXT NOT NULL, ret REAL NOT NULL, PRIMARY KEY (set_name, name, date)) WITHOUT ROWID;
CREATE TABLE insider (symbol TEXT NOT NULL, known TEXT NOT NULL, owner INTEGER NOT NULL, usd REAL NOT NULL);
CREATE TABLE smallcap (symbol TEXT NOT NULL, month TEXT NOT NULL, PRIMARY KEY (symbol, month)) WITHOUT ROWID;
CREATE TABLE earnings (symbol TEXT NOT NULL, known TEXT NOT NULL, surprise REAL NOT NULL);
"""
)
HELD_FILE = "held.json"
PLAN_FILE = "plan.json"
OWN_FILE = "own.db"
PUBLIC_ROLE = "public"
PUBLIC_COVERAGE = "public_coverage"
GONE_SESSIONS = 10
WORKER_ROLES = dict.fromkeys(("held", "watch", "past", "plan"), "universe")
SMALLCAP_KIND = "stock"
SMALL_CAPS = "small_caps"
SMALLCAP_ROLE = "small_cap"
FRENCH_KIND = "french"
FRENCH_MARKET = "FF.MKT"
SCREEN_KIND = "screen"


def french_symbol(set_name: str, name: str) -> str:
    return f"FF.{set_name}.{name}"


class NotReady(RuntimeError):
    pass


def lab_dir(cfg: Config) -> Path:
    return cfg.data_dir / "lab"


def data_path(cfg: Config) -> Path:
    return lab_dir(cfg) / "data" / "lab.db"


def held_path(cfg: Config) -> Path:
    return data_path(cfg).with_name(HELD_FILE)


def plan_path(cfg: Config) -> Path:
    return data_path(cfg).with_name(PLAN_FILE)


def own_path(cfg: Config) -> Path:
    return data_path(cfg).with_name(OWN_FILE)


def ledger_path(cfg: Config) -> Path:
    return lab_dir(cfg) / "runs" / "ledger.db"


@cache
def lab_build() -> str:
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


# ---- Export (engine side) ----


def export(cfg: Config, desk: sqlite3.Connection, kinds: dict[str, str], targets: dict[str, float], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    final = data_path(cfg)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(".lab.db.tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp)
    try:
        out.executescript(EXPORT_SCHEMA)
        add = "INSERT OR IGNORE INTO bars VALUES (?, ?, ?, ?, ?, ?)"
        small = _small_caps(desk, out)
        kinds = _public_kinds(desk, kinds, targets)
        public, cover = _public(desk)
        shared = PUBLIC_FUNDS | frozenset(QUALITY) | public | small
        mine: dict[str, bool] = {}
        kept: list[tuple] = []

        def for_workers(rows):
            for r in rows:
                sym = r[0]
                if sym not in mine:
                    mine[sym] = sym not in shared and kinds.get(sym, "unknown") not in FUND_KINDS
                if mine[sym]:
                    kept.append(r)
                else:
                    yield r

        out.executemany(add, for_workers(tuple(r) for r in desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM price_bars")))
        daily = ((r[0], r[1], None, r[2], r[3], None) for r in desk.execute("SELECT symbol, date, close, adj_close FROM prices_daily"))
        out.executemany(add, for_workers(daily))
        if _has(desk, "alpaca_bars"):
            for sym in sorted(small | {SMALLCAP_BENCHMARK}):
                out.executemany(
                    add, (tuple(r) for r in desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM alpaca_bars WHERE symbol=?", (sym,)))
                )
        bars = out.execute("SELECT count(*) FROM bars").fetchone()[0]
        roles = {r["symbol"]: WORKER_ROLES.get(r["role"], r["role"]) for r in desk.execute("SELECT symbol, role FROM market_symbols")}
        roles |= {sym: roles.get(sym) or SMALLCAP_ROLE for sym in small}
        spans = {r[0]: (r[1], r[2]) for r in out.execute("SELECT symbol, min(date), max(date) FROM bars GROUP BY symbol")}
        rows = []
        for sym, (first, last) in spans.items():
            if sym in PUBLIC_FUNDS:
                rows.append((sym, "fund", "benchmark", first, last))
            elif sym in public:
                rows.append((sym, "stock", PUBLIC_ROLE, first, last))
            else:
                rows.append((sym, kinds.get(sym) or (SMALLCAP_KIND if sym in small else "unknown"), roles.get(sym), first, last))
        out.executemany("INSERT INTO symbols VALUES (?, ?, ?, ?, ?)", rows)
        own = _write_own(final.with_name(OWN_FILE), kept, kinds, roles)
        french_rows = 0
        if desk.execute("SELECT 1 FROM sqlite_master WHERE name='factors_daily'").fetchone():
            out.executemany("INSERT INTO factors VALUES (?, ?, ?)", (tuple(r) for r in desk.execute("SELECT series, date, value FROM factors_daily")))
            out.executemany("INSERT INTO french VALUES (?, ?, ?, ?)", (tuple(r) for r in desk.execute("SELECT set_name, name, date, ret FROM french_returns")))
            french_rows = out.execute("SELECT count(*) FROM french").fetchone()[0]
        if desk.execute("SELECT 1 FROM sqlite_master WHERE name='macro_daily'").fetchone():
            out.executemany("INSERT INTO macro VALUES (?, ?, ?)", (tuple(r) for r in desk.execute("SELECT series, date, value FROM macro_daily")))
        rate = desk.execute(
            "SELECT value FROM metric_values WHERE metric_id='tax.marginal_rate' AND scope='portfolio' AND value IS NOT NULL ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        settings = {"exported_at": now.isoformat(timespec="seconds"), "marginal_rate_pct": str(rate[0]) if rate else None}
        held, covered, held_day = _held_mix(desk, spans | own)
        listed = cover({s for s in public if s in spans})
        if listed:
            settings[PUBLIC_COVERAGE] = json.dumps(listed)
        if small and _has(desk, "insider_buys"):
            from desk.engine.insider import coverage

            settings["insider_coverage"] = json.dumps(coverage(desk))
        if small and _has(desk, "earnings_events"):
            from desk.engine import earnings

            out.executemany("INSERT INTO earnings VALUES (?, ?, ?)", (tuple(r) for r in desk.execute("SELECT symbol, known, surprise FROM earnings_events")))
            settings["earnings_coverage"] = json.dumps(earnings.coverage(desk))
        out.executemany("INSERT INTO settings VALUES (?, ?)", list(settings.items()))
        out.commit()
    finally:
        out.close()
    os.replace(tmp, final)
    _write_box(final.with_name(HELD_FILE), {"as_of": held_day, "covered": covered, "weights": held})
    _write_box(final.with_name(PLAN_FILE), {"weights": {s: w for s, w in targets.items() if w > 0}})
    return {
        "ok": True,
        "path": str(final),
        "symbols": len(spans),
        "bars": bars,
        "french_rows": french_rows,
        "small_caps": len(small),
        "held_mix": len(held),
        "public_stocks": (listed or {}).get("priced", 0),
        "kept_on_box": len(own),
    }


def _public(desk: sqlite3.Connection):
    from desk.engine import public

    priced = frozenset(r["symbol"] for r in public.names(desk) if r["state"] == public.PRICED and r["symbol"])
    return priced, lambda loaded: public.coverage(desk, loaded)


def _write_own(path: Path, rows: list[tuple], kinds: dict[str, str], roles: dict[str, str | None]) -> dict[str, tuple[str, str]]:
    if not rows:
        path.unlink(missing_ok=True)
        return {}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(BARS_SCHEMA)
        conn.executemany("INSERT OR IGNORE INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        spans = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT symbol, min(date), max(date) FROM bars GROUP BY symbol")}
        conn.executemany("INSERT INTO symbols VALUES (?, ?, ?, ?, ?)", [(s, kinds.get(s) or "unknown", roles.get(s), a, b) for s, (a, b) in spans.items()])
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)
    return spans


def _write_box(path: Path, body: dict) -> None:
    if not body["weights"]:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(body, sort_keys=True))
    os.replace(tmp, path)


def read_held(path: Path) -> dict:
    try:
        body = json.loads(path.read_text())
        weights = {str(s): float(w) for s, w in (body.get("weights") or {}).items() if float(w) > 0}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    return {"as_of": body.get("as_of"), "covered": body.get("covered"), "weights": weights} if weights else {}


def read_plan(path: Path) -> dict[str, float]:
    return read_held(path).get("weights") or {}


def _public_kinds(desk: sqlite3.Connection, kinds: dict[str, str], symbols) -> dict[str, str]:
    from desk.engine.core import guess_kind

    funds = {r[0] for r in desk.execute("SELECT symbol FROM sec_funds")} if _has(desk, "sec_funds") else set()
    titles = {r[0]: r[1] or "" for r in desk.execute("SELECT symbol, title FROM sec_tickers")} if _has(desk, "sec_tickers") else {}
    guessed = {s: guess_kind(s, funds, titles) for s in symbols if kinds.get(s, "unknown") == "unknown"}
    return kinds | {s: "fund" if kind == "unknown" else kind for s, kind in guessed.items()}


def _held_mix(desk: sqlite3.Connection, priced) -> tuple[dict[str, float], float | None, str | None]:
    if not _has(desk, "holdings_daily"):
        return {}, None, None
    day = desk.execute("SELECT max(date) FROM holdings_daily").fetchone()[0]
    if not day:
        return {}, None, None
    rows = desk.execute("SELECT symbol, sum(value) FROM holdings_daily WHERE date=? AND is_cash=0 GROUP BY symbol HAVING sum(value) > 0", (day,))
    values = {r[0]: r[1] for r in rows}
    kept = {s: v for s, v in values.items() if s in priced}
    have = sum(kept.values())
    if not have:
        return {}, None, day
    mix = {s: round(v / have, 4) for s, v in kept.items()}
    return {s: w for s, w in mix.items() if w > 0}, round(have / sum(values.values()), 2), day


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _small_caps(desk: sqlite3.Connection, out: sqlite3.Connection) -> set[str]:
    if not _has(desk, "smallcap_months"):
        return set()
    from desk.engine.insider import known_day

    out.executemany("INSERT INTO smallcap VALUES (?, ?)", (tuple(r) for r in desk.execute("SELECT symbol, month FROM smallcap_months")))
    if _has(desk, "insider_buys"):
        known: dict[str, str] = {}
        out.executemany(
            "INSERT INTO insider VALUES (?, ?, ?, ?)",
            (
                (r[0], known.get(r[1]) or known.setdefault(r[1], known_day(r[1])), r[2], r[3])
                for r in desk.execute("SELECT symbol, filed_date, owner_cik, usd FROM insider_buys")
            ),
        )
    return {r[0] for r in out.execute("SELECT DISTINCT symbol FROM smallcap")}


# ---- Load (lab side) ----


class DayIndex(Mapping):
    __slots__ = ("pos", "first", "slots", "size")

    def __init__(self, pos: dict[str, int], dates: list[str]):
        self.pos, self.first, self.size = pos, pos[dates[0]], len(dates)
        self.slots = array("i", [-1]) * (pos[dates[-1]] - self.first + 1)
        for i, d in enumerate(dates):
            self.slots[pos[d] - self.first] = i

    def get(self, day, default=None):
        at = self.pos.get(day)
        if at is None or not 0 <= at - self.first < len(self.slots):
            return default
        i = self.slots[at - self.first]
        return i if i >= 0 else default

    def __getitem__(self, day):
        i = self.get(day)
        if i is None:
            raise KeyError(day)
        return i

    def __contains__(self, day):
        return self.get(day) is not None

    def __iter__(self):
        return (d for d in self.pos if d in self)

    def __len__(self):
        return self.size


@dataclass
class Series:
    dates: list[str]
    adj: Sequence[float]
    open_adj: Sequence[float]
    volume: Sequence[float | None]
    index: Mapping[str, int] = field(default_factory=dict)

    def at(self, day: str) -> int | None:
        i = bisect_right(self.dates, day) - 1
        return i if i >= 0 else None


@dataclass
class LabData:
    series: dict[str, Series]
    kinds: dict[str, str]
    roles: dict[str, str | None]
    last: dict[str, str]
    macro: dict[str, tuple[list[str], list[float]]]
    plan_mix: dict[str, float]
    settings: dict[str, str | None]
    calendar: list[str]
    factors: dict[str, dict[str, float]] = field(default_factory=dict)
    screen_days: list[str] | None = None
    path: Path | None = None
    french_sets: dict[str, list[str]] = field(default_factory=dict)
    insider: dict[str, tuple[list[str], list[int], list[float]]] = field(default_factory=dict)
    smallcap: dict[str, set[str]] = field(default_factory=dict)
    earnings: dict[str, tuple[list[str], list[float]]] = field(default_factory=dict)
    held_mix: dict[str, float] = field(default_factory=dict)

    def coverage(self, key: str = "insider_coverage") -> dict | None:
        raw = self.settings.get(key)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    @property
    def end(self) -> str:
        return self.calendar[-1]

    def calendar_for(self, kind: str) -> list[str]:
        if kind == FRENCH_KIND:
            s = self.series.get(FRENCH_MARKET)
            return s.dates if s else []
        if kind == SCREEN_KIND and self.screen_days:
            return self.screen_days
        return self.calendar

    def end_for(self, kind: str) -> str:
        cal = self.calendar_for(kind)
        return cal[-1] if cal else self.end

    def french(self, set_name: str) -> list[str]:
        if set_name in self.french_sets:
            return self.french_sets[set_name]
        symbols: list[str] = []
        if self.path is not None and self.path.exists():
            conn = connect(self.path, readonly=True)
            try:
                shared: dict[tuple[str, str, int], tuple[list[str], dict[str, int], list[None]]] = {}
                days: dict[str, str] = {}
                name, dates, pcts = None, [], array("d")

                def flush():
                    if name is None or not dates:
                        return
                    key = (dates[0], dates[-1], len(dates))
                    if key not in shared:
                        shared[key] = (dates, {d: i for i, d in enumerate(dates)}, [None] * len(dates))
                    same, index, nones = shared[key]
                    sym = french_symbol(set_name, name)
                    self.series[sym] = _levels(same, pcts, index, nones)
                    self.kinds[sym] = FRENCH_KIND
                    self.roles[sym] = None
                    self.last[sym] = same[-1]
                    symbols.append(sym)

                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='french'").fetchone():
                    for r in conn.execute("SELECT name, date, ret FROM french WHERE set_name=? ORDER BY name, date", (set_name,)):
                        if r[0] != name:
                            flush()
                            name, dates, pcts = r[0], [], array("d")
                        dates.append(days.setdefault(r[1], r[1]))
                        pcts.append(r[2])
                    flush()
            finally:
                conn.close()
        self.french_sets[set_name] = sorted(symbols)
        return self.french_sets[set_name]

    def macro_at(self, series: str, day: str) -> float | None:
        dates, values = self.macro.get(series, ([], []))
        i = bisect_right(dates, day)
        return values[i - 1] if i else None


def gone_before(calendar: list[str]) -> str:
    return calendar[max(0, len(calendar) - 1 - GONE_SESSIONS)] if calendar else ""


def _screen_days(calendar: list[str], lasts: list[str]) -> list[str] | None:
    if not lasts:
        return None
    usual = min(sorted(lasts)[len(lasts) // 2], calendar[-1])
    floor = gone_before(calendar[: bisect_right(calendar, usual)])
    through = min(d for d in lasts if d >= floor)
    return calendar[: bisect_right(calendar, min(through, calendar[-1]))] or None


def _levels(dates: list[str], pcts: Sequence[float], index: dict[str, int], volume: list) -> Series:
    level, adj = 100.0, array("d")
    for x in pcts:
        level *= 1 + x / 100
        adj.append(level)
    return Series(dates, adj, adj, volume, index)


def _french_market(factors: dict[str, dict[str, float]]) -> Series | None:
    mkt, rf = factors.get("mkt_rf") or {}, factors.get("rf") or {}
    dates = sorted(mkt)
    if not dates:
        return None
    return _levels(dates, [mkt[d] + rf.get(d, 0.0) for d in dates], {d: i for i, d in enumerate(dates)}, [None] * len(dates))


def load(path: Path) -> LabData:
    if not path.exists():
        raise NotReady("No lab data yet; the engine's lab-export job writes it nightly.")
    conn = connect(path, readonly=True)
    side = path.with_name(OWN_FILE)
    own = connect(side, readonly=True) if side.exists() else None
    files = [c for c in (own, conn) if c is not None]
    try:
        series: dict[str, Series] = {}
        pos = {d: i for i, d in enumerate(sorted({r[0] for c in files for r in c.execute("SELECT DISTINCT date FROM bars")}))}
        days = {d: d for d in pos}
        kinds, roles, last = {}, {}, {}
        for c in files:
            cur, dates, adj, opens, volume = None, [], array("d"), array("d"), array("d")
            for sym, day, close, adjusted, opened, vol in c.execute("SELECT symbol, date, close, adj_close, open, volume FROM bars ORDER BY symbol, date"):
                if sym != cur:
                    if cur and dates:
                        series[cur] = Series(dates, adj, opens, volume, DayIndex(pos, dates))
                    cur, dates, adj, opens, volume = sym, [], array("d"), array("d"), array("d")
                a = adjusted if adjusted else close
                dates.append(days[day])
                adj.append(a)
                opens.append((opened * (adjusted / close) if adjusted and close else opened) if opened else a)
                volume.append(vol or 0.0)
            if cur and dates:
                series[cur] = Series(dates, adj, opens, volume, DayIndex(pos, dates))
            for r in c.execute("SELECT symbol, kind, role, last FROM symbols"):
                kinds[r[0]], roles[r[0]], last[r[0]] = r[1], r[2], r[3]
        for sym in LISTED_FUNDS:
            if sym in kinds and kinds[sym] not in FUND_KINDS:
                kinds[sym] = "etf"
        macro: dict[str, tuple[list[str], list[float]]] = {}
        for r in conn.execute("SELECT series, date, value FROM macro ORDER BY series, date"):
            d, v = macro.setdefault(r[0], ([], []))
            d.append(r[1])
            v.append(r[2])
        settings = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM settings")}
        factors: dict[str, dict[str, float]] = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='factors'").fetchone():
            for r in conn.execute("SELECT series, date, value FROM factors"):
                factors.setdefault(r[0], {})[days.setdefault(r[1], r[1])] = r[2]
        insider: dict[str, tuple[list[str], list[int], list[float]]] = {}
        smallcap: dict[str, set[str]] = {}
        if _has(conn, "insider"):
            for r in conn.execute("SELECT symbol, known, owner, usd FROM insider ORDER BY symbol, known"):
                d, o, u = insider.setdefault(r[0], ([], [], []))
                d.append(r[1])
                o.append(r[2])
                u.append(r[3])
            for r in conn.execute("SELECT symbol, month FROM smallcap"):
                smallcap.setdefault(r[0], set()).add(r[1])
        earnings: dict[str, tuple[list[str], list[float]]] = {}
        if _has(conn, "earnings"):
            for r in conn.execute("SELECT symbol, known, surprise FROM earnings ORDER BY symbol, known"):
                d, v = earnings.setdefault(r[0], ([], []))
                d.append(r[1])
                v.append(r[2])
    finally:
        for c in files:
            c.close()
    ref = next((s for s in ("SPY", "VTI", "FXAIX") if s in series), None) or max(series, key=lambda s: len(series[s].dates), default=None)
    market = _french_market(factors)
    if market is not None:
        series[FRENCH_MARKET], kinds[FRENCH_MARKET], roles[FRENCH_MARKET], last[FRENCH_MARKET] = market, FRENCH_KIND, None, market.dates[-1]
    if not ref:
        ref = FRENCH_MARKET if market is not None else None
    if not ref:
        raise NotReady("The lab data has no prices yet.")
    held = read_held(path.with_name(HELD_FILE))
    if held:
        settings |= {"held_mix_as_of": held["as_of"], "held_mix_covered": str(held["covered"]) if held["covered"] is not None else None}
    calendar = list(series[ref].dates)
    return LabData(
        series,
        kinds,
        roles,
        last,
        macro,
        read_plan(path.with_name(PLAN_FILE)),
        settings,
        calendar,
        factors,
        _screen_days(calendar, [series[s].dates[-1] for s, role in roles.items() if role == PUBLIC_ROLE and s in series]),
        path,
        insider=insider,
        smallcap=smallcap,
        earnings=earnings,
        held_mix=held.get("weights") or {},
    )
