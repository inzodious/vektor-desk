import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from desk import boxkeys, boxrun
from desk.config import Config

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

host_only = pytest.mark.skipif(
    any(shutil.which(t) is None for t in ("bash", "jq", "openssl")) or os.geteuid() != 0, reason="needs bash, jq, openssl and root, like the box"
)

PAPER_ID = "PK" + "TEST" * 4
SECRET = "synthetic-" + "s3cr3t" * 4


def ready(cfg: Config) -> rsa.RSAPrivateKey:
    folder = boxrun.box_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    (folder / "keys.pub").write_bytes(pem)
    (folder / "host.alive").write_text(boxrun.stamp(boxrun.now_utc()))
    return private


def test_keys_are_listed_without_values_and_refused_when_unsafe(client, cfg):
    assert client.put("/api/box/keys/TIINGO_API_KEY", json={"value": SECRET}).json()["error"] == "host_down"
    ready(cfg)
    assert client.put("/api/box/keys/NOT_A_DESK_KEY", json={"value": "x"}).status_code == 404
    assert client.put("/api/box/keys/LD_PRELOAD", json={"value": "/x.so"}).status_code == 400
    assert client.put("/api/box/keys/lower", json={"value": "x"}).status_code == 400
    live = client.put("/api/box/keys/ALPACA_API_KEY_ID", json={"value": "AK" + "LIVE" * 4})
    assert live.status_code == 400 and "paper" in live.json()["message"]
    assert client.put("/api/box/keys/TIINGO_API_KEY", json={"value": "a\nB=1"}).status_code == 400
    assert client.put("/api/box/keys/TIINGO_API_KEY", json={"value": ""}).status_code == 400
    assert client.put("/api/box/keys/TIINGO_API_KEY", content=b"not json").json()["error"] == "bad_body"
    body = client.get("/api/box/keys").json()
    assert body["ready"] is True and body["host_alive"] is True
    row = next(r for r in body["keys"] if r["name"] == "ALPACA_API_KEY_ID")
    assert row == {"name": "ALPACA_API_KEY_ID", "file": "desk.env", "secret": True, "what": row["what"], "set": False, "pending": False, "last": None}


def test_a_saved_key_is_sealed_for_the_host_and_never_readable_back(client, cfg):
    private = ready(cfg)
    ok = client.put("/api/box/keys/TIINGO_API_KEY", json={"value": f"  {SECRET}  "})
    assert ok.status_code == 202 and ok.json()["request_id"]
    req = boxkeys.keys_dir(cfg) / "TIINGO_API_KEY.req"
    assert oct(req.stat().st_mode & 0o777) == "0o600"
    raw = req.read_text()
    assert SECRET not in raw
    sealed = json.loads(raw)["ciphertext"]
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    assert private.decrypt(base64.b64decode(sealed), oaep).decode() == SECRET
    listing = client.get("/api/box/keys").text
    assert SECRET not in listing and json.loads(listing)["keys"][2]["pending"] is True
    log = (cfg.data_dir / "run" / "box-requests.log").read_text()
    assert SECRET not in log and '"key": "TIINGO_API_KEY"' in log


def host(root: Path) -> subprocess.CompletedProcess:
    env = {"DESK_ROOT": str(root), "DESK_SELF": "/bin/true", "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        ["bash", "-c", f'source "{DEPLOY}"; LOG={root}/deploy.log; dir=$(box_dir) && box_keys "$dir"'], capture_output=True, text=True, env=env, timeout=60
    )


@host_only
def test_host_makes_its_key_then_saves_sealed_values_and_queues_a_redeploy(tmp_path):
    root = tmp_path / "app"
    (root / "data" / "run").mkdir(parents=True)
    (root / "desk.env").write_text("TIINGO_API_KEY=old\nFRED_API_KEY=keepme\n")
    (root / "settings.env").write_text("DESK_UID=user-1\n")
    assert host(root).returncode == 0
    pem = root / "box-keys.pem"
    assert oct(pem.stat().st_mode & 0o777) == "0o600"
    cfg = Config(data_dir=root / "data", project="demo-project", uid="user-1", claude_token_expires="2027-11-01")
    assert boxkeys.public_key(cfg) is not None
    names = {r["name"] for r in json.loads((boxrun.box_dir(cfg) / "keys.json").read_text())["present"]}
    assert names == {"TIINGO_API_KEY", "FRED_API_KEY", "DESK_UID"}
    (boxrun.box_dir(cfg) / "host.alive").write_text(boxrun.stamp(boxrun.now_utc()))
    assert boxkeys.request_key(cfg, "TIINGO_API_KEY", SECRET)[0] == 202
    assert boxkeys.request_key(cfg, "DESK_SEC_USER_AGENT", "Vektor Desk someone@example.com")[0] == 202
    key = boxkeys.public_key(cfg)
    folder = boxkeys.keys_dir(cfg)
    (folder / "ALPACA_API_KEY_ID.req").write_text(json.dumps({"id": "abc", "ciphertext": boxkeys.seal(key, "AK" + "LIVE" * 4)}))
    (folder / "PATH.req").write_text(json.dumps({"id": "abd", "ciphertext": boxkeys.seal(key, "/tmp")}))
    res = host(root)
    assert res.returncode == 0, res.stderr
    env = (root / "desk.env").read_text()
    assert f"TIINGO_API_KEY={SECRET}" in env and "FRED_API_KEY=keepme" in env and "TIINGO_API_KEY=old" not in env
    assert "DESK_SEC_USER_AGENT='Vektor Desk someone@example.com'" in env and "ALPACA" not in env
    assert oct((root / "desk.env").stat().st_mode & 0o777) == "0o600"
    assert "PATH" not in (root / "settings.env").read_text()
    assert json.loads((folder / "TIINGO_API_KEY.json").read_text())["result"] == "saved"
    assert json.loads((folder / "ALPACA_API_KEY_ID.json").read_text())["result"] == "refused"
    assert json.loads((folder / "PATH.json").read_text())["result"] == "refused"
    assert not list(folder.glob("*.req"))
    assert json.loads((boxrun.requests_dir(cfg) / "redeploy.json").read_text())["id"]
    for f in [*folder.iterdir(), boxrun.box_dir(cfg) / "keys.json", root / "deploy.log"]:
        assert SECRET not in f.read_text()


def test_the_app_the_box_and_setup_set_agree_on_where_each_key_lives(tmp_path):
    names = " ".join(boxkeys.KNOWN)
    env = {"DESK_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"}
    box = subprocess.run(
        ["bash", "-c", f'source "{DEPLOY}"; for k in {names}; do key_file_for "$k"; done'], capture_output=True, text=True, env=env, check=True
    )
    setup = DEPLOY.parent / "setup-truenas.sh"
    fn = setup.read_text().split("env_file_for() {", 1)[1].split("\n}\n", 1)[0]
    shell = subprocess.run(
        ["bash", "-c", f'ROOT={tmp_path}; is_secret() {{ return 1; }}; env_file_for() {{{fn}\n}}; for k in {names}; do env_file_for "$k"; done'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    want = [k.file for k in boxkeys.KNOWN.values()]
    assert box.stdout.split() == want and shell.stdout.split() == want
