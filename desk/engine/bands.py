import json
import math
import os
import sqlite3

from desk.config import Config
from desk.db import connect
from desk.engine import catalog as book
from desk.engine import fi
from desk.engine.scoring import Rng

HORIZONS = (1, 5, 10, 20, 40)
PATHS = 2000
PATHS_ENV = "DESK_BANDS_PATHS"
SEED = 0xB4D5
RESID_SEED = 0x5EED
MIN_MONTHS = 36
REAL_SHARE = 0.8
DD_YEARS = 10
FI_YEARS_MAX = 40
PREMIUM_CUT_PTS = 2.0
DEPOSIT_LADDER = (500.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 8000.0, 10000.0)
POLICY_YEARS = (1, 5, 10, 20)
OWN_SLEEVES = 6
OWN_MIN_WEIGHT = 0.02
REST = "rest"
CASH = "cash"
NEW_MONEY = "new-money"
POLICIES = (
    ("hold", "Hold", "Nothing sold or topped up; new money goes to the safe mix."),
    ("rebalance", "Rebalance", "Topped back up, or trimmed, to today's weight every month."),
    ("trim", "Trim to band", "Held, and sold back to the top of its band whenever it grows past it."),
)
LADDER = tuple({"band": b, "worst_year_loss_pct": w} for b, w in ((1, 10), (2, 18), (3, 25), (4, 33), (5, 45)))
METHOD = (
    "Each mix is fitted to the US market on its own price history (beta plus leftover swings, alpha set to zero), "
    "then replayed in 12-month blocks of market history since 1926. As held is fitted holding by holding and left to drift"
)


class NotReady(Exception):
    pass


# ---- Monthly history ----


def month_closes(series: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in sorted(series):
        if series[d]:
            out[d[:7]] = series[d]
    return out


def month_returns(series: dict[str, float]) -> dict[str, float]:
    closes = month_closes(series)
    months = sorted(closes)
    return {b: closes[b] / closes[a] - 1 for a, b in zip(months, months[1:], strict=False) if closes[a]}


def market(history: list[tuple[str, float, float]]) -> dict[str, tuple[float, float]]:
    return {d[:7]: (m, rf) for d, m, rf in history}


def pick_series(tr, symbol: str, sources: list[str]) -> tuple[str | None, dict[str, float]]:
    best, best_start = None, None
    for s in [symbol, *sources]:
        start = tr.starts(s)
        if start and (best_start is None or start < best_start):
            best, best_start = s, start
    return best, (tr.series.get(best) or {}) if best else {}


def mix_history(mix: dict, rets: dict[str, dict[str, float]], mkt: dict[str, tuple[float, float]]) -> tuple[list[tuple[str, float, float, float]], list[str]]:
    weights = mix["weights"]
    months = sorted(mkt)
    first = None
    for m in months:
        real = sum(w for s, w in weights.items() if m in rets.get(s, {}))
        if real >= REAL_SHARE - 1e-9:
            first = m
            break
    if first is None:
        return [], []
    filled: dict[str, str] = {}
    out = []
    for m in (x for x in months if x >= first):
        mr, rf = mkt[m]
        r = 0.0
        for s, w in weights.items():
            got = rets.get(s, {}).get(m)
            if got is None:
                filled.setdefault(s, m)
                got = mr
            r += w * got
        out.append((m, r, mr, rf))
    notes = [f"{s} uses the US market for missing months from {m}" for s, m in sorted(filled.items())]
    return out, notes


# ---- Fit ----


def fit(hist: list[tuple[str, float, float, float]]) -> dict | None:
    if len(hist) < MIN_MONTHS:
        return None
    y = [r - rf for _, r, _, rf in hist]
    x = [m - rf for _, _, m, rf in hist]
    n = len(y)
    mx, my = sum(x) / n, sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / vx if vx else 1.0
    alpha = my - beta * mx
    resid = [b - alpha - beta * a for a, b in zip(x, y, strict=True)]
    sd = math.sqrt(sum(e * e for e in resid) / max(1, n - 2))
    return {"beta": beta, "alpha_m": alpha, "resid": resid, "resid_sd_m": sd, "months": n}


# ---- Backtest stats ----


def drawdown(levels: list[float]) -> float:
    peak, worst = 0.0, 0.0
    for v in levels:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1)
    return worst * 100


