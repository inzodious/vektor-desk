import json
import os
import sqlite3
from datetime import UTC, date, datetime, timedelta
from statistics import NormalDist

from desk.config import Config
from desk.db import connect
from desk.engine import catalog, gate
from desk.engine.lab.data import PUBLIC_COVERAGE, data_path, lab_build, ledger_path, plan_path, read_plan
from desk.engine.lab.rulebook import STAND_IN
from desk.engine.lab.runner import PBO_BAR
from desk.engine.lab.simcache import queue_dir
from desk.engine.lab.spec import SCREEN_HINDSIGHT

FAMILY = "library"
HINDSIGHT_FAMILY = "library-hindsight"
HINDSIGHT_LINE = "Hindsight, not a test: you hold these knowing how they did, and the last two years are held back."
LEAN_AHEAD = "Ahead, but it leans on hindsight:"
LEAN_BARRED = "Not counted as held up, because the stock list is small and includes names you hold or held."
LEAN_WORDS = "Leans on hindsight: the stock list is small and includes names you hold or held."
THIN_AHEAD = "Ahead, but too little of the stock list has prices:"
THIN_BARRED = "Not counted as held up until 90% of the list is priced."
THIN_WORDS = "Research only: under 90% of the stock list has prices."
HINDSIGHT_NOTE = "The rows for what you hold today are hindsight, not a test, and are never counted as held up."
KINDS = (("classic", "Old and tested"), ("practical", "Practical"), ("novel", "Novel and creative"))
SPY, PLAN, MARKET, SMALL = "S&P 500 (SPY)", "Your plan's mix", "US stock market (French)", "Small caps (IWM)"
PLAINLY = "The same deposits, invested plainly"
RULE_BENCH = {
    "spread": "Investing it all on day one",
    "margin": "The same deposits, never borrowing",
    "paydown": "Investing every deposit and leaving the debit",
}
BENCH_WORDS = {
    SPY: "The S&P 500 index fund SPY, bought and held with dividends reinvested.",
    PLAN: "The funds in your plan at their target weights. With no plan loaded this is the S&P 500.",
    MARKET: "Every US stock weighted by size, from Ken French's research data.",
    SMALL: "The small-company index fund IWM, bought and held with dividends reinvested.",
    PLAINLY: "The same starting money and monthly deposits put into the same funds, without the rule.",
    RULE_BENCH["spread"]: "The whole sum invested in the same funds on the first day.",
    RULE_BENCH["margin"]: "The same deposits into the same funds, with no borrowing.",
    RULE_BENCH["paydown"]: "The same starting debit, with every deposit invested and the debit left to grow with interest.",
}
NOTE = (
    "Every number here is out of sample: from periods the strategy was not tuned on. The last two years of data are held back and untouched. "
    "Each row names what it is measured against; for most that is the S&P 500 with dividends reinvested. "
    "Held up means ahead of its benchmark by more than luck allows across every variant tried in the library."
)
BAR_NOTE = "The luck bar counts all {trials} variants tried across the library, not only a row's own, so it rises for every row as strategies are added."
N = NormalDist()
RETRY_AFTER = timedelta(hours=12)
LOADING_RETRY = timedelta(hours=20)
REFRESH_AFTER = timedelta(days=30)
HINDSIGHT_REFRESH = timedelta(days=7)
REV = 2
MIX_REV = 3
SCREEN_REV = 5
OUTDATED = "were measured before the lab's latest fix and are being run again; until then their numbers lean a little."
LEVEL_PTS = 0.2
YARDSTICK = "lib-buy-hold-sp500"
PLAIN = (
    (("no plan mix",), "No plan of your own is loaded on the desk yet, so there is no plan mix to test. The Safe mix row is the built-in stand-in."),
    (("no held mix",), "The desk has not sent the lab what you hold yet. This runs the night after the next lab export."),
    (("small-cap history",), "Small-company price history is still loading. This runs once that finishes."),
    (("public stock list",), "The public stock list is still loading its prices. This runs once that finishes."),
    (("company sizes",), "Company sizes have not reached the lab yet. This runs the night after the next lab export."),
    (("is not in the lab yet",), "Its data file has not reached the lab yet. This runs the night after the file arrives."),
    (("no price history", "too little price history"), "Most of its funds have no price history in the lab yet."),
    (("no common history", "too late for anything", "needs 2.5 or more"), "Its funds have not all traded long enough to test before the two-year holdout."),
    (("not funds", "not a fund"), "The lab did not recognise one of its funds, so it was held back."),
)
PLAIN_DEFAULT = "The lab could not run this one. It is tried again on a later night."
ORDER = {"held_up": 0, "within_noise": 1, "fell_short": 2, "inconclusive": 3, None: 4}

