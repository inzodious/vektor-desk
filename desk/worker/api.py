import hashlib
import io
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

import desk
from desk import jobrun
from desk.config import Config
from desk.worker import BEAT_EVERY, RESULT_MAX, home, offer, registry, snapshots, store
from desk.worker.kinds import CHECK

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}
BUILD = os.environ.get("DESK_BUILD", "dev")
ERROR_MAX = 4096
_CODE: dict[str, str] = {}


# ---- The desk's own code, for the worker to run ----


def code(cfg: Config) -> tuple[str, Path]:
    folder = home(cfg) / "code"
    if _CODE.get("id") and (folder / f"{_CODE['id']}.tar.gz").is_file():
        return _CODE["id"], folder / f"{_CODE['id']}.tar.gz"
    root = Path(desk.__file__).resolve().parent
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    digest = hashlib.sha256()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=6) as tar:
        for path in files:
            data = path.read_bytes()
            name = f"desk/{path.relative_to(root).as_posix()}"
            digest.update(name.encode() + b"\0" + data)
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    code_id = digest.hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.tar.gz"):
        old.unlink(missing_ok=True)
    tmp = folder / f".{code_id}.{os.getpid()}.tmp"
    tmp.write_bytes(buffer.getvalue())
    os.replace(tmp, folder / f"{code_id}.tar.gz")
    _CODE["id"] = code_id
    return code_id, folder / f"{code_id}.tar.gz"


# ---- What the app sees ----


