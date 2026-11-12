import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from statistics import NormalDist

from desk.config import Config
from desk.db import connect
from desk.engine import catalog, gate
from desk.engine.lab.data import data_path, lab_build, ledger_path
from desk.engine.lab.rulebook import STAND_IN
from desk.engine.lab.runner import PBO_BAR
from desk.engine.lab.simcache import queue_dir

FAMILY = "library"
KINDS = (("classic", "Old and tested"), ("practical", "Practical"), ("novel", "Novel and creative"))
SPY, PLAN, MARKET, SMALL = "S&P 500 (SPY)", "Your plan's mix", "US stock market (French)", "Small caps (IWM)"
NOTE = (
    "Every number here is out of sample: from periods the strategy was not tuned on. The last two years of data are held back and untouched. "
    "Held up means ahead of its benchmark by more than luck allows across every variant tried in the library."
)
N = NormalDist()
RETRY_AFTER = timedelta(hours=12)
YARDSTICK = "lib-buy-hold-sp500"
SAME_PTS = 0.1
PLAIN = (
    (("no plan mix",), "No plan of your own is loaded on the desk yet, so there is no plan mix to test. The Safe mix row is the built-in stand-in."),
    (("small-cap history",), "Small-company price history is still loading. This runs once that finishes."),
    (("is not in the lab yet",), "Its data file has not reached the lab yet. This runs the night after the file arrives."),
    (("no price history", "too little price history"), "Most of its funds have no price history in the lab yet."),
    (("no common history", "too late for anything"), "Its funds do not share enough price history yet."),
    (("not funds", "not a fund"), "The lab did not recognise one of its funds, so it was held back."),
)
PLAIN_DEFAULT = "The lab could not run this one. It is tried again on a later night."
ORDER = {"held_up": 0, "within_noise": 1, "fell_short": 2, "inconclusive": 3, None: 4}

SECTORS = {"type": "fund_list", "set": "sector_etfs"}
STOCKS = {"type": "screen", "min_history_days": 300, "min_price": 5}
SMALL_CAPS = {"type": "small_caps"}
SAFE_MIX = {s: round(w * 100, 2) for s, w in catalog.proxied(catalog.SAFE_MIX)[0].items()}
TECH_TILT = {s: round(w * 100, 2) for s, w in catalog.TECH_TILT.items()}


def _sig(metric: str, window: str, transform: str = "rank") -> dict:
    return {"metric_id": metric, "window": window, "transform": transform}


def _flt(metric: str, window: str, **bounds) -> dict:
    return {"metric_id": metric, "window": window, **bounds}


def _mix(weights: dict, **more) -> dict:
    return {"universe": {"type": "fund_list", "symbols": list(weights)}, "sizing": {"method": "fixed", "weights": weights}, **more}


def _exp(sid, kind, family, title, description, benchmark, spec, grid=None, **request) -> dict:
    spec = {"rebalance": "monthly", "sizing": "equal", "exit": "rebalance", **spec}
    return {"id": sid, "kind": kind, "family": family, "title": title, "description": description, "benchmark": benchmark, "type": "experiment"} | {
        "spec": spec,
        "grid": grid or {},
        "request": request,
    }


def _rule(sid, kind, family, title, description, rule, params, mix=None, **more) -> dict:
    body = {"rule": rule, "params": params, "horizons": [5, 10], **({"mix": mix} if mix else {}), **more}
    benchmark = {"spread": "Investing it all on day one", "margin": "The same deposits, never borrowing"}.get(rule, "The same deposits, invested plainly")
    return {"id": sid, "kind": kind, "family": family, "title": title, "description": description, "benchmark": benchmark, "type": "rule", "body": body}


TOP = {"top_n": {"min": 1, "max": 5, "default": 3}}
LOOK = {"lookback": {"min": 21, "max": 504, "default": 126}}

