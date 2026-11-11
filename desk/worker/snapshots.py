import gzip
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from desk import jobrun
from desk.backup import _source
from desk.config import Config
from desk.worker import home

SHA = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1 << 20
AS_BYTES = frozenset({"lab"})


def sources(cfg: Config) -> dict[str, Path]:
    return {"lab": cfg.data_dir / "lab" / "data" / "lab.db", "desk": cfg.desk_db, "mirror": cfg.mirror_db}


def folder(cfg: Config) -> Path:
    return home(cfg) / "snapshots"


def path_of(cfg: Config, sha: str) -> Path | None:
    if not SHA.match(sha or ""):
        return None
    path = folder(cfg) / f"{sha}.db.gz"
    return path if path.is_file() else None


def _stat(db: Path) -> list:
    seen = []
    for path in (db, db.with_name(db.name + "-wal")):
        try:
            st = path.stat()
            seen.append([st.st_size, st.st_mtime_ns, st.st_ino])
        except OSError:
            seen.append(None)
    return seen


def take(cfg: Config, name: str) -> dict:
    db = sources(cfg).get(name)
    if db is None or not db.is_file():
        raise FileNotFoundError(f"There is no {name} database to copy yet.")
    out = folder(cfg)
    out.mkdir(parents=True, exist_ok=True)
    index = out / f"{name}.latest.json"
    stat = _stat(db)
    last = jobrun._read(index) or {}
    if last.get("stat") == stat and path_of(cfg, str(last.get("sha256"))):
        return {"name": name, "sha256": last["sha256"], "bytes": last["bytes"]}
    raw = out / f".{name}.{os.getpid()}.db"
    packed = out / f".{name}.{os.getpid()}.gz"
    try:
        if name in AS_BYTES:
            source = db
        else:
            source = raw
            src = _source(db)
            dst = sqlite3.connect(raw)
            try:
                src.backup(dst, pages=4096)
            finally:
                dst.close()
                src.close()
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as f, gzip.open(packed, "wb", compresslevel=1) as z:
            while chunk := f.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
                z.write(chunk)
        sha = digest.hexdigest()
        os.replace(packed, out / f"{sha}.db.gz")
    finally:
        raw.unlink(missing_ok=True)
        packed.unlink(missing_ok=True)
    jobrun._write(index, {"stat": stat, "sha256": sha, "bytes": size, "taken_at": jobrun.stamp(jobrun.now_utc())})
    return {"name": name, "sha256": sha, "bytes": size}


def prune(cfg: Config, keep: set[str]) -> list[str]:
    out = folder(cfg)
    latest = set()
    for index in out.glob("*.latest.json") if out.is_dir() else []:
        try:
            latest.add(str(json.loads(index.read_text()).get("sha256")))
        except (OSError, ValueError):
            continue
    gone = []
    for path in sorted(out.glob("*.db.gz")) if out.is_dir() else []:
        sha = path.name.removesuffix(".db.gz")
        if sha not in keep and sha not in latest:
            path.unlink(missing_ok=True)
            gone.append(sha)
    return gone


def unpack(packed: Path, target: Path, sha: str) -> None:
    digest = hashlib.sha256()
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with gzip.open(packed, "rb") as z, tmp.open("wb") as f:
            while chunk := z.read(CHUNK):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != sha:
            raise ValueError("The database copy didn't match its fingerprint after the download.")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def current(cfg: Config, copy: dict) -> bool:
    try:
        return take(cfg, str(copy.get("name")))["sha256"] == copy.get("sha256")
    except (OSError, sqlite3.Error):
        return False
