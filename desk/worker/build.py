import base64
import binascii
import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from desk import jobrun
from desk.config import Config
from desk.runlock import run_dir
from desk.worker.api import NO_STORE, ago, caller

PROTOCOL = 1
IMAGE_MAX = 3 * 2**30
KEY_MAX = 2048
SIG_MAX = 1024
ERROR_MAX = 4096
PENDING_MAX = 8
ALIVE = timedelta(seconds=180)
COMMIT = re.compile(r"^[0-9a-f]{40}$")
PRINT = re.compile(r"^[0-9a-f]{64}$")
PEM = re.compile(r"^-----BEGIN PUBLIC KEY-----\n([A-Za-z0-9+/=\n]+)-----END PUBLIC KEY-----\n?$")

router = APIRouter()

# ---- Files (the box makes this folder; the app only adds to it) ----


def folder(cfg: Config) -> Path:
    return run_dir(cfg) / "box" / "build"


def host_state(cfg: Config) -> dict:
    return jobrun._read(run_dir(cfg) / "box" / "builder.json") or {}


def approved(cfg: Config) -> dict[str, str | None]:
    rows = host_state(cfg).get("approved")
    return {str(r.get("fingerprint")): r.get("name") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}


def fingerprint(pem: str) -> str | None:
    found = PEM.match(pem.replace("\r\n", "\n")) if isinstance(pem, str) and len(pem) <= KEY_MAX else None
    if found is None:
        return None
    try:
        return hashlib.sha256(base64.b64decode(found.group(1), validate=False)).hexdigest()
    except (binascii.Error, ValueError):
        return None


def want(cfg: Config) -> dict | None:
    row = jobrun._read(folder(cfg) / "want.json")
    if not isinstance(row, dict) or not COMMIT.match(str(row.get("commit"))) or not PRINT.match(str(row.get("sha256"))):
        return None
    source = folder(cfg) / f"{row['commit']}.src.tar.gz"
    return row | {"path": source} if source.is_file() and not source.is_symlink() else None


def arrived(cfg: Config, commit: str) -> str | None:
    inbox = folder(cfg) / "in"
    if (inbox / f"{commit}.tar.gz").is_file():
        return "image"
    return "failed" if (inbox / f"{commit}.failed").is_file() else None


def alive(cfg: Config, now: datetime) -> dict | None:
    row = jobrun._read(folder(cfg) / "builder.alive")
    seen = jobrun.parse_stamp((row or {}).get("at"))
    return row | {"online": now - seen <= ALIVE} if row and seen else None


def pending(cfg: Config) -> list[dict]:
    rows = []
    known = approved(cfg)
    for path in sorted((folder(cfg) / "pending").glob("*.json")):
        row = jobrun._read(path)
        if isinstance(row, dict) and PRINT.match(str(row.get("fingerprint"))) and row["fingerprint"] not in known:
            rows.append({"fingerprint": row["fingerprint"], "name": row.get("name"), "asked_at": row.get("at")})
    return rows


def short(print_: str) -> str:
    return " ".join(print_[i : i + 4] for i in range(0, 16, 4))


# ---- What the app sees ----