def stats(rets: list[float], rf: list[float]) -> dict:
    n = len(rets)
    if n < 12:
        return {"months": n}
    level, levels = 1.0, []
    for r in rets:
        level *= 1 + r
        levels.append(level)
    cagr = (level ** (12 / n) - 1) * 100
    ex = [a - b for a, b in zip(rets, rf, strict=True)]
    mean = sum(ex) / n
    sd = math.sqrt(sum((e - mean) ** 2 for e in ex) / (n - 1))
    down = math.sqrt(sum(min(0.0, e) ** 2 for e in ex) / n)
    mdd = drawdown([1.0, *levels])
    years = [math.prod(1 + r for r in rets[i : i + 12]) - 1 for i in range(0, n - 11, 12)]
    return {
        "months": n,
        "cagr_pct": round(cagr, 4),
        "vol_pct": round(sd * math.sqrt(12) * 100, 4),
        "sharpe": round(mean / sd * math.sqrt(12), 4) if sd else None,
        "sortino": round(mean / down * math.sqrt(12), 4) if down else None,
        "max_drawdown_pct": round(mdd, 4),
        "calmar": round(cagr / -mdd, 4) if mdd < 0 else None,
        "worst_year_pct": round(min(years) * 100, 4) if years else None,
        "hit_rate": round(sum(1 for r in rets if r > 0) / n, 4),
    }


def backtest(hist: list[tuple[str, float, float, float]], mix: dict) -> dict:
    dip = book.Dip(mix["cash"], tuple(mix["steps"])) if mix.get("steps") else None
    cash, level, rets = mix.get("cash", 0.0), 1.0, []
    for _, r, mr, rf in hist:
        c = dip.cash() if dip else cash
        rets.append(c * rf + (1 - c) * r)
        if dip:
            level *= 1 + mr
            dip.step(level)
    out = stats(rets, [h[3] for h in hist])
    return out | {"start": hist[0][0], "end": hist[-1][0]} if hist else out


def long_history(model: dict, mix: dict, history: list[tuple[str, float, float]]) -> dict:
    dip = book.Dip(mix["cash"], tuple(mix["steps"])) if mix.get("steps") else None
    cash, level, rets = mix.get("cash", 0.0), 1.0, []
    for _, mr, rf in history:
        core = rf + model["beta"] * (mr - rf)
        c = dip.cash() if dip else cash
        rets.append(c * rf + (1 - c) * core)
        if dip:
            level *= 1 + mr
            dip.step(level)
    s = stats(rets, [h[2] for h in history])
    return {k: s.get(k) for k in ("months", "cagr_pct", "max_drawdown_pct", "worst_year_pct")} | {"start": history[0][0][:7], "end": history[-1][0][:7]}


# ---- Monte Carlo ----


def pct(xs: list[float], p: float) -> float | None:
    return fi.pct(xs, p) if xs else None


def sleeve(sid: str, model: dict, *, start: float = 0.0, deposit: float = 0.0, fee_pct: float = 0.0, cash: float = 0.0, steps=None) -> dict:
    return {
        "id": sid,
        "start": start,
        "deposit": deposit,
        "beta": model["beta"],
        "resid": model.get("resid") or [],
        "sd_m": model.get("resid_sd_m", 0.0),
        "alpha_m": model.get("alpha_m", 0.0),
        "months": model.get("months"),
        "fee_pct": fee_pct,
        "cash": cash,
        "steps": steps,
    }


def reach(hits: list[int], paths: int, p: float) -> float | None:
    i = int(p * (paths - 1))
    return round(hits[i] / 12, 2) if i < len(hits) else None


