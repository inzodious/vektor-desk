import json
import os
import sqlite3
from array import array
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from desk.config import Config
from desk.db import connect
from desk.engine.market import BENCHMARKS

SMALLCAP_BENCHMARK = "IWM"

FUND_KINDS = ("fund", "etf")
EXPORT_SCHEMA = """
CREATE TABLE bars (
  symbol TEXT NOT NULL, date TEXT NOT NULL, open REAL, close REAL NOT NULL, adj_close REAL, volume REAL, PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE symbols (symbol TEXT PRIMARY KEY, kind TEXT NOT NULL, role TEXT, first TEXT, last TEXT) WITHOUT ROWID;
CREATE TABLE macro (series TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series, date)) WITHOUT ROWID;
CREATE TABLE plan_mix (symbol TEXT PRIMARY KEY, weight REAL NOT NULL) WITHOUT ROWID;
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE factors (series TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series, date)) WITHOUT ROWID;
CREATE TABLE french (set_name TEXT NOT NULL, name TEXT NOT NULL, date TEXT NOT NULL, ret REAL NOT NULL, PRIMARY KEY (set_name, name, date)) WITHOUT ROWID;
CREATE TABLE insider (symbol TEXT NOT NULL, known TEXT NOT NULL, owner INTEGER NOT NULL, usd REAL NOT NULL);
CREATE TABLE smallcap (symbol TEXT NOT NULL, month TEXT NOT NULL, PRIMARY KEY (symbol, month)) WITHOUT ROWID;
CREATE TABLE earnings (symbol TEXT NOT NULL, known TEXT NOT NULL, surprise REAL NOT NULL);
"""
SMALLCAP_KIND = "stock"
SMALL_CAPS = "small_caps"
SMALLCAP_ROLE = "small_cap"
FRENCH_KIND = "french"
FRENCH_MARKET = "FF.MKT"


def french_symbol(set_name: str, name: str) -> str:
    return f"FF.{set_name}.{name}"


class NotReady(RuntimeError):
    pass


def lab_dir(cfg: Config) -> Path:
    return cfg.data_dir / "lab"


def data_path(cfg: Config) -> Path:
    return lab_dir(cfg) / "data" / "lab.db"


