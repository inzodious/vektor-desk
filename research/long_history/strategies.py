import json
import sys

import load
import numpy as np
import pandas as pd

# ---------- data ----------
M = load.monthly()
D = load.daily()

FEE = {
    "mkt": 0.0003,
    "rf": 0.0010,
    "small_value": 0.005,
    "large_value": 0.004,
    "small_q": 0.004,
    "small_growth": 0.004,
    "value_q": 0.005,
    "mom_top3": 0.008,
    "mom_top1": 0.012,
    "prof_q": 0.004,
    "lowvol_q": 0.004,
    "highdiv_q": 0.003,
    "intl": 0.0006,
    "bond10": 0.0005,
}
for c in M.columns:
    if c.startswith("ind_"):
        FEE[c] = 0.001
SIDE_COST = 0.0005


def lev_series(L, er, spread=0.006):
    r = L * D["mkt"] - (L - 1) * (D["rf"] + spread / 252) - er / 252
    g = (1 + r).groupby(D.index.to_period("M")).prod() - 1
    return g


M["lev15"] = lev_series(1.5, 0.006)
M["lev2"] = lev_series(2.0, 0.009)
M["lev125"] = lev_series(1.25, 0.004)
for k in ("lev15", "lev2", "lev125"):
    FEE[k] = 0.0
M["rvol"] = D["mkt"].groupby(D.index.to_period("M")).std() * np.sqrt(252)

NET = M.copy()
for a, f in FEE.items():
    NET[a] = M[a] - f / 12

ASSETS = list(FEE.keys())


# ---------- engine ----------
def run(weights):
    w = weights.reindex(NET.index).ffill()
    w = w.shift(1)
    cols = [c for c in w.columns]
    R = NET[cols]
    valid = w.notna().all(axis=1) & R.notna().all(axis=1)
    w, R = w[valid], R[valid]
    gross = (w * R).sum(axis=1)
    drift = w * (1 + R)
    drift = drift.div(drift.sum(axis=1), axis=0)
    nxt = w.shift(-1)
    turn = (nxt - drift).abs().sum(axis=1).fillna(0)
    return gross - turn * SIDE_COST


def static(mix):
    return pd.DataFrame({a: mix.get(a, 0.0) for a in mix}, index=M.index)


def sma_signal(series_ret, n=10):
    lvl = (1 + series_ret.fillna(0)).cumprod()
    return (lvl > lvl.rolling(n).mean()).astype(float)


def mom_signal(series_ret, rf, n=12):
    cum = (1 + series_ret).rolling(n).apply(np.prod, raw=True)
    cumrf = (1 + rf).rolling(n).apply(np.prod, raw=True)
    return (cum > cumrf).astype(float)


def switch(risk, safe, sig):
    w = pd.DataFrame(0.0, index=M.index, columns=sorted({risk, safe}))
    w[risk] = sig
    w[safe] = w[safe] + (1 - sig)
    return w.where(sig.notna())


STRATS = {}
STRATS["baseline_total_market"] = static({"mkt": 1})
STRATS["small_value_100"] = static({"small_value": 1})
STRATS["small_value_50"] = static({"mkt": 0.5, "small_value": 0.5})
STRATS["large_value_100"] = static({"large_value": 1})
STRATS["value_quintile_100"] = static({"value_q": 1})
STRATS["small_cap_100"] = static({"small_q": 1})
STRATS["momentum_top30_100"] = static({"mom_top3": 1})
STRATS["momentum_top30_50"] = static({"mkt": 0.5, "mom_top3": 0.5})
STRATS["profitability_100"] = static({"prof_q": 1})
STRATS["low_vol_100"] = static({"lowvol_q": 1})
STRATS["high_dividend_100"] = static({"highdiv_q": 1})
STRATS["tech_sector_100"] = static({"ind_BusEq": 1})
STRATS["multifactor_sv_mom_prof"] = static({"small_value": 1 / 3, "mom_top3": 1 / 3, "prof_q": 1 / 3})
STRATS["stocks_bonds_80_20"] = static({"mkt": 0.8, "bond10": 0.2})
STRATS["leverage_1.25x_daily"] = static({"lev125": 1})
STRATS["leverage_1.5x_daily"] = static({"lev15": 1})
STRATS["leverage_2x_daily"] = static({"lev2": 1})

sig10 = sma_signal(M["mkt"], 10)
STRATS["trend_sma10_cash"] = switch("mkt", "rf", sig10)
STRATS["trend_12m_momentum_cash"] = switch("mkt", "rf", mom_signal(M["mkt"], M["rf"], 12))
STRATS["trend_sma10_1.5x"] = switch("lev15", "rf", sig10)
STRATS["trend_sma10_2x"] = switch("lev2", "rf", sig10)

vt = pd.DataFrame(index=M.index)
vt["mkt"] = (0.15 / M["rvol"]).clip(upper=1.0)
vt["rf"] = 1 - vt["mkt"]
STRATS["vol_target_15_cap1"] = vt
vt2 = pd.DataFrame(index=M.index)
x = (0.16 / M["rvol"]).clip(upper=1.5)
vt2["lev15"] = (x - 1).clip(lower=0) / 0.5
vt2["mkt"] = np.where(x > 1, 1 - vt2["lev15"], x)
vt2["rf"] = np.where(x > 1, 0, 1 - x)
STRATS["vol_target_16_cap1.5"] = vt2

