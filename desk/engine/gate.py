import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from statistics import NormalDist

PAPER_DAYS = 182
STEP_DAYS = 91
LUCK_BAR = 0.10
MIN_EVENTS = 30
MIN_OBS = 60
MIN_BAND_PTS = 1.0
FAMILY_KEYS = ("insider", "drift", "filings")
STATUS = {"eligible": "eligible", "unproven": "paper", "retired": "retired"}
VERDICT_KEYS = ("checkpoint", "as_of", "verdict", "reason", "excess_pts", "band_pts", "retire_pts", "luck", "events")
N = NormalDist()


# ---- Families and checkpoints ----


def family(strategy_id: str) -> str | None:
    head, dash, _ = str(strategy_id or "").partition("-")
    return head if dash and head in FAMILY_KEYS else None


def checkpoints(days: int) -> list[int]:
    return list(range(PAPER_DAYS, days + 1, STEP_DAYS))


def next_checkpoint(days: int) -> int:
    if days < PAPER_DAYS:
        return PAPER_DAYS
    return PAPER_DAYS + ((days - PAPER_DAYS) // STEP_DAYS + 1) * STEP_DAYS


def cut_day(started: str, checkpoint: int) -> str:
    return (date.fromisoformat(started) + timedelta(days=checkpoint)).isoformat()


# ---- Noise band ----


def measure(values: list[float | None], bench: list[float | None], family_size: int = 1) -> dict | None:
    pairs = [(v, b) for v, b in zip(values, bench, strict=True) if v and b]
    if len(pairs) < 3:
        return None
    gaps = [v1 / v0 - b1 / b0 for (v0, b0), (v1, b1) in zip(pairs, pairs[1:], strict=False)]
    n = len(gaps)
    mean = sum(gaps) / n
    sd = math.sqrt(sum((g - mean) ** 2 for g in gaps) / (n - 1))
    excess = (pairs[-1][0] / pairs[0][0] - pairs[-1][1] / pairs[0][1]) * 100
    noise = sd * math.sqrt(n) * 100
    k = max(1, int(family_size or 1))
    out = {
        "obs": n,
        "excess_pts": round(excess, 4),
        "tracking_error_pct": round(sd * math.sqrt(252) * 100, 4),
        "noise_pts": round(noise, 4),
        "family_size": k,
        "score": None,
        "band_pts": None,
        "retire_pts": None,
        "luck": None,
        "luck_alone": None,
    }
    if noise <= 1e-9:
        return out
    alone = 1 - N.cdf(excess / noise)
    return out | {
        "score": round(excess / noise, 4),
        "band_pts": round(max(MIN_BAND_PTS, N.inv_cdf((1 - LUCK_BAR) ** (1 / k)) * noise), 4),
        "retire_pts": round(-max(MIN_BAND_PTS, N.inv_cdf(1 - LUCK_BAR) * noise), 4),
        "luck": round(1 - (1 - alone) ** k, 4),
        "luck_alone": round(alone, 4),
    }


def judge(m: dict | None, events: int | None = None, bars: bool | None = None) -> tuple[str, str]:
    if m is None or m["obs"] < MIN_OBS or m["band_pts"] is None:
        return "unproven", "short_record"
    if m["excess_pts"] <= m["retire_pts"]:
        return "retired", "behind"
    if m["excess_pts"] < m["band_pts"]:
        return "unproven", "noise"
    if bars is False:
        return "unproven", "bars"
    if events is not None and events < MIN_EVENTS:
        return "unproven", "events"
    return "eligible", "ahead"


# ---- Stored verdicts ----


def verdicts(conn: sqlite3.Connection, strategy_id: str, version: int) -> list[dict]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='paper_verdicts'").fetchone() is None:
        return []
    rows = conn.execute("SELECT * FROM paper_verdicts WHERE strategy_id=? AND version=? ORDER BY checkpoint", (strategy_id, version))
    return [dict(r) for r in rows]


def settle(
    conn: sqlite3.Connection,
    strategy_id: str,
    version: int,
    started: str,
    days: list[str],
    values: list[float | None],
    bench: list[float | None],
    *,
    events: Callable[[str], int | None] | None = None,
    bars: bool | None = None,
    family_size: int = 1,
    now: datetime | None = None,
) -> dict:
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    age = (date.fromisoformat(days[-1]) - date.fromisoformat(started)).days if days else 0
    stored = {v["checkpoint"]: v for v in verdicts(conn, strategy_id, version)}
    for cp in checkpoints(age):
        if any(v["verdict"] == "retired" for v in stored.values()):
            break
        if cp in stored:
            continue
        cut = cut_day(started, cp)
        keep = [i for i, d in enumerate(days) if d <= cut]
        m = measure([values[i] for i in keep], [bench[i] for i in keep], family_size)
        count = events(cut) if events else None
        verdict, reason = judge(m, count, bars)
        row = {
            "strategy_id": strategy_id,
            "version": version,
            "checkpoint": cp,
            "as_of": cut,
            "verdict": verdict,
            "reason": reason,
            "excess_pts": m["excess_pts"] if m else None,
            "band_pts": m["band_pts"] if m else None,
            "retire_pts": m["retire_pts"] if m else None,
            "luck": m["luck"] if m else None,
            "tracking_error_pct": m["tracking_error_pct"] if m else None,
            "obs": m["obs"] if m else 0,
            "events": count,
            "family_size": max(1, int(family_size or 1)),
            "decided_at": stamp,
        }
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO paper_verdicts VALUES "
                "(:strategy_id, :version, :checkpoint, :as_of, :verdict, :reason, :excess_pts, :band_pts, :retire_pts, :luck, "
                ":tracking_error_pct, :obs, :events, :family_size, :decided_at)",
                row,
            )
        stored[cp] = row
    last = stored[max(stored)] if stored else None
    status = STATUS[last["verdict"]] if last else "paper"
    live = measure(values, bench, family_size) or {}
    upcoming = next_checkpoint(age)
    gate = {
        "luck": live.get("luck"),
        "luck_alone": live.get("luck_alone"),
        "luck_bar": LUCK_BAR,
        "family_size": max(1, int(family_size or 1)),
        "score": live.get("score"),
        "tracking_error_pct": live.get("tracking_error_pct"),
        "band_pts": live.get("band_pts"),
        "retire_pts": live.get("retire_pts"),
        "obs": live.get("obs", 0),
        "events": events(days[-1]) if events and days else None,
        "min_events": MIN_EVENTS if events else None,
        "bars": bars,
        "checkpoints": len(stored),
        "next_checkpoint": None if status == "retired" else {"day": upcoming, "on": cut_day(started, upcoming)},
        "verdict": {k: last[k] for k in VERDICT_KEYS} if last else None,
    }
    return {"status": status, "gate": gate}
