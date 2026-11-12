import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from desk import jobrun, overnight
from desk.config import Config
from desk.runlock import run_dir

PROC = Path("/proc/meminfo")
ARC = Path("/proc/spl/kstat/zfs/arcstats")
CGROUP = Path("/sys/fs/cgroup")
LOW_MB = 1000
ROOMY_MB = 1500
TIGHT_MB = 1000
KILL_HOLD = timedelta(minutes=30)
MODES = ("auto", "on", "off")
PAUSED: tuple[str, ...] = ()
FRESH = timedelta(minutes=10)
HOST_FRESH = timedelta(minutes=15)
RECENT = timedelta(hours=48)
SAME_KILL = timedelta(minutes=3)
SAMPLE_EVERY = timedelta(minutes=5)
SAMPLE_SLACK = timedelta(seconds=30)
SAMPLE_KEEP = timedelta(hours=48)
SAMPLE_MAX = SAMPLE_KEEP // SAMPLE_EVERY
SAMPLE_JOBS = 12
KILLED = (-9, 137)
LOG_KEEP = 200
SERVICES = {"cron": "scheduler", "api": "app", "lab": "lab", "eval": "eval session", "caddy": "web server", "ntfy": "phone alerts", "tailscale": "tailnet"}


# ---- Reading the box ----


def _arc(path: Path | None = None) -> int | None:
    try:
        for line in (path or ARC).read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == "size":
                return int(parts[2]) // 2**20
    except (OSError, ValueError):
        return None
    return None


def meminfo(path: Path | None = None, arc: Path | None = None) -> dict | None:
    try:
        rows = {}
        for line in (path or PROC).read_text().splitlines():
            key, _, rest = line.partition(":")
            rows[key.strip()] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    if "MemTotal" not in rows or "MemAvailable" not in rows:
        return None
    return {
        "total_mb": rows["MemTotal"] // 1024,
        "available_mb": rows["MemAvailable"] // 1024,
        "swap_mb": rows.get("SwapTotal", 0) // 1024,
        "cache_mb": _arc(arc),
    }