LIBRARY: tuple[dict, ...] = (
    # ---- Old and tested ----
    _exp("lib-buy-hold-sp500", "classic", "Buy and hold", "Buy and hold the S&P 500", "Own the S&P 500 and never trade.", PLAN, _mix({"SPY": 100})),
    _exp(
        "lib-buy-hold-total-world",
        "classic",
        "Buy and hold",
        "Buy and hold US plus international",
        "70% US stocks, 30% international, rebalanced monthly.",
        SPY,
        _mix({"VTI": 70, "VXUS": 30}, benchmark="SPY"),
    ),
    _exp(
        "lib-60-40",
        "classic",
        "Allocation",
        "60/40 stocks and bonds",
        "60% S&P 500, 40% US bonds, rebalanced monthly.",
        SPY,
        _mix({"SPY": 60, "AGG": 40}, benchmark="SPY"),
    ),
    _exp(
        "lib-risk-parity",
        "classic",
        "Allocation",
        "Risk parity across four funds",
        "US stocks, international, small caps and bonds, each sized so it adds the same risk.",
        SPY,
        {
            "universe": {"type": "fund_list", "symbols": ["SPY", "VXUS", "IWM", "AGG"]},
            "signals": [_sig("ret", "21d")],
            "entry": {"top_n": 4},
            "sizing": "inverse_vol",
            "benchmark": "SPY",
        },
    ),
    _exp(
        "lib-trend-200d",
        "classic",
        "Trend",
        "200-day trend on the S&P 500",
        "Hold the S&P 500 while it is above its long moving average, cash otherwise.",
        SPY,
        {
            "universe": {"type": "fund_list", "symbols": ["SPY"]},
            "signals": [_sig("ma_gap", "{ma}d", "raw")],
            "entry": {"top_n": 1, "min_signal": 0},
            "params": {"ma": [200, 150, 250]},
            "benchmark": "SPY",
        },
        {"ma": [150, 200, 250]},
    ),
    _exp(
        "lib-vol-cap",
        "classic",
        "Trend",
        "Volatility cap on the S&P 500",
        "Hold the S&P 500 only while its three-month volatility is under 20%; cash when markets get rough.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("vol", "63d", max=0.20)], benchmark="SPY"),
    ),
    _exp(
        "lib-dual-momentum",
        "classic",
        "Momentum",
        "Dual momentum",
        "Each month hold whichever of US stocks, international or bonds did best, and go to cash if even the best one is falling.",
        SPY,
        {
            "universe": {"type": "fund_list", "symbols": ["SPY", "VXUS", "AGG"]},
            "signals": [_sig("ret", "{lookback}d", "raw")],
            "entry": {"top_n": 1, "min_signal": 0},
            "params": LOOK,
            "benchmark": "SPY",
        },
        {"lookback": [126, 252]},
    ),
    _exp(
        "lib-sector-momentum-12-1",
        "classic",
        "Momentum",
        "12-1 momentum across sectors",
        "Hold the sectors that led over the past year, skipping the latest month.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("ret_skip", "252d")], "entry": {"top_n": "param:top_n"}, "params": TOP, "benchmark": "SPY"},
        {"top_n": [2, 3, 4]},
    ),
    _exp(
        "lib-sector-rotation",
        "classic",
        "Momentum",
        "Sector rotation",
        "Hold the three sectors with the best recent return and rotate monthly.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("ret", "{lookback}d")], "entry": {"top_n": 3}, "params": LOOK, "benchmark": "SPY"},
        {"lookback": [63, 126]},
    ),
    _exp(
        "lib-sector-low-vol",
        "classic",
        "Low volatility",
        "Low-volatility sectors",
        "Hold the three calmest sectors.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("vol", "{lookback}d", "inverse_rank")], "entry": {"top_n": 3}, "params": LOOK, "benchmark": "SPY"},
        {"lookback": [63, 126, 252]},
    ),
    _exp(
        "lib-stock-momentum",
        "classic",
        "Momentum",
        "12-1 momentum in stocks",
        "Hold the 20 stocks that led over the past year, skipping the latest month.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("ret_skip", "252d")], "entry": {"top_n": 20}, "benchmark": "SPY"},
    ),
    _exp(
        "lib-stock-low-vol",
        "classic",
        "Low volatility",
        "Low-volatility stocks",
        "Hold the 20 calmest stocks, refreshed each quarter.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("vol", "252d", "inverse_rank")], "entry": {"top_n": 20}, "rebalance": "quarterly", "benchmark": "SPY"},
    ),
    _exp(
        "lib-size-small",
        "classic",
        "Factor tilt",
        "Size tilt: the smallest companies",
        "Hold the smallest tenth of US stocks, as in the classic size studies.",
        MARKET,
        {"universe": {"type": "french", "set": "size_deciles", "members": ["lo"]}},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-momentum-top-tenth",
        "classic",
        "Factor tilt",
        "Momentum tilt: last year's winners",
        "Hold the tenth of US stocks with the best past-year return, as in the classic momentum studies.",
        MARKET,
        {"universe": {"type": "french", "set": "momentum_deciles", "members": ["hi"]}},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-value-tilt",
        "classic",
        "Factor tilt",
        "Value tilt: the cheapest companies",
        "Hold the tenth of US stocks that are cheapest against their book value, as in the classic value studies.",
        MARKET,
        {"universe": {"type": "french", "set": "value_deciles", "members": ["hi"]}},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-profitability-tilt",
        "classic",
        "Factor tilt",
        "Profitability tilt: the most profitable companies",
        "Hold the tenth of US stocks with the highest operating profitability.",
        MARKET,
        {"universe": {"type": "french", "set": "profitability_deciles", "members": ["hi"]}},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-quality-tilt",
        "classic",
        "Factor tilt",
        "Quality tilt: companies that invest carefully",
        "Hold the tenth of US stocks that grow their assets the least, a common marker of quality.",
        MARKET,
        {"universe": {"type": "french", "set": "investment_deciles", "members": ["lo"]}},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-industry-momentum",
        "classic",
        "Momentum",
        "12-1 momentum across 12 industries",
        "Hold the industries that led over the past year, on research data with no survivorship bias.",
        MARKET,
        {"universe": {"type": "french", "set": "industry_12"}, "signals": [_sig("ret_skip", "252d")], "entry": {"top_n": "param:top_n"}, "params": TOP},
        {"top_n": [2, 3, 4]},
        date_range={"start": "1990-01-01"},
    ),
    _exp(
        "lib-industry-low-vol",
        "classic",
        "Low volatility",
        "Low-volatility industries",
        "Hold the ten calmest of 49 industries.",
        MARKET,
        {
            "universe": {"type": "french", "set": "industry_49"},
            "signals": [_sig("vol", "252d", "inverse_rank")],
            "entry": {"top_n": 10},
            "rebalance": "quarterly",
        },
        date_range={"start": "1990-01-01"},
    ),
    # ---- Practical ----
    _exp(
        "lib-plan-mix",
        "practical",
        "Allocation",
        "Your plan's mix",
        "Hold the funds in your plan at their target weights, rebalanced monthly.",
        SPY,
        {"universe": {"type": "fund_list", "set": "plan_mix"}, "benchmark": "SPY"},
    ),
    _exp(
        "lib-safe-mix",
        "practical",
        "Allocation",
        "Safe mix",
        "The broad index mix from your October plan, at fixed weights.",
        SPY,
        _mix(SAFE_MIX, benchmark="SPY"),
    ),
    _exp(
        "lib-tech-tilt",
        "practical",
        "Allocation",
        "Aggressive tech tilt",
        "Half S&P 500, the rest leaning into technology and chips with a slice of international.",
        SPY,
        _mix(TECH_TILT, benchmark="SPY"),
    ),
    _exp(
        "lib-dip-only",
        "practical",
        "Dip buying",
        "Own the S&P 500 only in a dip",
        "Sit in cash until the S&P 500 is 10% or more below its one-year high, and hold it only while it stays there.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("dd", "252d", max=-0.10)], benchmark="SPY"),
    ),
    _exp(
        "lib-dip-sectors",
        "practical",
        "Dip buying",
        "Buy the most beaten-down sectors",
        "Each month hold the three sectors furthest below their recent high.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("dd", "{lookback}d", "inverse_rank")], "entry": {"top_n": 3}, "params": LOOK, "benchmark": "SPY"},
        {"lookback": [63, 126]},
    ),
    _rule(
        "lib-dip-reserve",
        "practical",
        "Dip buying",
        "Hold back deposits for a dip",
        "Keep part of each monthly deposit in cash and invest all of it when the market is down 10% or 20%.",
        "dip_reserve",
        {"hold_pct": [25, 50], "dip_pct": [10, 20]},
        {"SPY": 1.0},
    ),
    _rule(
        "lib-margin-dip",
        "practical",
        "Dip buying",
        "Borrow on margin to buy a dip",
        "Borrow 10% of the account when the market is down 10% or 20%, and repay it from deposits.",
        "margin",
        {"dip_pct": [10, 20], "borrow_pct": 10, "rate_pct": 12},
        {"SPY": 1.0},
    ),
    _rule(
        "lib-lump-sum-spread",
        "practical",
        "Deposits",
        "Lump sum now or spread over months",
        "Invest a lump sum in equal monthly parts over 6 or 12 months instead of all at once.",
        "spread",
        {"months": [6, 12]},
        {"SPY": 1.0},
        deposit_monthly=0,
    ),
    _rule(
        "lib-deposit-steering",
        "practical",
        "Deposits",
        "Steer deposits to what is behind",
        "Send each deposit to whichever fund is furthest below its target, so deposits do the rebalancing.",
        "deposit_steering",
        {},
        {"SPY": 0.6, "AGG": 0.4},
    ),
    _rule(
        "lib-rebalance-bands",
        "practical",
        "Rebalancing",
        "Rebalance bands on 60/40",
        "Sell back to target only when a fund drifts 5 or 10 points from its weight.",
        "rebalance_band",
        {"band_pts": [5, 10]},
        {"SPY": 0.6, "AGG": 0.4},
    ),
    _rule(
        "lib-rebalance-bands-plan",
        "practical",
        "Rebalancing",
        "Rebalance bands on your plan",
        "The same 5 and 10 point bands, on your plan's own funds and weights.",
        "rebalance_band",
        {"band_pts": [5, 10]},
        mix_without_plan=SAFE_MIX,
    ),
    _rule(
        "lib-harvest",
        "practical",
        "Rebalancing",
        "Tax-loss harvesting",
        "Sell a fund when its loss passes $500 or $1,000 and buy a close substitute, banking the loss for taxes.",
        "harvest",
        {"threshold_usd": [500, 1000]},
        {"SPY": 1.0},
    ),
    # ---- Novel and creative ----
    _exp(
        "lib-trend-dip",
        "novel",
        "Dip buying",
        "Trend-filtered dip-buy",
        "Buy the sectors that dipped most this quarter, but only the ones still above their 200-day average.",
        SPY,
        {
            "universe": SECTORS,
            "signals": [_sig("dd", "63d", "inverse_rank")],
            "filters": [_flt("ma_gap", "200d", min=0)],
            "entry": {"top_n": "param:top_n"},
            "params": TOP,
            "benchmark": "SPY",
        },
        {"top_n": [2, 3]},
    ),
    _exp(
        "lib-sector-momentum-uptrend",
        "novel",
        "Momentum",
        "Sector momentum, uptrends only",
        "Hold the leading sectors, but drop any that has fallen below its 200-day average and wait in cash.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("ret", "126d")], "filters": [_flt("ma_gap", "200d", min=0)], "entry": {"top_n": 3}, "benchmark": "SPY"},
    ),
    _exp(
        "lib-calm-winners",
        "novel",
        "Momentum",
        "Calm winners",
        "Hold the 20 stocks that score best on past-year return and low volatility together.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("ret_skip", "252d"), _sig("vol", "252d", "inverse_rank")], "entry": {"top_n": 20}, "benchmark": "SPY"},
    ),
    _exp(
        "lib-breakout-vol-cap",
        "novel",
        "Breakout",
        "52-week-high breakout with a volatility cap",
        "Hold stocks trading within 5% of their one-year high, skipping the jumpy ones.",
        SPY,
        {
            "universe": STOCKS,
            "signals": [_sig("range_52w", "252d")],
            "filters": [_flt("range_52w", "252d", min=0.95), _flt("vol", "63d", max=0.35)],
            "entry": {"top_n": 20},
            "benchmark": "SPY",
        },
    ),
    _exp(
        "lib-discount-day",
        "novel",
        "Dip buying",
        "Discount-day entries",
        "Each week buy the stocks that fell 7% or more in five days while still above their 200-day average, and hold them a week.",
        SPY,
        {
            "universe": STOCKS,
            "signals": [_sig("ret", "5d", "inverse_rank")],
            "filters": [_flt("ret", "5d", max=-0.07), _flt("ma_gap", "200d", min=0)],
            "entry": {"top_n": 10},
            "rebalance": "weekly",
            "benchmark": "SPY",
        },
    ),
    _exp(
        "insider-momentum-filter",
        "novel",
        "Insiders",
        "Insider cluster with a momentum filter",
        "Hold small caps where two or more insiders bought in the past six months and the stock is up over that time.",
        SMALL,
        {
            "universe": SMALL_CAPS,
            "signals": [_sig("insider.buyers", "126d", "raw")],
            "filters": [_flt("ret", "126d", min=0)],
            "entry": {"top_n": 20, "min_signal": 1.5},
        },
    ),
    _exp(
        "drift-insider-confirmed",
        "novel",
        "Earnings",
        "Earnings drift where insiders also bought",
        "Hold small caps with a positive earnings surprise in the past quarter where an insider also bought.",
        SMALL,
        {
            "universe": SMALL_CAPS,
            "signals": [_sig("earnings.surprise", "63d", "raw")],
            "filters": [_flt("insider.buyers", "126d", min=1)],
            "entry": {"top_n": 20, "min_signal": 0},
        },
    ),
)
IDS = frozenset(e["id"] for e in LIBRARY)


