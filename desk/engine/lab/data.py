import json
import os
import sqlite3
from bisect import bisect_right
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
        bars: dict[tuple[str, str], tuple] = {}
        for r in desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM price_bars"):
            bars[(r["symbol"], r["date"])] = (r["symbol"], r["date"], r["open"], r["close"], r["adj_close"], r["volume"])
        for r in desk.execute("SELECT symbol, date, close, adj_close FROM prices_daily"):
            bars.setdefault((r["symbol"], r["date"]), (r["symbol"], r["date"], None, r["close"], r["adj_close"], None))
        small = _small_caps(desk, out)
        for sym in small | {SMALLCAP_BENCHMARK}:
            for r in (
                desk.execute("SELECT symbol, date, open, close, adj_close, volume FROM alpaca_bars WHERE symbol=?", (sym,)) if _has(desk, "alpaca_bars") else []
            ):
                bars.setdefault((r["symbol"], r["date"]), (r["symbol"], r["date"], r["open"], r["close"], r["adj_close"], r["volume"]))
        out.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", bars.values())
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
            out.executemany("INSERT INTO macro VALUES (?, ?, ?)", [tuple(r) for r in desk.execute("SELECT series, date, value FROM macro_daily")])
        out.executemany("INSERT INTO plan_mix VALUES (?, ?)", list(targets.items()))
        rate = desk.execute(
            "SELECT value FROM metric_values WHERE metric_id='tax.marginal_rate' AND scope='portfolio' AND value IS NOT NULL ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        settings = {"exported_at": now.isoformat(timespec="seconds"), "marginal_rate_pct": str(rate[0]) if rate else None}
        if small and _has(desk, "insider_buys"):
            from desk.engine.insider import coverage

            settings["insider_coverage"] = json.dumps(coverage(desk))
        out.executemany("INSERT INTO settings VALUES (?, ?)", list(settings.items()))
        out.commit()
    finally:
        out.close()
    os.replace(tmp, final)
    return {"ok": True, "path": str(final), "symbols": len(spans), "bars": len(bars), "french_rows": french_rows, "small_caps": len(small)}


def _has(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _small_caps(desk: sqlite3.Connection, out: sqlite3.Connection) -> set[str]:
    if not _has(desk, "smallcap_months"):
        return set()
    from desk.engine.insider import known_day

    months = desk.execute("SELECT symbol, month FROM smallcap_months").fetchall()
    out.executemany("INSERT INTO smallcap VALUES (?, ?)", [tuple(r) for r in months])
    if _has(desk, "insider_buys"):
        out.executemany(
            "INSERT INTO insider VALUES (?, ?, ?, ?)",
            [(r[0], known_day(r[1]), r[2], r[3]) for r in desk.execute("SELECT symbol, filed_date, owner_cik, usd FROM insider_buys")],
        )
    return {r[0] for r in months}


# ---- Load (lab side) ----


@dataclass
class Series:
    dates: list[str]
    adj: list[float]
    open_adj: list[float]
    volume: list[float | None]
    index: dict[str, int] = field(default_factory=dict)

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

    def coverage(self) -> dict | None:
        raw = self.settings.get("insider_coverage")
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
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='french'").fetchone():
                    rows = conn.execute("SELECT name, date, ret FROM french WHERE set_name=? ORDER BY name, date", (set_name,)).fetchall()
                else:
                    rows = []
            finally:
                conn.close()
            shared: dict[tuple[str, str, int], tuple[list[str], dict[str, int], list[None]]] = {}
            by_name: dict[str, list[tuple[str, float]]] = {}
            for r in rows:
                by_name.setdefault(r[0], []).append((r[1], r[2]))
            for name, pts in by_name.items():
                sym = french_symbol(set_name, name)
                key = (pts[0][0], pts[-1][0], len(pts))
                if key not in shared:
                    dates = [d for d, _ in pts]
                    shared[key] = (dates, {d: i for i, d in enumerate(dates)}, [None] * len(dates))
                dates, index, nones = shared[key]
                self.series[sym] = _levels(dates, [x for _, x in pts], index, nones)
                self.kinds[sym] = FRENCH_KIND
                self.roles[sym] = None
                self.last[sym] = dates[-1]
                symbols.append(sym)
        self.french_sets[set_name] = sorted(symbols)
        return self.french_sets[set_name]

    def macro_at(self, series: str, day: str) -> float | None:
        dates, values = self.macro.get(series, ([], []))
        i = bisect_right(dates, day)
        return values[i - 1] if i else None


def _levels(dates: list[str], pcts: list[float], index: dict[str, int], volume: list) -> Series:
    level, adj = 100.0, []
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
        cur, rows = None, []

        def flush():
            if cur and rows:
                dates = [r[0] for r in rows]
                adj = [r[2] if r[2] else r[1] for r in rows]
                opens = [(r[3] * (r[2] / r[1]) if r[2] and r[1] else r[3]) if r[3] else a for r, a in zip(rows, adj, strict=True)]
                s = Series(dates, adj, opens, [r[4] for r in rows])
                s.index = {d: i for i, d in enumerate(dates)}
                series[cur] = s

        for r in conn.execute("SELECT symbol, date, close, adj_close, open, volume FROM bars ORDER BY symbol, date"):
            if r[0] != cur:
                flush()
                cur, rows = r[0], []
            rows.append((r[1], r[2], r[3], r[4], r[5]))
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
                factors.setdefault(r[0], {})[r[1]] = r[2]
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
    return LabData(series, kinds, roles, last, macro, plan, settings, list(series[ref].dates), factors, path, insider=insider, smallcap=smallcap)
