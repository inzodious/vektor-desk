import os
import sqlite3
from datetime import date

from desk.engine.lab.factors import FACTORS, ols_hac
from desk.engine.scoring import Rng

PATHS = 10_000
BLOCK = 12
SEED = 0xF1F1F1
MAX_MONTHS = 600
EXTRA_MONTHS = 120
DEPOSIT_MONTHS = 12
FACTOR_DAYS = 756
BOND_WORDS = ("bond", "fixed", "income", "treasury", "aggregate")
BOND_FUNDS = {"AGG", "BND", "BNDX", "FXNAX", "VBTLX", "VBMFX", "SCHZ", "IUSB", "FBND", "TLT", "IEF", "SHY", "VGIT", "VGSH", "GOVT", "SGOV", "BIL", "FUAMX"}


# ---- Inputs ----


def fi_prefs(rows) -> dict | None:
    for p in rows:
        if p.get("key") == "fi" and isinstance(p.get("value"), dict):
            v = p["value"]
            spend, multiple = v.get("fiYearlySpend"), v.get("fiMultiple") or 25
            birth, age = v.get("birthDate"), v.get("fiTargetAge")
            if not isinstance(spend, int | float) or spend <= 0 or not isinstance(multiple, int | float) or multiple <= 0:
                return None
            target = None
            if isinstance(birth, str) and isinstance(age, int | float) and age > 0:
                b = date.fromisoformat(birth)
                year = b.year + int(age)
                try:
                    target = b.replace(year=year).isoformat()
                except ValueError:
                    target = b.replace(year=year, day=28).isoformat()
            return {
                "fi_number": float(spend) * float(multiple),
                "target_date": target,
                "inflation": float(v.get("inflation") or 0.0),
                "real": bool(v.get("inflationAdjusted")),
            }
    return None


def monthly_deposit(deposits: list[tuple[str, float]], as_of: str) -> tuple[float | None, str, int]:
    start = add_months(as_of, -DEPOSIT_MONTHS)
    seen = sorted((d, a) for d, a in deposits if a and d <= as_of)
    if not any(a > 0 for _, a in seen):
        return None, "none", 0
    first = max(next(d for d, a in seen if a > 0), start)
    months = max(1, min(DEPOSIT_MONTHS, months_between(first, as_of) + 1))
    total = sum(a for d, a in seen if d > start)
    return max(0.0, total / months), "activity", months


def bond_share(plan: dict, targets: dict[str, float]) -> float:
    extra = {s.strip().upper() for s in os.environ.get("DESK_BOND_FUNDS", "").split(",") if s.strip()}
    sleeves = {str(f.get("ticker") or "").upper(): str(f.get("sleeve") or "").lower() for f in plan.get("funds") or []}
    return sum(w for s, w in targets.items() if s in BOND_FUNDS | extra or any(word in sleeves.get(s, "") for word in BOND_WORDS))


def monthly_history(desk: sqlite3.Connection) -> list[tuple[str, float, float]]:
    if not desk.execute("SELECT 1 FROM sqlite_master WHERE name='factors_daily'").fetchone():
        return []
    mkt = dict(desk.execute("SELECT date, value FROM factors_daily WHERE series='mkt_rf_m'").fetchall())
    rf = dict(desk.execute("SELECT date, value FROM factors_daily WHERE series='rf_m'").fetchall())
    return [(d, (mkt[d] + rf[d]) / 100, rf[d] / 100) for d in sorted(mkt) if d in rf]


# ---- Monte Carlo ----


def months_between(a: str, b: str) -> int:
    x, y = date.fromisoformat(a), date.fromisoformat(b)
    return (y.year - x.year) * 12 + y.month - x.month - (1 if y.day < x.day else 0)


def add_months(day: str, n: int) -> str:
    d = date.fromisoformat(day)
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, 28)).isoformat()


def required_return(start: float, deposit: float, months: int, goal: float) -> float | None:
    if months <= 0:
        return None

    def fv(r):
        v = start
        for _ in range(months):
            v = v * (1 + r) + deposit
        return v

    lo, hi = -0.05, 0.05
    if fv(hi) < goal:
        return None
    if fv(lo) >= goal:
        return (1 + lo) ** 12 - 1
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fv(mid) < goal else (lo, mid)
    return (1 + hi) ** 12 - 1