def walk(
    history: list[tuple[str, float, float]],
    sleeves: list[dict],
    *,
    start: float,
    deposit: float,
    goal: float | None,
    goal_month: int | None,
    inflation: float,
    real: bool,
    paths: int,
    seed: int = SEED,
    premium_cut_pts: float = 0.0,
    ladder: tuple[float, ...] = (),
    policy: str = "hold",
    watch: tuple[int, ...] = (),
    cap: float | None = None,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict:
    n = len(history)
    block, draw = Rng(seed).below, Rng(seed ^ RESID_SEED).below
    cut_m = premium_cut_pts / 100 / 12
    ex = [mr - rf - cut_m for _, mr, rf in history]
    rfs = [rf for _, _, rf in history]
    deflate = (1 + inflation) ** (1 / 12) if real else 1.0
    count = len(sleeves)
    order = range(count)
    beta = [s["beta"] for s in sleeves]
    resid = [s.get("resid") or [] for s in sleeves]
    sizes = [len(r) for r in resid]
    fee_m = [s.get("fee_pct", 0.0) / 100 / 12 for s in sleeves]
    cash0 = [s.get("cash", 0.0) for s in sleeves]
    steps = [tuple(s["steps"]) if s.get("steps") else None for s in sleeves]
    w0 = [s["start"] for s in sleeves]
    dep = [s["deposit"] for s in sleeves]
    fed = [j for j in order if dep[j]]
    dipped = any(steps)
    months = max(horizons) * 12
    dd_months = min(DD_YEARS, max(horizons)) * 12
    marks = {h * 12: h for h in horizons}
    levels = sorted(set(ladder)) if goal and policy == "hold" else []
    top = len(levels) - 1
    reached: list[list[int]] = [[] for _ in levels]
    values: dict[int, list[float]] = {h: [] for h in horizons}
    index_at: dict[int, list[float]] = {h: [] for h in horizons}
    shares: dict[int, dict[int, list[float]]] = {h: {j: [] for j in watch} for h in horizons}
    years: list[float] = []
    dds: list[float] = []
    firsts: list[int] = []
    for _ in range(paths):
        dips = [book.Dip(cash0[j], steps[j]) if steps[j] else None for j in order]
        u = [start * w for w in w0]
        a = [0.0] * count
        v, idx, mkt_level, peak, worst, year_start = start, 1.0, 1.0, 1.0, 0.0, 1.0
        first = None
        jl = top
        g = 1.0
        k = i = 0
        for m in range(1, months + 1):
            if k == 0:
                i = block(n)
            t = (i + k) % n
            x, rf = ex[t], rfs[t]
            k = (k + 1) % fi.BLOCK
            held = grown = 0.0
            for j in order:
                core = rf + beta[j] * x + (resid[j][draw(sizes[j])] if sizes[j] else 0.0) - fee_m[j]
                c = dips[j].cash() if dips[j] else cash0[j]
                g = (c * rf + (1 - c) * core + 1) / deflate
                uj = u[j] * g
                aj = a[j] * g
                u[j] = uj
                a[j] = aj + dep[j]
                held += uj
                grown += aj
            before = held + deposit * grown
            if count == 1:
                idx *= g
            elif v > 0:
                idx *= before / v
            v = before + deposit
            if dipped:
                mkt_level *= 1 + x + rf
                for d in dips:
                    if d:
                        d.step(mkt_level)
            while jl >= 0 and held + levels[jl] * (grown + 1) >= goal:
                reached[jl].append(m)
                jl -= 1
            if policy == "rebalance":
                for j in order:
                    u[j] = v * w0[j]
                    a[j] = 0.0
            elif policy == "trim" and cap is not None:
                for j in watch:
                    own = u[j] + deposit * a[j]
                    if own > cap * v > 0:
                        keep = cap * v / own
                        u[j] *= keep
                        a[j] *= keep
                        for f in fed:
                            u[f] += (own - cap * v) * dep[f]
            if m <= dd_months:
                peak = max(peak, idx)
                worst = min(worst, idx / peak - 1)
                if m % 12 == 0:
                    years.append(idx / year_start - 1)
                    year_start = idx
            if goal and first is None and v >= goal:
                first = m
            if m in marks:
                h = marks[m]
                values[h].append(v)
                index_at[h].append(idx)
                for j in watch:
                    shares[h][j].append((u[j] + deposit * a[j]) / v if v > 0 else 0.0)
        dds.append(worst)
        if first is not None:
            firsts.append(first)
    worst_years = sorted(years)
    tail = worst_years[: max(1, len(worst_years) // 20)]
    firsts.sort()
    for hits in reached:
        hits.sort()
    bands = []
    for h in horizons:
        vs, ix = values[h], index_at[h]
        row = {
            "years": h,
            "p10": round(pct(vs, 0.1), 2),
            "p50": round(pct(vs, 0.5), 2),
            "p90": round(pct(vs, 0.9), 2),
            "contributed": round(start + deposit * h * 12, 2),
            "chance_loss": round(sum(1 for x in ix if x < 1) / len(ix), 4),
            "chance_below_contributed": round(sum(1 for x in vs if x < start + deposit * h * 12) / len(vs), 4),
            "return_p50_pct": round(((pct(ix, 0.5) or 1) ** (1 / h) - 1) * 100, 4),
        }
        if watch:
            row["weights"] = {sleeves[j]["id"]: {p: round(pct(shares[h][j], q) * 100, 2) for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))} for j in watch}
        bands.append(row)
    by_target = goal_month if goal and goal_month else None
    return {
        "bands": bands,
        "worst_year_p10_pct": round(pct(worst_years, 0.1) * 100, 4),
        "cvar95_1y_pct": round(sum(tail) / len(tail) * 100, 4),
        "drawdown_10y": {p: round(pct(dds, q) * 100, 4) for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))},
        "chance_fi": round(sum(1 for m in firsts if m <= by_target) / paths, 4) if by_target else None,
        "fi_years": {p: reach(firsts, paths, q) for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))} if goal else None,
        "fi_time": [
            {
                "deposit": level,
                "years_p10": reach(hits, paths, 0.1),
                "years_p50": reach(hits, paths, 0.5),
                "years_p90": reach(hits, paths, 0.9),
                "chance_by_target": round(sum(1 for m in hits if m <= by_target) / paths, 4) if by_target else None,
            }
            for level, hits in zip(levels, reached, strict=True)
        ]
        if levels
        else None,
    }