# ---- Requests ----


def request(entry: dict, written_at: str) -> dict:
    if entry["type"] == "rule":
        return {"request": "rule", "id": entry["id"], "version": 1, "written_at": written_at, **entry["body"]}
    spec = {
        "id": entry["id"],
        "version": 1,
        "parent_id": FAMILY,
        "title": entry["title"],
        "hypothesis": entry["description"],
        "constraints": {"long_only": True, "margin": False, "max_position_pct": 100},
        "horizons": [3, 5],
        **entry["spec"],
    }
    body = {"request": "experiment", "spec": spec, "grid": entry["grid"], "seed": 7, "trial_budget": 12, "analyses": ["turnover_cost"], "model": "library"}
    return body | entry["request"] | {"written_at": written_at}


def _latest(cfg: Config, bodies: bool = True) -> tuple[dict[str, dict], set[str], int]:
    path = ledger_path(cfg)
    if not path.exists():
        return {}, set(), 0
    conn = connect(path, readonly=True)
    try:
        body = "body" if bodies else "CASE WHEN kind='rejected' THEN body END AS body"
        rows = conn.execute(f"SELECT strategy_id, kind, result_at, {body} FROM lab_results ORDER BY result_at").fetchall()
        done = {r[0] for r in conn.execute("SELECT file FROM queue_done")}
        trials = conn.execute(
            "SELECT count(*) FROM (SELECT DISTINCT strategy_id, version, params FROM strategy_trials WHERE kind='full' AND strategy_id IN "
            "(SELECT id FROM strategies WHERE parent_id=?))",
            (FAMILY,),
        ).fetchone()[0]
    except sqlite3.Error:
        return {}, set(), 0
    finally:
        conn.close()
    latest = {r["strategy_id"]: {"kind": r["kind"], "result_at": r["result_at"], "body": r["body"]} for r in rows if r["strategy_id"] in IDS}
    return latest, done, trials