def status(cfg: Config, now: datetime | None = None) -> dict:
    now = now or jobrun.now_utc()
    host = host_state(cfg)
    known = approved(cfg)
    listed = [r for r in host.get("listed") or [] if isinstance(r, dict)]
    beat = alive(cfg, now)
    asking = pending(cfg)
    wanted = want(cfg)
    last = host.get("last") if isinstance(host.get("last"), dict) else None
    builders = [
        {
            "fingerprint": fp,
            "name": name,
            "online": bool(beat and beat.get("fingerprint") == fp and beat["online"]),
            "last_seen": beat.get("at") if beat and beat.get("fingerprint") == fp else None,
        }
        for fp, name in known.items()
    ]
    waiting = [r for r in listed if not r.get("approved")]
    if builders:
        best = next((b for b in builders if b["online"]), builders[0])
        name = best["name"] or "A builder"
        if best["online"]:
            state, words = "online", f"{name} builds the desk's images, so the box doesn't have to."
        elif best["last_seen"]:
            state = "asleep"
            heard = ago(jobrun.parse_stamp(best["last_seen"]), now)
            words = f"{name} is approved to build but is asleep or off (last heard {heard}). The box builds here meanwhile."
        else:
            state, words = "asleep", f"{name} is approved to build but hasn't checked in yet. The box builds here meanwhile."
    elif waiting:
        row = waiting[0]
        who = row.get("name") or "A builder"
        state = "approve"
        if any(a["fingerprint"] == row.get("fingerprint") for a in asking):
            words = f"{who} is listed in main and has sent its key. Tap Approve builder to let it build the desk's images."
        else:
            words = f"{who} is listed in main, but its builder hasn't checked in yet. Start it on that machine, then tap Approve builder."
    elif asking:
        row = asking[0]
        state = "asking"
        words = (
            f"{row['name'] or 'A machine'} asks to build the desk's images (key {short(row['fingerprint'])}). "
            "It can once that key's fingerprint is in main's deploy/builders.txt and you tap Approve builder."
        )
    else:
        state, words = "none", "The box builds its own images, one stage at a time."
    if wanted and builders and state == "online":
        short_commit = wanted["commit"][:7]
        words += {
            None: f" It is making {short_commit} now.",
            "image": f" Its image for {short_commit} is in; the box takes it at its next check.",
            "failed": f" It couldn't build {short_commit}, so the box builds that one here at its next check.",
        }[arrived(cfg, wanted["commit"])]
    if last and last.get("commit"):
        came = "a builder" if last.get("how") == "builder" else "this box"
        words += f" The last image ({str(last['commit'])[:7]}) came from {came}" + (f": {last['why']}." if last.get("why") else ".")
    return {
        "state": state,
        "words": words,
        "builders": builders,
        "asking": asking,
        "listed": listed,
        "want": {"commit": wanted["commit"], "since": wanted.get("since"), "arrived": arrived(cfg, wanted["commit"])} if wanted else None,
        "last": last,
        "wait_seconds": host.get("wait_seconds"),
        "settle_seconds": host.get("settle_seconds"),
        "host_seen": bool(host),
    }


@router.get("/api/build")
def get_build(request: Request) -> JSONResponse:
    return JSONResponse({"now": jobrun.stamp(jobrun.now_utc())} | status(request.app.state.cfg), headers=NO_STORE)


# ---- For the builder ----


def refuse(code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error, "message": message}, status_code=code, headers=NO_STORE)


