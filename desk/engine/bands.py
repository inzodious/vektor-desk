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
MIN_MONTHS = 36
REAL_SHARE = 0.8
DD_YEARS = 10
FI_YEARS_MAX = 40
LADDER = tuple({"band": b, "worst_year_loss_pct": w} for b, w in ((1, 10), (2, 18), (3, 25), (4, 33), (5, 45)))
METHOD = (
    "Each mix is fitted to the US market on its own price history (beta plus leftover swings, alpha set to zero), "
    "then replayed in 12-month blocks of market history since 1926"
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
) -> dict:
    n = len(history)
    rng = Rng(seed)
    beta, resid = model["beta"], model["resid"]
    k_res = len(resid)
    fee_m = fee_pct / 100 / 12
    deflate = (1 + inflation) ** (1 / 12) if real else 1.0
    months = max(HORIZONS) * 12
    marks = {h * 12: h for h in HORIZONS}
    values: dict[int, list[float]] = {h: [] for h in HORIZONS}
    index_at: dict[int, list[float]] = {h: [] for h in HORIZONS}
    years: list[float] = []
    dds: list[float] = []
    fi_hits = 0
    for _ in range(paths):
        dip = book.Dip(mix["cash"], tuple(mix["steps"])) if mix.get("steps") else None
        cash = mix.get("cash", 0.0)
        v, idx, mkt_level, peak, worst, year_start = start, 1.0, 1.0, 1.0, 0.0, 1.0
        hit = False
        k = i = 0
        for m in range(1, months + 1):
            if k == 0:
                i = rng.below(n)
            _, mr, rf = history[(i + k) % n]
            k = (k + 1) % fi.BLOCK
            eps = resid[rng.below(k_res)] if k_res else 0.0
            core = rf + beta * (mr - rf) + eps - fee_m
            c = dip.cash() if dip else cash
            r = (c * rf + (1 - c) * core + 1) / deflate - 1
            idx *= 1 + r
            v = v * (1 + r) + deposit
            if dip:
                mkt_level *= 1 + mr
                dip.step(mkt_level)
            if m <= DD_YEARS * 12:
                peak = max(peak, idx)
                worst = min(worst, idx / peak - 1)
                if m % 12 == 0:
                    years.append(idx / year_start - 1)
                    year_start = idx
            if goal and goal_month and not hit and m <= goal_month and v >= goal:
                hit = True
            if m in marks:
                values[marks[m]].append(v)
                index_at[marks[m]].append(idx)
        dds.append(worst)
        fi_hits += hit
    worst_years = sorted(years)
    tail = worst_years[: max(1, len(worst_years) // 20)]
    bands = []
    for h in HORIZONS:
        vs, ix = values[h], index_at[h]
        bands.append(
            {
                "years": h,
                "p10": round(pct(vs, 0.1), 2),
                "p50": round(pct(vs, 0.5), 2),
                "p90": round(pct(vs, 0.9), 2),
                "contributed": round(start + deposit * h * 12, 2),
                "chance_loss": round(sum(1 for x in ix if x < 1) / len(ix), 4),
                "chance_below_contributed": round(sum(1 for x in vs if x < start + deposit * h * 12) / len(vs), 4),
                "return_p50_pct": round(((pct(ix, 0.5) or 1) ** (1 / h) - 1) * 100, 4),
            }
        )
    return {
        "bands": bands,
        "worst_year_p10_pct": round(pct(worst_years, 0.1) * 100, 4),
        "cvar95_1y_pct": round(sum(tail) / len(tail) * 100, 4),
        "drawdown_10y": {p: round(pct(dds, q) * 100, 4) for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))},
        "chance_fi": round(fi_hits / paths, 4) if goal and goal_month else None,
    }


# ---- Risk band fit ----


def ladder_and_profile(cfg: Config | None) -> tuple[list[dict], dict | None, str]:
    try:
        from desk.decisions import risk as profile_risk
    except ImportError:
        return list(LADDER), None, "default"
    raw = getattr(profile_risk, "BANDS", None) or LADDER
    ladder = [{"band": int(k)} | dict(v) for k, v in raw.items()] if isinstance(raw, dict) else [dict(b) for b in raw]
    current = getattr(profile_risk, "current", None)
    try:
        prof = current(cfg) if current and cfg is not None else None
    except Exception:
        prof = None
    return ladder, prof, "profile"


