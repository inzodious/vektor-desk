import json
import sys

import load
import numpy as np
import pandas as pd
from strategies import FEE, NET, TEST, D, M, boot_p, cagr, run, sma_signal, summarize, switch, window

POST = (pd.Period("2000-01", "M"), pd.Period("2026-09", "M"))

# ---------- industry momentum grid ----------
IND = {}
for n, fname in ((12, "12_Industry_Portfolios"), (30, "30_Industry_Portfolios"), (49, "49_Industry_Portfolios")):
    df = load.french(fname)
    df.columns = [f"i{n}_{c}" for c in df.columns]
    IND[n] = df
    for c in df.columns:
        M[c] = df[c]
        NET[c] = df[c] - 0.001 / 12
        FEE[c] = 0.001


def ind_mom(n, look, skip, top):
    cols = list(IND[n].columns)
    R = M[cols]
    cum = (1 + R).rolling(look).apply(np.prod, raw=True)
    if skip:
        cum = (1 + R).rolling(look - 1).apply(np.prod, raw=True).shift(1)
    ok = cum.notna().sum(axis=1) >= n * 0.8
    rank = cum.rank(axis=1, ascending=False)
    w = (rank <= top).astype(float)
    w = w.div(w.sum(axis=1), axis=0)
    return w.where(ok)


GRID = {}
for n in (12, 30, 49):
    tops = {12: (2, 3, 4), 30: (3, 5, 8), 49: (5, 8, 12)}[n]
    for look in (6, 9, 12):
        for skip in (0, 1):
            for top in tops:
                GRID[f"indmom_n{n}_L{look}_s{skip}_top{top}"] = ind_mom(n, look, skip, top)


# ---------- leveraged trend grid ----------
def lev_m(L, er, spread):
    r = L * D["mkt"] - (L - 1) * (D["rf"] + spread / 252) - er / 252
    return (1 + r).groupby(D.index.to_period("M")).prod() - 1


for L in (1.5, 2.0, 3.0):
    for sp in (0.006, 0.015):
        er = {1.5: 0.006, 2.0: 0.009, 3.0: 0.0095}[L]
        k = f"lev{L}_{sp}"
        M[k] = lev_m(L, er, sp)
        NET[k] = M[k]
        FEE[k] = 0.0
        for n in (8, 10, 12):
            GRID[f"trendlev_L{L}_sp{sp}_sma{n}"] = switch(k, "rf", sma_signal(M["mkt"], n))


def daily_trend(L, er, sp, n=200, band=0.0):
    lvl = (1 + D["mkt"]).cumprod()
    ma = lvl.rolling(n).mean()
    sig = pd.Series(np.nan, index=D.index)
    state = 0.0
    vals = []
    for p, m in zip(lvl.values, ma.values, strict=True):
        if np.isnan(m):
            vals.append(np.nan)
            continue
        if p > m * (1 + band):
            state = 1.0
        elif p < m * (1 - band):
            state = 0.0
        vals.append(state)
    sig = pd.Series(vals, index=D.index).shift(1)
    lev = L * D["mkt"] - (L - 1) * (D["rf"] + sp / 252) - er / 252
    r = sig * lev + (1 - sig) * (D["rf"] - 0.001 / 252)
    flips = sig.diff().abs().fillna(0)
    r = r - flips * 0.0005
    return (1 + r).groupby(D.index.to_period("M")).prod() - 1, flips.groupby(D.index.year).sum().mean()


DAILY = {}
for L in (1.0, 2.0, 3.0):
    for band in (0.0, 0.03):
        er = {1.0: 0.0003, 2.0: 0.009, 3.0: 0.0095}[L]
        r, fl = daily_trend(L, er, 0.01, 200, band)
        DAILY[f"trend200d_L{L}_band{band}"] = (r, fl)