def ledger_path(cfg: Config) -> Path:
    return lab_dir(cfg) / "runs" / "ledger.db"


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
        out.executemany(add, (tuple(r) for r in desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM price_bars")))
        out.executemany(add, ((r[0], r[1], None, r[2], r[3], None) for r in desk.execute("SELECT symbol, date, close, adj_close FROM prices_daily")))
        small = _small_caps(desk, out)
        if _has(desk, "alpaca_bars"):
            for sym in sorted(small | {SMALLCAP_BENCHMARK}):
                out.executemany(
                    add, (tuple(r) for r in desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM alpaca_bars WHERE symbol=?", (sym,)))
                )
        bars = out.execute("SELECT count(*) FROM bars").fetchone()[0]
        roles = {r["symbol"]: r["role"] for r in desk.execute("SELECT symbol, role FROM market_symbols")}
        roles |= {sym: roles.get(sym) or SMALLCAP_ROLE for sym in small}
        spans = {r[0]: (r[1], r[2]) for r in out.execute("SELECT symbol, min(date), max(date) FROM bars GROUP BY symbol")}
        rows = []
        for sym, (first, last) in spans.items():
            kind = kinds.get(sym) or (
                "fund" if sym in BENCHMARKS or sym in targets or sym == SMALLCAP_BENCHMARK else SMALLCAP_KIND if sym in small else "unknown"
            )
            rows.append((sym, kind, roles.get(sym), first, last))
        out.executemany("INSERT INTO symbols VALUES (?, ?, ?, ?, ?)", rows)
        french_rows = 0
        if desk.execute("SELECT 1 FROM sqlite_master WHERE name='factors_daily'").fetchone():
            out.executemany("INSERT INTO factors VALUES (?, ?, ?)", (tuple(r) for r in desk.execute("SELECT series, date, value FROM factors_daily")))
            out.executemany("INSERT INTO french VALUES (?, ?, ?, ?)", (tuple(r) for r in desk.execute("SELECT set_name, name, date, ret FROM french_returns")))
            french_rows = out.execute("SELECT count(*) FROM french").fetchone()[0]
        if desk.execute("SELECT 1 FROM sqlite_master WHERE name='macro_daily'").fetchone():
            out.executemany("INSERT INTO macro VALUES (?, ?, ?)", (tuple(r) for r in desk.execute("SELECT series, date, value FROM macro_daily")))
        out.executemany("INSERT INTO plan_mix VALUES (?, ?)", list(targets.items()))
        rate = desk.execute(
            "SELECT value FROM metric_values WHERE metric_id='tax.marginal_rate' AND scope='portfolio' AND value IS NOT NULL ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        settings = {"exported_at": now.isoformat(timespec="seconds"), "marginal_rate_pct": str(rate[0]) if rate else None}
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
    return {"ok": True, "path": str(final), "symbols": len(spans), "bars": bars, "french_rows": french_rows, "small_caps": len(small)}


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
    path: Path | None = None
    french_sets: dict[str, list[str]] = field(default_factory=dict)
    insider: dict[str, tuple[list[str], list[int], list[float]]] = field(default_factory=dict)
    smallcap: dict[str, set[str]] = field(default_factory=dict)
    earnings: dict[str, tuple[list[str], list[float]]] = field(default_factory=dict)

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
    try:
        series: dict[str, Series] = {}
        pos = {r[0]: i for i, r in enumerate(conn.execute("SELECT DISTINCT date FROM bars ORDER BY date"))}
        days = {d: d for d in pos}
        cur, dates, adj, opens, volume = None, [], array("d"), array("d"), array("d")

        def flush():
            if cur and dates:
                series[cur] = Series(dates, adj, opens, volume, DayIndex(pos, dates))

        for sym, day, close, adjusted, opened, vol in conn.execute("SELECT symbol, date, close, adj_close, open, volume FROM bars ORDER BY symbol, date"):
            if sym != cur:
                flush()
                cur, dates, adj, opens, volume = sym, [], array("d"), array("d"), array("d")
            a = adjusted if adjusted else close
            dates.append(days[day])
            adj.append(a)
            opens.append((opened * (adjusted / close) if adjusted and close else opened) if opened else a)
            volume.append(vol or 0.0)
        flush()
        kinds, roles, last = {}, {}, {}
        for r in conn.execute("SELECT symbol, kind, role, last FROM symbols"):
            kinds[r[0]], roles[r[0]], last[r[0]] = r[1], r[2], r[3]
        macro: dict[str, tuple[list[str], list[float]]] = {}
        for r in conn.execute("SELECT series, date, value FROM macro ORDER BY series, date"):
            d, v = macro.setdefault(r[0], ([], []))
            d.append(r[1])
            v.append(r[2])
        plan = {r[0]: r[1] for r in conn.execute("SELECT symbol, weight FROM plan_mix")}
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
        conn.close()
    ref = next((s for s in ("SPY", "VTI", "FXAIX") if s in series), None) or max(series, key=lambda s: len(series[s].dates), default=None)
    market = _french_market(factors)
    if market is not None:
        series[FRENCH_MARKET], kinds[FRENCH_MARKET], roles[FRENCH_MARKET], last[FRENCH_MARKET] = market, FRENCH_KIND, None, market.dates[-1]
    if not ref:
        ref = FRENCH_MARKET if market is not None else None
    if not ref:
        raise NotReady("The lab data has no prices yet.")
    return LabData(
        series, kinds, roles, last, macro, plan, settings, list(series[ref].dates), factors, path, insider=insider, smallcap=smallcap, earnings=earnings
    )