def ago(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "never"
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"{hours} hours ago" if hours < 48 else f"{hours // 24} days ago"


def worker_words(row: dict, now: datetime, titles: dict[str, str]) -> str:
    if row["state"] == "never":
        return f"{row['name']} has a key but hasn't checked in yet."
    if row["state"] == "asleep":
        return f"{row['name']} is asleep or off: last heard {ago(jobrun.parse_stamp(row['last_seen']), now)}."
    doing = titles.get(row.get("job_id") or "")
    return f"{row['name']} is online" + (f", working on: {doing}." if doing else ".")


def job_words(job: dict, crew: list[dict], now: datetime) -> tuple[str | None, str | None]:
    names = {w["id"]: w["name"] for w in crew}
    if job["state"] == "queued":
        online = next((w for w in crew if w["state"] == "online"), None)
        if online:
            return "queue", f"Next in line for {online['name']}."
        asleep = next((w for w in crew if w["state"] == "asleep"), None)
        if asleep:
            return "queue", f"Waiting for {asleep['name']}, which is asleep or off (last heard {ago(jobrun.parse_stamp(asleep['last_seen']), now)})."
        return "queue", "Waiting for a worker. None has checked in yet."
    if job["state"] == "leased":
        name = names.get(job["worker_id"], "a worker")
        if not any(w["id"] == job["worker_id"] and w["state"] == "online" for w in crew):
            return "queue", f"{name} went quiet while running it. It goes back in line when a worker checks in."
        return "worker", f"Running on {name}, started {ago(jobrun.parse_stamp(job['leased_at']), now)}."
    if job["state"] == "returned":
        return "here", "Back from the worker. The desk checks it and saves it within a few seconds."
    return None, job["note"] if job["state"] == "done" else job["error"]


def describe(cfg: Config, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    known = registry()
    crew = store.workers(cfg, now)
    jobs = store.recent(cfg)
    titles = {j["id"]: known[j["kind"]].title if j["kind"] in known else j["kind"] for j in jobs}
    for row in crew:
        row["words"] = worker_words(row, now, titles)
    rows = []
    for job in jobs:
        where, why = job_words(job, crew, now)
        keep = ("id", "kind", "state", "queued_at", "leased_at", "finished_at", "attempts", "seconds", "peak_mb")
        rows.append({k: job[k] for k in keep} | {"title": titles[job["id"]], "where": where, "why": why})
    best = next((w for state in ("online", "asleep", "never") for w in crew if w["state"] == state), None)
    waiting = sum(1 for j in jobs if j["state"] == "queued")
    if best is None:
        words = "No worker has joined. Everything runs on this box."
    else:
        words = best["words"] + (f" {waiting} job{'s' if waiting != 1 else ''} waiting." if waiting and best["state"] != "online" else "")
    return {
        "now": jobrun.stamp(now),
        "summary": {"state": best["state"] if best else "none", "name": best["name"] if best else None, "waiting": waiting, "words": words},
        "workers": crew,
        "jobs": rows,
    }


# ---- For him ----


@router.get("/api/workers")
def get_workers(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg), headers=NO_STORE)


@router.post("/api/workers")
def add_worker(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:  # noqa: B008
    cfg = request.app.state.cfg
    client = request.client.host if request.client else None
    try:
        made = store.add_worker(cfg, body.get("name") if isinstance(body, dict) else "")
    except OverflowError as e:
        return JSONResponse({"ok": False, "error": "too_many", "message": str(e)}, status_code=409, headers=NO_STORE)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": "bad_name", "message": str(e)}, status_code=422, headers=NO_STORE)
    jobrun.log_request(cfg, {"at": made["added_at"], "job": "worker-add", "client": client, "outcome": made["id"]})
    url = cfg.public_url.replace("://desk.", "://desk-lan.") if "://desk." in cfg.public_url else cfg.public_url
    return JSONResponse(
        {"ok": True, "message": "Copy the key now. It isn't shown again.", "desk_url": url} | made | describe(cfg), status_code=201, headers=NO_STORE
    )


@router.delete("/api/workers/{worker_id}")
def remove_worker(worker_id: str, request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    client = request.client.host if request.client else None
    if not store.ID.match(worker_id) or not store.remove_worker(cfg, worker_id):
        return JSONResponse({"ok": False, "error": "unknown_worker", "message": "There is no worker with that id."}, status_code=404, headers=NO_STORE)
    jobrun.log_request(cfg, {"at": jobrun.stamp(jobrun.now_utc()), "job": "worker-remove", "client": client, "outcome": worker_id})
    return JSONResponse({"ok": True} | describe(cfg), headers=NO_STORE)


@router.post("/api/worker/check")
def ask_check(request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    name = next((n for n in ("lab", "desk") if snapshots.sources(cfg)[n].is_file()), None)
    if name is None:
        return JSONResponse({"ok": False, "error": "no_data", "message": "There is no database to send yet."}, status_code=409, headers=NO_STORE)
    job = offer(cfg, CHECK, {}, (name,), key=None)
    return JSONResponse({"ok": True, "job": job["id"]} | describe(cfg), status_code=202, headers=NO_STORE)


# ---- For the worker ----


def caller(request: Request) -> dict:
    scheme, _, key = (request.headers.get("authorization") or "").partition(" ")
    worker = store.worker_for(request.app.state.cfg, key.strip()) if scheme.lower() == "bearer" else None
    if worker is None:
        raise HTTPException(status_code=401, detail="This worker key isn't accepted.", headers={"WWW-Authenticate": "Bearer"})
    return worker


@router.post("/api/worker/beat")
def post_beat(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:  # noqa: B008
    cfg = request.app.state.cfg
    worker = caller(request)
    store.beat(cfg, worker["id"], body if isinstance(body, dict) else {})
    return JSONResponse(
        {"ok": True, "name": worker["name"], "build": BUILD, "now": jobrun.stamp(jobrun.now_utc()), "beat_seconds": BEAT_EVERY}, headers=NO_STORE
    )


@router.get("/api/worker/next")
def get_next(request: Request) -> Response:
    cfg = request.app.state.cfg
    worker = caller(request)
    job = store.lease(cfg, worker["id"], set(registry()))
    if job is None:
        return Response(status_code=204, headers=NO_STORE)
    code_id, _ = code(cfg)
    copies = [c | {"url": f"/api/worker/snapshots/{c['sha256']}"} for c in job["snapshots"]]
    return JSONResponse(
        {
            "job": {"id": job["id"], "kind": job["kind"], "key": job["key"], "inputs": job["inputs"], "attempts": job["attempts"], "snapshots": copies},
            "code": {"id": code_id, "url": f"/api/worker/code/{code_id}"},
            "build": BUILD,
        },
        headers=NO_STORE,
    )


@router.get("/api/worker/snapshots/{sha}")
def get_snapshot(sha: str, request: Request) -> Response:
    caller(request)
    path = snapshots.path_of(request.app.state.cfg, sha)
    if path is None:
        return JSONResponse({"ok": False, "error": "gone", "message": "That database copy isn't kept any more."}, status_code=404, headers=NO_STORE)
    return FileResponse(path, media_type="application/gzip", headers=NO_STORE)


@router.get("/api/worker/code/{code_id}")
def get_code(code_id: str, request: Request) -> Response:
    caller(request)
    current, path = code(request.app.state.cfg)
    if code_id != current:
        return JSONResponse({"ok": False, "error": "gone", "message": "The desk has moved to a newer build."}, status_code=404, headers=NO_STORE)
    return FileResponse(path, media_type="application/gzip", headers=NO_STORE)


@router.post("/api/worker/jobs/{job_id}/result")
async def post_result(job_id: str, request: Request, ok: bool = True, seconds: float | None = None, peak_mb: int | None = None) -> JSONResponse:
    cfg = request.app.state.cfg
    caller(request)
    job = store.get(cfg, job_id)
    if job is None:
        return JSONResponse({"ok": False, "error": "unknown_job", "message": "There is no job with that id."}, status_code=404, headers=NO_STORE)
    if job["state"] not in ("queued", "leased"):
        return JSONResponse({"ok": True, "already": True, "state": job["state"]}, headers=NO_STORE)
    target = store.result_path(cfg, job_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    size, limit, head = 0, RESULT_MAX if ok else ERROR_MAX, b""
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return JSONResponse({"ok": False, "error": "too_big", "message": "The result is larger than the desk accepts."}, status_code=413)
                head = (head + chunk)[:ERROR_MAX] if len(head) < ERROR_MAX else head
                f.write(chunk)
        if ok and head[:2] != b"\x1f\x8b":
            return JSONResponse({"ok": False, "error": "not_gzip", "message": "A result is sent as gzip-compressed JSON."}, status_code=415, headers=NO_STORE)
        if ok:
            os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    seconds = round(seconds, 1) if seconds is not None and 0 <= seconds < 10**7 else None
    peak_mb = peak_mb if peak_mb is not None and 0 <= peak_mb < 10**7 else None
    state = store.returned(cfg, job_id, ok, seconds, peak_mb, None if ok else head.decode("utf-8", "replace"))
    if state == "returned":
        nudge(cfg)
    return JSONResponse({"ok": True, "state": state}, headers=NO_STORE)


def nudge(cfg: Config) -> None:
    folder = jobrun.requests_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(folder / "worker-apply.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    with os.fdopen(fd, "w") as f:
        json.dump({"id": None, "requested_at": jobrun.stamp(jobrun.now_utc()), "client": "worker"}, f)
