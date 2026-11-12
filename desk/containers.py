import re
from datetime import datetime, timedelta
from pathlib import Path

from desk import jobrun
from desk.config import Config
from desk.runlock import run_dir

PREFIX = "vektor-desk-"
TITLES = {
    "api": "the app",
    "cron": "the scheduler",
    "caddy": "the web server",
    "ntfy": "phone alerts",
    "tailscale": "the Tailscale link",
    "lab": "the lab",
    "eval": "the eval session",
}
CORE = ("api", "cron", "caddy", "ntfy", "tailscale")
FRESH = timedelta(minutes=15)
ALONE = 600
TAIL = 200
REPEATS = 3
UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000, "year": 31536000}
DOWN = ("stopped", "restarting", "unhealthy", "missing")
OK_SIGNS = re.compile(r"startup complete|-> running|active login|derp-\d+ connected|peerapi: serving", re.I)
ADDRESS = re.compile(r"peerapi: serving on http://(100\.\d{1,3}\.\d{1,3}\.\d{1,3})[:/]")
TROUBLE = (
    (
        "key",
        re.compile(r"invalid key|api key does not exist|auth ?key\b.*\b(expired|invalid|not valid|revoked)|unable to validate|key rejected", re.I),
        "Tailscale refused the box's sign-in key (expired, revoked or already used). Add a new auth key in Settings, then Redeploy.",
    ),
    (
        "signed_out",
        re.compile(r"needs ?login|logged out|to authenticate, visit|not logged in|login required", re.I),
        "The box is signed out of your tailnet. Add a new auth key in Settings, then Redeploy.",
    ),
    (
        "expired",
        re.compile(r"node key (has )?expired|key has expired|keyexpired", re.I),
        "The box's Tailscale key has expired. Renew it in the Tailscale admin, or add a new auth key in Settings and Redeploy.",
    ),
    (
        "device",
        re.compile(r"/dev/net/tun|tun\b.*\b(not exist|permission denied|failed)|operation not permitted", re.I),
        "Tailscale can't set up its network device on the box.",
    ),
    (
        "unreachable",
        re.compile(r"(control|bootstrapdns)\b.*\b(timeout|timed out|no such host|connection refused|unreachable)", re.I),
        "The box can't reach Tailscale's servers.",
    ),
)


# ---- What the host exported ----


def folder(cfg: Config) -> Path:
    return run_dir(cfg) / "logs"


def _text(path: Path, limit: int = 400_000) -> str | None:
    try:
        with path.open("rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def exported_at(cfg: Config) -> datetime | None:
    text = (_text(folder(cfg) / "exported_at", 64) or "").strip()
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def up_seconds(status: str) -> int | None:
    low = status.lower()
    if not low.startswith("up"):
        return None
    if "less than a second" in low:
        return 0
    found = re.search(r"up (about an?|\d+) (second|minute|hour|day|week|month|year)s?", low)
    if found is None:
        return None
    count = 1 if found.group(1).startswith("about") else int(found.group(1))
    return count * UNITS[found.group(2)]


def state_of(status: str) -> str:
    low = status.lower()
    if low.startswith("up"):
        return "unhealthy" if "(unhealthy)" in low else "starting" if "health: starting" in low else "stopped" if "(paused)" in low else "up"
    return "restarting" if low.startswith("restarting") else "stopped"


def exit_code(status: str) -> int | None:
    found = re.match(r"(?:exited|restarting) \((\d+)\)", status.lower())
    return int(found.group(1)) if found else None


def rows(cfg: Config) -> dict[str, dict] | None:
    text = _text(folder(cfg) / "containers.txt")
    if text is None:
        return None
    out: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].startswith(PREFIX):
            continue
        name, status = parts[0][len(PREFIX) :], parts[1].strip()
        if name in TITLES:
            out[name] = {"status": status[:80], "state": state_of(status), "up_seconds": up_seconds(status), "exit_code": exit_code(status)}
    return out


# ---- Why the Tailscale address stopped answering ----


