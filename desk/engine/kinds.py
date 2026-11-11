import json
import sqlite3
from datetime import UTC, datetime

from desk.config import Config
from desk.db import connect
from desk.engine.lab import runner, simcache
from desk.engine.lab.data import data_path, ledger_path
from desk.worker import Kind, offer, online

# ---- Lab simulations on a worker ----


def run(inputs: dict, files: dict) -> dict:
    return runner.sims(files["lab"], inputs)


def accept(cfg: Config, job: dict, path) -> str:
    out = simcache.stage_file(cfg, path)
    if not out.get("ok"):
        raise ValueError(out.get("error") or "the lab refused it")
    return "Handed to the lab, which checks it before using it."


KINDS = [Kind(simcache.KIND, "Lab simulations", run, accept)]


# ---- Offering queued experiments (engine side: after lab-export, then each minute of the lab hours) ----


def waiting(cfg: Config) -> list[tuple[str, dict]]:
    folder = simcache.queue_dir(cfg)
    done: set[str] = set()
    if ledger_path(cfg).exists():
        conn = connect(ledger_path(cfg), readonly=True)
        try:
            done = {r[0] for r in conn.execute("SELECT file FROM queue_done")}
        except sqlite3.Error:
            done = set()
        finally:
            conn.close()
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if path.name in done:
            continue
        try:
            request = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(request, dict) and request.get("request") == "experiment":
            out.append((path.name, request))
    return out


def offer_queue(cfg: Config, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        if not online(cfg, now):
            return {"offered": 0, "note": "No worker is online, so the lab runs its queue itself."}
        if not data_path(cfg).exists():
            return {"offered": 0}
        snapshot = simcache.snapshot_hash(data_path(cfg))
        before = simcache.read_offers(cfg)
        kept = before["files"] if before.get("snapshot") == snapshot else {}
        files, fresh = {}, 0
        for name, request in waiting(cfg):
            key = simcache.job_key(snapshot, request)
            old = kept.get(name)
            if isinstance(old, dict) and old.get("key") == key and old.get("at"):
                files[name] = old
                continue
            offer(cfg, simcache.KIND, request, ("lab",), key=key)
            files[name] = {"key": key, "at": now.isoformat(timespec="seconds")}
            fresh += 1
        simcache.write_offers(cfg, snapshot, files, now)
    except (OSError, sqlite3.Error, ValueError) as e:
        return {"offered": 0, "error": f"{e.__class__.__name__}: {e}"[:200]}
    return {"offered": fresh, "wait_minutes": simcache.wait_minutes()}