def simulate(
    history: list[tuple[str, float, float]],
    model: dict,
    mix: dict,
    *,
    start: float,
    deposit: float,
    goal: float | None,
    goal_month: int | None,
    fee_pct: float,
    inflation: float,
    real: bool,
    paths: int,
    seed: int = SEED,
    premium_cut_pts: float = 0.0,
    ladder: tuple[float, ...] = (),
) -> dict:
    one = sleeve("mix", model, start=1.0, deposit=1.0, fee_pct=fee_pct, cash=mix.get("cash", 0.0), steps=mix.get("steps"))
    return walk(
        history,
        [one],
        start=start,
        deposit=deposit,
        goal=goal,
        goal_month=goal_month,
        inflation=inflation,
        real=real,
        paths=paths,
        seed=seed,
        premium_cut_pts=premium_cut_pts,
        ladder=ladder,
    )


# ---- As held, holding by holding ----


def symbol_history(rets: dict[str, float], mkt: dict[str, tuple[float, float]]) -> list[tuple[str, float, float, float]]:
    return [(m, rets[m], mkt[m][0], mkt[m][1]) for m in sorted(rets) if m in mkt]


def own_symbols(mix: dict, rets: dict[str, dict[str, float]], mkt: dict, kinds: dict[str, str], pinned: set[str]) -> list[str]:
    share = 1 - mix.get("cash", 0.0)
    picks = []
    for sym, w in mix["weights"].items():
        single = sym in pinned or kinds.get(sym) == "stock"
        if single and w * share >= OWN_MIN_WEIGHT and len(symbol_history(rets.get(sym, {}), mkt)) >= MIN_MONTHS:
            picks.append((sym not in pinned, -w, sym))
    return [sym for _, _, sym in sorted(picks)[:OWN_SLEEVES]]


