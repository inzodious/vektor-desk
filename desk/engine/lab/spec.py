import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field

from desk.engine.french import PORTFOLIO_FILES
from desk.engine.lab.data import FRENCH_KIND, FRENCH_MARKET, FUND_KINDS, PUBLIC_COVERAGE, SCREEN_KIND, SMALL_CAPS, SMALLCAP_BENCHMARK, LabData
from desk.engine.lab.library import FEATURES, TRANSFORMS, window_days
from desk.engine.market import BENCHMARKS

SETS = {
    "sector_etfs": ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"),
    "core_etfs": ("SPY", "VTI", "VXUS", "AGG", "QQQ", "IWM"),
    "benchmarks": BENCHMARKS,
}
SET_WORDS = (("sector", "sector_etfs"), ("core", "core_etfs"), ("broad", "core_etfs"), ("benchmark", "benchmarks"))
REBALANCE = {"weekly": "W", "monthly": "M", "quarterly": "Q", "w": "W", "m": "M", "q": "Q"}
SIZING = (("fixed", "fixed"), ("inverse", "inverse_vol"), ("volatility", "inverse_vol"), ("risk parity", "inverse_vol"), ("rank", "rank"), ("equal", "equal"))
MIN_WEIGHT_PRESENT = 0.5
MIN_LIVE = 0.9
PLAN_SET = "plan_mix"
HELD_SET = "held_mix"
FRENCH_TYPES = ("french", "french_portfolios", "ff")
SMALLCAP_TYPES = (SMALL_CAPS, "small_cap", "smallcaps")
MIX_SETS = {PLAN_SET: "there is no plan mix in the lab data yet", HELD_SET: "there is no held mix in the lab data yet"}
HINDSIGHT = "Today's holdings tested on the past. You chose them knowing how they had done, so this is hindsight, not evidence; a pass never goes to paper."
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
    filters: list[tuple[str, int, float | None, float | None, str | None]] = field(default_factory=list)
    weights: dict[str, float] | None = None
    start: str | None = None
    vol_target: float | None = None

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
    if isinstance(value, dict) and value.get("weights"):
        return "fixed"
    text = str(value.get("method") if isinstance(value, dict) else value).lower()
    return next((code for word, code in SIZING if word in text), "equal")


SCREEN_HINDSIGHT = "Tested on a small set of stocks that includes names you hold or held, so it leans on hindsight."
NO_PUBLIC = "the public stock list has no prices in the lab yet; the engine's public stock list job and the price backfill load it"
PUBLIC_LOADING = "the public stock list is still loading its prices: {priced} of {listed} are in and {loading} are on the way"
THIN = "That is under 90%, so this stays research only."
PUBLIC_EXITS = (
    "A company that stopped trading leaves at its last price, as in a buyout. It is counted at 30% less only when that price was under half its one-year high."
)


def public_words(cov: dict) -> str:
    listed, priced, loading = int(cov["listed"]), int(cov["priced"]), int(cov.get("loading") or 0)
    rest = listed - priced - loading
    head = f"Tested on the {listed} largest US companies of mid-{str(cov['as_of'])[:4]}, a list that owes nothing to what you hold."
    if priced >= listed:
        return f"{head} All {listed} have prices."
    parts = [f"{head} {priced} of them have prices."]
    if loading:
        parts.append(f"{loading} more are still loading.")
    if rest:
        were = "was most likely" if rest == 1 else "were mostly"
        parts.append(f"The {rest} without {were} bought or failed, so the result still leans to survivors by that much.")
    if not cov.get("enough"):
        parts.append(THIN)
    return " ".join(parts)


def _weights(value, problems: list[str]) -> dict[str, float] | None:
    raw = value.get("weights") if isinstance(value, dict) else None
    if not raw:
        return None
    try:
        out = {str(s).upper(): float(w) for s, w in raw.items() if float(w) > 0}
    except (TypeError, ValueError, AttributeError):
        problems.append('sizing weights must look like {"SPY": 60, "AGG": 40}')
        return None
    if not out:
        problems.append("sizing weights need at least one fund above zero")
        return None
    total = sum(out.values())
    return {s: w / total for s, w in out.items()}


def mix_start(data: LabData, weights: dict[str, float]) -> tuple[str | None, list[str]]:
    firsts = sorted((data.series[s].dates[0], s) for s in weights if s in data.series)
    live, start = 0.0, None
    for first, s in firsts:
        live += weights[s]
        if live >= MIN_LIVE - 1e-9:
            start = first
            break
    return start, [s for first, s in firsts if start and first > start]


