from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose.yaml"


def services():
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_eval_masks_the_desks_claude_home():
    tmpfs = services()["eval"]["tmpfs"]
    assert any(t.split(":")[0] == "/data/home" for t in tmpfs)
    assert services()["api"]["user"] == services()["eval"]["user"]


def test_eval_is_read_only_keyless_and_off_the_desk_network():
    svc = services()["eval"]
    mounts = {v.split(":")[1]: v for v in svc["volumes"]}
    assert mounts["/data"].endswith(":ro") and mounts["/src"].endswith(":ro")
    assert set(mounts) == {"/data", "/src", "/home/eval", "/work"}
    assert not any(".env" in v or "firestore" in v or "docker.sock" in v for v in svc["volumes"])
    assert "env_file" not in svc
    assert svc["networks"] == ["eval"]
    assert svc["cap_drop"] == ["ALL"] and svc["read_only"] is True
    assert "no-new-privileges:true" in svc["security_opt"]
    others = {name for name, s in services().items() if "eval" in (s.get("networks") or [])}
    assert others == {"eval"}
