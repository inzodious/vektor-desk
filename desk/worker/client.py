import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import requests

from desk.worker import BEAT_EVERY, snapshots

BUILD = os.environ.get("DESK_BUILD", "dev")
KEEP_CODE = 3
IDLE = 15
COPIES = "snapshots"
WORKER_COPY = re.compile(r"^\.{0,2}[0-9a-f]{64}\.(db|gz)(\.[0-9]+\.tmp|\.part)?$")
SECRET_ENV = ("DESK_WORKER_KEY", "DESK_URL")


def say(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} worker {msg}", flush=True)


class Refused(RuntimeError):
    pass


class Desk:
    def __init__(self, url: str, key: str, session: requests.Session | None = None):
        self.url = url.rstrip("/")
        self.http = session or requests.Session()
        self.auth = {"Authorization": f"Bearer {key}"}

    def _check(self, res) -> None:
        if res.status_code == 401:
            raise Refused("the desk doesn't accept this key (was the worker removed in Settings, Box?)")
        res.raise_for_status()

    def beat(self, state: dict) -> dict:
        res = self.http.post(f"{self.url}/api/worker/beat", json=state, headers=self.auth, timeout=20)
        self._check(res)
        return res.json()

    def next(self) -> dict | None:
        res = self.http.get(f"{self.url}/api/worker/next", headers=self.auth, timeout=120)
        self._check(res)
        return res.json() if res.status_code == 200 else None

    def fetch(self, path: str, target: Path) -> None:
        tmp = target.with_name(f".{target.name}.part")
        with self.http.get(f"{self.url}{path}", headers=self.auth, timeout=120, stream=True) as res:
            self._check(res)
            with tmp.open("wb") as f:
                for chunk in res.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(tmp, target)

    def result(self, job_id: str, ok: bool, seconds: float, peak_mb: int | None, body: bytes | Path) -> dict:
        params = {"ok": "1" if ok else "0", "seconds": f"{seconds:.1f}"} | ({"peak_mb": str(peak_mb)} if peak_mb is not None else {})
        url = f"{self.url}/api/worker/jobs/{job_id}/result"
        headers = self.auth | {"Content-Type": "application/gzip" if ok else "text/plain; charset=utf-8"}
        if isinstance(body, Path):
            with body.open("rb") as f:
                res = self.http.post(url, params=params, data=f, headers=headers, timeout=300)
        else:
            res = self.http.post(url, params=params, data=body, headers=headers, timeout=60)
        self._check(res)
        return res.json()


# ---- What a job needs on disk ----