def _filters(raw, data: LabData | None, problems: list[str]) -> list[tuple[str, int, float | None, float | None, str | None]]:
    out = []
    for i, f in enumerate(raw or []):
        metric = f.get("metric_id") if isinstance(f, dict) else None
        if metric not in FEATURES:
            problems.append(f"filter {i + 1}: {metric!r} is not in the feature library ({', '.join(FEATURES)})")
            continue
        try:
            days = window_days(f.get("window"))
            lo, hi = (float(f[k]) if f.get(k) is not None else None for k in ("min", "max"))
        except (TypeError, ValueError) as e:
            problems.append(f"filter {i + 1}: {e}")
            continue
        if lo is None and hi is None:
            problems.append(f"filter {i + 1}: give a min, a max or both")
            continue
        market = str(f.get("symbol") or "").upper() or None
        if market and data is not None and market not in data.series:
            problems.append(f"filter {i + 1}: {market} has no price history in the lab yet")
            continue
        out.append((metric, days, lo, hi, market))
    return out


def _vol_target(value, problems: list[str]) -> float | None:
    raw = value.get("vol_target") if isinstance(value, dict) else None
    if raw is None:
        return None
    try:
        target = float(raw)
    except (TypeError, ValueError):
        target = 0.0
    if not 0.02 <= target <= 1.0:
        problems.append("sizing vol_target must be a yearly volatility between 0.02 and 1, for example 0.15")
        return None
    return target


def cap_stocks(weights: dict[str, float], stocks: set[str], cap: float) -> tuple[dict[str, float], list[str]]:
    out, capped = dict(weights), set()
    for _ in out:
        over = [s for s in out if s in stocks and s not in capped and out[s] > cap + 1e-12]
        if not over:
            break
        capped |= set(over)
        excess = sum(out[s] - cap for s in over)
        for s in over:
            out[s] = cap
        free = [s for s in out if s not in capped]
        room = sum(out[s] for s in free)
        if not room:
            break
        for s in free:
            out[s] += excess * out[s] / room
    return out, sorted(capped)


def _universe(u: dict, data: LabData | None, problems: list[str], caveats: list[str], weights: dict[str, float] | None = None) -> dict:
    kind = str(u.get("type") or u.get("kind") or "").lower()
    if kind in ("fund_list", "funds", "etf_list", "fund_set"):
        symbols = [str(s).upper() for s in u.get("symbols") or []] or list(weights or {})
        name = u.get("set")
        if not symbols and not name:
            text = str(u.get("rule") or "").lower()
            name = next((n for w, n in SET_WORDS if w in text), None)
        if name in MIX_SETS:
            symbols = sorted(set_mix(data, name)) if data is not None else []
            if data is not None and not symbols:
                problems.append(MIX_SETS[name])
                return {}
            return {"kind": "fund_list", "symbols": symbols, "set": name}
        if name and not symbols:
            if name not in SETS:
                problems.append(f"universe set {name!r} is not one of {', '.join(SETS)}")
                return {}
            symbols = list(SETS[name])
        if not symbols:
            problems.append(f"a fund_list universe needs symbols or a set ({', '.join(SETS)})")
            return {}
        if data is not None:
            known = [s for s in symbols if weights is None or s in data.series]
            stocks = [s for s in known if data.kinds.get(s, "unknown") not in FUND_KINDS and s not in BENCHMARKS]
            if stocks:
                problems.append(f"{', '.join(stocks)} are not funds; single stocks enter only through a screen, never a hand-picked list")
        return {"kind": "fund_list", "symbols": symbols, "set": name}
    if kind in FRENCH_TYPES:
        name = str(u.get("set") or "")
        if name not in PORTFOLIO_FILES:
            problems.append(f"a french universe needs a set: {', '.join(PORTFOLIO_FILES)}")
            return {}
        if data is not None and not data.french(name):
            problems.append(f"French {name} data is not in the lab yet; the engine's monthly french job fetches it")
            return {}
        members = [str(m).lower() for m in u.get("members") or []]
        if members and data is not None and not french_members(data.french(name), members):
            problems.append(f"French {name} has no portfolio starting with {', '.join(members)}")
            return {}
        caveats.append("French portfolios are value-weighted research portfolios, not funds you can buy; a pass here is research and never goes to paper.")
        return {"kind": FRENCH_KIND, "set": name} | ({"members": members} if members else {})
    if kind == SCREEN_KIND:
        cov = data.coverage(PUBLIC_COVERAGE) if data is not None else None
        if data is not None and not (cov and cov.get("priced")):
            problems.append(NO_PUBLIC)
            return {}
        if cov and not cov.get("enough") and cov.get("loading"):
            problems.append(PUBLIC_LOADING.format(**cov))
            return {}
        if cov:
            caveats += [public_words(cov), PUBLIC_EXITS]
        return {"kind": SCREEN_KIND, "min_history_days": int(u.get("min_history_days") or 252), "min_price": float(u.get("min_price") or 5.0)}
    if kind in SMALLCAP_TYPES:
        if data is not None and not data.smallcap:
            problems.append("small-cap history is not in the lab yet; the engine's insider job builds it")
            return {}
        caveats.append(
            "Small caps are point in time from SEC share counts and prices since 2016; names come from insider filings, so firms that later vanished stay in."
        )
        return {"kind": SMALL_CAPS, "min_price": float(u.get("min_price") or 2.0)}
    problems.append('universe type must be "fund_list", "french", "screen" or "small_caps"')
    return {}


