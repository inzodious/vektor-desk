import os
import sqlite3
from bisect import bisect_right
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from desk.config import Config
from desk.engine import cash

HORIZONS = (30, 90, 365)
SCORED = ("buy", "sell", "trim", "rebalance", "harvest", "deposit_route", "hold_off")
TAKEN = ("approved", "placed", "filled", "done", "logged")
NOT_TAKEN = ("dismissed", "passed", "expired")
SKIP = ("rejected",)
BOOT = 1000
SEED = 0x5EED5C0
CI = 0.90
TOO_EARLY_DAYS = 182
MIN_KEEP = 10
CAL_MIN = 30
CAL_BINS = 5
CAL_HORIZON = 90


# ---- Random ----


class Rng:
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n


def bootstrap_mean(xs: list[float], *, n: int = BOOT, seed: int = SEED, level: float = CI) -> tuple[float | None, float | None]:
    if len(xs) < 2:
        return None, None
    rng = Rng(seed + len(xs))
    k = len(xs)
    means = sorted(sum(xs[rng.below(k)] for _ in range(k)) / k for _ in range(n))
    lo = means[int((1 - level) / 2 * (n - 1))]
    hi = means[int((1 + level) / 2 * (n - 1))]
    return lo, hi


# ---- Inputs ----


def decision_rows(cfg: Config) -> list[dict]:
    try:
        from desk.decisions.records import scoring_rows
    except ImportError:
        return []
    try:
        return scoring_rows(cfg)
    except sqlite3.Error:
        return []


def local_day(stamp: str | None, tz: str) -> str | None:
    if not stamp:
        return None
    if len(stamp) == 10:
        return stamp
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date().isoformat()


def anchor(d: dict, tz: str) -> str | None:
    if d["origin"] == "you" and d.get("filled_at"):
        return local_day(d["filled_at"], tz)
    return local_day(d["created_at"], tz)


def start_day(cal: list[str], day: str) -> str | None:
    i = bisect_right(cal, day)
    return cal[i] if i < len(cal) else None


def end_day(cal: list[str], t0: str, days: int) -> str | None:
    target = (date.fromisoformat(t0) + timedelta(days=days)).isoformat()
    if not cal or target > cal[-1]:
        return None
    i = bisect_right(cal, target) - 1
    return cal[i] if i >= 0 else None


def mix_return(tr, targets: dict[str, float], a: str, b: str, fallback: str | None) -> tuple[float | None, str]:
    priced = {s: w for s, w in targets.items() if w > 0 and tr.starts(s) and tr.starts(s) <= a}
    quality = "ok" if priced and len(priced) == len([w for w in targets.values() if w > 0]) else "pro_forma"
    if not priced:
        if not fallback:
            return None, "insufficient_history"
        priced, quality = {fallback: 1.0}, "modelled"
    total = sum(priced.values())
    r = 0.0
    for s, w in priced.items():
        p0, p1 = tr.price(s, a), tr.price(s, b)
        if not p0 or not p1:
            return None, "insufficient_history"
        r += w / total * (p1 / p0)
    return r - 1, quality


def sym_return(tr, symbol: str | None, a: str, b: str) -> float | None:
    if not symbol or not tr.starts(symbol) or tr.starts(symbol) > a:
        return None
    p0, p1 = tr.price(symbol, a), tr.price(symbol, b)
    return p1 / p0 - 1 if p0 and p1 else None


def side(d: dict) -> str | None:
    if d["kind"] in ("sell", "trim", "harvest"):
        return "sell"
    if d["kind"] in ("buy", "deposit_route"):
        return "buy"
    if d["kind"] == "rebalance":
        fill = d.get("fill") or {}
        action = str((fill.get("placed") or {}).get("action") or fill.get("action") or "").lower()
        return "sell" if action.startswith("sell") else "buy"
    return None


# ---- One decision ----


