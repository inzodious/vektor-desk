import json
import shutil
import subprocess
from pathlib import Path

import pytest

from desk import boxrun

yaml = pytest.importorskip("yaml")

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"
COMPOSE = (DEPLOY.parent / "compose.yaml").read_text()
BOX_ROOT = "/mnt/Manifest/apps/vektor-desk"

host_only = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq, like the box")


def box(tmp_path: Path, installed: dict, main: dict | None = None, root: str = BOX_ROOT) -> dict:
    src = tmp_path / "src"
    (src / "deploy").mkdir(parents=True, exist_ok=True)
    (src / "deploy" / "compose.yaml").write_text(yaml.safe_dump(main) if main is not None else COMPOSE)
    version = tmp_path / "app_configs" / "vektor-desk" / "versions" / "1.0.0"
    shutil.rmtree(tmp_path / "app_configs", ignore_errors=True)
    version.mkdir(parents=True)
    (version / "user_config.yaml").write_text(yaml.safe_dump({"custom_compose_config_string": yaml.safe_dump(installed)}))
    return {"DESK_ROOT": root, "DESK_SRC": str(src), "DESK_APP_CONFIGS": str(tmp_path / "app_configs"), "PATH": "/usr/local/bin:/usr/bin:/bin"}


def bash(env: dict, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; {script}'], capture_output=True, text=True, env=env, timeout=60)


def report(env: dict) -> dict:
    return json.loads(bash(env, "compose_report").stdout)


def current(root: Path | None = None) -> dict:
    return yaml.safe_load(COMPOSE.replace(BOX_ROOT + "/", f"{root}/") if root else COMPOSE)


@host_only
def test_a_plain_change_can_be_applied_from_the_app(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    old = current(root)
    old["services"]["eval"]["command"] = ["sh", "-c", "old"]
    del old["services"]["lab"]
    env = box(tmp_path, old, current(root), root=str(root))
    r = report(env)
    assert r["state"] == "drift" and r["drift"] == ["eval: command", "lab missing"]
    assert r["escalations"] == [] and r["missing_files"] == []
    assert f"{root}/data/lab/queue" in r["missing_dirs"]
    state = json.loads(bash(env, "compose_state").stdout)
    assert state["can_apply"] is True and state["compose"] == yaml.safe_dump(current(root))
    assert "Settings → Box → Apply compose" in bash(env, "compose_drift").stdout
    same = box(tmp_path, current())
    assert report(same)["state"] == "current"
    assert json.loads(bash(same, "compose_state").stdout)["compose"] is None


@host_only
def test_a_change_that_widens_what_containers_can_do_is_left_to_him(tmp_path):
    new = current()
    api, cron = new["services"]["api"], new["services"]["cron"]
    api["privileged"] = True
    del api["user"]
    api["cap_add"] = ["SYS_ADMIN"]
    api["cap_drop"] = []
    cron["volumes"].append("/etc:/host-etc")
    cron["volumes"].append("/var/run/docker.sock:/var/run/docker.sock")
    cron["volumes"].append(f"{BOX_ROOT}/../vektor-desk-src:/x")
    new["services"]["ntfy"]["image"] = "example/evil:1"
    new["services"]["lab"]["network_mode"] = "host"
    new["services"]["lab"]["devices"] = ["/dev/sda:/dev/sda"]
    env = box(tmp_path, current(), new)
    esc = report(env)["escalations"]
    for want in (
        "api: privileged",
        "api: user",
        "api: cap_add SYS_ADMIN",
        "api: cap_drop loosened",
        "cron: host path /etc",
        "cron: host path /var/run/docker.sock",
        f"cron: host path {BOX_ROOT}/../vektor-desk-src",
        "ntfy: new image example/evil",
        "lab: network_mode host",
        "lab: devices /dev/sda:/dev/sda",
    ):
        assert want in esc
    state = json.loads(bash(env, "compose_state").stdout)
    assert state["can_apply"] is False and state["compose"]
    assert "needs your eyes" in bash(env, "compose_drift").stdout


@host_only
def test_a_symlink_inside_the_app_folder_does_not_widen_a_mount(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "data").symlink_to("/")
    new = current()
    new["services"]["api"]["volumes"].append(f"{root}/data:/host")
    env = box(tmp_path, current(), new, root=str(root))
    assert f"api: host path {root}/data" in report(env)["escalations"]


STUBS = """
at_main() { return 0; }
repo() { if [ "$1" = rev-parse ]; then echo abc1234def; else command git "$@"; fi; }
live_build() { echo abc1234def; }
busy() { return 1; }
backup() { echo backup.tar.gz; }
healthy() { return 0; }
app_card() { return 0; }
docker() { return 1; }
run_job() {
  printf '%s\\n' "$@" > "$CALLS"
  jq -r .custom_compose_config_string <<<"$3" | python3 -c "$INSTALL" "$DESK_APP_CONFIGS/vektor-desk/versions/1.0.0/user_config.yaml"
}
LOG=$TMPLOG
"""


INSTALL = "import sys, yaml; open(sys.argv[1], 'w').write(yaml.safe_dump({'custom_compose_config_string': sys.stdin.read()}))"


def apply(tmp_path: Path, env: dict) -> subprocess.CompletedProcess:
    env = env | {"CALLS": str(tmp_path / "calls"), "TMPLOG": str(tmp_path / "deploy.log"), "INSTALL": INSTALL}
    return bash(env, STUBS + "apply_compose")


@host_only
def test_apply_hands_truenas_the_checkout_compose_and_makes_new_folders(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    old = current(root)
    del old["services"]["lab"]
    new = current(root)
    new["services"]["lab"]["volumes"] = [f"{root}/lab:/data/lab"]
    env = box(tmp_path, old, new, root=str(root))
    res = apply(tmp_path, env)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[:2] == ["app.update", "vektor-desk"]
    assert json.loads("\n".join(calls[2:]))["custom_compose_config_string"] == yaml.safe_dump(new)
    assert (root / "lab").is_dir()
    assert "Compose applied at abc1234" in (tmp_path / "deploy.log").read_text()
    assert report(env)["state"] == "current"
    again = apply(tmp_path, env)
    assert again.returncode == 0 and "already matches" in again.stdout


@host_only
def test_apply_refuses_a_widening_change_and_touches_nothing(tmp_path):
    new = current()
    new["services"]["api"]["privileged"] = True
    env = box(tmp_path, current(), new)
    res = apply(tmp_path, env)
    assert res.returncode == 1 and "widens what containers can do" in res.stdout and "Copy button" in res.stdout
    assert not (tmp_path / "calls").exists()


def test_box_api_shows_compose_state_and_serves_the_file_to_copy(client, cfg):
    assert client.get("/api/box/compose.yaml").status_code == 404
    folder = boxrun.box_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    state = {"state": "drift", "drift": ["eval: command"], "escalations": ["api: privileged"], "can_apply": False, "compose": "services: {}\n"}
    (folder / "compose.json").write_text(json.dumps(state))
    body = client.get("/api/box").json()["compose"]
    assert body["can_apply"] is False and body["copy_available"] is True and "compose" not in body
    text = client.get("/api/box/compose.yaml")
    assert text.status_code == 200 and text.text == "services: {}\n" and text.headers["content-type"].startswith("text/yaml")


def test_the_low_memory_lab_command_and_worker_count_can_be_applied_from_the_app(tmp_path):
    before = current()
    before["services"]["lab"]["command"] = ["python", "-m", "desk.engine.lab"]
    before["services"]["lab"]["environment"]["DESK_LAB_WORKERS"] = "3"
    seen = report(box(tmp_path, before))
    assert seen["state"] == "drift" and seen["escalations"] == [] and any("lab" in d for d in seen["drift"])