def simulate(
    history,
    *,
    start: float,
    deposit: float,
    equity: float,
    fee_pct: float,
    months: int,
    goal: float,
    inflation: float,
    real: bool,
    paths: int,
    seed: int = SEED,
):
    n = len(history)
    rng = Rng(seed)
    monthly_fee = fee_pct / 100 / 12
    deflate = (1 + inflation) ** (1 / 12) if real else 1.0
    rets = [((1 + equity * s + (1 - equity) * b - monthly_fee) / deflate) - 1 for _, s, b in history]
    hit: list[int | None] = []
    years = list(range(12, months + 1, 12))
    at_year: list[list[float]] = [[] for _ in years]
    for _ in range(paths):
        v, first, k, i = start, None, 0, 0
        for m in range(1, months + 1):
            if k == 0:
                i = rng.below(n)
            v = v * (1 + rets[(i + k) % n]) + deposit
            k = (k + 1) % BLOCK
            if first is None and v >= goal:
                first = m
            if m % 12 == 0:
                at_year[m // 12 - 1].append(v)
        hit.append(first)
    return hit, years, at_year


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * (len(s) - 1)))]


def run(
    out,
    plan: dict,
    targets: dict[str, float],
    fees: dict[str, float],
    prefs: dict | None,
    desk: sqlite3.Connection,
    value: float | None,
    deposits: list[tuple[str, float]] | None = None,
) -> dict:
    view = {"as_of": out.as_of, "status": "not_ready"}
    if prefs is None:
        view["note"] = "No FI goal in Escape Vektor yet; set yearly spend and target age there."
        return view
    goal = prefs["fi_number"]
    out.m("fi.number", goal, "usd", quality="ok")
    if value is not None:
        out.m("fi.progress", value / goal * 100, "pct", quality="modelled")
    deposit, source, months = monthly_deposit(deposits or [], out.as_of)
    months_left = months_between(out.as_of, prefs["target_date"]) if prefs["target_date"] else None
    req = required_return(value or 0.0, deposit or 0.0, months_left, goal) if months_left else None
    out.m("fi.required_return", req * 100 if req is not None else None, "pct", quality="modelled")
    history = monthly_history(desk)
    view |= {"fi_number": goal, "target_date": prefs["target_date"], "start_value": value, "monthly_deposit": deposit, "deposit_source": source}
    view["deposit_note"] = f"from your last {months} month{'s' if months != 1 else ''} of deposits, net of withdrawals" if months else "no deposits seen yet"
    view["required_return_pct"] = round(req * 100, 4) if req is not None else None
    if len(history) < 10 * 12 or value is None:
        view["note"] = "The Monte Carlo needs the French monthly market history; the engine's monthly french job fetches it."
        return view
    bonds = bond_share(plan, targets)
    fee = sum(w * fees.get(s, 0.0) for s, w in targets.items())
    horizon = min(MAX_MONTHS, max((months_left or 0) + EXTRA_MONTHS, 360))
    paths = max(100, int(os.environ.get("DESK_MC_PATHS", PATHS) or PATHS))
    hit, years, at_year = simulate(
        history,
        start=value,
        deposit=deposit or 0.0,
        equity=1 - bonds,
        fee_pct=fee,
        months=horizon,
        goal=goal,
        inflation=prefs["inflation"],
        real=prefs["real"],
        paths=paths,
    )
    reached = sorted(m for m in hit if m is not None)
    share = len(reached) / len(hit)
    dates = {}
    for label, p in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
        idx = int(p * (len(hit) - 1))
        m = reached[idx] if idx < len(reached) else None
        dates[label] = add_months(out.as_of, m) if m is not None else None
        out.m(
            "fi.date_pctl",
            (date.fromisoformat(dates[label]) - date.fromisoformat(out.as_of)).days if dates[label] else None,
            "days",
            window=label,
            quality="modelled",
            n_obs=paths,
        )
    on_time = None
    if months_left is not None:
        on_time = sum(1 for m in hit if m is not None and m <= months_left) / len(hit)
        out.m("fi.on_time", on_time * 100, "pct", quality="modelled", n_obs=paths)
    quality = "modelled"
    caveats = [
        "It replays 12-month blocks of US market history since 1926; it cannot imagine a worse stretch than history had.",
        "Bond funds are modelled as Treasury bills, which understates both their return and their swings; international funds as the US market.",
        "Only the accounts the desk sees count toward the start value.",
    ]
    if source == "none":
        caveats.append("No deposits in your activity yet, so the paths add nothing each month.")
    else:
        caveats.append(f"Each path adds {deposit:,.0f} a month, the average {view['deposit_note']}.")
    view |= {
        "status": "ok",
        "quality": quality,
        "paths": paths,
        "months": horizon,
        "history": {"start": history[0][0], "end": history[-1][0], "months": len(history)},
        "mix": {"equity": round(1 - bonds, 4), "bonds_as_bills": round(bonds, 4)},
        "fee_pct": round(fee, 4),
        "real": prefs["real"],
        "inflation": prefs["inflation"],
        "fi_date": dates,
        "reached_share": round(share, 4),
        "on_time_share": round(on_time, 4) if on_time is not None else None,
        "lines": [
            {"year": y // 12, "date": add_months(out.as_of, y), "p10": round(pct(vs, 0.1), 2), "p50": round(pct(vs, 0.5), 2), "p90": round(pct(vs, 0.9), 2)}
            for y, vs in zip(years, at_year, strict=True)
        ],
        "method": f"Block bootstrap of {BLOCK}-month blocks, {paths} paths, fixed seed",
        "caveats": caveats,
    }
    return view


# ---- Factor exposure ----


def exposure(out, tr, desk: sqlite3.Connection, weights: dict[str, float]) -> dict:
    view = {"as_of": out.as_of, "holdings": {}, "portfolio": {}, "coverage_pct": 0.0}
    if not desk.execute("SELECT 1 FROM sqlite_master WHERE name='factors_daily'").fetchone():
        return view | {"note": "No French factors yet."}
    fac: dict[str, dict[str, float]] = {}
    for r in desk.execute("SELECT series, date, value FROM factors_daily WHERE series IN ('mkt_rf', 'smb', 'hml', 'rmw', 'cma', 'mom', 'rf')"):
        fac.setdefault(r[0], {})[r[1]] = r[2]
    if any(f not in fac for f in (*FACTORS, "rf")):
        return view | {"note": "No French factors yet."}
    days = sorted(d for d in fac["mkt_rf"] if all(d in fac[f] for f in (*FACTORS, "rf")))[-FACTOR_DAYS - 1 :]
    covered = {}
    for sym, w in sorted(weights.items()):
        if w <= 0 or not days or not tr.starts(sym) or tr.starts(sym) > days[0]:
            continue
        y, x = [], []
        for a, b in zip(days, days[1:], strict=False):
            p0, p1 = tr.price(sym, a), tr.price(sym, b)
            if p0 and p1:
                y.append((p1 / p0 - 1) * 100 - fac["rf"][b])
                x.append([1.0] + [fac[f][b] for f in FACTORS])
        if len(y) < FACTOR_DAYS * 0.9:
            continue
        fit = ols_hac(y, x)
        if fit is None:
            continue
        loads = {f: round(fit["beta"][i + 1], 4) for i, f in enumerate(FACTORS)}
        view["holdings"][sym] = {
            "weight": round(w, 4),
            "loadings": loads,
            "alpha_ann_pct": round(fit["beta"][0] * 252, 4),
            "r2": round(fit["r2"], 4) if fit["r2"] else None,
        }
        covered[sym] = w
    total = sum(covered.values())
    if not total:
        return view | {"note": "No holding has three years of prices overlapping the factors."}
    for f in FACTORS:
        beta = sum(w * view["holdings"][s]["loadings"][f] for s, w in covered.items()) / total
        view["portfolio"][f] = round(beta, 4)
        out.m("risk.factor", beta, "ratio", scope="factor", scope_id=f, window="3Y", n_obs=len(covered), quality="ok")
    view["coverage_pct"] = round(total * 100, 2)
    view["window"] = {"start": days[0], "end": days[-1]}
    out.m("risk.factor_coverage", total * 100, "pct", window="3Y", n_obs=len(covered))
    return view
