import base64
import gzip
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from desk import boxrun, jobrun
from desk.api.app import create_app
from desk.worker import build, builder, store

NOW = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER = "f" * 40

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl, like the box and the image")


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture(scope="module")
def pair(tmp_path_factory) -> tuple[Path, str]:
    return builder.key_pair(tmp_path_factory.mktemp("builder-key"))


@pytest.fixture
def client(app_client):
    return app_client(packages=["worker"])


@pytest.fixture
def horizon(client) -> dict:
    return client.post("/api/workers", json={"name": "Horizon"}).json()


def approve(cfg, mark: str, name: str = "Horizon", last: dict | None = None) -> None:
    row = {"fingerprint": mark, "name": name}
    state = {
        "checked_at": jobrun.stamp(NOW),
        "approved": [row],
        "listed": [row | {"approved": True}],
        "wait_seconds": 1200,
        "settle_seconds": 600,
        "last": last,
    }
    jobrun._write(boxrun.box_dir(cfg) / "builder.json", state)


def ask(cfg, commit: str = COMMIT, body: bytes = b"source") -> dict:
    folder = build.folder(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{commit}.src.tar.gz").write_bytes(body)
    row = {"commit": commit, "since": jobrun.stamp(NOW), "source": f"{commit}.src.tar.gz", "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    jobrun._write(folder / "want.json", row)
    return row


def signed(key: Path, commit: str, image: bytes) -> dict:
    sha = hashlib.sha256(image).hexdigest()
    return {"X-Desk-Sha256": sha, "X-Desk-Signature": builder.sign(key, builder.statement(commit, sha))}


# ---- Asking to be a builder ----


def test_a_new_builder_is_only_asking_until_the_box_says_it_is_approved(client, horizon, cfg, pair):
    key, pub = pair
    mark = builder.fingerprint(pub)
    assert client.get("/api/build").json()["state"] == "none"
    assert client.post("/api/build/hello", json={"public_key": pub}).status_code == 401
    assert client.post("/api/build/hello", json={"public_key": "ssh-ed25519 AAAA"}, headers=auth(horizon["key"])).status_code == 422
    said = client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=auth(horizon["key"])).json()
    assert said["approved"] is False and said["want"] is None and said["fingerprint"] == mark and f"'{mark} Horizon'" in said["words"]
    kept = build.folder(cfg) / "pending" / f"{mark}.pub"
    made = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(kept), "-outform", "DER"], capture_output=True, check=True)
    assert hashlib.sha256(made.stdout).hexdigest() == mark
    assert not (build.folder(cfg) / "builder.alive").exists()
    seen = client.get("/api/build").json()
    assert seen["state"] == "asking" and seen["asking"] == [{"fingerprint": mark, "name": "Horizon", "asked_at": seen["asking"][0]["asked_at"]}]
    assert seen["words"].startswith(f"Horizon asks to build the desk's images (key {mark[:4]} {mark[4:8]} {mark[8:12]} {mark[12:16]}).")
    ask(cfg)
    again = client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=auth(horizon["key"])).json()
    assert again["want"] is None and client.get(f"/api/build/source/{COMMIT}", headers=auth(horizon["key"])).status_code == 200
    listed = {"fingerprint": mark, "name": "Horizon", "approved": False}
    jobrun._write(boxrun.box_dir(cfg) / "builder.json", {"approved": [], "listed": [listed], "last": None})
    assert client.get("/api/build").json()["state"] == "approve" and "Tap Approve builder" in client.get("/api/build").json()["words"]


def test_old_pending_keys_make_room_for_a_new_one(client, horizon, cfg, pair):
    asked = build.folder(cfg) / "pending"
    asked.mkdir(parents=True)
    for i in range(build.PENDING_MAX + 3):
        (asked / f"{i:064x}.pub").write_text("x")
        os.utime(asked / f"{i:064x}.pub", (1000 + i, 1000 + i))
    assert client.post("/api/build/hello", json={"public_key": pair[1]}, headers=auth(horizon["key"])).status_code == 200
    left = sorted(p.name for p in asked.glob("*.pub"))
    assert len(left) == build.PENDING_MAX and f"{builder.fingerprint(pair[1])}.pub" in left and f"{0:064x}.pub" not in left


# ---- An approved builder ----