def _queued(cfg: Config, done: set[str]) -> set[str]:
    folder = queue_dir(cfg)
    out = set()
    for path in folder.glob("*.json") if folder.is_dir() else []:
        if path.name in done:
            continue
        out |= {sid for sid in IDS if f"-{sid}-v1-" in path.name}
    return out


def _retry(seen: dict, now: datetime) -> bool:
    if seen["kind"] != "rejected":
        return False
    try:
        build = json.loads(seen["body"] or "{}").get("lab_build")
    except ValueError:
        build = None
    return build != lab_build() or now - datetime.fromisoformat(seen["result_at"]) >= RETRY_AFTER


def queue_missing(cfg: Config, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        latest, done, _ = _latest(cfg, bodies=False)
        waiting = _queued(cfg, done)
        folder = queue_dir(cfg)
        folder.mkdir(parents=True, exist_ok=True)
        stamp, made = now.strftime("%Y%m%dT%H%M%SZ"), []
        ordered = sorted(LIBRARY, key=lambda e: e["type"] == "rule")
        for i, entry in enumerate(ordered):
            seen = latest.get(entry["id"])
            if entry["id"] in waiting or (seen and not _retry(seen, now)):
                continue
            final = folder / f"{stamp}-{i:02d}-{entry['id']}-v1-{entry['type']}.json"
            tmp = folder / f".{final.name}.tmp"
            tmp.write_text(json.dumps(request(entry, now.isoformat(timespec="seconds")), indent=1, sort_keys=True))
            os.replace(tmp, final)
            made.append(entry["id"])
    except (OSError, sqlite3.Error) as e:
        return {"queued": 0, "error": f"{e.__class__.__name__}: {e}"[:200]}
    return {"queued": len(made), "of": len(LIBRARY)}


# ---- Results ----


def plain(problems: list) -> str:
    text = " ".join(str(p) for p in problems).lower()
    return next((line for words, line in PLAIN if any(w in text for w in words)), PLAIN_DEFAULT)


def _years(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).days / 365.25, 1)