def _number(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def cgroup(root: Path | None = None) -> dict:
    root = root or CGROUP
    limit, used = _number(root / "memory.max"), _number(root / "memory.current")
    events: dict[str, int] = {}
    try:
        for line in (root / "memory.events").read_text().splitlines():
            key, _, value = line.partition(" ")
            events[key] = int(value)
    except (OSError, ValueError):
        events = {}
    return {
        "limit_mb": limit // 2**20 if limit else None,
        "used_mb": used // 2**20 if used is not None else None,
        "oom_kills": events.get("oom_kill"),
        "cap_hits": events.get("oom"),
    }


def kill_scope(before: dict | None, after: dict | None) -> str | None:
    if not before or not after or before.get("oom_kills") is None or after.get("oom_kills") is None:
        return None
    if after["oom_kills"] <= before["oom_kills"]:
        return None
    return "cap" if (after.get("cap_hits") or 0) > (before.get("cap_hits") or 0) else "box"


def job_words(scope: str, limit_mb: int | None = None) -> str:
    if scope == "cap":
        return f"It needed more memory than the scheduler is allowed{f' ({limit_mb:,} MB)' if limit_mb else ''} and was stopped."
    return "The box ran out of memory and stopped it."


# ---- Low-memory mode ----


def mode_file(cfg: Config) -> Path:
    return run_dir(cfg) / "low-memory.mode.json"


def state_file(cfg: Config) -> Path:
    return run_dir(cfg) / "low-memory.state.json"


def waiting_file(cfg: Config) -> Path:
    return run_dir(cfg) / "waiting.json"


def history_file(cfg: Config) -> Path:
    return run_dir(cfg) / "memory-history.json"


def read_mode(cfg: Config) -> str:
    chosen = (jobrun._read(mode_file(cfg)) or {}).get("mode")
    if chosen in MODES:
        return chosen
    default = os.environ.get("DESK_LOW_MEMORY", "auto")
    return default if default in MODES else "auto"


def set_mode(cfg: Config, mode: str, client: str | None = None, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    jobrun._write(mode_file(cfg), {"mode": mode, "set_at": jobrun.stamp(now), "client": client})
    jobrun.log_request(cfg, {"at": jobrun.stamp(now), "job": "low-memory", "client": client, "outcome": mode})
    return low_memory(cfg, now, trust=False)


def decide(mode: str, available_mb: int | None, was_on: bool, stopped: bool = False) -> tuple[bool, str | None]:
    if mode == "on":
        return True, "You switched it on."
    if mode == "off":
        return False, None
    if stopped:
        return True, f"Something was stopped for memory in the last {int(KILL_HOLD.total_seconds() // 60)} minutes."
    if available_mb is None:
        return was_on, "The box's memory can't be read, so it stays on." if was_on else None
    if available_mb < LOW_MB:
        return True, f"The box has {gb(available_mb)} free, under the {gb(LOW_MB)} floor."
    if was_on and available_mb < ROOMY_MB:
        return True, f"The box has {gb(available_mb)} free. It switches itself off at {gb(ROOMY_MB)}."
    return False, None


def stopped_lately(cfg: Config, now: datetime) -> bool:
    rows = killed(cfg, now, host_report(cfg, now))
    return any(timedelta(0) <= now - jobrun.parse_stamp(e["at"]) <= KILL_HOLD for e in rows)


def low_memory(cfg: Config, now: datetime | None = None, trust: bool = True, info: dict | None = None) -> dict:
    now = now or jobrun.now_utc()
    mode = read_mode(cfg)
    last = jobrun._read(state_file(cfg)) or {}
    seen = jobrun.parse_stamp(last.get("checked_at"))
    if trust and last.get("mode") == mode and seen is not None and timedelta(0) <= now - seen <= FRESH:
        return last
    info = info or meminfo() or {}
    on, why = decide(mode, info.get("available_mb"), bool(last.get("on")), mode == "auto" and stopped_lately(cfg, now))
    since = None if not on else last.get("since") if last.get("on") and last.get("since") else jobrun.stamp(now)
    return {"on": on, "mode": mode, "why": why, "since": since, "checked_at": jobrun.stamp(now), "paused": list(PAUSED) if on else []}


def refresh(cfg: Config, now: datetime | None = None, info: dict | None = None, group: dict | None = None) -> dict:
    state = low_memory(cfg, now, trust=False, info=info)
    group = group if group is not None else cgroup()
    state["scheduler"] = {"limit_mb": group.get("limit_mb"), "used_mb": group.get("used_mb")}
    try:
        jobrun._write(state_file(cfg), state)
    except OSError:
        pass
    return state


# ---- What was stopped ----


def kills_file(cfg: Config) -> Path:
    return run_dir(cfg) / "oom.log"


def record_kill(cfg: Config, name: str, title: str, scope: str, now: datetime | None = None) -> None:
    path = kills_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text().splitlines()[-LOG_KEEP:]
    except OSError:
        lines = []
    lines.append(json.dumps({"at": jobrun.stamp(now or jobrun.now_utc()), "name": name, "title": title, "scope": scope}))
    path.write_text("\n".join(lines) + "\n")


def host_report(cfg: Config, now: datetime) -> dict | None:
    report = jobrun._read(run_dir(cfg) / "box" / "memory.json")
    seen = jobrun.parse_stamp((report or {}).get("checked_at"))
    if report is None or seen is None:
        return None
    return report | {"fresh": now - seen <= HOST_FRESH}


def _job_kills(cfg: Config) -> list[dict]:
    out = []
    try:
        lines = kills_file(cfg).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or jobrun.parse_stamp(row.get("at")) is None:
            continue
        what = str(row.get("title") or row.get("name") or "A job")
        why = "it needed more memory than the scheduler is allowed" if row.get("scope") == "cap" else "the box ran out of memory"
        out.append(
            {"at": row["at"], "kind": "job", "name": str(row.get("name") or ""), "scope": row.get("scope") or "box", "words": f"{what} was stopped: {why}."}
        )
    return out


def _host_kills(host: dict | None, jobs: list[dict]) -> list[dict]:
    out = []
    times = [jobrun.parse_stamp(j["at"]) for j in jobs]
    for row in (host or {}).get("kills") or []:
        at = jobrun.parse_stamp(row.get("at")) if isinstance(row, dict) else None
        if at is None:
            continue
        service = str(row.get("service") or "")
        if service == "cron" and any(t is not None and abs(t - at) <= SAME_KILL for t in times):
            continue
        process = jobrun.plain(str(row.get("process") or "")) or "a program"
        where = f"the desk's {SERVICES.get(service, service)}" if service else None
        if row.get("scope") == "cap" and where:
            words = f"{where[0].upper()}{where[1:]} needed more memory than it is allowed, and {process} was stopped."
        elif where:
            words = f"The box ran out of memory and stopped {process} in {where}."
        else:
            words = f"The box ran out of memory and stopped {process}, a program outside the desk."
        out.append(
            {"at": row["at"], "kind": "service" if service else "outside", "name": service or process, "scope": row.get("scope") or "box", "words": words}
        )
    return out


def killed(cfg: Config, now: datetime, host: dict | None = None) -> list[dict]:
    jobs = _job_kills(cfg)
    rows = jobs + _host_kills(host, jobs)
    recent = [e for e in rows if timedelta(0) <= now - jobrun.parse_stamp(e["at"]) <= RECENT]
    return sorted(recent, key=lambda e: jobrun.parse_stamp(e["at"]), reverse=True)[:20]


# ---- What the app sees ----


def gb(mb: int) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:,} MB"


def waiting(cfg: Config) -> list[dict]:
    rows = jobrun._read(waiting_file(cfg)) or {}
    out = [{"job": name, "title": jobrun.job_title(name), "since": row.get("since")} for name, row in rows.items() if isinstance(row, dict)]
    return sorted(out, key=lambda w: str(w["since"]))


def night_on(cfg: Config) -> bool:
    try:
        return overnight.active(cfg)
    except Exception:  # noqa: BLE001
        return False


def turns(cfg: Config) -> tuple[list[dict], list[dict]]:
    queue = waiting(cfg)
    return ([], queue) if queue and night_on(cfg) else (queue, [])


def waiting_for(cfg: Config) -> str:
    return "night" if night_on(cfg) else "memory"


def note(info: dict | None, low: dict, queue: list[dict], events: list[dict]) -> str:
    if info is None:
        words = "The box's memory can't be read from here."
    else:
        words = f"The box has {gb(info['available_mb'])} of {gb(info['total_mb'])} free" + ("" if info["swap_mb"] else ", and no swap") + "."
        if (info.get("cache_mb") or 0) >= 1024:
            words += f" Its ZFS file cache holds {gb(info['cache_mb'])}, which it hands back under pressure, but slowly."
    if low["on"]:
        words += " Low-memory mode is on: heavy jobs run one at a time."
        if low.get("paused"):
            words += f" Paused: {', '.join(SERVICES.get(p, p) for p in low['paused'])}."
    if queue:
        words += f" Waiting for a turn: {', '.join(w['title'] for w in queue[:4])}{' and more' if len(queue) > 4 else ''}."
    if events:
        words += f" Stopped for memory in the last two days: {len(events)}. Latest: {events[0]['words']}"
    return words


def status(cfg: Config, now: datetime | None = None, info: dict | None = None) -> dict:
    now = now or jobrun.now_utc()
    info = info if info is not None else meminfo()
    low = low_memory(cfg, now, info=info)
    host = host_report(cfg, now)
    events = killed(cfg, now, host)
    queue, night = turns(cfg)
    state = "unknown" if info is None else "tight" if info["available_mb"] < TIGHT_MB else "ok"
    return {
        "state": state,
        "total_mb": (info or {}).get("total_mb"),
        "available_mb": (info or {}).get("available_mb"),
        "swap_mb": (info or {}).get("swap_mb"),
        "cache_mb": (info or {}).get("cache_mb"),
        "scheduler": (jobrun._read(state_file(cfg)) or {}).get("scheduler"),
        "low_memory": {k: low.get(k) for k in ("on", "mode", "why", "since", "paused")} | {"low_mb": LOW_MB, "roomy_mb": ROOMY_MB},
        "waiting": queue,
        "queued_for_night": night,
        "killed": events,
        "host_seen": host is not None and bool(host.get("fresh")),
        "note": note(info, low, queue, events),
    }


# ---- The last two days ----


def history(cfg: Config, now: datetime | None = None) -> list[dict]:
    now = now or jobrun.now_utc()
    rows = (jobrun._read(history_file(cfg)) or {}).get("samples")
    kept = []
    for row in rows if isinstance(rows, list) else []:
        seen = jobrun.parse_stamp(row.get("at")) if isinstance(row, dict) else None
        if seen is not None and now - SAMPLE_KEEP <= seen <= now:
            kept.append(row)
    return kept[-SAMPLE_MAX:]


def sample(
    cfg: Config, now: datetime | None = None, low: bool = False, running: list[str] | None = None, info: dict | None = None, group: dict | None = None
) -> dict | None:
    now = now or jobrun.now_utc()
    rows = history(cfg, now)
    last = jobrun.parse_stamp(rows[-1]["at"]) if rows else None
    if last is not None and now - last < SAMPLE_EVERY - SAMPLE_SLACK:
        return None
    info = info if info is not None else meminfo() or {}
    group = group if group is not None else cgroup()
    row = {
        "at": jobrun.stamp(now),
        "free_mb": info.get("available_mb"),
        "cache_mb": info.get("cache_mb"),
        "scheduler_mb": group.get("used_mb"),
        "low": bool(low),
        "running": [str(name) for name in (running or [])[:SAMPLE_JOBS]],
    }
    jobrun._write(history_file(cfg), {"samples": [*rows, row][-SAMPLE_MAX:]})
    return row


def history_block(cfg: Config, now: datetime | None = None) -> dict:
    return {"every_minutes": SAMPLE_EVERY // timedelta(minutes=1), "keeps_hours": SAMPLE_KEEP // timedelta(hours=1), "samples": history(cfg, now)}


# ---- Pausing a service while the mode is on ----


def hold(command: list[str], name: str, cfg: Config, every: float = 30.0, grace: float = 20.0) -> int:
    child: subprocess.Popen | None = None
    stopping = False

    def stop(*_) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def end() -> None:
        nonlocal child
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        child = None

    paused = None
    while not stopping:
        on = bool(low_memory(cfg).get("on"))
        if on and paused is not True:
            print(f"low-memory mode is on: {name} is paused", flush=True)
            end()
        if not on and child is None:
            print(f"starting {name}" if paused is None else f"low-memory mode is off: starting {name}", flush=True)
            child = subprocess.Popen(command)  # noqa: S603
        paused = on
        waited = 0.0
        while waited < every and not stopping:
            if child is not None and child.poll() is not None:
                return child.returncode if child.returncode >= 0 else 128 - child.returncode
            time.sleep(min(1.0, every))
            waited += 1.0
    end()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(json.dumps(status(Config.from_env()), indent=2))
        return 0
    if argv == ["line"]:
        print(status(Config.from_env())["note"])
        return 0
    if argv[0] == "hold" and "--" in argv:
        split = argv.index("--")
        opts, command = argv[1:split], argv[split + 1 :]
        name = opts[opts.index("--name") + 1] if "--name" in opts[:-1] else "this service"
        cfg = Config.from_env()
        if "--data" in opts[:-1]:
            cfg = dataclasses.replace(cfg, data_dir=Path(opts[opts.index("--data") + 1]))
        if command:
            return hold(command, name, cfg)
    print("usage: python -m desk.memory [line | hold [--name NAME] [--data DIR] -- COMMAND...]", file=sys.stderr)
    return 2


# ---- API ----

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/memory")
def get_memory(request: Request, history: bool = False) -> JSONResponse:
    cfg = request.app.state.cfg
    return JSONResponse(status(cfg) | ({"history": history_block(cfg)} if history else {}), headers=NO_STORE)


@router.put("/api/memory/low")
def put_low(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:  # noqa: B008
    cfg = request.app.state.cfg
    mode = body.get("mode") if isinstance(body, dict) else None
    if mode not in MODES:
        return JSONResponse({"ok": False, "error": "bad_mode", "message": "Mode is auto, on or off."}, status_code=422, headers=NO_STORE)
    set_mode(cfg, mode, request.client.host if request.client else None)
    return JSONResponse({"ok": True} | status(cfg), headers=NO_STORE)


if __name__ == "__main__":
    sys.exit(main())