# ---------- taxable simulation ----------
def taxable(weights, st=0.28, lt=0.19, years=None):
    w = weights.reindex(NET.index).ffill().shift(1)
    cols = list(w.columns)
    valid = w.notna().all(axis=1) & NET[cols].notna().all(axis=1)
    w = w[valid]
    R = NET.loc[w.index, cols]
    lots = {c: [] for c in cols}
    val = {c: float(w.iloc[0][c]) for c in cols}
    for c in cols:
        if val[c] > 0:
            lots[c].append([val[c], val[c], 0])
    out = []
    carry = 0.0
    year_gain_st = year_gain_lt = 0.0
    for i, (t, row) in enumerate(R.iterrows()):
        for c in cols:
            g = 1 + row[c]
            val[c] *= g
            for lot in lots[c]:
                lot[0] *= g
        if "rf" in cols:
            interest = val["rf"] * row["rf"] / (1 + row["rf"]) if val["rf"] > 0 else 0.0
            val["rf"] -= interest * st
        total = sum(val.values())
        T0 = total
        target = w.iloc[i + 1] if i + 1 < len(w) else w.iloc[i]
        for c in cols:
            want = float(target[c]) * total
            if want < val[c] - 1e-12:
                sell = val[c] - want
                remaining = sell
                while remaining > 1e-12 and lots[c]:
                    lot = lots[c][0]
                    take = min(remaining, lot[0])
                    basis = lot[1] * take / lot[0]
                    gain = take - basis
                    if i - lot[2] >= 12:
                        year_gain_lt += gain
                    else:
                        year_gain_st += gain
                    lot[1] -= basis
                    lot[0] -= take
                    remaining -= take
                    if lot[0] <= 1e-12:
                        lots[c].pop(0)
                val[c] -= sell
        if t.month == 12 or i == len(R) - 1:
            net_st, net_lt = year_gain_st, year_gain_lt
            pool = net_st + net_lt + carry
            if pool < 0:
                carry = pool
                tax = 0.0
            else:
                st_part = min(max(net_st + carry, 0), pool)
                carry = 0.0
                tax = st_part * st + (pool - st_part) * lt
            year_gain_st = year_gain_lt = 0.0
            T0 -= tax
        total = T0
        for c in cols:
            want = float(target[c]) * total
            if want > val[c] + 1e-12:
                buy = want - val[c]
                lots[c].append([buy, buy, i])
                val[c] += buy
        out.append(total)
    s = pd.Series(out, index=R.index)
    unreal = sum(sum(lot[0] - lot[1] for lot in lots[c]) for c in cols)
    after_liq = s.iloc[-1] - max(unreal, 0) * lt
    return s, after_liq


def tax_compare(name, weights, span):
    w = weights.copy()
    base = pd.DataFrame({"mkt": 1.0, "rf": 0.0}, index=M.index)

    def sub(df):
        return df[(df.index >= span[0] - 1) & (df.index <= span[1])]

    s, liq = taxable(sub(w))
    b, bliq = taxable(sub(base))
    yrs = len(s) / 12
    return {
        "name": name,
        "pre_liq_cagr": s.iloc[-1] ** (1 / yrs) - 1,
        "base_pre_liq_cagr": b.iloc[-1] ** (1 / yrs) - 1,
        "after_liq_cagr": liq ** (1 / yrs) - 1,
        "base_after_liq_cagr": bliq ** (1 / yrs) - 1,
    }


if __name__ == "__main__":
    base = run(pd.DataFrame({"mkt": 1.0}, index=M.index))
    res = []
    for k, w in GRID.items():
        r = run(w)
        s = summarize(k, r, base)
        p = window(r, POST)
        b = window(base, POST)
        s["post2000"] = {"excess_cagr": cagr(p) - cagr(b), "p_boot": boot_p(p, b)[0]}
        res.append(s)
    for k, (r, fl) in DAILY.items():
        s = summarize(k, r, base)
        p = window(r, POST)
        b = window(base, POST)
        s["post2000"] = {"excess_cagr": cagr(p) - cagr(b), "p_boot": boot_p(p, b)[0]}
        s["flips_per_year"] = float(fl)
        res.append(s)
    taxes = []
    for k in ("indmom_n12_L12_s1_top3", "indmom_n49_L12_s1_top8", "trendlev_L2.0_sp0.015_sma10"):
        taxes.append(tax_compare(k, GRID[k], TEST))
    json.dump({"grid": res, "tax": taxes}, open(sys.argv[1], "w"), indent=1, default=float)
    print("done", len(res))
