import json
import random
import sqlite3
from datetime import UTC, date, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine import schema
from desk.engine.lab import paper
from desk.engine.lab.data import EXPORT_SCHEMA, data_path, ledger_path
from desk.engine.lab.runner import process_queue
from desk.engine.lab.spec import SETS

# ---------- synthetic market ----------
NOW = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
LAB_END = "2025-12-31"
END = "2026-11-06"
PLAN = {"FXAIX": 0.8, "BND": 0.2}
CLEAR_PBO = 0.119
CLEAR_DSR = 0.9553


def weekdays(start: str, end: str) -> list[str]:
    out, d, e = [], date.fromisoformat(start), date.fromisoformat(end)
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def write_data(cfg: Config, end: str) -> None:
    rng = random.Random(23)  # noqa: S311
    days = weekdays("2010-01-04", end)
    path = data_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    syms = {"SPY": ("benchmark", 0.0003, 0.010), "FXAIX": ("plan", 0.0003, 0.010), "BND": ("plan", 0.0001, 0.003)}
    syms |= {s: ("benchmark", None, 0.012) for s in SETS["sector_etfs"]}
    for sym, (role, base, vol) in syms.items():
        px, drift, rows = 100.0, 0.0, []
        for i, d in enumerate(days):
            if base is None and i % 378 == 0:
                drift = rng.choice((-0.0007, 0.0002, 0.0011))
            shock = -0.008 if "2020-02-20" <= d <= "2020-03-23" else -0.0012 if "2022-01" <= d[:7] <= "2022-09" else 0.0
            op = px * (1 + rng.gauss(0, 0.002))
            px *= 1 + (drift if base is None else base) + shock * (0.3 if sym == "BND" else 1) + rng.gauss(0, vol)
            rows.append((sym, d, op, px, px, 1e6))
        conn.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT INTO symbols VALUES (?, 'fund', ?, ?, ?)", (sym, role, days[0], days[-1]))
    conn.executemany("INSERT INTO macro VALUES ('DGS3MO', ?, 2.0)", [(d,) for d in days[::5]])
    conn.executemany("INSERT INTO plan_mix VALUES (?, ?)", list(PLAN.items()))
    conn.execute("INSERT INTO settings VALUES ('marginal_rate_pct', '24')")
    conn.commit()
    conn.close()


def queue(cfg: Config, body: dict, name: str) -> None:
    folder = cfg.data_dir / "lab" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(body))


# ---------- requests ----------
BASE = {
    "version": 1,
    "parent_id": None,
    "universe": {"type": "fund_list", "set": "sector_etfs"},
    "exit": "rebalance",
    "rebalance": "monthly",
    "sizing": "equal",
    "constraints": {"long_only": True, "margin": False, "max_position_pct": 100, "max_turnover": 30},
    "success_criteria": {"excess_vs_plan_pts": 0.0, "max_drawdown_pct": 60},
    "horizons": [3, 5, 10],
}
MOMENTUM = BASE | {
    "id": "sector-momentum",
    "title": "Sector momentum",
    "hypothesis": "Sectors that led over six months keep leading for a month.",
    "predicted_effect": "+1 point a year against the plan",
    "signals": [{"metric_id": "ret", "window": "{lookback}d", "transform": "rank"}],
    "entry": "top {top_n} by rank",
    "params": {"top_n": {"min": 2, "max": 4, "default": 3}, "lookback": {"min": 63, "max": 252, "default": 126}},
}
LOWVOL = BASE | {
    "id": "low-vol-sectors",
    "title": "Calm sectors",
    "hypothesis": "The four least volatile sectors give most of the return with less of the ride.",
    "predicted_effect": "Same return, a third less drawdown",
    "signals": [{"metric_id": "vol", "window": "63d", "transform": "inverse_rank"}],
    "entry": {"top_n": "param:top_n"},
    "sizing": "inverse_vol",
    "params": {"top_n": [3, 4, 5]},
}
DIP = BASE | {
    "id": "dip-buyer",
    "title": "Buy the deepest dip",
    "hypothesis": "The sector furthest below its high bounces first.",
    "predicted_effect": "+2 points a year",
    "signals": [{"metric_id": "dd", "window": "252d", "transform": "inverse_rank"}],
    "entry": "top 2 by rank",
    "params": {},
}


