import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from desk import jobrun
from desk.config import Config
from desk.db import connect
from desk.runlock import run_dir

FIXES, NEEDS, BLOCKS = "fixes_itself", "needs_you", "blocks"
KINDS = (FIXES, NEEDS, BLOCKS)
ACCOUNTS, DAILY, BACKFILL, RESEARCH, LOOKTHROUGH = "mirror", "engine-daily", "engine-backfill", "engine-research", "engine-lookthrough"
COOLDOWN = {
    ACCOUNTS: timedelta(hours=1),
    BACKFILL: timedelta(hours=1),
    DAILY: timedelta(minutes=30),
    RESEARCH: timedelta(hours=12),
    LOOKTHROUGH: timedelta(hours=24),
}
FOLLOW = (ACCOUNTS, RESEARCH, LOOKTHROUGH)
ESCALATE = (BACKFILL,)
PATIENCE = 3
SLOW = 6
STATE = "heal.json"
CLIENT = "desk"
OLD_BUILD = "health"
COUNT = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")
STUCK = "The desk has tried {n} times and it has not cleared. Settings, Box shows why."

# ---- Words ----


def plain_day(day: str, ref: str | None = None) -> str:
    d = date.fromisoformat(day[:10])
    near = date.fromisoformat(ref[:10]) if ref else d
    return f"{d:%A}" if abs((near - d).days) < 7 else f"{d:%b} {d.day}"


def count(n: int) -> str:
    return COUNT[n] if 0 <= n < len(COUNT) else str(n)


def listed(words: list[str], most: int = 3) -> str:
    shown = list(words[:most])
    if len(words) > most:
        shown.append(f"{len(words) - most} more")
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def names(conn: sqlite3.Connection, symbols: list[str]) -> list[str]:
    known: dict[str, str] = {}
    for table, column in (("sec_tickers", "title"), ("sym_profiles", "name")):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            marks = ",".join("?" * len(symbols))
            known |= {r[0]: r[1] for r in conn.execute(f"SELECT symbol, {column} FROM {table} WHERE symbol IN ({marks})", symbols) if r[1]}
    return [known.get(s, s) for s in symbols]


# ---- Kinds ----


def kind_of(status: str, kind: str | None) -> str | None:
    if status == "ok":
        return None
    return kind if kind in KINDS else (BLOCKS if status == "fail" else NEEDS)


def counts(status: str, kind: str | None) -> bool:
    return status == "fail" or (status == "warn" and kind_of(status, kind) != FIXES)


def overall(checks: list[dict]) -> str:
    if any(c["status"] == "fail" for c in checks):
        return "fail"
    return "warn" if any(counts(c["status"], c.get("kind")) for c in checks) else "ok"


# ---- State ----


def _state_file(cfg: Config):
    return run_dir(cfg) / STATE


def read_state(cfg: Config) -> dict:
    try:
        data = json.loads(_state_file(cfg).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(cfg: Config, state: dict) -> None:
    path = _state_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


def latest(cfg: Config) -> list[dict]:
    if not cfg.desk_db.exists():
        return []
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='data_health'").fetchone():
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM data_health WHERE as_of=(SELECT max(as_of) FROM data_health) ORDER BY check_name")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _jobs() -> list:
    from desk.scheduler import all_jobs

    return all_jobs()


# ---- Ask for what fixes it ----


def run(cfg: Config, *, now: datetime | None = None, jobs: list | None = None) -> dict:
    now = now or jobrun.now_utc()
    rows = latest(cfg)
    state = read_state(cfg)
    want: dict[str, list[str]] = {}
    for r in rows:
        if r["status"] != "ok" and r.get("job"):
            want.setdefault(r["job"], []).append(r["check_name"])
    if rows and all(r.get("say") is None for r in rows):
        want.setdefault(DAILY, []).append(OLD_BUILD)
    follow = [name for name in FOLLOW if name in want and _finished_since_asked(cfg, name, state.get(name) or {})]
    if follow:
        want.setdefault(DAILY, []).extend(follow)
    for name in [n for n in state if n not in want]:
        state.pop(name)
    out: dict = {"asked": [], "waiting": {}}
    if want:
        jobs = jobs if jobs is not None else _jobs()
    for name, checks in want.items():
        s = state.get(name) or {}
        tries = int(s.get("attempts") or 0)
        wait = COOLDOWN.get(name, COOLDOWN[ACCOUNTS]) * (SLOW if tries >= PATIENCE else 1)
        asked = jobrun.parse_stamp(s.get("asked_at"))
        if asked and now < asked + wait:
            out["waiting"][name] = jobrun.stamp(asked + wait)
            continue
        code, body = jobrun.request_run(cfg, jobs, name, CLIENT, now)
        if code == 202:
            state[name] = {"asked_at": jobrun.stamp(now), "attempts": tries + 1, "checks": checks, "followed": False}
            out["asked"].append(name)
        else:
            out["waiting"][name] = body.get("error")
    if DAILY in out["asked"]:
        for name in follow:
            if name not in out["asked"]:
                state[name]["followed"] = True
    _write_state(cfg, state)
    return out


def _finished_since_asked(cfg: Config, name: str, s: dict) -> bool:
    asked = jobrun.parse_stamp(s.get("asked_at"))
    if not asked or s.get("followed"):
        return False
    last = jobrun.last_run(cfg, name) or {}
    done = jobrun.parse_stamp(last.get("finished"))
    return bool(done and done > asked and last.get("result") == "ok")


# ---- What the page reads ----


def annotate(cfg: Config, rows: list[dict]) -> list[dict]:
    state = read_state(cfg)
    out = []
    for r in rows:
        status, job = r["status"], r.get("job")
        kind = kind_of(status, r.get("kind"))
        say = r.get("say") or r.get("detail")
        s = state.get(job) if job and status != "ok" else None
        heal = None
        if s:
            tries = int(s.get("attempts") or 0)
            stuck = tries >= PATIENCE
            heal = {"job": job, "asked_at": s.get("asked_at"), "attempts": tries, "stuck": stuck}
            if stuck and (job in ESCALATE or status == "fail"):
                kind = NEEDS if kind == FIXES else kind
                say = f"{say} {STUCK.format(n=tries)}"
        out.append(
            {
                "check_name": r["check_name"],
                "status": status,
                "detail": say,
                "kind": kind,
                "counts": counts(status, kind),
                "job": job if status != "ok" else None,
                "heal": heal,
                "diagnosis": r.get("detail"),
            }
        )
    return out