SECTORS = {"type": "fund_list", "set": "sector_etfs"}
STOCKS = {"type": "screen", "min_history_days": 300, "min_price": 5}
SMALL_CAPS = {"type": "small_caps"}
SAFE_MIX = {s: round(w * 100, 2) for s, w in catalog.proxied(catalog.SAFE_MIX)[0].items()}
TECH_TILT = {s: round(w * 100, 2) for s, w in catalog.TECH_TILT.items()}
THEMES = ("UFO", "NLR", "GRID", "SMH", "ICLN")
ASSETS = ("SPY", "EFA", "IEF", "VNQ", "DBC")


def _sig(metric: str, window: str, transform: str = "rank") -> dict:
    return {"metric_id": metric, "window": window, "transform": transform}


def _flt(metric: str, window: str, **bounds) -> dict:
    return {"metric_id": metric, "window": window, **bounds}


def _mix(weights: dict, **more) -> dict:
    return {"universe": {"type": "fund_list", "symbols": list(weights)}, "sizing": {"method": "fixed", "weights": weights}, **more}


def _exp(sid, kind, family, title, description, benchmark, spec, grid=None, rev=REV, **request) -> dict:
    spec = {"rebalance": "monthly", "sizing": "equal", "exit": "rebalance", **spec}
    return {"id": sid, "kind": kind, "family": family, "title": title, "description": description, "benchmark": benchmark, "type": "experiment"} | {
        "spec": spec,
        "grid": grid or {},
        "request": request,
        "rev": rev,
    }


def _rule(sid, kind, family, title, description, rule, params, mix=None, rev=REV, **more) -> dict:
    body = {"rule": rule, "params": params, "horizons": [5, 10], **({"mix": mix} if mix else {}), **more}
    benchmark = RULE_BENCH.get(rule, PLAINLY)
    return {
        "id": sid,
        "kind": kind,
        "family": family,
        "title": title,
        "description": description,
        "benchmark": benchmark,
        "type": "rule",
        "body": body,
        "rev": rev,
    }