def test_an_approved_builder_is_told_what_to_build_and_can_fetch_the_source(client, horizon, cfg, pair):
    key, pub = pair
    mark = builder.fingerprint(pub)
    approve(cfg, mark)
    head = auth(horizon["key"])
    idle = client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=head).json()
    assert idle["approved"] is True and idle["want"] is None and idle["words"] == "Nothing to build."
    beat = jobrun._read(build.folder(cfg) / "builder.alive")
    assert beat["fingerprint"] == mark and beat["name"] == "Horizon"
    assert client.get("/api/build").json()["state"] == "online"
    row = ask(cfg)
    said = client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=head).json()
    assert said["want"] == {"commit": COMMIT, "source": f"/api/build/source/{COMMIT}", "sha256": row["sha256"], "bytes": 6}
    assert client.get(said["want"]["source"], headers=head).content == b"source"
    assert client.get(said["want"]["source"]).status_code == 401
    assert client.get(f"/api/build/source/{OTHER}", headers=head).status_code == 404
    assert client.get("/api/build/source/..%2Fwant.json", headers=head).status_code == 404
    old = client.post("/api/build/hello", json={"public_key": pub, "protocol": 0}, headers=head).json()
    assert old["want"] is None and "older than the desk" in old["words"]
    assert "It is making 0123456 now." in client.get("/api/build").json()["words"]


def test_an_image_is_kept_only_when_it_arrives_whole_signed_and_for_the_wanted_commit(client, horizon, cfg, pair):
    key, pub = pair
    approve(cfg, builder.fingerprint(pub))
    ask(cfg)
    head = auth(horizon["key"])
    image = gzip.compress(b"layers")
    good = signed(key, COMMIT, image)
    inbox = build.folder(cfg) / "in"
    assert client.post(f"/api/build/image/{COMMIT}", content=image, headers=good).status_code == 401
    assert client.post(f"/api/build/image/{OTHER}", content=image, headers=head | good).status_code == 404
    assert client.post(f"/api/build/image/{COMMIT}", content=image, headers=head).json()["error"] == "unsigned"
    assert client.post(f"/api/build/image/{COMMIT}", content=image, headers=head | good | {"X-Desk-Signature": "not base64!"}).json()["error"] == "unsigned"
    assert client.post(f"/api/build/image/{COMMIT}", content=image + b"x", headers=head | good).json()["error"] == "damaged"
    assert client.post(f"/api/build/image/{COMMIT}", content=b"plain", headers=head | signed(key, COMMIT, b"plain")).json()["error"] == "not_gzip"
    assert not inbox.exists() or list(inbox.iterdir()) == []
    res = client.post(f"/api/build/image/{COMMIT}", content=image, headers=head | good)
    assert res.status_code == 200 and res.json()["bytes"] == len(image)
    assert (inbox / f"{COMMIT}.tar.gz").read_bytes() == image and (inbox / f"{COMMIT}.sig").read_text().strip() == good["X-Desk-Signature"]
    assert sorted(p.name for p in inbox.iterdir()) == [f"{COMMIT}.sig", f"{COMMIT}.tar.gz"]
    assert client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=head).json()["want"] is None
    seen = client.get("/api/build").json()
    assert seen["want"] == {"commit": COMMIT, "since": jobrun.stamp(NOW), "arrived": "image"} and "Its image for 0123456 is in" in seen["words"]


def test_an_image_larger_than_the_limit_is_cut_off(client, horizon, cfg, pair, monkeypatch):
    key, pub = pair
    approve(cfg, builder.fingerprint(pub))
    ask(cfg)
    monkeypatch.setattr(build, "IMAGE_MAX", 64)
    image = gzip.compress(os.urandom(4096))
    res = client.post(f"/api/build/image/{COMMIT}", content=image, headers=auth(horizon["key"]) | signed(key, COMMIT, image))
    assert res.status_code == 413 and list((build.folder(cfg) / "in").iterdir()) == []


def test_a_builder_that_fails_says_so_and_the_box_stops_waiting(client, horizon, cfg, pair):
    key, pub = pair
    approve(cfg, builder.fingerprint(pub))
    ask(cfg)
    head = auth(horizon["key"])
    assert client.post(f"/api/build/failed/{OTHER}", content=b"x", headers=head).status_code == 404
    assert client.post(f"/api/build/failed/{COMMIT}", content=b"docker build stopped:\nnpm ERR!", headers=head).status_code == 200
    row = jobrun._read(build.folder(cfg) / "in" / f"{COMMIT}.failed")
    assert row["error"] == "docker build stopped: npm ERR!" and row["name"] == "Horizon"
    assert client.post("/api/build/hello", json={"public_key": pub, "protocol": 1}, headers=head).json()["want"] is None
    assert client.get("/api/build").json()["want"]["arrived"] == "failed"
    words = client.get("/api/build").json()["words"]
    assert "couldn't build 0123456, so the box builds that one here" in words and "is in;" not in words


