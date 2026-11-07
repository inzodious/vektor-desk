import math

FACTORS = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")
MIN_DAYS = 252
LAGS = 5
ALPHA_T = 2.0
DISGUISE_T = 3.0


# ---- Linear algebra ----


def inverse(m: list[list[float]]) -> list[list[float]] | None:
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        piv = a[c][c]
        a[c] = [x / piv for x in a[c]]
        for r in range(n):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c], strict=True)]
    return [row[n:] for row in a]


def _mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    cols = list(zip(*b, strict=True))
    return [[sum(x * y for x, y in zip(row, col, strict=True)) for col in cols] for row in a]


def ols_hac(y: list[float], x: list[list[float]], lags: int = LAGS) -> dict | None:
    n, k = len(y), len(x[0]) if x else 0
    if n <= k + 1:
        return None
    xtx = [[sum(r[i] * r[j] for r in x) for j in range(k)] for i in range(k)]
    inv = inverse(xtx)
    if inv is None:
        return None
    xty = [sum(r[i] * v for r, v in zip(x, y, strict=True)) for i in range(k)]
    beta = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    e = [v - sum(b * c for b, c in zip(beta, r, strict=True)) for r, v in zip(x, y, strict=True)]
    u = [[c * ei for c in r] for r, ei in zip(x, e, strict=True)]
    s = [[sum(row[i] * row[j] for row in u) for j in range(k)] for i in range(k)]
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        g = [[sum(u[t][i] * u[t - lag][j] for t in range(lag, n)) for j in range(k)] for i in range(k)]
        for i in range(k):
            for j in range(k):
                s[i][j] += w * (g[i][j] + g[j][i])
    v = _mul(_mul(inv, s), inv)
    se = [math.sqrt(max(v[i][i], 0.0)) * math.sqrt(n / (n - k)) for i in range(k)]
    ybar = sum(y) / n
    tss = sum((t - ybar) ** 2 for t in y)
    r2 = 1 - sum(t * t for t in e) / tss if tss else None
    return {"beta": beta, "se": se, "n": n, "r2": r2}


# ---- Factor check ----


def regress(days: list[str], values: list[float], factors: dict[str, dict[str, float]]) -> dict:
    have = [f for f in FACTORS if factors.get(f)]
    if len(have) < len(FACTORS) or not factors.get("rf"):
        return {"status": "not_available", "note": "The French factors are not in the lab yet; the engine's monthly french job fetches them."}
    rf = factors["rf"]
    y, x, used = [], [], []
    for a, b, d in zip(values, values[1:], days[1:], strict=False):
        if not a or d not in rf or any(d not in factors[f] for f in FACTORS):
            continue
        y.append((b / a - 1) * 100 - rf[d])
        x.append([1.0] + [factors[f][d] for f in FACTORS])
        used.append(d)
    if len(y) < MIN_DAYS:
        return {"status": "not_available", "days": len(y), "note": f"Fewer than {MIN_DAYS} days overlap the French factors, which lag a month or two."}
    fit = ols_hac(y, x)
    if fit is None:
        return {"status": "not_available", "days": len(y), "note": "The factor regression is singular on this window."}
    t = [b / s if s else None for b, s in zip(fit["beta"], fit["se"], strict=True)]
    loadings = {f: {"beta": round(fit["beta"][i + 1], 4), "t": round(t[i + 1], 2) if t[i + 1] is not None else None} for i, f in enumerate(FACTORS)}
    alpha_t = t[0]
    tilts = [f for f in FACTORS if f != "mkt_rf" and loadings[f]["t"] is not None and abs(loadings[f]["t"]) > DISGUISE_T]
    significant = alpha_t is not None and alpha_t >= ALPHA_T
    label = "alpha" if significant else ("factor_in_disguise" if tilts else "no_alpha")
    return {
        "status": "ok",
        "start": used[0],
        "end": used[-1],
        "days": len(y),
        "alpha_ann_pct": round(fit["beta"][0] * 252, 4),
        "alpha_t": round(alpha_t, 2) if alpha_t is not None else None,
        "loadings": loadings,
        "r2": round(fit["r2"], 4) if fit["r2"] is not None else None,
        "label": label,
        "tilts": tilts,
        "method": f"OLS of daily excess return on the six French factors, Newey-West standard errors with {LAGS} lags",
    }


def bar(result: dict | None) -> bool | None:
    if not result or result.get("status") != "ok" or result.get("alpha_t") is None:
        return None
    return result["alpha_t"] >= ALPHA_T
