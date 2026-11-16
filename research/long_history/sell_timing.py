import load
import numpy as np
import pandas as pd

ind = load.french("12_Industry_Portfolios_daily", daily=True)
mk = load.daily()["mkt"]
ind = ind.loc[ind.index.intersection(mk.index)]
mk = mk.loc[ind.index]
rel = ind.sub(mk, axis=0)
lrel = np.log1p(ind).sub(np.log1p(mk), axis=0)
rows = []
for span, lo, hi in (("1990-2026", "1990-01-01", "2026-12-31"), ("2010-2026", "2010-01-01", "2026-12-31"), ("1927-1989", "1927-01-01", "1989-12-31")):
    L = lrel.loc[lo:hi]
    R = rel.loc[lo:hi]
    for thr in (-0.02, -0.03, -0.04):
        ev = R <= thr
        for h in (1, 5, 10, 20):
            fwd = L[::-1].rolling(h).sum()[::-1].shift(-1)
            x = fwd[ev].stack()
            base = fwd.stack()
            rows.append(
                {
                    "span": span,
                    "drop_vs_market": thr,
                    "days_after": h,
                    "events": int(ev.sum().sum()),
                    "avg_rel_after_pct": 100 * x.mean(),
                    "all_days_avg_pct": 100 * base.mean(),
                    "t": x.mean() / (x.std() / np.sqrt(max(len(x) / h, 1))),
                }
            )
df = pd.DataFrame(rows)
print(df.round(3).to_string())
