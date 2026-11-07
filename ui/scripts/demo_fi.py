import json
import math
import random
import sqlite3
from datetime import date, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import schema

# ---------- synthetic goal ----------
FI = {"key": "fi", "value": {"birthDate": "1991-03-20", "fiTargetAge": 60, "fiYearlySpend": 28000, "fiMultiple": 25, "inflation": 0.03, "inflationAdjusted": True}}
BACK_YEARS = 2
VOL = {"FXAIX": 0.16, "FTEC": 0.26, "VXUS": 0.15, "BND": 0.05, "ACME": 0.55}
DRIFT = {"FXAIX": 0.10, "FTEC": 0.14, "VXUS": 0.06, "BND": 0.02, "ACME": 0.05}
RF_DAY = 0.012


def weekdays(start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def mirror_closes(mirror: sqlite3.Connection) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for (body,) in mirror.execute("SELECT json FROM rows WHERE tbl='priceCloses'"):
        row = json.loads(body)
        for d, close, _ in row["rows"]:
            out.setdefault(row["symbol"], {})[d] = close
    return out


# ---------- back-filled prices ----------
def backfill(rng: random.Random, closes: dict[str, dict[str, float]]) -> tuple[list[tuple], dict[str, dict[str, float]]]:
    first = min(min(ds) for ds in closes.values())
    start = date.fromisoformat(first) - timedelta(days=365 * BACK_YEARS + 10)
    days = weekdays(start, date.fromisoformat(first) - timedelta(days=1))
    bars, full = [], {}
    for sym, ds in closes.items():
        if sym not in VOL:
            continue
        steps = [DRIFT[sym] / 252 + rng.gauss(0, VOL[sym] / math.sqrt(252)) for _ in days]
        px = ds[first]
        back = {}
        for d, r in zip(reversed(days), reversed(steps), strict=True):
            px /= 1 + r
            back[d] = round(px, 4)
        bars += [(sym, d, back[d], back[d], back[d], back[d], back[d], 1e6) for d in days]
        full[sym] = back | ds
    return bars, full


# ---------- factors ----------
def rets(series: dict[str, float]) -> dict[str, float]:
    ds = sorted(series)
    return {b: (series[b] / series[a] - 1) * 100 for a, b in zip(ds, ds[1:], strict=False)}


def daily_factors(rng: random.Random, full: dict[str, dict[str, float]]) -> list[tuple]:
    r = {s: rets(v) for s, v in full.items()}
    days = sorted(set.intersection(*(set(v) for v in r.values())))
    rows = []
    for d in days:
        mkt = 0.75 * r["FXAIX"][d] + 0.15 * r["FTEC"][d] + 0.1 * r["VXUS"][d] - RF_DAY + rng.gauss(0, 0.15)
        smb = 0.12 * (r["ACME"][d] - r["FXAIX"][d]) + rng.gauss(0, 0.5)
        hml = 0.3 * (r["VXUS"][d] - r["FTEC"][d]) + rng.gauss(0, 0.5)
        rmw = 0.1 * (r["FXAIX"][d] - r["FTEC"][d]) + rng.gauss(0, 0.35)
        cma = 0.1 * (r["BND"][d] - r["FTEC"][d]) + rng.gauss(0, 0.35)
        mom = 0.25 * (r["FTEC"][d] - r["VXUS"][d]) + rng.gauss(0, 0.6)
        for name, v in (("mkt_rf", mkt), ("smb", smb), ("hml", hml), ("rmw", rmw), ("cma", cma), ("mom", mom), ("rf", RF_DAY)):
            rows.append((name, d, round(v, 4)))
    return rows


def monthly_market(rng: random.Random, end: str) -> list[tuple]:
    rows, y, m = [], 1926, 7
    while f"{y:04d}-{m:02d}" <= end[:7]:
        day = f"{y:04d}-{m:02d}-01"
        rf = max(0.0, 0.28 + 0.2 * math.sin((y - 1926) / 9) + rng.gauss(0, 0.03))
        crash = -6.0 if (1929 <= y <= 1932 or y in (1974, 2008)) and rng.random() < 0.35 else 0.0
        mkt = 0.65 + crash + rng.gauss(0, 5.0)
        rows += [("mkt_rf_m", day, round(mkt, 2)), ("rf_m", day, round(rf, 2))]
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return rows


def main() -> None:
    cfg = Config.from_env()
    rng = random.Random(41)  # noqa: S311
    mirror = sqlite3.connect(cfg.mirror_db)
    with mirror:
        mirror.execute("INSERT OR REPLACE INTO rows (tbl, id, json, at) VALUES ('prefs', 'fi', ?, '2026-11-01T12:00:00+00:00')", (json.dumps(FI),))
    closes = mirror_closes(mirror)
    mirror.close()
    bars, full = backfill(rng, closes)
    factors = daily_factors(rng, full)
    end = max(d for _, d, _ in factors)
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.execute("DELETE FROM factors_daily")
        desk.executemany("INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", bars)
        desk.executemany("INSERT INTO factors_daily VALUES (?, ?, ?)", factors + monthly_market(rng, end))
    desk.close()
    print(json.dumps({"bars": len(bars), "factor_rows": len(factors), "through": end}))


if __name__ == "__main__":
    main()