# ---- What he sees ----


def test_the_box_block_says_who_built_the_last_image(client, cfg, pair):
    mark = builder.fingerprint(pair[1])
    assert client.get("/api/box").json()["build"]["words"] == "The box builds its own images, one stage at a time."
    approve(
        cfg,
        mark,
        last={"commit": COMMIT, "how": "box", "why": "the builder's image was refused: it isn't signed by an approved builder for this commit", "at": "x"},
    )
    seen = build.status(cfg, NOW)
    assert seen["state"] == "asleep" and seen["host_seen"] is True and seen["wait_seconds"] == 1200 and seen["settle_seconds"] == 600
    assert seen["words"] == (
        "Horizon is approved to build but hasn't checked in yet. The box builds here meanwhile. "
        "The last image (0123456) came from this box: the builder's image was refused: it isn't signed by an approved builder for this commit."
    )
    jobrun._write(build.folder(cfg) / "builder.alive", {"at": jobrun.stamp(NOW - timedelta(hours=3)), "fingerprint": mark, "name": "Horizon"})
    assert "asleep or off (last heard 3 hours ago)" in build.status(cfg, NOW)["words"]
    approve(cfg, mark, last={"commit": COMMIT, "how": "builder", "why": None, "at": "x"})
    jobrun._write(build.folder(cfg) / "builder.alive", {"at": jobrun.stamp(NOW), "fingerprint": mark, "name": "Horizon"})
    box = boxrun.describe(cfg, NOW)
    assert box["build"]["words"] == "Horizon builds the desk's images, so the box doesn't have to. The last image (0123456) came from a builder."
    assert box["build"]["builders"] == [{"fingerprint": mark, "name": "Horizon", "online": True, "last_seen": jobrun.stamp(NOW)}]
    assert "approve-builder" in [a["name"] for a in box["actions"]]


# ---- The builder itself, against a live desk and a stand-in for docker ----

FAKE_DOCKER = """#!/bin/sh
echo "$@" >>"$FAKE_LOG"
case "$1" in
  version) echo 27.0.0 ;;
  build)
    [ ! -e "$FAKE_LOG.broken" ] || { echo "npm ERR! out of luck" >&2; exit 1; }
    for last; do :; done
    cat "$last/Dockerfile" >"$FAKE_LOG.image"
    ;;
  save) cat "$FAKE_LOG.image" ;;
  rmi) : ;;
esac
"""


@pytest.fixture
def live(cfg):
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, packages=["worker"]), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def source_tar(tmp_path: Path, text: str = "FROM scratch\n") -> bytes:
    import tarfile

    root = tmp_path / "tree"
    root.mkdir(exist_ok=True)
    (root / "Dockerfile").write_text(text)
    with tarfile.open(tmp_path / "src.tar.gz", "w:gz") as tar:
        tar.add(root / "Dockerfile", arcname="Dockerfile")
    return (tmp_path / "src.tar.gz").read_bytes()


def test_the_builder_builds_signs_and_sends_what_the_box_asked_for(live, cfg, tmp_path, monkeypatch, capsys):
    fake = tmp_path / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setattr(builder, "DOCKER", str(fake))
    worker = store.add_worker(cfg, "Horizon")
    work = tmp_path / "work"
    assert builder.loop(live, worker["key"], work, rounds=1) == 0
    key = work / "builder" / "key.pem"
    pub = (work / "builder" / "key.pub").read_text()
    mark = builder.fingerprint(pub)
    assert key.stat().st_mode & 0o777 == 0o600 and (build.folder(cfg) / "pending" / f"{mark}.pub").read_text() == pub
    out = capsys.readouterr().out
    assert f"key fingerprint {mark}" in out and "isn't approved yet" in out and "PRIVATE KEY" not in out
    approve(cfg, mark)
    ask(cfg, COMMIT, source_tar(tmp_path, "FROM scratch\nLABEL made=here\n"))
    assert builder.loop(live, worker["key"], work, rounds=2, idle=0) == 0
    inbox = build.folder(cfg) / "in"
    image = (inbox / f"{COMMIT}.tar.gz").read_bytes()
    assert gzip.decompress(image) == b"FROM scratch\nLABEL made=here\n"
    said = base64.b64decode((inbox / f"{COMMIT}.sig").read_text())
    (tmp_path / "sig").write_bytes(said)
    (tmp_path / "statement").write_bytes(f"vektor-desk-image 1\ncommit {COMMIT}\nsha256 {hashlib.sha256(image).hexdigest()}\n".encode())
    (tmp_path / "pub.pem").write_text(pub)
    check = ["openssl", "dgst", "-sha256", "-verify", str(tmp_path / "pub.pem"), "-signature", str(tmp_path / "sig"), str(tmp_path / "statement")]
    assert subprocess.run(check, capture_output=True).returncode == 0
    (tmp_path / "statement").write_bytes(f"vektor-desk-image 1\ncommit {OTHER}\nsha256 {hashlib.sha256(image).hexdigest()}\n".encode())
    assert subprocess.run(check, capture_output=True).returncode != 0
    calls = log.read_text().splitlines()
    assert f"build --build-arg DESK_BUILD={COMMIT} --label vektor-desk.app=1 -t vektor-desk:built-{COMMIT} {work}/builder/src/{COMMIT}" in calls
    assert f"save vektor-desk:built-{COMMIT}" in calls and f"rmi vektor-desk:built-{COMMIT}" in calls
    assert calls.count(f"save vektor-desk:built-{COMMIT}") == 1 and not (work / "builder" / "out" / f"{COMMIT}.tar.gz").exists()
    assert "0123456 built and sent" in capsys.readouterr().out
    assert jobrun._read(build.folder(cfg) / "builder.alive")["fingerprint"] == mark


