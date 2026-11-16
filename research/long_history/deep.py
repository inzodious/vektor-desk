import json
import sys

import grid as s2
import numpy as np
import pandas as pd
from strategies import DESIGN, RECENT, TEST, M, cagr, maxdd, run, sma_signal, window


def beta_alpha(r, b, rf):
    x, y = (b - rf).values, (r - rf).values
    beta = np.cov(x, y)[0, 1] / np.var(x, ddof=1)
    a = (y - beta * x).mean() * 12
    return beta, a


base = run(pd.DataFrame({"mkt": 1.0}, index=M.index))
out = {}
picks = [
    "indmom_n12_L12_s1_top3",
    "indmom_n12_L12_s1_top4",
    "indmom_n30_L12_s1_top8",
    "indmom_n49_L12_s1_top8",
    "trendlev_L2.0_sp0.015_sma10",
    "trendlev_L1.5_sp0.015_sma10",
    "trendlev_L3.0_sp0.015_sma10",
]
for k in picks:
    w = s2.GRID[k]
    r = run(w)
    row = {}
    for lab, sp in (("design", DESIGN), ("test", TEST), ("recent", RECENT)):
        rr, bb = window(r, sp), window(base, sp)
        rr, bb = rr.loc[rr.index.intersection(bb.index)], bb.loc[rr.index.intersection(bb.index)]
        be, al = beta_alpha(rr, bb, M["rf"].loc[rr.index])
        row[lab] = {"beta": be, "alpha": al, "maxdd": maxdd(rr), "base_maxdd": maxdd(bb), "vol": rr.std() * 12**0.5, "base_vol": bb.std() * 12**0.5}
    dec = {}
    for y0 in range(1930, 2030, 10):
        sp = (pd.Period(f"{y0}-01", "M"), pd.Period(f"{y0 + 9}-12", "M"))
        rr, bb = window(r, sp), window(base, sp)
        if len(rr) > 24:
            dec[str(y0)] = cagr(rr) - cagr(bb)
    row["decades"] = dec
    wv = w.reindex(M.index).ffill()
    row["turnover_per_year"] = float(wv.diff().abs().sum(axis=1).groupby(wv.index.year).sum().loc[1990:2025].mean() / 2)
    out[k] = row
    tx = s2.tax_compare(k, w, TEST)
    row["tax"] = tx
sleeve = {}
for k in ("indmom_n12_L12_s1_top3", "trendlev_L2.0_sp0.015_sma10"):
    r = run(s2.GRID[k])
    for pct in (0.1, 0.2, 0.3):
        mix = (1 - pct) * base + pct * r
        rr, bb = window(mix, TEST), window(base, TEST)
        sleeve[f"{k}@{int(pct * 100)}"] = {"excess": cagr(rr) - cagr(bb), "maxdd": maxdd(rr), "base_maxdd": maxdd(bb)}
out["sleeves"] = sleeve
ind = s2.GRID["indmom_n12_L12_s1_top3"]
sig = sma_signal(M["mkt"], 10)
w2 = ind.mul(sig, axis=0)
w2["rf"] = 1 - sig
r2 = run(w2)
out["indmom_plus_trend"] = {lab: cagr(window(r2, sp)) - cagr(window(base, sp)) for lab, sp in (("design", DESIGN), ("test", TEST), ("recent", RECENT))}
out["indmom_plus_trend"]["test_maxdd"] = maxdd(window(r2, TEST))
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
print("done")