def held_sleeves(
    mix: dict, rets: dict, mkt: dict, kinds: dict[str, str], pinned: set[str], fees: dict[str, float], new_money: dict | None
) -> tuple[list[dict], list[str]] | None:
    share = 1 - mix.get("cash", 0.0)
    own = own_symbols(mix, rets, mkt, kinds, pinned)
    source = mix.get("source") or mix["weights"]
    out, notes = [], []
    for sym in own:
        fee = book.mix_fee({s: w for s, w in source.items() if book.proxy(s) == sym}, fees)
        out.append(sleeve(sym, fit(symbol_history(rets[sym], mkt)), start=mix["weights"][sym] * share, fee_pct=fee))
    rest = {s: w for s, w in mix["weights"].items() if s not in own}
    total = sum(rest.values())
    if total > 1e-9:
        hist, _ = mix_history({"weights": {s: w / total for s, w in rest.items()}}, rets, mkt)
        model = fit(hist)
        if model is None:
            return None
        fee = book.mix_fee({s: w for s, w in source.items() if book.proxy(s) in rest}, fees)
        out.append(sleeve(REST, model, start=total * share, fee_pct=fee) | {"holds": sorted(rest)})
        if new_money is None:
            new_money = {"model": model, "fee_pct": fee, "to": REST}
        short = sorted(s for s in rest if kinds.get(s) == "stock" and rest[s] * share >= OWN_MIN_WEIGHT)
        if short:
            notes.append(f"{', '.join(short)}: under {MIN_MONTHS} months of prices, so modelled with the funds")
    if mix.get("cash"):
        out.append(sleeve(CASH, {"beta": 0.0}, start=mix["cash"]))
    if new_money is None:
        new_money = {"model": {"beta": 1.0}, "fee_pct": 0.0, "to": "market"}
    out.append(sleeve(NEW_MONEY, new_money["model"], deposit=1.0, fee_pct=new_money["fee_pct"]) | {"to": new_money["to"]})
    return out, notes


def blended(sleeves: list[dict]) -> dict:
    live = [s for s in sleeves if s["start"] > 0]
    fitted = [s["months"] for s in live if s["months"]]
    return {
        "beta": round(sum(s["start"] * s["beta"] for s in live), 4),
        "alpha_dropped_pct": round(sum(s["start"] * ((1 + s["alpha_m"]) ** 12 - 1) for s in live) * 100, 4),
        "resid_vol_pct": round(math.sqrt(sum((s["start"] * s["sd_m"]) ** 2 for s in live) * 12) * 100, 4),
        "months": min(fitted) if fitted else 0,
    }


def sleeve_rows(sleeves: list[dict]) -> list[dict]:
    out = []
    for s in sleeves:
        row = {
            "id": s["id"],
            "weight": round(s["start"], 6),
            "beta": round(s["beta"], 4),
            "resid_vol_pct": round(s["sd_m"] * math.sqrt(12) * 100, 4),
            "fee_pct": round(s["fee_pct"], 4),
            "months": s["months"],
        }
        out.append(row | {k: s[k] for k in ("holds", "to") if k in s})
    return out


def brief(sim: dict, ladder: list[dict], years: tuple[int, ...] | None = None) -> dict:
    ten = next((b for b in sim["bands"] if b["years"] == 10), None)
    return {
        "risk_rank": rank(sim["worst_year_p10_pct"], ladder),
        "worst_year_p10_pct": sim["worst_year_p10_pct"],
        "cvar95_1y_pct": sim["cvar95_1y_pct"],
        "max_drawdown_pct": sim["drawdown_10y"]["p50"],
        "drawdown_10y": sim["drawdown_10y"],
        "p50_value_10y": ten["p50"] if ten else None,
        "chance_fi": sim["chance_fi"],
        "fi_years": sim["fi_years"],
        "bands": [b for b in sim["bands"] if years is None or b["years"] in years],
    }


# ---- Risk band fit ----