def _experiment(entry: dict, body: dict, trials: int, alone: bool = False, lean: float | None = None) -> dict:
    wf = body.get("walk_forward") or {}
    if not wf.get("days") or wf.get("excess_pts") is None:
        return {"verdict": "inconclusive", "line": "No variant produced an out-of-sample record to judge."}
    noise = body.get("noise") or {}
    if alone and entry["id"] == YARDSTICK:
        return _yardstick(wf)
    k = max(trials, int(noise.get("family_size") or 1), 1)
    x, band, luck = wf["excess_pts"], None, None
    if noise.get("tracking_error_pct") and noise.get("obs"):
        per_year = noise["tracking_error_pct"] / (noise["obs"] / 252) ** 0.5
        band = round(N.inv_cdf((1 - gate.LUCK_BAR) ** (1 / k)) * per_year, 2)
        luck = round(1 - N.cdf(x / per_year) ** k, 4)
    years = _years(wf.get("start"), wf.get("end"))
    span = f"over {years:g} years out of sample" if years else "out of sample"
    bench = entry["benchmark"]
    overfit = body.get("pbo") is not None and body["pbo"] >= PBO_BAR
    if x <= 0 and lean is not None and lean < x:
        verdict = "within_noise"
        line = (
            f"Trailed {bench} by {abs(x):.1f} points a year {span}, less than the {abs(lean):.1f} points a year a row loses "
            "by starting each test year in cash, so it is inside the noise."
        )
    elif x <= 0:
        verdict, line = "fell_short", f"Trailed {bench} by {abs(x):.1f} points a year {span}."
    elif band is None:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, on too short a record to tell from luck."
    elif x < band:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, but luck alone allows {band:.1f} across the {k} variants tried."
    elif overfit:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, but its best settings look fitted to the past."
    elif lean is not None and lean > 0 and x - lean < band:
        verdict = "within_noise"
        line = (
            f"Ahead of {bench} by {x:.1f} points a year {span}, but about {lean:.1f} of that comes from starting each test year in cash, "
            f"which leaves it inside the {band:.1f} luck allows."
        )
    else:
        verdict = "held_up"
        line = f"Beat {bench} by {x:.1f} points a year {span}, more than the {band:.1f} luck allows across the {k} variants tried."
    return {
        "verdict": verdict,
        "line": line,
        "out_of_sample": {key: wf.get(key) for key in ("start", "end", "ann_return_pct", "excess_pts", "sharpe", "mdd_pct")},
        "noise": {"trials": k, "band_pts": band, "luck": luck},
        "deflated_sharpe": body.get("deflated_sharpe"),
        "pbo": body.get("pbo"),
        "variants": body.get("variants"),
    }


