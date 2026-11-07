import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field

from desk.engine.lab.data import FUND_KINDS, LabData
from desk.engine.lab.library import FEATURES, TRANSFORMS, window_days
from desk.engine.market import BENCHMARKS

SETS = {
    "sector_etfs": ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"),
    "core_etfs": ("SPY", "VTI", "VXUS", "AGG", "QQQ", "IWM"),
    "benchmarks": BENCHMARKS,
}
SET_WORDS = (("sector", "sector_etfs"), ("core", "core_etfs"), ("broad", "core_etfs"), ("benchmark", "benchmarks"))
REBALANCE = {"weekly": "W", "monthly": "M", "quarterly": "Q", "w": "W", "m": "M", "q": "Q"}
SIZING = (("inverse", "inverse_vol"), ("volatility", "inverse_vol"), ("risk parity", "inverse_vol"), ("rank", "rank"), ("equal", "equal"))
SHELTERED = ("hsa", "ira", "roth", "401k", "401(k)")
MAX_VARIANTS = 200


class SpecError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Spec:
    raw: dict
    id: str
    version: int
    parent_id: str | None
    title: str
    universe: dict
    signals: list[tuple[str, object, str]]
    entry: dict
    exit: dict
    rebalance: str
    sizing: str
    params: dict
    constraints: dict
    success_criteria: dict
    horizons: list[int]
    benchmark: str | None
    taxable: bool
    model: str
    caveats: list[str] = field(default_factory=list)

    @property
    def hash(self) -> str:
        return spec_hash(self.raw)


@dataclass
class Variant:
    params: dict
    top_n: int
    min_signal: float | None
    hold_rank: int | None
    windows: list[int]

    @property
    def key(self) -> str:
        return json.dumps(self.params, sort_keys=True)


