import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desk.engine import replay  # noqa: E402

# ---------- synthetic market ----------
OUT = Path(__file__).resolve().parents[1] / "src" / "fixtures"
ACCOUNT, HSA = "individual-0003", "hsa-0002"
START, END = date(2022, 9, 1), date(2026, 11, 9)
FIRST_TRADE = "2023-08-02"
NAMES = {
    "SPY": {"start": 395.0, "legs": [("2022-09-01", 0.19, 0.15)]},
    "FXAIX": {"start": 137.0, "legs": [("2022-09-01", 0.19, 0.15)]},
    "ACME": {"start": 42.0, "legs": [("2022-09-01", 0.10, 0.34), ("2023-08-01", 0.95, 0.36), ("2025-03-01", 0.05, 0.38)]},
    "NOVA": {"start": 118.0, "legs": [("2022-09-01", 0.12, 0.30), ("2024-01-01", 0.62, 0.32), ("2025-06-01", 0.10, 0.30)]},
    "HELX": {"start": 64.0, "legs": [("2022-09-01", 0.05, 0.40), ("2024-09-01", 1.10, 0.44), ("2025-10-01", -0.10, 0.42)]},
    "VOLT": {"start": 27.0, "legs": [("2022-09-01", 0.15, 0.45), ("2024-05-01", -0.55, 0.50), ("2025-01-01", 0.20, 0.45)]},
    "KITE": {"start": 88.0, "legs": [("2022-09-01", 0.08, 0.28), ("2025-02-01", 0.55, 0.30), ("2026-02-01", -0.15, 0.32)]},
    "ZEPH": {"start": 15.0, "legs": [("2022-09-01", 0.20, 0.55), ("2025-08-01", -0.70, 0.60), ("2026-03-01", 0.30, 0.55)]},
    "ORBT": {"start": 21.0, "legs": [("2022-09-01", 0.25, 0.50), ("2026-01-01", 2.60, 0.65), ("2026-06-01", -1.75, 0.70), ("2026-10-10", 0.10, 0.60)]},
}