def _yardstick(wf: dict) -> dict:
    x = wf["excess_pts"]
    gap = ""
    if abs(x) >= SAME_PTS:
        gap = (
            f" The {abs(x):.1f} points a year it {'trails' if x < 0 else 'leads'} itself by comes mostly from each test year starting in cash "
            "until its first monthly rebalance; most rows carry a similar gap."
        )
    return {
        "verdict": None,
        "yardstick": True,
        "gap_pts": x,
        "line": f"The yardstick most rows here are measured against. No plan of your own is loaded, so it is measured against itself.{gap}",
        "out_of_sample": {key: wf.get(key) for key in ("start", "end", "ann_return_pct", "sharpe", "mdd_pct")} | {"excess_pts": None},
    }


def _lean(latest: dict[str, dict]) -> float | None:
    seen = latest.get(YARDSTICK)
    if seen is None or seen["kind"] != "experiment":
        return None
    x = (json.loads(seen["body"]).get("walk_forward") or {}).get("excess_pts")
    return x if isinstance(x, int | float) and abs(x) >= SAME_PTS else None


def _lean_note(lean: float | None) -> str:
    start = "Every row except the deposit rules starts each test year in cash until its first rebalance."
    if lean is None:
        return f"{start} That leans the results a little. A corrected run is planned for tonight."
    if lean < 0:
        return (
            f"{start} That costs roughly the {abs(lean):.1f} points a year the S&P 500 row shows against itself, "
            "so a row that trails by less than that is shown as inside the noise, not as fell short. A corrected run is planned for tonight."
        )
    return (
        f"{start} That adds roughly the {lean:.1f} points a year the S&P 500 row shows against itself, "
        "so a row needs to clear its luck band by more than that to count as held up. A corrected run is planned for tonight."
    )