def rank(worst_p10: float, ladder: list[dict]) -> int:
    for b in sorted(ladder, key=lambda b: b["band"]):
        if -worst_p10 <= float(b["worst_year_loss_pct"]):
            return int(b["band"])
    return max(int(b["band"]) for b in ladder)


def fit_to(worst_p10: float, prof: dict | None, ladder: list[dict]) -> str | None:
    if not prof or prof.get("worst_year_loss_pct") is None:
        return None
    if -worst_p10 > float(prof["worst_year_loss_pct"]):
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
    rows = []
    for sid, mix in mixes.items():
        rets, used = {}, {}
        for sym in mix["weights"]:
            sources = [s for s in (mix.get("source") or {}) if book.proxy(s) == sym and s != sym]
            got, series = pick_series(tr, sym, sources)
            if got:
                rets[sym] = month_returns(series)
                used[sym] = got
        hist, fill_notes = mix_history(mix, rets, mkt)
        model = fit(hist)
        notes = list(mix.get("notes") or []) + fill_notes
        row = {"id": sid, "name": book.NAMES[sid], "weights": mix["weights"], "cash": mix.get("cash", 0.0), "priced_from": used}
        if model is None:
            rows.append(row | {"status": "not_ready", "note": f"Needs {MIN_MONTHS} months of prices for its funds; has {len(hist)}.", "notes": notes})
            continue
        fee = sum(w * fees.get(s, 0.0) for s, w in (mix.get("source") or {}).items()) if sid in ("safe-mix", "dip-buy") else 0.0
        sim = simulate(
            history,
            model,
            mix,
            start=value,
            deposit=deposit or 0.0,
            goal=goal,
            goal_month=goal_month,
            fee_pct=fee,
            inflation=prefs["inflation"] if prefs else 0.0,
            real=bool(prefs and prefs["real"]),
            paths=paths,
        )
        bt = backtest(hist, mix)
        ten = next(b for b in sim["bands"] if b["years"] == 10)
        row |= {
            "status": "ok",
            "risk_rank": rank(sim["worst_year_p10_pct"], ladder),
            "fit": fit_to(sim["worst_year_p10_pct"], prof, ladder),
            "worst_year_p10_pct": sim["worst_year_p10_pct"],
            "cvar95_1y_pct": sim["cvar95_1y_pct"],
            "p50_value_10y": ten["p50"],
            "chance_fi": sim["chance_fi"],
            "sharpe": bt.get("sharpe"),
            "max_drawdown_pct": sim["drawdown_10y"]["p50"],
            "drawdown_10y": sim["drawdown_10y"],
            "bands": sim["bands"],
            "backtest": bt,
            "long_history": long_history(model, mix, history),
            "model": {
                "beta": round(model["beta"], 4),
                "alpha_dropped_pct": round(((1 + model["alpha_m"]) ** 12 - 1) * 100, 4),
                "resid_vol_pct": round(model["resid_sd_m"] * math.sqrt(12) * 100, 4),
                "months": model["months"],
                "start": hist[0][0],
                "end": hist[-1][0],
            },
            "fee_pct": round(fee, 4),
            "proxy_note": "; ".join(n for n in notes if "trades as" in n or "ETF twin" in n) or None,
            "notes": notes,
        }
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
        "Leftover swings are drawn month by month, so a fund's own long slumps are understated.",
        "International and bond funds are modelled through their link to the US market since 1926.",
        "The margin debit is not modelled.",
    ]
    return view | {
        "status": "ok" if any(r.get("status") == "ok" for r in rows) else "not_ready",
        "rows": rows,
        "start_value": round(value, 2),
        "monthly_deposit": round(deposit, 2) if deposit is not None else None,
        "deposit_source": source,
        "deposit_note": f"from your last {n_months} month{'s' if n_months != 1 else ''} of deposits, net of withdrawals" if n_months else "no deposits yet",
        "fi_number": goal,
        "target_date": prefs.get("target_date") if prefs else None,
        "real": bool(prefs and prefs["real"]),
        "horizons": list(HORIZONS),
        "paths": paths,
        "history": {"start": history[0][0][:7], "end": history[-1][0][:7], "months": len(history)},
        "ladder": ladder,
        "ladder_source": ladder_source,
        "profile": {k: prof.get(k) for k in ("band", "label", "worst_year_loss_pct", "version")} if prof else None,
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