def score(d: dict, tr, cal: list[str], targets: dict[str, float], *, tz: str, rate: float | None, margin_rate: float | None, fallback: str | None) -> dict:
    out = {"id": d["id"], "origin": d["origin"], "kind": d["kind"], "symbol": d["symbol"], "taken": d["status"] in TAKEN, "scores": {}}
    day = anchor(d, tz)
    t0 = start_day(cal, day) if day else None
    out["start"] = t0
    if t0 is None or d["kind"] not in SCORED:
        out["note"] = "not scored" if d["kind"] not in SCORED else "waiting for the next close"
        return out
    amount = d.get("amount_usd")
    if amount is None and d.get("shares") and d["symbol"]:
        px = tr.price(d["symbol"], t0)
        amount = d["shares"] * px if px else None
    amount = abs(amount) if amount is not None else None
    out["amount_usd"] = amount
    for h in HORIZONS:
        t1 = end_day(cal, t0, h)
        if t1 is None:
            continue
        plan_r, quality = mix_return(tr, targets, t0, t1, fallback)
        usd, detail = None, {}
        interest = amount * margin_rate / 100 * h / 360 if amount and margin_rate is not None and d.get("funding") == "margin" else None
        if d["kind"] == "harvest":
            realized = (d.get("tax_impact") or {}).get("realized")
            if realized is not None and rate is not None:
                usd = max(0.0, -realized) * rate
                detail = {"basis": "realized loss times marginal rate", "realized": realized}
            else:
                quality = "insufficient_history"
        elif d["kind"] == "hold_off":
            s_r = sym_return(tr, d["symbol"], t0, t1)
            usd = 0.0
            if amount and s_r is not None and plan_r is not None:
                usd += amount * (plan_r - s_r)
                detail["avoided_vs_plan"] = round(amount * (plan_r - s_r), 2)
            if interest is not None:
                usd += interest
                detail["interest_avoided"] = round(interest, 2)
            if not detail:
                usd = None
        else:
            s_r = sym_return(tr, d["symbol"], t0, t1)
            if amount is None or s_r is None or plan_r is None:
                quality = "insufficient_history"
            elif side(d) == "sell":
                usd = amount * (plan_r - s_r)
            else:
                usd = amount * (s_r - plan_r)
                if interest is not None:
                    usd -= interest
                    detail["interest"] = round(interest, 2)
            if s_r is not None and plan_r is not None:
                detail |= {"symbol_pct": round(s_r * 100, 4), "plan_pct": round(plan_r * 100, 4)}
        out["scores"][h] = {"end": t1, "usd": round(usd, 2) if usd is not None else None, "quality": quality, **detail}
    return out


# ---- Summaries ----


def summarize(xs: list[float], seed: int = SEED) -> dict:
    if not xs:
        return {"n": 0, "total_usd": 0.0, "mean_usd": None, "hit_rate": None, "ci_low": None, "ci_high": None}
    lo, hi = bootstrap_mean(xs, seed=seed)
    return {
        "n": len(xs),
        "total_usd": round(sum(xs), 2),
        "mean_usd": round(sum(xs) / len(xs), 2),
        "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 4),
        "ci_low": round(lo, 2) if lo is not None else None,
        "ci_high": round(hi, 2) if hi is not None else None,
        "note": "The interval includes zero, so this is not yet different from following the plan." if lo is not None and lo <= 0 <= hi else None,
    }


def calibration(pairs: list[tuple[float, int]]) -> dict:
    if not pairs:
        return {"n": 0, "brier": None, "bins": []}
    brier = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
    bins = []
    if len(pairs) >= CAL_MIN:
        for b in range(CAL_BINS):
            lo, hi = b / CAL_BINS, (b + 1) / CAL_BINS
            inside = [(p, o) for p, o in pairs if lo <= p < hi or (b == CAL_BINS - 1 and p == 1.0)]
            if inside:
                bins.append(
                    {
                        "low": lo,
                        "high": hi,
                        "n": len(inside),
                        "said": round(sum(p for p, _ in inside) / len(inside), 4),
                        "happened": round(sum(o for _, o in inside) / len(inside), 4),
                    }
                )
    return {"n": len(pairs), "brier": round(brier, 4), "bins": bins}


def _usd(s: dict, h: int) -> float | None:
    v = s["scores"].get(h)
    return v["usd"] if v else None


def offplan(d: dict, targets: dict[str, float]) -> bool:
    return d["origin"] == "you" and (bool(d.get("override")) or d.get("funding") == "margin" or (d["kind"] == "buy" and d["symbol"] not in targets))


def lag_days(d: dict) -> float | None:
    if d["origin"] == "you" or not d.get("decided_at"):
        return None
    a = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00"))
    b = datetime.fromisoformat(d["decided_at"].replace("Z", "+00:00"))
    return max(0.0, (b - a).total_seconds() / 86400)