TOP = {"top_n": {"min": 1, "max": 5, "default": 3}}
DISCOUNT_DAY = {
    "universe": STOCKS,
    "signals": [_sig("ret", "5d", "inverse_rank")],
    "filters": [_flt("ret", "5d", max=-0.07), _flt("ma_gap", "200d", min=0)],
    "entry": {"top_n": 10},
    "rebalance": "weekly",
    "benchmark": "SPY",
}
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
        rev=MIX_REV,
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
        rev=MIX_REV,
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
        rev=SCREEN_REV,
    ),
    _exp(
        "lib-stock-low-vol",
        "classic",
        "Low volatility",
        "Low-volatility stocks",
        "Hold the 20 calmest stocks, refreshed each quarter.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("vol", "252d", "inverse_rank")], "entry": {"top_n": 20}, "rebalance": "quarterly", "benchmark": "SPY"},
        rev=SCREEN_REV,
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
    _exp(
        "lib-three-fund",
        "classic",
        "Allocation",
        "Three-fund portfolio",
        "US stocks, international stocks and US bonds at 60/20/20, rebalanced monthly.",
        SPY,
        _mix({"VTI": 60, "VXUS": 20, "AGG": 20}, benchmark="SPY"),
    ),
    _exp(
        "lib-permanent",
        "classic",
        "Allocation",
        "Permanent portfolio",
        "A quarter each in stocks, long Treasuries, gold and Treasury bills.",
        SPY,
        _mix({"SPY": 25, "TLT": 25, "GLD": 25, "BIL": 25}, benchmark="SPY"),
    ),
    _exp(
        "lib-all-weather",
        "classic",
        "Allocation",
        "All-weather style mix",
        "30% stocks, 55% long and medium Treasuries, and 15% split between gold and commodities.",
        SPY,
        _mix({"VTI": 30, "TLT": 40, "IEF": 15, "GLD": 7.5, "DBC": 7.5}, benchmark="SPY"),
    ),
    _exp(
        "lib-trend-five",
        "classic",
        "Trend",
        "10-month trend across five asset classes",
        "A fifth each in US stocks, foreign stocks, bonds, real estate and commodities, each held only while above its 10-month average.",
        SPY,
        _mix(dict.fromkeys(ASSETS, 20), filters=[_flt("ma_gap", "210d", min=0)], benchmark="SPY"),
    ),
    _exp(
        "lib-golden-cross",
        "classic",
        "Trend",
        "Golden cross on the S&P 500",
        "Hold the S&P 500 while its 50-day average is above its 200-day average, cash otherwise.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("ma_cross", "200d", min=0)], benchmark="SPY"),
    ),
    _exp(
        "lib-asset-momentum",
        "classic",
        "Momentum",
        "Momentum across asset classes",
        "Hold the two best of US stocks, foreign stocks, bonds, real estate, commodities and gold, skipping any that is falling.",
        SPY,
        {
            "universe": {"type": "fund_list", "symbols": [*ASSETS, "GLD"]},
            "signals": [_sig("ret", "{lookback}d", "raw")],
            "entry": {"top_n": 2, "min_signal": 0},
            "params": LOOK,
            "benchmark": "SPY",
        },
        {"lookback": [126, 252]},
    ),
    _exp(
        "lib-equal-sectors",
        "classic",
        "Allocation",
        "Equal-weight sectors",
        "Hold every US sector fund at the same weight instead of by company size.",
        SPY,
        {"universe": SECTORS, "signals": [_sig("ret", "21d")], "entry": {"top_n": 11}, "benchmark": "SPY"},
    ),
    _exp(
        "lib-equal-weight-500",
        "classic",
        "Factor tilt",
        "Equal-weight S&P 500",
        "Own the 500 companies at the same weight each, as one fund, instead of by size.",
        SPY,
        _mix({"RSP": 100}, benchmark="SPY"),
    ),
    _exp(
        "lib-dividend-growers",
        "classic",
        "Factor tilt",
        "Dividend growers",
        "Own a fund of companies that have raised their dividend for ten years running.",
        SPY,
        _mix({"VIG": 100}, benchmark="SPY"),
    ),
    _exp(
        "lib-small-value-fund",
        "classic",
        "Factor tilt",
        "Small value companies, as a fund",
        "Own a fund of small, cheaply priced US companies.",
        SPY,
        _mix({"VBR": 100}, benchmark="SPY"),
    ),
    _exp(
        "lib-value-momentum",
        "classic",
        "Factor tilt",
        "Value and momentum together",
        "Half in a fund of cheap stocks and half in a fund of recent winners, rebalanced monthly.",
        SPY,
        _mix({"VLUE": 50, "MTUM": 50}, benchmark="SPY"),
    ),
    _exp(
        "lib-small-reversal",
        "classic",
        "Reversal",
        "Short-term reversal in small caps",
        "Hold the 20 small caps that fell most over the past month, on the bet that they bounce.",
        SMALL,
        {"universe": SMALL_CAPS, "signals": [_sig("ret", "21d", "inverse_rank")], "entry": {"top_n": 20}},
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
        rev=MIX_REV,
    ),
    _exp(
        "lib-as-held",
        "practical",
        "Allocation",
        "What you hold today",
        "Today's holdings at today's weights, set back to those weights every quarter. Cash and anything without a market price are left out.",
        SPY,
        {"universe": {"type": "fund_list", "set": "held_mix"}, "rebalance": "quarterly", "benchmark": "SPY"},
    )
    | {"hindsight": True},
    _exp(
        "lib-safe-mix",
        "practical",
        "Allocation",
        "Safe mix",
        "The broad index mix from your October plan, at fixed weights.",
        SPY,
        _mix(SAFE_MIX, benchmark="SPY"),
        rev=MIX_REV,
    ),
    _exp(
        "lib-tech-tilt",
        "practical",
        "Allocation",
        "Aggressive tech tilt",
        "Half S&P 500, the rest leaning into technology and chips with a slice of international.",
        SPY,
        _mix(TECH_TILT, benchmark="SPY"),
        rev=MIX_REV,
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
    _exp(
        "lib-core-satellite",
        "practical",
        "Allocation",
        "Core and satellite",
        "80% S&P 500 with 4% each in space, nuclear, grid, chip and clean-energy funds.",
        SPY,
        _mix({"SPY": 80} | dict.fromkeys(THEMES, 4), benchmark="SPY"),
    ),
    _exp(
        "lib-themes-equal",
        "practical",
        "Allocation",
        "Theme funds, equal weight",
        "Space, nuclear, grid, chip and clean-energy funds at a fifth each, with no index core.",
        SPY,
        _mix(dict.fromkeys(THEMES, 20), benchmark="SPY"),
    ),
    _exp(
        "lib-as-held-capped",
        "practical",
        "Allocation",
        "What you hold today, single stocks capped",
        "Today's holdings with any single stock above 10% trimmed to 10% each quarter and the rest spread over your other holdings.",
        SPY,
        {"universe": {"type": "fund_list", "set": "held_mix", "cap_stocks_pct": 10}, "rebalance": "quarterly", "benchmark": "SPY"},
    )
    | {"hindsight": True},
    _rule(
        "lib-margin-paydown",
        "practical",
        "Margin",
        "Pay the margin debit first",
        "Start with a margin debit worth 10% of the account at 12% interest, and send each deposit to the debit before investing.",
        "paydown",
        {"debit_pct": 10, "rate_pct": 12},
        {"SPY": 1.0},
    ),
    _exp(
        "lib-stock-dip-hold",
        "practical",
        "Dip buying",
        "Buy large companies 30% under their high",
        "Buy a large company when it sits 30% under its one-year high, hold it a year, and keep the rest in the S&P 500.",
        SPY,
        {
            "universe": STOCKS,
            "signals": [_sig("dd", "252d", "inverse_rank")],
            "filters": [_flt("dd", "252d", max=-0.30)],
            "entry": {"top_n": 20},
            "exit": {"hold_days": 252},
            "sizing": {"method": "equal", "idle": "SPY"},
            "benchmark": "SPY",
        },
        rev=SCREEN_REV,
    ),
    _exp(
        "lib-core-stock-picks",
        "practical",
        "Momentum",
        "Core plus five stock picks",
        "Keep 80% in the S&P 500 and put 4% in each of the five large companies that led over the past year.",
        SPY,
        {
            "universe": STOCKS,
            "signals": [_sig("ret_skip", "252d")],
            "entry": {"top_n": 5},
            "sizing": {"method": "equal", "idle": "SPY"},
            "constraints": {"long_only": True, "margin": False, "max_position_pct": 4},
            "benchmark": "SPY",
        },
        rev=SCREEN_REV,
    ),
    _exp(
        "lib-ten-largest",
        "practical",
        "Factor tilt",
        "Ten largest companies, equal weight",
        "Once a year buy the ten largest companies in equal parts and hold them for the year.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("size", "252d")], "entry": {"top_n": 10}, "rebalance": "yearly", "benchmark": "SPY"},
        rev=SCREEN_REV,
    ),
    _exp(
        "lib-ten-beaten",
        "practical",
        "Dip buying",
        "Ten most beaten-down large companies",
        "Once a year buy the ten large companies furthest under their one-year high and hold them for the year.",
        SPY,
        {"universe": STOCKS, "signals": [_sig("dd", "252d", "inverse_rank")], "entry": {"top_n": 10}, "rebalance": "yearly", "benchmark": "SPY"},
        rev=SCREEN_REV,
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
        rev=SCREEN_REV,
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
        rev=SCREEN_REV,
    ),
    _exp(
        "lib-discount-day",
        "novel",
        "Dip buying",
        "Discount-day entries",
        "Each week buy the stocks that fell 7% or more in five days while still above their 200-day average, and hold them a week.",
        SPY,
        DISCOUNT_DAY,
        rev=SCREEN_REV,
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
    _exp(
        "lib-momentum-calm",
        "novel",
        "Momentum",
        "Sector momentum that stands down in rough markets",
        "Hold the three leading sectors, but wait in cash while the S&P 500's three-month volatility is above 25%.",
        SPY,
        {
            "universe": SECTORS,
            "signals": [_sig("ret", "126d")],
            "filters": [_flt("vol", "63d", max=0.25, symbol="SPY")],
            "entry": {"top_n": 3},
            "benchmark": "SPY",
        },
    ),
    _exp(
        "lib-drawdown-stop",
        "novel",
        "Trend",
        "Drawdown stop with a way back in",
        "Hold the S&P 500 while it is within 10% of its one-year high; step aside below that and return when it climbs back.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("dd", "252d", min=-0.10)], rebalance="weekly", benchmark="SPY"),
    ),
    _exp(
        "lib-down-week",
        "novel",
        "Dip buying",
        "Buy after a 5% down week",
        "Hold the S&P 500 for the week after it falls 5% or more in five days, cash otherwise.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("ret", "5d", max=-0.05)], rebalance="weekly", benchmark="SPY"),
    ),
    _exp(
        "lib-canary",
        "novel",
        "Trend",
        "Canary rule",
        "Hold the S&P 500 only while emerging markets and US bonds are both up over six months; cash when either turns down.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("ret", "126d", min=0, symbol="EEM"), _flt("ret", "126d", min=0, symbol="AGG")], benchmark="SPY"),
    ),
    _exp(
        "lib-credit-canary",
        "novel",
        "Trend",
        "Credit canary",
        "Hold the S&P 500 only while high-yield bonds are above their 200-day average, cash otherwise.",
        SPY,
        _mix({"SPY": 100}, filters=[_flt("ma_gap", "200d", min=0, symbol="HYG")], benchmark="SPY"),
    ),
    _exp(
        "lib-tech-tilt-vol-target",
        "novel",
        "Allocation",
        "Tech tilt held to a volatility target",
        "The aggressive tech tilt, scaled back into cash whenever its last three months ran hotter than 15% a year.",
        SPY,
        {
            "universe": {"type": "fund_list", "symbols": list(TECH_TILT)},
            "sizing": {"method": "fixed", "weights": TECH_TILT, "vol_target": 0.15},
            "benchmark": "SPY",
        },
    ),
    _exp(
        "lib-discount-day-uptrend",
        "novel",
        "Dip buying",
        "Discount-day entries, only in an uptrend",
        "The discount-day rule, switched off while the S&P 500 itself is below its 200-day average.",
        SPY,
        DISCOUNT_DAY | {"filters": [*DISCOUNT_DAY["filters"], _flt("ma_gap", "200d", min=0, symbol="SPY")]},
        rev=SCREEN_REV,
    ),
)
IDS = frozenset(e["id"] for e in LIBRARY)


# ---- Requests ----


def request(entry: dict, written_at: str) -> dict:
    if entry["type"] == "rule":
        return {"request": "rule", "id": entry["id"], "version": 1, "written_at": written_at, "library_rev": entry["rev"], **entry["body"]}
    spec = {
        "id": entry["id"],
        "version": 1,
        "parent_id": HINDSIGHT_FAMILY if entry.get("hindsight") else FAMILY,
        "title": entry["title"],
        "hypothesis": entry["description"],
        "constraints": {"long_only": True, "margin": False, "max_position_pct": 100},
        "horizons": [3, 5],
        **entry["spec"],
    }
    body = {"request": "experiment", "spec": spec, "grid": entry["grid"], "seed": 7, "trial_budget": 12, "analyses": ["turnover_cost"], "model": "library"}
    return body | entry["request"] | {"written_at": written_at, "library_rev": entry["rev"]}


def _latest(cfg: Config, bodies: bool = True, only: list[str] | None = None) -> tuple[dict[str, dict], set[str], int]:
    path = ledger_path(cfg)
    if not path.exists():
        return {}, set(), 0
    conn = connect(path, readonly=True)
    try:
        body = "body" if bodies else "CASE WHEN kind='rejected' THEN body END AS body"
        which = "" if only is None else f"WHERE strategy_id IN ({', '.join('?' * len(only))}) "
        rows = conn.execute(
            f"SELECT strategy_id, kind, result_at, json_extract(body, '$.library_rev') AS rev, "
            f"json_extract(body, '$.{PUBLIC_COVERAGE}.loading') AS loading, {body} FROM lab_results {which}ORDER BY result_at",
            only or (),
        ).fetchall()
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
    latest = {
        r["strategy_id"]: {"kind": r["kind"], "result_at": r["result_at"], "rev": r["rev"] or 1, "loading": r["loading"] or 0, "body": r["body"]}
        for r in rows
        if r["strategy_id"] in IDS
    }
    return latest, done, trials


def _queued(cfg: Config, done: set[str]) -> set[str]:
    folder = queue_dir(cfg)
    out = set()
    for path in folder.glob("*.json") if folder.is_dir() else []:
        if path.name in done:
            continue
        out |= {sid for sid in IDS if f"-{sid}-v1-" in path.name}
    return out


def _outdated(entry: dict, seen: dict) -> bool:
    return seen["kind"] != "rejected" and seen["rev"] < entry["rev"]


def _tried(sid: str, done: set[str]) -> datetime | None:
    stamps = [name[:16] for name in done if f"-{sid}-v1-" in name]
    try:
        return datetime.strptime(max(stamps), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if stamps else None
    except ValueError:
        return None


def _due(entry: dict, seen: dict, now: datetime, done: set[str]) -> bool:
    made = datetime.fromisoformat(seen["result_at"])
    if seen["kind"] == "rejected":
        try:
            build = json.loads(seen["body"] or "{}").get("lab_build")
        except ValueError:
            build = None
        return build != lab_build() or now - made >= RETRY_AFTER
    if not _outdated(entry, seen):
        if seen.get("loading"):
            return now - made >= LOADING_RETRY
        return now - made >= (HINDSIGHT_REFRESH if entry.get("hindsight") else REFRESH_AFTER)
    tried = _tried(entry["id"], done)
    return tried is None or tried <= made.astimezone(UTC) or now - tried >= RETRY_AFTER


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
            if entry["id"] in waiting or (seen and not _due(entry, seen, now, done)):
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


def _experiment(entry: dict, body: dict, trials: int, alone: bool = False) -> dict:
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
    if not round(x, 1):
        verdict, line = "within_noise", f"Level with {bench} {span}."
    elif x <= 0:
        verdict, line = "fell_short", f"Trailed {bench} by {abs(x):.1f} points a year {span}."
    elif band is None:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, on too short a record to tell from luck."
    elif x < band:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, but luck alone allows {band:.1f} across the {k} variants tried."
    elif overfit:
        verdict, line = "within_noise", f"Ahead of {bench} by {x:.1f} points a year {span}, but its best settings look fitted to the past."
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


def _month(day: str) -> str:
    return f"{date.fromisoformat(day[:10]):%b %Y}"


def _hindsight(entry: dict, body: dict) -> dict:
    wf = body.get("walk_forward") or {}
    if not wf.get("days") or wf.get("excess_pts") is None:
        return {"verdict": None, "line": f"No record to show for today's mix yet. {HINDSIGHT_LINE}"}
    x, bench = wf["excess_pts"], entry["benchmark"]
    span = f"From {_month(wf['start'])} to {_month(wf['end'])}" if wf.get("start") and wf.get("end") else "Over the test period"
    how = f"level with {bench}" if not round(x, 1) else f"{abs(x):.1f} points a year {'ahead of' if x > 0 else 'behind'} {bench}"
    return {
        "verdict": None,
        "line": f"{span}, today's mix would have run {how}. {HINDSIGHT_LINE}",
        "out_of_sample": {key: wf.get(key) for key in ("start", "end", "ann_return_pct", "excess_pts", "sharpe", "mdd_pct")},
    }


def _yardstick(wf: dict) -> dict:
    return {
        "verdict": None,
        "yardstick": True,
        "gap_pts": wf["excess_pts"],
        "line": "The yardstick most rows here are measured against. No plan of your own is loaded, so it is measured against itself.",
        "out_of_sample": {key: wf.get(key) for key in ("start", "end", "ann_return_pct", "sharpe", "mdd_pct")} | {"excess_pts": None},
    }


def _no_plan(cfg: Config) -> bool:
    return data_path(cfg).exists() and not read_plan(plan_path(cfg))


RULE_VERDICT = {"helps": "held_up", "no_clear_edge": "within_noise", "hurts": "fell_short", "inconclusive": "inconclusive"}


def _tenth(x: float) -> float:
    return round(x, 1) or 0.0


def _split(h: dict) -> str:
    n, ahead = h["starts"], round(h["share_better"] * 100)
    if h.get("share_worse") is None:
        if not h["share_better"] and not _tenth(h["p50_pts"]):
            return f"never ahead, and no different in at least half of {n} start months"
        return f"ahead in {ahead}% of {n} start months"
    behind = round(h["share_worse"] * 100)
    same = max(0, 100 - ahead - behind)
    if not same:
        return f"ahead in {ahead}% and behind in {behind}% of {n} start months"
    return f"ahead in {ahead}%, behind in {behind}% and no different in {same}% of {n} start months"


def _rule_row(entry: dict, body: dict) -> dict:
    best = next((v for v in body.get("variants") or [] if v.get("params") == body.get("best")), None) or {}
    h = next((x for x in sorted(best.get("horizons") or [], key=lambda x: -x["years"]) if x.get("starts")), None)
    verdict = RULE_VERDICT.get(str(body.get("verdict")), "inconclusive")
    if not h:
        return {"verdict": "inconclusive", "line": "Not enough history before the two-year holdout to judge this rule.", "variants": body.get("trials")}
    bench = entry["benchmark"].lower()
    if not any(_tenth(h[k]) for k in ("p5_pts", "p50_pts", "p95_pts")):
        verdict = "within_noise"
        line = (
            f"No difference: within a tenth of a point of {bench} in nearly every one of {h['starts']} start months over {h['years']} years. "
            "The rule seldom acted, or changed little when it did."
        )
    else:
        lead = {"held_up": "Helped", "within_noise": "No clear edge", "fell_short": "Hurt"}.get(verdict, "Unclear")
        typical = _tenth(h["p50_pts"])
        line = f"{lead}: a typical {f'{typical:+.1f}' if typical else '0.0'} points of the money put in over {h['years']} years against {bench}; {_split(h)}."
    if any(str(c).startswith(STAND_IN) for c in body.get("caveats") or []):
        line = f"Run on the built-in safe mix, as no plan of your own is loaded. {line}"
    return {
        "verdict": verdict,
        "line": line,
        "rule": {"horizon_years": h["years"], **{k: h.get(k) for k in ("starts", "p5_pts", "p50_pts", "p95_pts", "share_better", "share_worse")}},
        "variants": body.get("trials"),
    }


def _barred(row: dict, ahead: str, barred: str, words: str) -> dict:
    if row["verdict"] == "held_up":
        return {"verdict": "within_noise", "line": f"{ahead} {row['line'][0].lower()}{row['line'][1:]} {barred}"}
    return {"line": f"{row['line']} {words}"} if row["line"] else {}


BACKS = {"held_up": "yes", "within_noise": "no_edge", "fell_short": "no"}
LOOKUP = ("id", "title", "kind", "type", "status", "verdict", "line", "tested_at", "outdated", "rule", "backs")


def _backs(row: dict) -> str | None:
    if row["status"] != "tested" or row["outdated"] or row["thin_coverage"] or row["leans_on_hindsight"] or row["hindsight"] or row["yardstick"]:
        return None
    rule = row.get("rule")
    if rule and row["verdict"] == "within_noise" and any(_tenth(rule[k] or 0.0) for k in ("p5_pts", "p50_pts", "p95_pts")):
        if (rule.get("share_better") or 0.0) > 0.5:
            return "yes"
        if (rule.get("share_worse") or 0.0) > 0.5:
            return "no"
    return BACKS.get(row["verdict"])


def _row(entry: dict, seen: dict | None, waiting: set[str], trials: int, alone: bool) -> dict:
    row = {k: entry[k] for k in ("id", "title", "kind", "family", "description", "benchmark", "type")}
    row["benchmark_words"] = BENCH_WORDS[entry["benchmark"]]
    row |= {"status": "waiting", "verdict": None, "line": None, "reason": None, "tested_at": None, "out_of_sample": None, "noise": None, "rule": None}
    row |= {"yardstick": False, "gap_pts": None, "outdated": False, "hindsight": bool(entry.get("hindsight"))}
    screen = (entry.get("spec") or {}).get("universe", {}).get("type") == "screen"
    row |= {
        "leans_on_hindsight": False,
        "thin_coverage": False,
        "research_only": (entry.get("spec") or {}).get("universe", {}).get("type") == "french",
        "caveats": [],
        "detail": f"/api/lab/strategies/{entry['id']}",
    }
    if seen is None or entry["id"] in waiting:
        row["reason"] = "Queued for tonight's lab run." if entry["id"] in waiting else "Joins the queue at tonight's lab export, just before 1 AM."
    if seen is not None and (entry["id"] not in waiting or seen["kind"] != "rejected"):
        body = json.loads(seen["body"])
        row["tested_at"] = seen["result_at"]
        if seen["kind"] == "rejected":
            row |= {"status": "not_run", "reason": plain(body.get("problems") or [])}
        else:
            row |= {"status": "tested", "reason": None, "caveats": body.get("caveats") or [], "outdated": _outdated(entry, seen)}
            if seen["kind"] == "rule":
                row |= _rule_row(entry, body)
            else:
                row |= _hindsight(entry, body) if row["hindsight"] else _experiment(entry, body, trials, alone)
            cover = body.get(PUBLIC_COVERAGE)
            if screen and cover is None:
                row["leans_on_hindsight"] = True
                row["caveats"] = [SCREEN_HINDSIGHT, *(c for c in row["caveats"] if c != SCREEN_HINDSIGHT)]
                row |= _barred(row, LEAN_AHEAD, LEAN_BARRED, LEAN_WORDS)
            elif screen and not cover.get("enough"):
                row |= {"thin_coverage": True, "research_only": True} | _barred(row, THIN_AHEAD, THIN_BARRED, THIN_WORDS)
    return row | {"backs": _backs(row)}


def rows(cfg: Config, ids) -> dict[str, dict]:
    wanted = list(dict.fromkeys(str(i) for i in ids))
    known = {e["id"]: e for e in LIBRARY}
    latest, done, trials = _latest(cfg, only=[i for i in wanted if i in known])
    waiting = _queued(cfg, done)
    alone = _no_plan(cfg)
    blank = {k: None for k in LOOKUP} | {"status": "not_run", "outdated": False}
    out = {}
    for sid in wanted:
        row = _row(known[sid], latest.get(sid), waiting, trials, alone) if sid in known else {"id": sid}
        out[sid] = blank | {k: row[k] for k in LOOKUP if k in row}
    return out


def view(cfg: Config) -> dict:
    latest, done, trials = _latest(cfg)
    waiting = _queued(cfg, done)
    alone = _no_plan(cfg)
    rows = [_row(entry, latest.get(entry["id"]), waiting, trials, alone) for entry in LIBRARY]
    kinds = [k for k, _ in KINDS]
    rows.sort(
        key=lambda r: (
            kinds.index(r["kind"]),
            r["status"] != "tested",
            not r["yardstick"],
            not r["hindsight"],
            ORDER.get(r["verdict"], 4),
            -((r["out_of_sample"] or {}).get("excess_pts") or -1e9),
        )
    )
    counts = {"total": len(rows), "tested": sum(r["status"] == "tested" for r in rows)}
    counts |= {v: sum(r["verdict"] == v for r in rows) for v in ("held_up", "within_noise", "fell_short", "inconclusive")}
    counts |= {s: sum(r["status"] == s for r in rows) for s in ("waiting", "not_run")}
    counts["yardstick"] = sum(r["yardstick"] for r in rows)
    counts["hindsight"] = hind = sum(r["hindsight"] and r["status"] == "tested" for r in rows)
    counts["outdated"] = old = sum(r["outdated"] for r in rows)
    several = "All of these" if old == counts["tested"] else "Some of these"
    gap = next((r["gap_pts"] for r in rows if r["yardstick"] and not r["outdated"] and r["gap_pts"] is not None), None)
    level = gap is None or abs(gap) < LEVEL_PTS
    note = f"{NOTE} {BAR_NOTE.format(trials=trials)}" if trials > 1 else NOTE
    note = f"{note} {HINDSIGHT_NOTE}" if hind else note
    note = f"{note} {several} {OUTDATED}" if old else note
    if not level:
        note += (
            f" The S&P 500 row is measured against itself and should read level, but it is off by {abs(gap):.1f} points a year, "
            "so every row except the deposit rules may lean by about that much. This is being looked into."
        )
    stamps = [r["tested_at"] for r in rows if r["status"] == "tested"]
    return {
        "as_of": max(stamps) if stamps else None,
        "trials": trials,
        "note": note,
        "self_check": None if gap is None else {"gap_pts": gap, "level": level},
        "counts": counts,
        "kinds": [{"key": k, "title": t} for k, t in KINDS],
        "benchmarks": [{"name": name, "words": words, "rows": sum(r["benchmark"] == name for r in rows)} for name, words in BENCH_WORDS.items()],
        "rows": rows,
    }


def ready(cfg: Config) -> str | None:
    counts = view(cfg)["counts"]
    if not counts["tested"]:
        return None
    return f"{counts['tested']} strategies tested, {counts['held_up']} held up out of sample"