@router.post("/api/build/hello")
def hello(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:  # noqa: B008
    cfg = request.app.state.cfg
    worker = caller(request)
    now = jobrun.now_utc()
    pem = body.get("public_key") if isinstance(body, dict) else None
    mark = fingerprint(pem) if isinstance(pem, str) else None
    if mark is None:
        return refuse(422, "bad_key", "Send the builder's public key as a PEM PUBLIC KEY block.")
    base = {"ok": True, "fingerprint": mark, "protocol": PROTOCOL, "want": None}
    if mark not in approved(cfg):
        asked = folder(cfg) / "pending"
        asked.mkdir(parents=True, exist_ok=True)
        if not (asked / f"{mark}.pub").is_file():
            for old in sorted(asked.glob("*.pub"), key=lambda q: q.stat().st_mtime, reverse=True)[PENDING_MAX - 1 :]:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
        (asked / f"{mark}.pub").write_text(pem.replace("\r\n", "\n"))
        jobrun._write(asked / f"{mark}.json", {"fingerprint": mark, "name": worker["name"], "at": jobrun.stamp(now)})
        words = (
            f"This key isn't approved yet. Add the line '{mark} {worker['name']}' to deploy/builders.txt in main, then tap Approve builder in Settings, Box."
        )
        return JSONResponse(base | {"approved": False, "words": words}, headers=NO_STORE)
    building = body.get("building") if isinstance(body.get("building"), str) and COMMIT.match(body["building"]) else None
    jobrun._write(folder(cfg) / "builder.alive", {"at": jobrun.stamp(now), "fingerprint": mark, "name": worker["name"], "building": building})
    if body.get("protocol") != PROTOCOL:
        words = "This builder is older than the desk. Start it again from an updated checkout (docs/setup.md, Builds on Horizon)."
        return JSONResponse(base | {"approved": True, "words": words}, headers=NO_STORE)
    wanted = want(cfg)
    if wanted is None or arrived(cfg, wanted["commit"]):
        return JSONResponse(base | {"approved": True, "words": "Nothing to build."}, headers=NO_STORE)
    ask = {"commit": wanted["commit"], "source": f"/api/build/source/{wanted['commit']}", "sha256": wanted["sha256"], "bytes": wanted.get("bytes")}
    return JSONResponse(base | {"approved": True, "want": ask, "words": f"Build {wanted['commit'][:7]}."}, headers=NO_STORE)


@router.get("/api/build/source/{commit}")
def get_source(commit: str, request: Request) -> Response:
    caller(request)
    wanted = want(request.app.state.cfg)
    if wanted is None or commit != wanted["commit"]:
        return refuse(404, "gone", "The box isn't waiting for that commit any more.")
    return FileResponse(wanted["path"], media_type="application/gzip", headers=NO_STORE)


@router.post("/api/build/failed/{commit}")
async def post_failed(commit: str, request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    worker = caller(request)
    wanted = want(cfg)
    if wanted is None or commit != wanted["commit"]:
        return refuse(404, "gone", "The box isn't waiting for that commit any more.")
    said = (await request.body())[:ERROR_MAX].decode("utf-8", "replace")
    inbox = folder(cfg) / "in"
    inbox.mkdir(parents=True, exist_ok=True)
    jobrun._write(
        inbox / f"{commit}.failed", {"at": jobrun.stamp(jobrun.now_utc()), "name": worker["name"], "error": jobrun.plain(said) or "It gave no reason."}
    )
    return JSONResponse({"ok": True, "words": "The box builds it itself at its next check."}, headers=NO_STORE)


@router.post("/api/build/image/{commit}")
async def post_image(commit: str, request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    caller(request)
    wanted = want(cfg)
    if wanted is None or commit != wanted["commit"]:
        return refuse(404, "gone", "The box isn't waiting for that commit any more.")
    signature = (request.headers.get("x-desk-signature") or "").strip()
    claimed = (request.headers.get("x-desk-sha256") or "").strip().lower()
    try:
        signed = 0 < len(signature) <= SIG_MAX and len(base64.b64decode(signature, validate=True)) >= 64
    except (binascii.Error, ValueError):
        signed = False
    if not signed or not PRINT.match(claimed):
        return refuse(422, "unsigned", "An image comes with its SHA-256 and the builder's signature.")
    inbox = folder(cfg) / "in"
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / f"{commit}.tar.gz"
    tmp = inbox / f".{commit}.{os.getpid()}.part"
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > IMAGE_MAX:
                    return refuse(413, "too_big", "The image is larger than the desk accepts.")
                head = (head + chunk)[:2] if len(head) < 2 else head
                digest.update(chunk)
                f.write(chunk)
        if head != b"\x1f\x8b":
            return refuse(415, "not_gzip", "An image is sent as a gzip-compressed docker save.")
        if digest.hexdigest() != claimed:
            return refuse(422, "damaged", "The image didn't arrive whole: its SHA-256 doesn't match. Send it again.")
        (inbox / f"{commit}.sig").write_text(signature + "\n")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return JSONResponse({"ok": True, "bytes": size, "words": "The box checks the signature and takes it at its next 5-minute check."}, headers=NO_STORE)