def scorecard(rows: list[dict], scored: list[dict], targets: dict[str, float], as_of: str) -> dict:
    by_id = {d["id"]: d for d in rows}
    groups: list[dict] = []
    keys = {
        "origin": lambda s: s["origin"],
        "kind": lambda s: s["kind"],
        "path": lambda s: "override" if by_id[s["id"]].get("override") else ("clean" if by_id[s["id"]].get("preflight_status") == "clear" else "flagged"),
        "taken": lambda s: "taken" if s["taken"] else "not_taken",
    }
    for name, fn in keys.items():
        for value in sorted({fn(s) for s in scored}):
            for h in HORIZONS:
                xs = [x for s in scored if fn(s) == value and (x := _usd(s, h)) is not None]
                if xs:
                    groups.append({"by": name, "group": value, "window": f"{h}D", **summarize(xs)})
    desks = []
    for origin in sorted({s["origin"] for s in scored if s["origin"] != "you"}):
        mine = [s for s in scored if s["origin"] == origin]
        xs = [x for s in mine if (x := _usd(s, CAL_HORIZON)) is not None]
        pairs = [
            (float(by_id[s["id"]]["confidence"]), int(x > 0))
            for s in mine
            if by_id[s["id"]].get("confidence") is not None and (x := _usd(s, CAL_HORIZON)) is not None
        ]
        first = min((s["start"] for s in mine if s["start"]), default=None)
        age = (date.fromisoformat(as_of) - date.fromisoformat(first)).days if first else 0
        total = sum(xs)
        chip = "too_early" if age < TOO_EARLY_DAYS or len(xs) < MIN_KEEP else ("keep" if total >= 0 else "behind")
        lags = [x for s in mine if (x := lag_days(by_id[s["id"]])) is not None]
        desks.append(
            {
                "desk": origin,
                "proposals": len(mine),
                "approved": sum(1 for s in mine if s["taken"]),
                "scored_90": len(xs),
                "record_usd": round(total, 2),
                "summary_90": summarize(xs),
                "calibration": calibration(pairs),
                "lag_days_median": round(median(lags), 2) if lags else None,
                "days_on": age,
                "chip": chip,
            }
        )
    saves_rows = [s for s in scored if (not s["taken"] or s["kind"] == "hold_off") and (x := _usd(s, CAL_HORIZON)) is not None]
    saves = [(-_usd(s, CAL_HORIZON) if s["kind"] != "hold_off" else _usd(s, CAL_HORIZON)) for s in saves_rows]
    saved = [x for x in saves if x > 0]
    gap = [x for s in scored if offplan(by_id[s["id"]], targets) and (x := _usd(s, CAL_HORIZON)) is not None]
    return {
        "as_of": as_of,
        "groups": groups,
        "desks": desks,
        "saves": {"n": len(saved), "usd": round(sum(saved), 2)},
        "offplan_gap": summarize(gap),
        "decisions": [{k: v for k, v in s.items()} | {"scores": {f"{h}D": v for h, v in s["scores"].items()}} for s in scored],
        "method": "Same dollars into the plan mix from the next trading day's close; 90% bootstrap interval for the mean",
    }


# ---- Engine hook ----


def metrics(
    out, cfg: Config, tr, targets: dict[str, float], *, rate: float | None, cal: list[str], fallback: str | None, rows: list[dict] | None = None
) -> dict:
    rows = decision_rows(cfg) if rows is None else rows
    rows = [d for d in rows if d["status"] not in SKIP]
    margin_rate = cash.margin_rate(cfg)[0]
    scored = [score(d, tr, cal, targets, tz=cfg.timezone, rate=rate, margin_rate=margin_rate, fallback=fallback) for d in rows]
    for s in scored:
        for h, v in s["scores"].items():
            out.m(f"dec.score_{h}", v["usd"], "usd", scope="decision", scope_id=s["id"], window=f"{h}D", quality=v["quality"])
    card = scorecard(rows, scored, targets, out.as_of)
    for g in card["groups"]:
        out.m("dec.score_by", g["total_usd"], "usd", scope="group", scope_id=f"{g['by']}:{g['group']}", window=g["window"], n_obs=g["n"])
    for desk_row in card["desks"]:
        out.m("dec.desk_record", desk_row["record_usd"], "usd", scope="desk", scope_id=desk_row["desk"], window="90D", n_obs=desk_row["scored_90"])
        cal_ = desk_row["calibration"]
        out.m("dec.brier", cal_["brier"], "ratio", scope="desk", scope_id=desk_row["desk"], window="90D", n_obs=cal_["n"])
        out.m("dec.lag", desk_row["lag_days_median"], "days", scope="desk", scope_id=desk_row["desk"])
    lags = [x for d in rows if (x := lag_days(d)) is not None]
    out.m("dec.lag", median(lags) if lags else None, "days", n_obs=len(lags))
    gap = card["offplan_gap"]
    out.m("dec.offplan_gap", gap["total_usd"] if gap["n"] else None, "usd", window="90D", n_obs=gap["n"])
    out.m("dec.saves", card["saves"]["usd"], "usd", window="90D", n_obs=card["saves"]["n"])
    return card


def _env_float(name: str) -> float | None:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return None