def spec_hash(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---- Parsing ----


def _expr(value, params: dict, problems: list[str], what: str):
    if isinstance(value, int | float):
        return value
    text = str(value).strip()
    m = re.fullmatch(r"(?:param:)?\{?([a-z_][a-z0-9_]*)\}?", text)
    if m and m.group(1) in params:
        return f"param:{m.group(1)}"
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        problems.append(f"{what}: {value!r} is neither a number nor one of params ({', '.join(params) or 'none'})")
        return None


def _entry(entry, params, problems) -> dict:
    out = {"top_n": None, "min_signal": None}
    if isinstance(entry, dict):
        if "top_n" in entry:
            out["top_n"] = _expr(entry["top_n"], params, problems, "entry.top_n")
        if entry.get("min_signal") is not None:
            out["min_signal"] = _expr(entry["min_signal"], params, problems, "entry.min_signal")
    else:
        text = str(entry).lower()
        m = re.search(r"top\s+(\{?[a-z0-9_]+\}?)", text)
        if m:
            out["top_n"] = _expr(m.group(1), params, problems, "entry")
        if re.search(r"(above|over)\s+(zero|0)|positive|beats? cash", text):
            out["min_signal"] = 0.0
    if out["top_n"] is None:
        problems.append('entry needs a top N, for example {"top_n": 3} or "top 3 by rank"')
    return out


def _exit(exit_, params, problems) -> dict:
    if isinstance(exit_, dict):
        rank = exit_.get("hold_rank", exit_.get("rank_above"))
        return {"hold_rank": _expr(rank, params, problems, "exit.hold_rank") if rank is not None else None}
    text = str(exit_ or "").lower()
    m = re.search(r"top\s+(\{?[a-z0-9_]+\}?)", text)
    if m:
        return {"hold_rank": _expr(m.group(1), params, problems, "exit")}
    if text and "rebalance" not in text and "drops" not in text and "falls out" not in text:
        problems.append('exit must be "rebalance" or keep a holding while it stays in the top N, for example {"hold_rank": 5}')
    return {"hold_rank": None}


def _rebalance(value, problems) -> str:
    text = str(value.get("every") if isinstance(value, dict) else value).lower().strip()
    for word, code in REBALANCE.items():
        if text == word or text.startswith(word) and len(word) > 1:
            return code
    problems.append("rebalance must be weekly, monthly or quarterly")
    return "M"


def _sizing(value) -> str:
    text = str(value.get("method") if isinstance(value, dict) else value).lower()
    return next((code for word, code in SIZING if word in text), "equal")


def _universe(u: dict, data: LabData | None, problems: list[str], caveats: list[str]) -> dict:
    kind = str(u.get("type") or u.get("kind") or "").lower()
    if kind in ("fund_list", "funds", "etf_list", "fund_set"):
        symbols = [str(s).upper() for s in u.get("symbols") or []]
        name = u.get("set")
        if not symbols and not name:
            text = str(u.get("rule") or "").lower()
            name = next((n for w, n in SET_WORDS if w in text), None)
        if name and not symbols:
            if name not in SETS:
                problems.append(f"universe set {name!r} is not one of {', '.join(SETS)}")
                return {}
            symbols = list(SETS[name])
        if not symbols:
            problems.append(f"a fund_list universe needs symbols or a set ({', '.join(SETS)})")
            return {}
        if data is not None:
            stocks = [s for s in symbols if data.kinds.get(s, "unknown") not in FUND_KINDS and s not in BENCHMARKS and s not in data.plan_mix]
            if stocks:
                problems.append(f"{', '.join(stocks)} are not funds; single stocks enter only through a screen, never a hand-picked list")
        return {"kind": "fund_list", "symbols": symbols, "set": name}
    if kind == "screen":
        caveats.append("Screens run over today's backfill list, which skips companies that vanished before the backfill: survivorship bias.")
        return {"kind": "screen", "min_history_days": int(u.get("min_history_days") or 252), "min_price": float(u.get("min_price") or 5.0)}
    problems.append('universe type must be "fund_list" or "screen"')
    return {}


def parse(raw: dict, data: LabData | None = None, *, model: str = "") -> Spec:
    problems: list[str] = []
    caveats: list[str] = []
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        problems.append("params must be an object")
        params = {}
    signals = []
    for i, s in enumerate(raw.get("signals") or []):
        metric, transform = s.get("metric_id"), s.get("transform") or "rank"
        if metric not in FEATURES:
            problems.append(f"signal {i + 1}: {metric!r} is not in the feature library ({', '.join(FEATURES)})")
        if transform not in TRANSFORMS:
            problems.append(f"signal {i + 1}: transform {transform!r} is not one of {', '.join(TRANSFORMS)}")
        window = s.get("window")
        m = re.fullmatch(r"(?:param:)?\{([a-z_][a-z0-9_]*)\}(d|m|y)?", str(window))
        if m and m.group(1) in params:
            window = ("param", m.group(1), m.group(2) or "d")
        else:
            try:
                window_days(window)
            except ValueError as e:
                problems.append(f"signal {i + 1}: {e}")
        signals.append((metric, window, transform))
    if not signals:
        problems.append("at least one signal is required")
    constraints = raw.get("constraints") or {}
    if constraints.get("margin") or constraints.get("long_only") is False:
        problems.append("the lab runs long only and never on margin")
    universe = _universe(raw.get("universe") or {}, data, problems, caveats)
    entry = _entry(raw.get("entry"), params, problems)
    exit_ = _exit(raw.get("exit"), params, problems)
    rebalance = _rebalance(raw.get("rebalance") or "monthly", problems)
    horizons = [int(h) for h in raw.get("horizons") or [] if int(h) in (3, 5, 10)]
    if not horizons:
        problems.append("horizons must include 3, 5 or 10")
    account = str(raw.get("account") or "taxable").lower()
    if problems:
        raise SpecError(problems)
    return Spec(
        raw=raw,
        id=str(raw["id"]),
        version=int(raw.get("version") or 1),
        parent_id=raw.get("parent_id"),
        title=str(raw.get("title") or raw["id"]),
        universe=universe,
        signals=signals,
        entry=entry,
        exit=exit_,
        rebalance=rebalance,
        sizing=_sizing(raw.get("sizing") or "equal"),
        params=params,
        constraints={"max_position_pct": float(constraints.get("max_position_pct") or 100), "max_turnover": constraints.get("max_turnover")},
        success_criteria=raw.get("success_criteria") or {},
        horizons=sorted(set(horizons)),
        benchmark=(str(raw["benchmark"]).upper() if raw.get("benchmark") else None),
        taxable=not any(k in account for k in SHELTERED),
        model=model or str(raw.get("model") or ""),
        caveats=caveats,
    )


# ---- Variants ----


def _default(p) -> object:
    if isinstance(p, list):
        return p[0]
    if isinstance(p, dict):
        return p.get("default", p.get("min"))
    return p


def _in_range(p, v) -> bool:
    if isinstance(p, list):
        return v in p
    if isinstance(p, dict) and isinstance(v, int | float):
        return p.get("min", v) <= v <= p.get("max", v)
    return True


def resolve(spec: Spec, params: dict) -> Variant:
    def get(expr):
        if isinstance(expr, str) and expr.startswith("param:"):
            return params[expr[6:]]
        return expr

    windows = []
    for _, w, _ in spec.signals:
        if isinstance(w, tuple):
            windows.append(window_days(f"{params[w[1]]}{w[2]}"))
        else:
            windows.append(window_days(w))
    top_n = int(get(spec.entry["top_n"]))
    hold = get(spec.exit["hold_rank"])
    minimum = get(spec.entry["min_signal"])
    return Variant(dict(params), max(1, top_n), float(minimum) if minimum is not None else None, max(top_n, int(hold)) if hold is not None else None, windows)


def variants(spec: Spec, grid: dict | None, budget: int, seed: int) -> list[Variant]:
    grid = grid or {}
    problems = [f"grid key {k!r} is not in params" for k in grid if k not in spec.params]
    for k, values in grid.items():
        if k in spec.params:
            problems += [f"grid {k}={v!r} is outside the range in params" for v in values if not _in_range(spec.params[k], v)]
    if problems:
        raise SpecError(problems)
    base = {k: _default(p) for k, p in spec.params.items()}
    keys = sorted(grid)
    combos = [dict(base, **dict(zip(keys, values, strict=True))) for values in itertools.product(*(grid[k] for k in keys))] or [base]
    cap = max(1, min(budget, MAX_VARIANTS))
    if len(combos) > cap:
        combos = sorted(combos, key=lambda c: hashlib.sha256(f"{seed}:{json.dumps(c, sort_keys=True)}".encode()).hexdigest())[:cap]
    out, seen = [], set()
    for c in combos:
        try:
            v = resolve(spec, c)
        except (ValueError, KeyError, TypeError) as e:
            raise SpecError([f"params {c}: {e}"]) from None
        if v.key not in seen:
            seen.add(v.key)
            out.append(v)
    return out