def test_a_build_that_breaks_is_reported_once_and_not_retried(live, cfg, tmp_path, monkeypatch, capsys):
    fake = tmp_path / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setattr(builder, "DOCKER", str(fake))
    (tmp_path / "docker.log.broken").touch()
    worker = store.add_worker(cfg, "Horizon")
    work = tmp_path / "work"
    key, pub = builder.key_pair(work)
    approve(cfg, builder.fingerprint(pub))
    ask(cfg, COMMIT, source_tar(tmp_path))
    assert builder.loop(live, worker["key"], work, rounds=3, idle=0) == 0
    row = jobrun._read(build.folder(cfg) / "in" / f"{COMMIT}.failed")
    assert row["error"] == "docker build stopped: npm ERR! out of luck" and not (build.folder(cfg) / "in" / f"{COMMIT}.tar.gz").exists()
    assert log.read_text().count("build --build-arg") == 1
    assert "couldn't build 0123456: docker build stopped: npm ERR! out of luck" in capsys.readouterr().out
    ask(cfg, OTHER, b"not the bytes the box named")
    want = jobrun._read(build.folder(cfg) / "want.json")
    jobrun._write(build.folder(cfg) / "want.json", want | {"sha256": "0" * 64})
    assert builder.loop(live, worker["key"], work, rounds=1) == 0
    assert "SHA-256 doesn't match" in jobrun._read(build.folder(cfg) / "in" / f"{OTHER}.failed")["error"]


def test_the_builder_says_when_it_cannot_reach_docker_or_has_no_key(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(builder, "DOCKER", str(tmp_path / "missing-docker"))
    assert builder.loop("http://127.0.0.1:9", "dwk_x", tmp_path / "work", rounds=1) == 0
    assert "can't reach Docker on this machine" in capsys.readouterr().out
    env = os.environ | {"DESK_URL": "https://desk.example", "DESK_WORKER_DIR": str(tmp_path / "empty"), "DESK_WORKER_KEY": ""}
    none = subprocess.run([sys.executable, "-m", "desk.worker", "build"], env=env, capture_output=True, text=True)
    assert none.returncode == 2 and "Start the worker first" in none.stderr
    plain = subprocess.run([sys.executable, "-m", "desk.worker", "build"], env=env | {"DESK_URL": "http://desk.example"}, capture_output=True, text=True)
    assert plain.returncode == 2 and "https://" in plain.stderr


def test_the_builder_service_is_opt_in_and_keeps_its_key_in_the_volume():
    import yaml

    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "deploy" / "worker" / "compose.yaml").read_text())["services"]
    made = services["builder"]
    assert made["profiles"] == ["builder"] and made["restart"] == "unless-stopped" and made["command"] == ["python", "-m", "desk.worker", "build"]
    assert "ports" not in made and "env_file" not in made and "privileged" not in made and made["read_only"] is True
    assert made["cap_drop"] == ["ALL"] and made["cap_add"] == ["DAC_OVERRIDE"]
    assert "${DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock" in made["volumes"] and "work:/work" in made["volumes"]
    assert not any("KEY" in name for name in made["environment"])
    assert "/var/run/docker.sock" not in json.dumps(services["worker"])
    listed = (root / "deploy" / "builders.txt").read_text().splitlines()
    assert all(line.startswith("#") or build.PRINT.match(line.split()[0]) for line in listed if line.strip())