def _no_plan(cfg: Config) -> bool:
    path = data_path(cfg)
    if not path.exists():
        return False
    try:
        conn = connect(path, readonly=True)
        try:
            return conn.execute("SELECT 1 FROM plan_mix LIMIT 1").fetchone() is None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


RULE_VERDICT = {"helps": "held_up", "no_clear_edge": "within_noise", "hurts": "fell_short", "inconclusive": "inconclusive"}


def _rule_row(entry: dict, body: dict) -> dict:
    best = next((v for v in body.get("variants") or [] if v.get("params") == body.get("best")), None) or {}
    h = next((x for x in sorted(best.get("horizons") or [], key=lambda x: -x["years"]) if x.get("starts")), None)
    verdict = RULE_VERDICT.get(str(body.get("verdict")), "inconclusive")
    if not h:
        return {"verdict": "inconclusive", "line": "Not enough history before the two-year holdout to judge this rule.", "variants": body.get("trials")}
    worse = round((1 - h["share_better"]) * 100)
    lead = {"held_up": "Helped", "within_noise": "No clear edge", "fell_short": "Hurt"}.get(verdict, "Unclear")
    line = (
        f"{lead}: a typical {h['p50_pts']:+.1f} points of the money put in over {h['years']} years against {entry['benchmark'].lower()}, "
        f"and worse in {worse}% of {h['starts']} start months."
    )
    if any(str(c).startswith(STAND_IN) for c in body.get("caveats") or []):
        line = f"Run on the built-in safe mix, as no plan of your own is loaded. {line}"
    return {
        "verdict": verdict,
        "line": line,
        "rule": {"horizon_years": h["years"], **{k: h.get(k) for k in ("starts", "p5_pts", "p50_pts", "p95_pts", "share_better")}},
        "variants": body.get("trials"),
    }