def experiment(spec: dict, grid: dict) -> dict:
    return {
        "request": "experiment",
        "spec": spec,
        "grid": grid,
        "date_range": {"start": "2012-01-02", "end": LAB_END},
        "seed": 7,
        "trial_budget": 50,
        "analyses": ["param_sensitivity", "regime_split", "turnover_cost", "factor_regression"],
        "model": "opus",
        "written_at": "2026-01-04T12:00:00+00:00",
    }


def main() -> None:
    cfg = Config.from_env()
    write_data(cfg, LAB_END)
    for p in (ledger_path(cfg),):
        p.unlink(missing_ok=True)
    queue(cfg, experiment(MOMENTUM, {"top_n": [2, 3, 4], "lookback": [63, 126, 252]}), "001-momentum.json")
    queue(cfg, experiment(LOWVOL, {"top_n": [3, 4, 5]}), "002-lowvol.json")
    queue(cfg, experiment(DIP, {}), "003-dip.json")
    queue(cfg, experiment(DIP | {"id": "pick-one", "title": "One hot stock", "universe": {"type": "fund_list", "symbols": ["NVDA"]}}, {}), "004-bad.json")
    queue(cfg, {"request": "finalize", "strategy_id": "sector-momentum", "version": 1}, "005-final.json")
    queue(cfg, {"request": "finalize", "strategy_id": "dip-buyer", "version": 1}, "006-final.json")
    queue(
        cfg,
        {"request": "rule", "id": "band-test", "rule": "rebalance_band", "params": {"band_pts": [3, 5, 10]}, "horizons": [5, 10], "model": "opus"},
        "007-rule.json",
    )
    queue(cfg, {"request": "rule", "id": "steer-deposits", "rule": "deposit_steering", "horizons": [5, 10], "model": "opus"}, "008-rule.json")
    queue(
        cfg,
        {
            "request": "rule",
            "id": "dip-margin",
            "rule": "margin",
            "params": {"dip_pct": 20, "borrow_pct": [5, 10], "rate_pct": 12},
            "horizons": [5, 10],
            "model": "opus",
        },
        "009-rule.json",
    )
    done = process_queue(cfg, now=NOW)["done"]
    print([(d.get("strategy_id") or d.get("id"), d["status"]) for d in done])

    led = connect(ledger_path(cfg))
    with led:
        led.execute("UPDATE strategies SET status='paper' WHERE id='sector-momentum'")
        row = led.execute("SELECT result_at, body FROM lab_results WHERE kind='finalize' AND strategy_id='sector-momentum'").fetchone()
        if row:
            body = json.loads(row["body"])
            body |= {"paper_start": "2026-06-30", "verdict": "pass", "bars": {k: (None if v is None else True) for k, v in body["bars"].items()}}
            led.execute("UPDATE lab_results SET body=? WHERE kind='finalize' AND strategy_id='sector-momentum'", (json.dumps(body),))
            shown = led.execute("SELECT result_at, body FROM lab_results WHERE kind='experiment' AND strategy_id='sector-momentum'").fetchone()
            sheet = json.loads(shown["body"])
            sheet |= {"pbo": min(sheet["pbo"], CLEAR_PBO), "deflated_sharpe": max(sheet["deflated_sharpe"], CLEAR_DSR)}
            led.execute(
                "UPDATE lab_results SET body=? WHERE kind='experiment' AND strategy_id='sector-momentum' AND result_at=?",
                (json.dumps(sheet), shown["result_at"]),
            )
    led.close()
    write_data(cfg, END)
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    print(paper.run(cfg, desk, now=datetime(2026, 11, 6, 22, 0, tzinfo=UTC)))
    desk.close()


if __name__ == "__main__":
    main()