def ladder_and_profile(cfg: Config | None) -> tuple[list[dict], dict | None, str]:
    try:
        from desk.decisions import risk as profile_risk
    except ImportError:
        return list(LADDER), None, "default"
    raw = getattr(profile_risk, "BANDS", None) or LADDER
    rows = [{"band": int(k)} | dict(v) for k, v in raw.items()] if isinstance(raw, dict) else [dict(b) for b in raw]
    ladder = [{"band": b["band"], "label": b.get("label") or b.get("name"), "worst_year_loss_pct": limit(b)} for b in rows if limit(b) is not None]
    current = getattr(profile_risk, "current", None)
    try:
        prof = current(cfg) if current and cfg is not None else None
    except Exception:
        prof = None
    return ladder, prof, "profile"


def limit(band: dict | None) -> float | None:
    raw = (band or {}).get("worst_year_loss_pct", (band or {}).get("worst_year_pct"))
    return abs(float(raw)) if isinstance(raw, int | float) else None


def rank(worst_p10: float, ladder: list[dict]) -> int:
    for b in sorted(ladder, key=lambda b: b["band"]):
        if -worst_p10 <= float(b["worst_year_loss_pct"]):
            return int(b["band"])
    return max(int(b["band"]) for b in ladder)


def fit_to(worst_p10: float, prof: dict | None, ladder: list[dict]) -> str | None:
    own = limit(prof)
    if own is None:
        return None
    if -worst_p10 > own:
        return "above"
    lower = [b for b in ladder if int(b["band"]) == int(prof.get("band") or 0) - 1]
    if lower and -worst_p10 <= float(lower[0]["worst_year_loss_pct"]):
        return "below"
    return "fits"


# ---- View ----


def _paths() -> int:
    try:
        return max(100, int(os.environ.get(PATHS_ENV, "") or PATHS))
    except ValueError:
        return PATHS


def strip(bands: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if k != "weights"} for b in bands]


def policy_row(pid: str, sim: dict, ladder: list[dict], symbol: str) -> dict:
    name, rule = next((n, r) for p, n, r in POLICIES if p == pid)
    got = brief(sim, ladder, POLICY_YEARS)
    got["bands"] = [{k: v for k, v in b.items() if k != "weights"} | {"weight_pct": (b.get("weights") or {}).get(symbol)} for b in got["bands"]]
    return {"id": pid, "name": name, "rule": rule} | got


