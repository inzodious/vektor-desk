import re

PROSE = ("title", "thesis", "bear_case", "invalidation", "horizon", "rule_served")
UNITS = r"(?=\s?(?:%|percent\b|pts\b|points\b|pp\b))"
PERCENT = re.compile(r"(?<![\w.])(-?\d[\d,]*)\.(\d{2,})" + UNITS)
WHOLE = re.compile(r"(?<![\w.])(-?\d[\d,]*)\.0" + UNITS)
DOLLARS = re.compile(r"\$(\d[\d,]*)\.(\d+)(?![\d])")
LONG = re.compile(r"(?<![\w.$,])(-?\d+)\.(\d{3,})(?!\d|\.\d)")
BIG = 1000
SLUG_MAX = 40
BUYS = ("buy", "deposit_route")
SELLS = ("sell", "trim", "harvest")


def _number(whole: str, frac: str) -> float:
    return float(f"{whole.replace(',', '')}.{frac}")


def _percent(m: re.Match) -> str:
    out = f"{_number(m.group(1), m.group(2)):,.1f}"
    return out[:-2] if out.endswith(".0") else out


def _dollars(m: re.Match) -> str:
    value = _number(m.group(1), m.group(2))
    if value >= BIG:
        return f"${value:,.0f}"
    return m.group(0) if len(m.group(2)) <= 2 else f"${value:,.2f}"


def tidy(text: object) -> object:
    if not isinstance(text, str) or not text:
        return text
    out = DOLLARS.sub(_dollars, text)
    out = PERCENT.sub(_percent, out)
    out = WHOLE.sub(lambda m: m.group(1), out)
    return LONG.sub(lambda m: f"{_number(m.group(1), m.group(2)):.2f}", out)


def tidy_proposal(p: dict) -> dict:
    return p | {k: tidy(p[k]) for k in PROSE if isinstance(p.get(k), str)}


def slug(text: object) -> str:
    words = re.sub(r"[^a-z]+", "-", str(text or "").lower()).strip("-")
    return words[:SLUG_MAX].strip("-")


def subject_for(desk: str, p: dict) -> str:
    kind = str(p.get("kind") or "memo")
    symbol = str(p.get("symbol") or "").strip().upper()
    words = f"{p.get('title') or ''} {p.get('rule_served') or ''}".lower()
    if desk == "plan_keeper" and kind == "hold_off" and "margin" in words:
        return "margin"
    if desk == "plan_keeper" and kind == "deposit_route":
        return "next-deposit"
    if symbol and kind in BUYS:
        return f"buy:{symbol}"
    if symbol and kind in SELLS:
        return f"sell:{symbol}"
    if symbol and kind in ("rebalance", "hold_off"):
        return f"{kind}:{symbol}"
    rule = slug(p.get("rule_served"))
    if kind == "alert":
        return f"rule:{rule or symbol.lower() or slug(p.get('title')) or 'general'}"
    return f"{kind}:{rule or symbol.lower() or slug(p.get('title')) or 'general'}"


def stamp(p: dict, desk: str, slice_: dict) -> dict:
    day = str(slice_.get("data_as_of") or slice_.get("as_of") or "")[:10]
    out = tidy_proposal(p) | {"subject": subject_for(desk, p)}
    return out | {"as_of": day} if day else out