def view(cfg: Config) -> dict:
    latest, done, trials = _latest(cfg)
    waiting = _queued(cfg, done)
    alone = _no_plan(cfg)
    lean = _lean(latest) if alone else None
    rows = []
    for entry in LIBRARY:
        row = {k: entry[k] for k in ("id", "title", "kind", "family", "description", "benchmark", "type")}
        row |= {"status": "waiting", "verdict": None, "line": None, "reason": None, "tested_at": None, "out_of_sample": None, "noise": None, "rule": None}
        row |= {"yardstick": False, "gap_pts": None}
        row |= {
            "research_only": (entry.get("spec") or {}).get("universe", {}).get("type") == "french",
            "caveats": [],
            "detail": f"/api/lab/strategies/{entry['id']}",
        }
        seen = latest.get(entry["id"])
        if seen is None or entry["id"] in waiting:
            row["reason"] = "Queued for tonight's lab run." if entry["id"] in waiting else "Joins the queue at tonight's lab export, just before 1 AM."
        if seen is not None and (entry["id"] not in waiting or seen["kind"] != "rejected"):
            body = json.loads(seen["body"])
            row["tested_at"] = seen["result_at"]
            if seen["kind"] == "rejected":
                row |= {"status": "not_run", "reason": plain(body.get("problems") or [])}
            else:
                row |= {"status": "tested", "reason": None, "caveats": body.get("caveats") or []}
                row |= _rule_row(entry, body) if seen["kind"] == "rule" else _experiment(entry, body, trials, alone, lean)
        rows.append(row)
    kinds = [k for k, _ in KINDS]
    rows.sort(
        key=lambda r: (
            kinds.index(r["kind"]),
            r["status"] != "tested",
            not r["yardstick"],
            ORDER.get(r["verdict"], 4),
            -((r["out_of_sample"] or {}).get("excess_pts") or -1e9),
        )
    )
    counts = {"total": len(rows), "tested": sum(r["status"] == "tested" for r in rows)}
    counts |= {v: sum(r["verdict"] == v for r in rows) for v in ("held_up", "within_noise", "fell_short", "inconclusive")}
    counts |= {s: sum(r["status"] == s for r in rows) for s in ("waiting", "not_run")}
    counts["yardstick"] = sum(r["yardstick"] for r in rows)
    stamps = [r["tested_at"] for r in rows if r["status"] == "tested"]
    return {
        "as_of": max(stamps) if stamps else None,
        "trials": trials,
        "note": f"{NOTE} {_lean_note(lean)}",
        "counts": counts,
        "kinds": [{"key": k, "title": t} for k, t in KINDS],
        "rows": rows,
    }


def ready(cfg: Config) -> str | None:
    counts = view(cfg)["counts"]
    if not counts["tested"]:
        return None
    return f"{counts['tested']} strategies tested, {counts['held_up']} held up out of sample"