def weekdays(start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def market() -> dict[str, dict[str, tuple[float, float]]]:
    days = weekdays(START, END)
    series = {}
    for i, (sym, spec) in enumerate(NAMES.items()):
        rng = random.Random(40 + i)  # noqa: S311
        px, out = spec["start"], {}
        for d in days:
            drift, vol = next((m, v) for since, m, v in reversed(spec["legs"]) if since <= d)
            px *= math.exp((drift - vol * vol / 2) / 252 + vol / math.sqrt(252) * rng.gauss(0, 1))
            out[d] = (round(px, 2), round(px, 2))
        series[sym] = out
    return series


# ---------- synthetic history ----------
PLAN = [
    ("2023-08-02", "deposit", 6000),
    ("2023-08-03", "buy", "FXAIX", 0.35),
    ("2023-08-03", "buy", "ACME", 0.6),
    ("2023-09-05", "deposit", 1500),
    ("2023-09-06", "buy", "NOVA", 0.9),
    ("2023-10-03", "deposit", 1500),
    ("2023-10-04", "buy", "VOLT", 0.6),
    ("2023-11-02", "deposit", 1500),
    ("2023-11-03", "buy", "ACME", 0.9),
    ("2023-12-04", "deposit", 1500),
    ("2023-12-05", "buy", "KITE", 0.9),
    ("2024-01-03", "deposit", 2000),
    ("2024-01-04", "buy", "NOVA", 0.95),
    ("2024-02-02", "sell", "ACME", 0.5),
    ("2024-02-05", "buy", "KITE", 0.9),
    ("2024-03-04", "deposit", 2000),
    ("2024-03-05", "buy", "FXAIX", 0.9),
    ("2024-04-02", "sell", "FXAIX", 0.6),
    ("2024-04-03", "withdrawal", 2500),
    ("2024-05-02", "deposit", 2000),
    ("2024-05-03", "buy", "VOLT", 0.9),
    ("2024-06-04", "deposit", 2000),
    ("2024-06-05", "buy", "ZEPH", 0.5),
    ("2024-07-02", "sell", "NOVA", 0.6),
    ("2024-07-03", "buy", "HELX", 0.9),
    ("2024-08-02", "deposit", 2500),
    ("2024-08-05", "buy", "HELX", 0.9),
    ("2024-09-04", "sell", "VOLT", 1.0),
    ("2024-09-05", "buy", "ACME", 0.9),
    ("2024-10-02", "deposit", 2500),
    ("2024-10-03", "buy", "KITE", 0.9),
    ("2024-12-03", "deposit", 2500),
    ("2024-12-04", "buy", "NOVA", 0.9),
    ("2025-01-06", "sell", "ACME", 1.0),
    ("2025-01-07", "buy", "KITE", 0.5),
    ("2025-01-07", "buy", "HELX", 0.9),
    ("2025-02-04", "deposit", 3000),
    ("2025-02-05", "buy", "FXAIX", 0.9),
    ("2025-03-04", "sell", "KITE", 0.4),
    ("2025-03-05", "withdrawal", 5000),
    ("2025-04-02", "deposit", 3000),
    ("2025-04-03", "buy", "NOVA", 0.9),
    ("2025-05-05", "sell", "HELX", 0.5),
    ("2025-05-06", "buy", "ZEPH", 0.4),
    ("2025-05-06", "buy", "FXAIX", 0.9),
    ("2025-06-03", "deposit", 3000),
    ("2025-06-04", "buy", "KITE", 0.9),
    ("2025-07-02", "sell", "KITE", 0.5),
    ("2025-07-03", "buy", "NOVA", 0.9),
    ("2025-08-04", "deposit", 3000),
    ("2025-08-05", "buy", "HELX", 0.9),
    ("2025-09-03", "sell", "NOVA", 1.0),
    ("2025-09-04", "buy", "FXAIX", 0.5),
    ("2025-09-04", "buy", "KITE", 0.9),
    ("2025-10-02", "deposit", 3000),
    ("2025-10-03", "sell", "HELX", 1.0),
    ("2025-10-06", "buy", "NOVA", 0.6),
    ("2025-10-06", "buy", "FXAIX", 0.9),
    ("2025-11-04", "sell", "ZEPH", 1.0),
    ("2025-11-05", "buy", "KITE", 0.9),
    ("2025-12-02", "deposit", 3000),
    ("2025-12-03", "buy", "FXAIX", 0.9),
    ("2026-01-05", "sell", "KITE", 1.0),
    ("2026-01-06", "buy", "NOVA", 0.5),
    ("2026-01-06", "buy", "FXAIX", 0.9),
    ("2026-02-03", "deposit", 3000),
    ("2026-02-04", "buy", "NOVA", 0.9),
    ("2026-03-03", "sell", "FXAIX", 0.3),
    ("2026-03-04", "withdrawal", 4000),
    ("2026-04-02", "deposit", 3000),
    ("2026-04-06", "buy", "FXAIX", 0.9),
    ("2026-05-26", "sell", "FXAIX", 0.5),
    ("2026-05-26", "buy", "ORBT", 0.95),
    ("2026-06-02", "deposit", 3000),
    ("2026-06-12", "buy", "ORBT", 2.8),
    ("2026-07-01", "margin_interest", 46),
    ("2026-07-07", "deposit", 3000),
    ("2026-07-20", "buy", "ORBT", 1500),
    ("2026-08-03", "margin_interest", 52),
    ("2026-08-12", "sell", "NOVA", 0.5),
    ("2026-09-02", "deposit", 3000),
    ("2026-09-03", "margin_interest", 21),
    ("2026-09-16", "buy", "ORBT", 1800),
    ("2026-10-02", "deposit", 2800),
    ("2026-10-05", "margin_interest", 7),
    ("2026-11-05", "buy", "ORBT", 1500),
]
HSA_PLAN = [("2024-02-01", "deposit", 1900), ("2024-02-02", "buy", "FXAIX", 0.65), ("2026-06-15", "buy", "ORBT", 0.9)]


def history(series: dict) -> list[dict]:
    rows, held, cash = [], {}, {}

    def add(acct, day, kind, amount, sym=None, qty=None, px=None):
        cash[acct] = cash.get(acct, 0.0) + amount
        rows.append(
            {
                "key": f"{acct}-{day}-{kind}-{sym or 'cash'}-{len(rows)}",
                "date": day,
                "accountKey": acct,
                "kind": kind,
                "symbol": sym,
                "quantity": qty,
                "price": px,
                "amount": round(amount, 2),
                "description": "Electronic funds transfer" if kind in ("deposit", "withdrawal") else kind,
            }
        )

    for acct, plan in ((ACCOUNT, PLAN), (HSA, HSA_PLAN)):
        for step in plan:
            day, kind = step[0], step[1]
            if kind in ("deposit", "withdrawal", "margin_interest"):
                add(acct, day, kind, step[2] if kind == "deposit" else -step[2])
                continue
            sym = step[2]
            px = series[sym][day][0]
            if kind == "buy":
                dollars = step[3] if step[3] > 10 else step[3] * max(cash.get(acct, 0.0), 0.0)
                qty = round(dollars / px, 3)
                held[(acct, sym)] = held.get((acct, sym), 0.0) + qty
                add(acct, day, "buy", -qty * px, sym, qty, px)
            else:
                qty = round(held[(acct, sym)] * step[3], 3)
                held[(acct, sym)] -= qty
                add(acct, day, "sell", qty * px, sym, -qty, px)
    return rows


# ---------- fixtures ----------
def save(name: str, body: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(body, indent=1) + "\n")
    print(f"wrote {name}.json")


def main() -> int:
    series = market()
    rows = history(series)
    cover = {ACCOUNT: (FIRST_TRADE, END.isoformat()), HSA: (FIRST_TRADE, END.isoformat())}

    def run(prices: dict, held: float | None) -> dict:
        return replay.run(
            END.isoformat(), rows, cover, prices, mutual={"FXAIX"}, sheltered=lambda a: a.startswith("hsa"), held_value=held, short_rate=28.0, state_rate=4.0
        )

    full = run(series, None)
    full = run(series, full["you"]["end_value"])
    save("engine.replay", full)
    save("engine.replay.partial", run({s: v for s, v in series.items() if s != "ZEPH"}, None))
    empty = replay.run(END.isoformat(), [], {}, series)
    save("engine.replay.fresh", empty)
    save("engine.replay.empty", empty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
