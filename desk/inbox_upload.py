import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk.config import Config
from desk.jobrun import stamp

BROKERS = {"fidelity": "engine-lots"}
SUFFIXES = (".json", ".csv")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,118}$")


def max_bytes() -> int:
    try:
        mb = int(os.environ.get("DESK_INBOX_MAX_MB", "25"))
    except ValueError:
        mb = 25
    return max(1, min(mb, 200)) * 1024 * 1024


class Refused(Exception):
    def __init__(self, code: int, error: str, message: str):
        super().__init__(message)
        self.code, self.error, self.message = code, error, message


# ---- Checks ----


def clean_name(name: str) -> str:
    name = name.strip()
    if not NAME.match(name) or ".." in name or not name.lower().endswith(SUFFIXES):
        raise Refused(400, "bad_name", "Use a plain file name ending in .json or .csv (letters, numbers, spaces, . _ - ( ) only).")
    return name


def check_content(name: str, raw: bytes) -> None:
    if not raw:
        raise Refused(400, "empty", "The file is empty.")
    if b"\x00" in raw:
        raise Refused(400, "not_text", "That isn't a text export.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refused(400, "not_text", "That isn't UTF-8 text; export it again as CSV or JSON.") from None
    if name.lower().endswith(".json"):
        try:
            json.loads(text)
        except ValueError:
            raise Refused(400, "bad_json", "That .json file doesn't parse as JSON.") from None
    elif "," not in text.split("\n", 1)[0] and "\t" not in text.split("\n", 1)[0]:
        raise Refused(400, "bad_csv", "That .csv file has no comma-separated header line.")


# ---- Store ----


def folder_for(cfg: Config, broker: str) -> Path:
    if broker not in BROKERS:
        raise Refused(404, "unknown_broker", f"Uploads go to {', '.join(sorted(BROKERS))} only.")
    return cfg.inbox / broker


def store(cfg: Config, broker: str, name: str, raw: bytes) -> dict:
    folder = folder_for(cfg, broker)
    name = clean_name(name)
    check_content(name, raw)
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    for existing in folder.iterdir():
        if (
            existing.is_file()
            and not existing.is_symlink()
            and existing.stat().st_size == len(raw)
            and hashlib.sha256(existing.read_bytes()).hexdigest() == digest
        ):
            return {"ok": True, "broker": broker, "name": existing.name, "size": len(raw), "sha256": digest, "duplicate": True, "import_job": BROKERS[broker]}
    tmp = folder / f".upload-{secrets.token_hex(6)}.part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    stem, dot, ext = name.rpartition(".")
    try:
        for n in range(1, 100):
            final = folder / (name if n == 1 else f"{stem}-{n}{dot}{ext}")
            try:
                os.link(tmp, final)
                break
            except FileExistsError:
                continue
        else:
            raise Refused(409, "too_many", f"There are already 99 files called {name}.")
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "broker": broker, "name": final.name, "size": len(raw), "sha256": digest, "duplicate": False, "import_job": BROKERS[broker]}


def listing(cfg: Config) -> dict:
    out = {}
    for broker, job in BROKERS.items():
        folder = cfg.inbox / broker
        files = []
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUFFIXES and not p.name.startswith("."):
                st = p.stat()
                files.append({"name": p.name, "size": st.st_size, "modified": stamp(datetime.fromtimestamp(st.st_mtime, UTC))})
        out[broker] = {"import_job": job, "files": files}
    return {"max_bytes": max_bytes(), "suffixes": list(SUFFIXES), "brokers": out}


def log_upload(cfg: Config, entry: dict) -> None:
    path = cfg.data_dir / "run" / "inbox-uploads.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


# ---- API ----

router = APIRouter()


@router.get("/api/inbox")
def get_inbox(request: Request) -> JSONResponse:
    return JSONResponse(listing(request.app.state.cfg), headers={"Cache-Control": "no-store"})


@router.put("/api/inbox/{broker}/{name}")
async def put_file(broker: str, name: str, request: Request) -> JSONResponse:
    cfg = request.app.state.cfg
    client = request.client.host if request.client else None
    limit = max_bytes()
    entry = {"at": stamp(datetime.now(UTC)), "broker": broker[:32], "name": name[:120], "client": client}
    try:
        folder_for(cfg, broker)
        clean_name(name)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise Refused(413, "too_large", f"Files up to {limit // (1024 * 1024)} MB.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise Refused(413, "too_large", f"Files up to {limit // (1024 * 1024)} MB.")
            chunks.append(chunk)
        body = store(cfg, broker, name, b"".join(chunks))
    except Refused as e:
        log_upload(cfg, entry | {"outcome": e.error})
        return JSONResponse({"ok": False, "error": e.error, "message": e.message}, status_code=e.code)
    log_upload(
        cfg, entry | {"outcome": "duplicate" if body["duplicate"] else "stored", "stored_as": body["name"], "size": body["size"], "sha256": body["sha256"]}
    )
    return JSONResponse(body, status_code=200 if body["duplicate"] else 201)