def _trim(folder: Path, keep: int = KEEP_CODE) -> None:
    rows = sorted((p for p in folder.iterdir() if not p.name.startswith(".")), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in rows[keep:]:
        shutil.rmtree(old) if old.is_dir() else old.unlink(missing_ok=True)


def only_these(in_use: list[Path]) -> list[str]:
    keep = {p.name for p in in_use}
    gone = []
    for folder in {p.parent for p in in_use if p.parent.name == COPIES}:
        try:
            found = sorted(folder.iterdir())
        except OSError:
            continue
        for path in found:
            if path.name in keep or not WORKER_COPY.match(path.name):
                continue
            try:
                path.unlink()
            except OSError:
                continue
            gone.append(path.name)
    if gone:
        say(f"removed {len(gone)} older {'copy' if len(gone) == 1 else 'copies'} of the desk's data")
    return gone


def ensure_code(desk: Desk, code: dict, work: Path) -> Path:
    folder = work / "code"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / str(code["id"])
    if not (target / "desk" / "__init__.py").is_file():
        packed = folder / f".{code['id']}.tar.gz"
        desk.fetch(code["url"], packed)
        fresh = folder / f".{code['id']}.new"
        shutil.rmtree(fresh, ignore_errors=True)
        with tarfile.open(packed, "r:gz") as tar:
            tar.extractall(fresh, filter="data")  # noqa: S202
        packed.unlink(missing_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(fresh, target)
        say(f"fetched the desk's code {code['id']}")
    os.utime(target)
    _trim(folder)
    return target


def ensure_copy(desk: Desk, copy: dict, work: Path) -> Path:
    folder = work / COPIES
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{copy['sha256']}.db"
    if not target.is_file():
        packed = folder / f".{copy['sha256']}.gz"
        desk.fetch(copy["url"], packed)
        try:
            snapshots.unpack(packed, target, copy["sha256"])
        finally:
            packed.unlink(missing_ok=True)
        target.chmod(0o444)
        say(f"fetched a copy of {copy['name']} ({copy.get('bytes', 0) / 2**20:.0f} MB)")
    os.utime(target)
    return target


# ---- One job ----


def run_job(desk: Desk, lease: dict, work: Path) -> tuple[bool, float, int | None, Path | bytes]:
    job = lease["job"]
    began = time.monotonic()
    scratch = work / "jobs" / job["id"]
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        code = ensure_code(desk, lease["code"], work)
        files = {c["name"]: str(ensure_copy(desk, c, work)) for c in job["snapshots"]}
        only_these([Path(p) for p in files.values()])
    except (OSError, ValueError, tarfile.TarError, requests.RequestException) as e:
        return False, time.monotonic() - began, None, f"The worker couldn't fetch what the job needs: {e}".encode()
    out = scratch / "result.json.gz"
    spec = scratch / "job.json"
    spec.write_text(json.dumps({"kind": job["kind"], "inputs": job["inputs"], "files": files, "out": str(out)}))
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV} | {"PYTHONPATH": str(code), "DESK_DATA_DIR": str(scratch / "data"), "HOME": str(scratch)}
    with (scratch / "stderr").open("wb") as err:
        proc = subprocess.Popen([sys.executable, "-m", "desk.worker", "run-job", str(spec)], cwd=code, env=env, stderr=err)  # noqa: S603
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
    seconds = time.monotonic() - began
    peak = int(usage.ru_maxrss / 1024) if usage.ru_maxrss else None
    if proc.returncode == 0 and out.is_file():
        return True, seconds, peak, out
    tail = (scratch / "stderr").read_bytes()[-2000:].decode("utf-8", "replace").strip().splitlines()
    why = tail[-1] if tail else f"it ended with exit code {proc.returncode}"
    if proc.returncode in (-9, 137):
        why = "the worker ran out of memory and stopped it"
    return False, seconds, peak, f"The job failed on the worker: {why}".encode()


def one(spec_path: Path) -> int:
    from desk.worker import registry

    spec = json.loads(spec_path.read_text())
    only_these([Path(path) for path in spec["files"].values()])
    kind = registry().get(spec["kind"])
    if kind is None:
        print(f"this build has no job kind called {spec['kind']}", file=sys.stderr)
        return 1
    try:
        result = kind.run(spec["inputs"], {name: Path(path) for name, path in spec["files"].items()})
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    out = Path(spec["out"])
    with gzip.open(out.with_name(out.name + ".part"), "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(result, f, allow_nan=False)
    os.replace(out.with_name(out.name + ".part"), out)
    return 0


# ---- The loop ----


def key_from(work: Path) -> str | None:
    stored = work / "key"
    given = os.environ.get("DESK_WORKER_KEY", "").strip()
    if given:
        work.mkdir(parents=True, exist_ok=True)
        fd = os.open(stored, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(given + "\n")
        return given
    try:
        return stored.read_text().strip() or None
    except OSError:
        return None


def loop(url: str, key: str, work: Path, session: requests.Session | None = None, rounds: int | None = None, idle: float = IDLE) -> int:
    desk = Desk(url, key, session)
    state = {"build": BUILD, "host": socket.gethostname(), "job_id": None, "code": None}
    stop = threading.Event()

    def beats() -> None:
        while not stop.is_set():
            try:
                desk.beat(dict(state))
            except (requests.RequestException, Refused, ValueError):
                pass
            stop.wait(BEAT_EVERY)

    work.mkdir(parents=True, exist_ok=True)
    say(f"started for {desk.url}, build {BUILD[:7]}, working in {work}")
    threading.Thread(target=beats, daemon=True).start()
    quiet = None
    done = 0
    try:
        while rounds is None or done < rounds:
            done += 1
            try:
                desk.beat(dict(state))
                lease = desk.next()
                if quiet:
                    say("the desk answers again")
                    quiet = None
            except Refused as e:
                say(str(e))
                stop.wait(idle * 8)
                continue
            except (requests.RequestException, ValueError) as e:
                if quiet != type(e).__name__:
                    say(f"can't reach the desk, trying again every {idle:g} s: {e}")
                    quiet = type(e).__name__
                stop.wait(idle)
                continue
            if lease is None:
                stop.wait(idle)
                continue
            job = lease["job"]
            state.update(job_id=job["id"], code=lease["code"]["id"])
            say(f"job {job['id']} {job['kind']} started (try {job['attempts']})")
            ok, seconds, peak, body = run_job(desk, lease, work)
            try:
                desk.result(job["id"], ok, seconds, peak, body)
                say(
                    f"job {job['id']} {'done' if ok else 'failed'} in {seconds:.1f} s"
                    + (f", peak {peak} MB" if peak else "")
                    + ("" if ok else f": {body.decode()}")
                )
            except (requests.RequestException, Refused, ValueError) as e:
                say(f"job {job['id']} finished but the result didn't reach the desk ({e}); the desk will hand it out again")
            state.update(job_id=None)
            shutil.rmtree(work / "jobs" / job["id"], ignore_errors=True)
    finally:
        stop.set()
    return 0