def tailnet(cfg: Config) -> dict:
    text = _text(folder(cfg) / "tailscale.log")
    if text is None:
        return {"state": "unknown", "kind": None, "words": "The Tailscale log hasn't been exported yet.", "address": None, "line": None}
    lines = text.splitlines()[-TAIL:]
    address, good, hits = None, -1, []
    for i, line in enumerate(lines):
        seen = ADDRESS.search(line)
        if seen:
            address = seen.group(1)
        if OK_SIGNS.search(line):
            good = i
        for kind, pattern, words in TROUBLE:
            if pattern.search(line):
                hits.append((i, kind, words, line))
                break
    after = [h for h in hits if h[0] > good]
    blips = sum(1 for h in after if h[1] == "unreachable")
    bad = next((h for h in reversed(after) if h[1] != "unreachable" or blips >= REPEATS), None)
    if bad is not None:
        return {"state": "trouble", "kind": bad[1], "words": bad[2], "address": address, "line": jobrun.plain(bad[3])}
    if good >= 0:
        words = "Tailscale is signed in and running on the box" + (f", at {address}." if address else ".")
        return {"state": "ok", "kind": None, "words": words, "address": address, "line": None}
    return {"state": "unknown", "kind": None, "words": "The Tailscale log shows neither a sign-in nor an error.", "address": address, "line": None}


# ---- What the app sees ----


def _ago(seconds: int) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'' if n == 1 else 's'}"
    return "under a minute"


def _words(name: str, row: dict, alone: bool) -> str:
    title = TITLES[name]
    what = f"{title[0].upper()}{title[1:]}"
    state = row["state"]
    if state == "missing":
        return f"{what} has no container on the box."
    if state == "restarting":
        return f"{what} keeps stopping and starting" + (", out of memory." if row["exit_code"] == 137 else ".")
    if state == "stopped":
        return f"{what} is stopped" + (", out of memory." if row["exit_code"] == 137 else ".")
    if state == "unhealthy":
        return f"{what} is running but failing its health check."
    if state == "starting":
        return f"{what} is starting."
    ran = f" for {_ago(row['up_seconds'])}" if row["up_seconds"] is not None else ""
    return f"{what} restarted by itself {_ago(row['up_seconds'])} ago." if alone else f"{what} has been running{ran}."


def status(cfg: Config, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    at = exported_at(cfg)
    seen = rows(cfg)
    fresh = at is not None and timedelta(0) <= now - at <= FRESH
    if seen is None or at is None:
        note = "The box hasn't reported its services yet. It does every 5 minutes once the box script's cron job runs."
        return {"state": "unknown", "checked_at": None, "fresh": False, "note": note, "services": [], "tailnet": tailnet(cfg)}
    deployed = max((seen[n]["up_seconds"] for n in ("api", "cron") if n in seen and seen[n]["up_seconds"] is not None), default=None)
    services = []
    for name in TITLES:
        row = seen.get(name)
        if row is None:
            if name not in CORE:
                continue
            row = {"status": None, "state": "missing", "up_seconds": None, "exit_code": None}
        alone = row["state"] == "up" and deployed is not None and row["up_seconds"] is not None and row["up_seconds"] + ALONE < deployed
        services.append(
            {"name": name, "title": TITLES[name], "container": f"{PREFIX}{name}", **row, "restarted_alone": alone, "words": _words(name, row, alone)}
        )
    link = tailnet(cfg)
    down = [s for s in services if s["state"] in DOWN]
    shaky = [s for s in services if s["restarted_alone"]]
    if not fresh:
        state = "unknown"
        note = f"The box last reported its services {_ago(int((now - at).total_seconds()))} ago, so this may be out of date."
    elif down:
        state, note = "trouble", " ".join(s["words"] for s in down)
    elif link["state"] == "trouble":
        state, note = "trouble", f"Every service is running, but the Tailscale address isn't answering: {link['words']}"
    elif shaky:
        state, note = "ok", f"Every service is running. {' '.join(s['words'] for s in shaky)}"
    else:
        state, note = "ok", f"All {len(services)} desk services are running."
    if fresh and down and link["state"] == "trouble" and any(s["name"] == "tailscale" for s in down):
        note += f" {link['words']}"
    return {"state": state, "checked_at": jobrun.stamp(at), "fresh": fresh, "note": note, "services": services, "tailnet": link}