def _cap_pct(value, problems: list[str]) -> float | None:
    if value is None:
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        pct = 0.0
    if not 1 <= pct <= 100:
        problems.append("universe cap_stocks_pct must be between 1 and 100")
        return None
    return pct / 100


def local_only(raw: object, plan: bool = False) -> bool:
    if not isinstance(raw, dict):
        return False
    universe = raw.get("universe") if isinstance(raw.get("universe"), dict) else {}
    if universe.get("set") in MIX_SETS:
        return True
    own = str(universe.get("type") or universe.get("kind") or "").lower() in (*FRENCH_TYPES, *SMALLCAP_TYPES)
    return plan and not raw.get("benchmark") and not own


def set_mix(data: LabData, name: str) -> dict[str, float]:
    return data.held_mix if name == HELD_SET else data.plan_mix


def french_members(symbols: list[str], members: list[str]) -> list[str]:
    if not members:
        return symbols
    return [s for s in symbols if any(s.rsplit(".", 1)[-1].lower().startswith(m) for m in members)]


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
    weights = _weights(raw.get("sizing"), problems)
    filters = _filters(raw.get("filters"), data, problems)
    vol_target = _vol_target(raw.get("sizing"), problems)
    constraints = raw.get("constraints") or {}
    if constraints.get("margin") or constraints.get("long_only") is False:
        problems.append("the lab runs long only and never on margin")
    universe = _universe(raw.get("universe") or {}, data, problems, caveats, weights)
    if universe.get("set") in MIX_SETS:
        mix = set_mix(data, universe["set"]) if data is not None else {}
        weights = dict(mix) if mix else {s: 1.0 for s in universe["symbols"]} or None
        if weights:
            total = sum(weights.values())
            weights = {s: w / total for s, w in weights.items()}
        cap = _cap_pct((raw.get("universe") or {}).get("cap_stocks_pct"), problems)
        if cap and mix and data is not None:
            weights, trimmed = cap_stocks(weights, {s for s in weights if data.kinds.get(s, "unknown") not in FUND_KINDS}, cap)
            if trimmed:
                caveats.append(f"{', '.join(trimmed)} trimmed to {cap:.0%} each; the difference is spread across the other holdings in proportion.")
    if universe.get("set") == HELD_SET:
        caveats.append(HINDSIGHT)
        settings = data.settings if data is not None else {}
        if settings.get("held_mix_as_of"):
            caveats.append(f"Holdings as of {settings['held_mix_as_of']}.")
        left_out = 1 - float(settings.get("held_mix_covered") or 1)
        if left_out >= 0.005:
            caveats.append(f"Holdings with no market price history, about {left_out:.0%} of what is invested, are left out.")
    if weights is not None:
        if universe.get("kind") != "fund_list":
            problems.append("fixed weights need a fund_list universe")
        elif data is not None:
            missing = sorted(s for s in weights if s not in data.series)
            have = sum(w for s, w in weights.items() if s in data.series)
            if have < MIN_WEIGHT_PRESENT:
                problems.append(f"{', '.join(missing)} have no price history in the lab yet, which is most of this mix")
            elif missing:
                caveats.append(f"{', '.join(missing)} have no price history in the lab yet; the rest of the mix was scaled up to cover them.")
                weights = {s: w / have for s, w in weights.items() if s in data.series}
    start = None
    if weights is not None and data is not None and universe.get("kind") == "fund_list":
        start, late = mix_start(data, weights)
        if start and data.calendar and start > data.calendar[0]:
            caveats.append(f"Uses prices from {start} on, the first day funds making up at least {MIN_LIVE:.0%} of the mix were trading.")
        if late:
            caveats.append(f"{', '.join(late)} started trading later; until each one lists, the rest of the mix carries its share.")
    if universe.get("kind") == SCREEN_KIND and data is not None:
        start = (data.coverage(PUBLIC_COVERAGE) or {}).get("tests_from")
    if vol_target:
        caveats.append(f"Scaled down whenever its last three months ran hotter than {vol_target:.0%} a year; it never borrows to scale up.")
    fixed = weights is not None or bool(universe.get("members")) or universe.get("set") in MIX_SETS
    if not signals and not fixed:
        problems.append("at least one signal is required, unless the spec holds a fixed mix (sizing weights) or named French portfolios (members)")
    entry_raw = raw.get("entry")
    if entry_raw is None and fixed:
        entry_raw = {"top_n": len(weights or universe.get("members") or [1])}
    entry = _entry(entry_raw, params, problems)
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
        benchmark=(
            str(raw["benchmark"]).upper() if raw.get("benchmark") else {FRENCH_KIND: FRENCH_MARKET, SMALL_CAPS: SMALLCAP_BENCHMARK}.get(universe.get("kind"))
        ),
        taxable=not any(k in account for k in SHELTERED),
        model=model or str(raw.get("model") or ""),
        caveats=caveats,
        filters=filters,
        weights=weights,
        start=start,
        vol_target=vol_target,
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
