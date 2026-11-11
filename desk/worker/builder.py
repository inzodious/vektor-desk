import base64
import hashlib
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import requests

from desk.worker.client import Desk, Refused

PROTOCOL = 1
IDLE = 30
KEEP_SOURCES = 2
TAIL = 1500
DOCKER = os.environ.get("DESK_DOCKER", "docker")
IMAGE = "vektor-desk"


def say(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} builder {msg}", flush=True)


class BuildFailed(RuntimeError):
    pass


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kw)  # noqa: S603


# ---- The builder's own key: made here, and the private half never leaves this machine ----


def key_pair(work: Path) -> tuple[Path, str]:
    home = work / "builder"
    home.mkdir(parents=True, exist_ok=True)
    key, pub = home / "key.pem", home / "key.pub"
    if not key.is_file():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        made = run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(key)], text=True)
        if made.returncode != 0:
            key.unlink(missing_ok=True)
            raise RuntimeError(f"openssl couldn't make the builder's key: {made.stderr.strip()[-300:]}")
        pub.unlink(missing_ok=True)
    if not pub.is_file():
        out = run(["openssl", "pkey", "-in", str(key), "-pubout"], text=True, check=True)
        pub.write_text(out.stdout)
    return key, pub.read_text()


def fingerprint(pem: str) -> str:
    body = "".join(line for line in pem.splitlines() if line and not line.startswith("-----"))
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


def statement(commit: str, sha256: str) -> bytes:
    return f"vektor-desk-image 1\ncommit {commit}\nsha256 {sha256}\n".encode()


def sign(key: Path, text: bytes) -> str:
    out = run(["openssl", "dgst", "-sha256", "-sign", str(key)], input=text, check=True)
    return base64.b64encode(out.stdout).decode()


# ---- One image ----


def sha_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_source(desk: Desk, want: dict, home: Path) -> Path:
    sources = home / "src"
    sources.mkdir(parents=True, exist_ok=True)
    target = sources / want["commit"]
    packed = sources / f".{want['commit']}.tar.gz"
    desk.fetch(want["source"], packed)
    try:
        if sha_of(packed) != want["sha256"]:
            raise BuildFailed("The source didn't arrive whole: its SHA-256 doesn't match.")
        shutil.rmtree(target, ignore_errors=True)
        with tarfile.open(packed, "r:gz") as tar:
            tar.extractall(target, filter="data")  # noqa: S202
    finally:
        packed.unlink(missing_ok=True)
    if not (target / "Dockerfile").is_file():
        raise BuildFailed("The source has no Dockerfile.")
    rows = sorted((p for p in sources.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in rows[KEEP_SOURCES:]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def build_image(source: Path, commit: str, out: Path) -> Path:
    tag = f"{IMAGE}:built-{commit}"
    made = run([DOCKER, "build", "--build-arg", f"DESK_BUILD={commit}", "--label", "vektor-desk.app=1", "-t", tag, str(source)], text=True)
    if made.returncode != 0:
        raise BuildFailed(f"docker build stopped: {(made.stderr or made.stdout).strip()[-TAIL:]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out.open("wb") as f:
            save = subprocess.Popen([DOCKER, "save", tag], stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603
            pack = subprocess.Popen(["gzip", "-1"], stdin=save.stdout, stdout=f)  # noqa: S603, S607
            save.stdout.close()
            pack.wait()
            said = save.stderr.read().decode("utf-8", "replace")
            if save.wait() != 0 or pack.returncode != 0:
                raise BuildFailed(f"docker save stopped: {said.strip()[-TAIL:]}")
    except BuildFailed:
        out.unlink(missing_ok=True)
        raise
    finally:
        run([DOCKER, "rmi", tag])
    return out


def send(desk: Desk, commit: str, image: Path, key: Path) -> dict:
    sha = sha_of(image)
    headers = desk.auth | {"Content-Type": "application/gzip", "X-Desk-Sha256": sha, "X-Desk-Signature": sign(key, statement(commit, sha))}
    with image.open("rb") as f:
        res = desk.http.post(f"{desk.url}/api/build/image/{commit}", data=f, headers=headers, timeout=1800)
    if res.status_code == 404:
        return {"ok": False, "words": "The box stopped waiting for that commit."}
    desk._check(res)
    return res.json()


def one(desk: Desk, want: dict, home: Path, key: Path) -> str:
    commit = want["commit"]
    began = time.monotonic()
    image = home / "out" / f"{commit}.tar.gz"
    try:
        source = fetch_source(desk, want, home)
        say(f"building {commit[:7]}")
        build_image(source, commit, image)
        size = image.stat().st_size
        said = send(desk, commit, image, key)
        return f"{commit[:7]} built and sent in {time.monotonic() - began:.0f} s ({size / 2**20:.0f} MB). {said.get('words', '')}".strip()
    except (BuildFailed, OSError, tarfile.TarError, subprocess.SubprocessError, requests.RequestException) as e:
        why = str(e) if isinstance(e, BuildFailed) else f"{type(e).__name__}: {e}"
        try:
            desk.http.post(f"{desk.url}/api/build/failed/{commit}", data=why.encode()[:4000], headers=desk.auth, timeout=30)
        except requests.RequestException:
            pass
        return f"couldn't build {commit[:7]}: {why}"
    finally:
        image.unlink(missing_ok=True)


# ---- The loop ----


def docker_ok() -> str | None:
    try:
        seen = run([DOCKER, "version", "--format", "{{.Server.Version}}"], text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"{type(e).__name__}: {e}"
    return None if seen.returncode == 0 else (seen.stderr.strip()[-300:] or "docker version failed")


def loop(url: str, worker_key: str, work: Path, session: requests.Session | None = None, rounds: int | None = None, idle: float = IDLE) -> int:
    desk = Desk(url, worker_key, session)
    home = work / "builder"
    key, pub = key_pair(work)
    mark = fingerprint(pub)
    say(f"key fingerprint {mark}")
    said, done, n = None, set(), 0
    while rounds is None or n < rounds:
        n += 1
        words, wait = None, idle
        try:
            trouble = docker_ok()
            if trouble:
                words = f"can't reach Docker on this machine ({trouble}); is /var/run/docker.sock mounted?"
            else:
                res = desk.http.post(f"{desk.url}/api/build/hello", json={"public_key": pub, "protocol": PROTOCOL}, headers=desk.auth, timeout=30)
                desk._check(res)
                answer = res.json()
                want = answer.get("want")
                if want and want["commit"] not in done:
                    done.add(want["commit"])
                    words, wait = one(desk, want, home, key), 0
                elif not answer.get("approved") or answer.get("protocol") != PROTOCOL:
                    words = answer.get("words")
        except Refused as e:
            words = str(e)
        except (requests.RequestException, ValueError, KeyError) as e:
            words = f"the desk isn't answering ({type(e).__name__}); trying again"
        if words and words != said:
            say(words)
        said = words
        if wait and (rounds is None or n < rounds):
            time.sleep(wait)
    return 0