def run(
    out,
    cfg: Config | None,
    desk: sqlite3.Connection,
    tr,
    mixes: dict[str, dict],
    *,
    value: float | None,
    deposits: list[tuple[str, float]],
    prefs: dict | None,
    fees: dict[str, float],
    kinds: dict[str, str] | None = None,
    convictions: dict[str, tuple[float, float]] | None = None,
) -> dict:
    view = {"as_of": out.as_of, "status": "not_ready", "rows": [], "book": "as-held"}
    history = fi.monthly_history(desk)
    if len(history) < 10 * 12:
        return view | {"note": "The bands need the French monthly market history; the engine's monthly french job fetches it."}
    if not value:
        return view | {"note": "No portfolio value yet."}
    deposit, source, n_months = fi.monthly_deposit(deposits, out.as_of)
    goal = prefs["fi_number"] if prefs else None
    goal_month = fi.months_between(out.as_of, prefs["target_date"]) if prefs and prefs.get("target_date") else None
    if goal_month is not None and (goal_month <= 0 or goal_month > FI_YEARS_MAX * 12):
        goal_month = None
    mkt = market(history)
    paths = _paths()
    ladder, prof, ladder_source = ladder_and_profile(cfg)
    kinds, convictions = kinds or {}, convictions or {}
    levels = tuple(sorted({*DEPOSIT_LADDER, round(deposit or 0.0, 2)})) if goal else ()
    common = {
        "start": value,
        "deposit": deposit or 0.0,
        "goal": goal,
        "goal_month": goal_month,
        "inflation": prefs["inflation"] if prefs else 0.0,
        "real": bool(prefs and prefs["real"]),
        "paths": paths,
    }
    fitted = {}
    for sid, mix in mixes.items():
        rets, used = {}, {}
        for sym in mix["weights"]:
            sources = [s for s in (mix.get("source") or {}) if book.proxy(s) == sym and s != sym]
            got, series = pick_series(tr, sym, sources)
            if got:
                rets[sym] = month_returns(series)
                used[sym] = got
        hist, fill_notes = mix_history(mix, rets, mkt)
        fitted[sid] = {"rets": rets, "used": used, "hist": hist, "model": fit(hist), "notes": list(mix.get("notes") or []) + fill_notes}
        fitted[sid]["fee"] = book.mix_fee(mix.get("source") or mix["weights"], fees)
    safe = fitted.get("safe-mix")
    new_money = {"model": safe["model"], "fee_pct": safe["fee"], "to": "safe-mix"} if safe and safe["model"] else None
    rows, held_view = [], []
    for sid, mix in mixes.items():
        f = fitted[sid]
        hist, model, notes, fee = f["hist"], f["model"], f["notes"], f["fee"]
        row = {"id": sid, "name": book.NAMES[sid], "weights": mix["weights"], "cash": mix.get("cash", 0.0), "priced_from": f["used"]}
        if model is None:
            rows.append(row | {"status": "not_ready", "note": f"Needs {MIN_MONTHS} months of prices for its funds; has {len(hist)}.", "notes": notes})
            continue
        held = held_sleeves(mix, f["rets"], mkt, kinds, set(convictions), fees, new_money) if mix.get("policy") == book.HOLD else None
        if held:
            sleeves, more = held
            notes = notes + more
        else:
            sleeves = [sleeve("mix", model, start=1.0, deposit=1.0, fee_pct=fee, cash=mix.get("cash", 0.0), steps=mix.get("steps"))]
        ids = [s["id"] for s in sleeves]
        watch = tuple(ids.index(sym) for sym in sorted(convictions) if sym in ids) if held else ()
        sim = walk(history, sleeves, **common, ladder=levels, watch=watch)
        low = walk(history, sleeves, **common, ladder=levels, premium_cut_pts=PREMIUM_CUT_PTS)
        bt = backtest(hist, mix)
        shape = {
            "beta": model["beta"],
            "alpha_dropped_pct": ((1 + model["alpha_m"]) ** 12 - 1) * 100,
            "resid_vol_pct": model["resid_sd_m"] * math.sqrt(12) * 100,
            "months": model["months"],
        }
        if held:
            shape = blended(sleeves)
        row |= {"status": "ok", "fit": fit_to(sim["worst_year_p10_pct"], prof, ladder)} | brief(sim, ladder)
        row |= {
            "bands": strip(sim["bands"]),
            "fi_time": sim["fi_time"],
            "lower": brief(low, ladder) | {"fi_time": low["fi_time"]},
            "sharpe": bt.get("sharpe"),
            "backtest": bt,
            "long_history": long_history({"beta": shape["beta"]}, mix, history),
            "model": {k: round(v, 4) for k, v in shape.items()} | {"start": hist[0][0], "end": hist[-1][0]},
            "fee_pct": round(sum(s["start"] * s["fee_pct"] for s in sleeves) if held else fee, 4),
            "policy": book.HOLD if held else "rebalance",
            "proxy_note": "; ".join(n for n in notes if "trades as" in n or "ETF twin" in n) or None,
            "notes": notes,
        }
        if held:
            again = walk(history, sleeves, **common, policy="rebalance", watch=watch)
            row |= {
                "sleeves": sleeve_rows(sleeves),
                "new_money": sleeves[-1]["to"],
                "variants": [{"id": "rebalanced", "name": "Topped back up to today's weights"} | brief(again, ladder) | {"bands": strip(again["bands"])}],
            }
            for sym, (lo, hi) in sorted(convictions.items()):
                if sym not in ids:
                    if sym in mix["weights"]:
                        note = f"Needs {MIN_MONTHS} months of {sym} prices and at least {OWN_MIN_WEIGHT * 100:g}% of the book."
                        held_view.append({"symbol": sym, "status": "not_ready", "band_min_pct": lo, "band_max_pct": hi, "note": note})
                    continue
                j = ids.index(sym)
                trim = walk(history, sleeves, **common, policy="trim", watch=(j,), cap=hi / 100, horizons=POLICY_YEARS)
                held_view.append(
                    {
                        "symbol": sym,
                        "status": "ok",
                        "weight_pct": round(sleeves[j]["start"] * 100, 2),
                        "band_min_pct": lo,
                        "band_max_pct": hi,
                        "beta": round(sleeves[j]["beta"], 4),
                        "resid_vol_pct": round(sleeves[j]["sd_m"] * math.sqrt(12) * 100, 4),
                        "months": sleeves[j]["months"],
                        "policies": [policy_row("hold", sim, ladder, sym), policy_row("rebalance", again, ladder, sym), policy_row("trim", trim, ladder, sym)],
                    }
                )
        rows.append(row)
    rows.sort(key=lambda r: (r.get("risk_rank") or 9, r.get("worst_year_p10_pct") is None, -(r.get("worst_year_p10_pct") or 0), r["id"]))
    for r in rows:
        if r.get("status") == "ok":
            out.m("bands.worst_year_p10", r["worst_year_p10_pct"], "pct", scope="strategy", scope_id=r["id"], quality="modelled", n_obs=paths)
            out.m("bands.p50_10y", r["p50_value_10y"], "usd", scope="strategy", scope_id=r["id"], quality="modelled", n_obs=paths)
            if r["chance_fi"] is not None:
                out.m("bands.chance_fi", r["chance_fi"] * 100, "pct", scope="strategy", scope_id=r["id"], quality="modelled", n_obs=paths)
    caveats = [
        "Alpha is set to zero: no mix gets credit for beating the market in its own history.",
        "Leftover swings are drawn month by month and holding by holding, so a fund's own long slumps and stocks that fall together are understated.",
        "International and bond funds are modelled through their link to the US market since 1926.",
        "As held is left to drift: nothing is sold or topped up, and new money goes to the safe mix.",
        f"The lower-return case takes {PREMIUM_CUT_PTS:g} points a year off what stocks earn over cash.",
        "Every mix pays its funds' yearly fees. Taxes and the margin debit are not modelled.",
    ]
    return view | {
        "status": "ok" if any(r.get("status") == "ok" for r in rows) else "not_ready",
        "rows": rows,
        "convictions": held_view,
        "start_value": round(value, 2),
        "monthly_deposit": round(deposit, 2) if deposit is not None else None,
        "deposit_source": source,
        "deposit_note": f"from your last {n_months} month{'s' if n_months != 1 else ''} of deposits, net of withdrawals" if n_months else "no deposits yet",
        "deposit_ladder": list(levels),
        "fi_number": goal,
        "target_date": prefs.get("target_date") if prefs else None,
        "fi_years_max": FI_YEARS_MAX,
        "real": bool(prefs and prefs["real"]),
        "horizons": list(HORIZONS),
        "policy_years": list(POLICY_YEARS),
        "premium_cut_pts": PREMIUM_CUT_PTS,
        "paths": paths,
        "history": {"start": history[0][0][:7], "end": history[-1][0][:7], "months": len(history)},
        "ladder": ladder,
        "ladder_source": ladder_source,
        "profile": {"band": prof.get("band"), "label": prof.get("label"), "worst_year_loss_pct": limit(prof), "version": prof.get("version")} if prof else None,
        "method": METHOD,
        "caveats": caveats,
    }


# ---- Seam for the agents ----


CATALOG_FIELDS = ("id", "name", "risk_rank", "fit", "worst_year_p10_pct", "p50_value_10y", "chance_fi", "sharpe", "max_drawdown_pct", "proxy_note")


def view(cfg: Config) -> dict:
    if not cfg.desk_db.exists():
        raise NotReady("The engine has not run yet.")
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='engine_views'").fetchone():
            raise NotReady("The engine has not run yet.")
        row = conn.execute("SELECT body FROM engine_views WHERE name='bands'").fetchone()
    finally:
        conn.close()
    body = json.loads(row[0]) if row else None
    if not body or body.get("status") != "ok":
        raise NotReady((body or {}).get("note") or "The bands are not built yet.")
    return body


def catalog(cfg: Config) -> list[dict]:
    return [{k: r.get(k) for k in CATALOG_FIELDS} for r in view(cfg)["rows"] if r.get("status") == "ok"]