ind_cols = [c for c in M.columns if c.startswith("ind_")]
cum = (1 + M[ind_cols]).rolling(11).apply(np.prod, raw=True).shift(1)
rank = cum.rank(axis=1, ascending=False)
STRATS["industry_momentum_top3"] = (rank <= 3).astype(float).div(3).where(cum.notna().all(axis=1))

hal = pd.DataFrame(index=M.index)
nxt_month = (M.index + 1).month
hal["mkt"] = np.isin(nxt_month, [11, 12, 1, 2, 3, 4]).astype(float)
hal["rf"] = 1 - hal["mkt"]
STRATS["halloween_sell_may"] = hal

gem = pd.DataFrame(0.0, index=M.index, columns=["mkt", "intl", "bond10"])
c_us = (1 + M["mkt"]).rolling(12).apply(np.prod, raw=True)
c_in = (1 + M["intl"]).rolling(12).apply(np.prod, raw=True)
c_rf = (1 + M["rf"]).rolling(12).apply(np.prod, raw=True)
risk_on = c_us > c_rf
gem["mkt"] = (risk_on & (c_us >= c_in)).astype(float)
gem["intl"] = (risk_on & (c_in > c_us)).astype(float)
gem["bond10"] = (~risk_on).astype(float)
STRATS["dual_momentum_gem"] = gem.where(c_in.notna())

STRATS["plan_v3_proxy"] = static({"mkt": 0.4, "highdiv_q": 0.2, "intl": 0.1, "ind_BusEq": 0.1, "small_growth": 0.2})
STRATS["us_intl_80_20"] = static({"mkt": 0.8, "intl": 0.2})

DESIGN = (pd.Period("1927-01", "M"), pd.Period("1989-12", "M"))
TEST = (pd.Period("1990-01", "M"), pd.Period("2026-09", "M"))
RECENT = (pd.Period("2010-01", "M"), pd.Period("2026-09", "M"))


# ---------- stats ----------
def cagr(r):
    return (1 + r).prod() ** (12 / len(r)) - 1


def maxdd(r):
    lvl = (1 + r).cumprod()
    return float((lvl / lvl.cummax() - 1).min())


def nw_t(d, lags=12):
    d = d - d.mean()
    n = len(d)
    g0 = (d * d).sum() / n
    s = g0
    for L in range(1, lags + 1):
        g = (d[L:].values * d[:-L].values).sum() / n
        s += 2 * (1 - L / (lags + 1)) * g
    return None, np.sqrt(max(s, 1e-18) / n)


def boot_p(rs, rb, reps=3000, block=12, seed=7):
    rng = np.random.default_rng(seed)
    a, b = rs.values, rb.values
    n = len(a)
    nb = int(np.ceil(n / block))
    diffs = np.empty(reps)
    for i in range(reps):
        st = rng.integers(0, n - block + 1, nb)
        idx = (st[:, None] + np.arange(block)).ravel()[:n]
        diffs[i] = (np.prod(1 + a[idx]) ** (12 / n)) - (np.prod(1 + b[idx]) ** (12 / n))
    return float((diffs <= 0).mean()), float(np.percentile(diffs, 5)), float(np.percentile(diffs, 95))


def window(r, span):
    return r[(r.index >= span[0]) & (r.index <= span[1])]


def dca_windows(rs, rb, years, span):
    rs, rb = window(rs, span), window(rb, span)
    n = years * 12
    out = []
    for i in range(0, len(rs) - n + 1):
        a = rs.iloc[i : i + n].values
        b = rb.iloc[i : i + n].values
        wa = wb = 0.0
        for k in range(n):
            wa = (wa + 1) * (1 + a[k])
            wb = (wb + 1) * (1 + b[k])
        out.append(wa / wb - 1)
    if not out:
        return None
    out = np.array(out)
    return {"win_rate": float((out > 0).mean()), "median_gap": float(np.median(out)), "worst_gap": float(out.min()), "n": len(out)}


def summarize(name, r, base):
    res = {"name": name}
    for label, span in (("design", DESIGN), ("test", TEST), ("recent", RECENT)):
        rs, rb = window(r, span), window(base, span)
        common = rs.index.intersection(rb.index)
        rs, rb = rs.loc[common], rb.loc[common]
        if len(rs) < 60:
            res[label] = None
            continue
        d = rs - rb
        se = nw_t(d)[1]
        p, lo, hi = boot_p(rs, rb)
        res[label] = {
            "from": str(rs.index[0]),
            "to": str(rs.index[-1]),
            "months": len(rs),
            "cagr": cagr(rs),
            "base_cagr": cagr(rb),
            "excess_cagr": cagr(rs) - cagr(rb),
            "vol": float(rs.std() * np.sqrt(12)),
            "base_vol": float(rb.std() * np.sqrt(12)),
            "sharpe": float((rs - M["rf"].loc[common]).mean() / rs.std() * np.sqrt(12)),
            "base_sharpe": float((rb - M["rf"].loc[common]).mean() / rb.std() * np.sqrt(12)),
            "maxdd": maxdd(rs),
            "base_maxdd": maxdd(rb),
            "t_nw": float(d.mean() / se) if se > 0 else 0.0,
            "p_boot": p,
            "excess_p5": lo,
            "excess_p95": hi,
        }
    res["dca10_test"] = dca_windows(r, base, 10, TEST)
    res["dca20_all"] = dca_windows(r, base, 20, (DESIGN[0], TEST[1]))
    return res


if __name__ == "__main__":
    base = run(STRATS["baseline_total_market"])
    rets = {k: run(v) for k, v in STRATS.items()}
    out = [summarize(k, v, base) for k, v in rets.items() if k != "baseline_total_market"]
    json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
    print("done", len(out))
