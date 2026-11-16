import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("LONG_HISTORY_DATA", Path.home() / ".cache" / "vektor-desk" / "long-history"))


def french(name, block=0, daily=False):
    lines = open(f"{DATA}/{name}.csv", encoding="latin-1").read().splitlines()
    pat = re.compile(r"^\s*(\d{8})\s*," if daily else r"^\s*(\d{6})\s*,")
    blocks, cur = [], None
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            if cur is None:
                hdr = lines[i - 1]
                cur = {"cols": [c.strip() for c in hdr.split(",")[1:]], "rows": []}
            cur["rows"].append([m.group(1)] + [x.strip() for x in ln.split(",")[1:]])
        else:
            if cur is not None:
                blocks.append(cur)
                cur = None
    if cur is not None:
        blocks.append(cur)
    b = blocks[block]
    idx = [r[0] for r in b["rows"]]
    vals = np.array([[float(x) for x in r[1 : len(b["cols"]) + 1]] for r in b["rows"]])
    vals[vals <= -99.99] = np.nan
    if daily:
        ix = pd.to_datetime(idx, format="%Y%m%d")
    else:
        ix = pd.PeriodIndex([f"{s[:4]}-{s[4:]}" for s in idx], freq="M")
    return pd.DataFrame(vals / 100.0, index=ix, columns=b["cols"])


def fred(name):
    df = pd.read_csv(f"{DATA}/{name}.csv")
    df.columns = ["date", name]
    df["date"] = pd.to_datetime(df["date"])
    df[name] = pd.to_numeric(df[name], errors="coerce")
    return df.set_index("date")[name]


def monthly():
    ff = french("F-F_Research_Data_Factors")
    out = pd.DataFrame(index=ff.index)
    out["rf"] = ff["RF"]
    out["mkt"] = ff["Mkt-RF"] + ff["RF"]
    mom = french("10_Portfolios_Prior_12_2")
    out["mom_top3"] = mom[["PRIOR 8", "PRIOR 9", "Hi PRIOR"]].mean(axis=1)
    out["mom_top1"] = mom["Hi PRIOR"]
    six = french("6_Portfolios_2x3")
    out["small_value"] = six["SMALL HiBM"]
    out["large_value"] = six["BIG HiBM"]
    out["small_growth"] = six["SMALL LoBM"]
    me = french("Portfolios_Formed_on_ME")
    out["small_q"] = me["Lo 20"]
    bm = french("Portfolios_Formed_on_BE-ME")
    out["value_q"] = bm["Hi 20"]
    op = french("Portfolios_Formed_on_OP")
    out["prof_q"] = op["Hi 20"]
    var = french("Portfolios_Formed_on_VAR")
    out["lowvol_q"] = var["Lo 20"]
    dp = french("Portfolios_Formed_on_D-P")
    out["highdiv_q"] = dp["Hi 20"]
    ind = french("12_Industry_Portfolios")
    for c in ind.columns:
        out["ind_" + c] = ind[c]
    dev = french("Developed_ex_US_3_Factors")
    out["intl"] = dev["Mkt-RF"] + dev["RF"]
    gs10 = fred("GS10") / 100.0
    gs10.index = gs10.index.to_period("M")
    y = gs10.reindex(out.index)
    dur = 7.5
    out["bond10"] = y.shift(1) / 12 - dur * (y - y.shift(1)) + 0.5 * 70 * (y - y.shift(1)) ** 2
    cpi = fred("CPIAUCSL")
    cpi.index = cpi.index.to_period("M")
    out["cpi"] = cpi.reindex(out.index).pct_change(fill_method=None)
    return out


def daily():
    d = french("F-F_Research_Data_Factors_daily", daily=True)
    out = pd.DataFrame(index=d.index)
    out["rf"] = d["RF"]
    out["mkt"] = d["Mkt-RF"] + d["RF"]
    return out
