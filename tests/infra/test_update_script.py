import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or shutil.which("jq") is None or os.geteuid() != 0,
    reason="needs bash, git, jq and root, like the box",
)


def git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin",
        "HOME": str(cwd),
    }
    return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=cwd, capture_output=True, text=True, env=env, check=True).stdout.strip()


def commit(src: Path, script: str, message: str) -> None:
    (src / "deploy" / "deploy.sh").write_text(script)
    git(src, "add", ".")
    git(src, "commit", "-q", "-m", message)
    git(src, "push", "-q", "origin", "HEAD:main")
    git(src, "fetch", "-q", "origin")


def setup(tmp_path: Path) -> tuple[Path, Path, dict]:
    origin, src = tmp_path / "origin.git", tmp_path / "src"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(src))
    (src / "deploy").mkdir()
    commit(src, "echo v1\n", "deploy.sh v1")
    commit(src, "echo v2\n", "deploy.sh v2")
    (src / "README").write_text("x")
    git(src, "add", ".")
    git(src, "commit", "-q", "-m", "not deploy.sh")
    git(src, "push", "-q", "origin", "HEAD:main")
    git(src, "fetch", "-q", "origin")
    commit(src, "echo v3\n", "deploy.sh v3")
    pinned = tmp_path / "pin" / "deploy.sh"
    pinned.parent.mkdir()
    pinned.write_text("echo v1\n")
    root = tmp_path / "root"
    root.mkdir()
    env = {
        "DESK_ROOT": str(root),
        "DESK_SRC": str(src),
        "DESK_PINNED": str(pinned),
        "DESK_GIT_CREDENTIALS": str(tmp_path / "none"),
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    return src, pinned, env


def run(tmp_path: Path, env: dict, fn: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; LOG={tmp_path}/deploy.log; {fn}'], capture_output=True, text=True, env=env, timeout=30)


def state(tmp_path: Path, env: dict) -> dict:
    return json.loads(run(tmp_path, env, "script_state").stdout)


def test_state_counts_deploy_sh_commits_since_the_pinned_copy(tmp_path):
    src, pinned, env = setup(tmp_path)
    s = state(tmp_path, env)
    assert s["pinned"] is True and s["current"] is False and s["behind"] == 2 and s["off"] is False
    assert s["from"] == git(src, "log", "--format=%H", "--grep=v1") and s["to"] == git(src, "rev-parse", "HEAD")
    assert "2 commits behind main" in run(tmp_path, env, "script_line").stdout
    pinned.write_text("echo hand edit\n")
    s = state(tmp_path, env)
    assert s["current"] is False and s["behind"] is None and s["from"] is None
    pinned.unlink()
    assert state(tmp_path, env)["pinned"] is False


def test_update_copies_main_and_shows_old_and_new_commit(tmp_path):
    src, pinned, env = setup(tmp_path)
    res = run(tmp_path, env, "update_script")
    assert res.returncode == 0, res.stdout + res.stderr
    assert pinned.read_text() == "echo v3\n"
    assert oct(pinned.stat().st_mode & 0o777) == "0o700"
    old, new = git(src, "log", "--format=%h", "--grep=v1"), git(src, "rev-parse", "--short=7", "HEAD")
    assert f"from {old} to {new}" in res.stdout and "deploy.sh v2" in res.stdout and "deploy.sh v3" in res.stdout
    assert not [p for p in pinned.parent.iterdir() if p.name.startswith(".")]
    s = state(tmp_path, env)
    assert s["current"] is True and s["behind"] == 0
    again = run(tmp_path, env, "update_script")
    assert again.returncode == 0 and "current" in again.stdout


def test_update_refuses_when_off_dirty_behind_main_or_broken(tmp_path):
    src, pinned, env = setup(tmp_path)
    (Path(env["DESK_ROOT"]) / "deploy.no-self-pin").touch()
    assert run(tmp_path, env, "update_script").returncode == 1
    assert state(tmp_path, env)["off"] is True
    assert pinned.read_text() == "echo v1\n"
    (Path(env["DESK_ROOT"]) / "deploy.no-self-pin").unlink()
    (src / "deploy" / "deploy.sh").write_text("echo local edit\n")
    assert run(tmp_path, env, "update_script").returncode == 1
    assert pinned.read_text() == "echo v1\n"
    git(src, "commit", "-q", "-am", "unpushed")
    assert run(tmp_path, env, "update_script").returncode == 75
    assert pinned.read_text() == "echo v1\n"
    commit(src, "if then fi (\n", "broken")
    assert run(tmp_path, env, "update_script").returncode == 1
    assert pinned.read_text() == "echo v1\n"


def test_auto_and_now_no_longer_touch_the_cron_copy():
    text = DEPLOY.read_text()
    main = text[text.index("main() {") :]
    assert "update_script" not in main.replace("update-script) update_script ;;", "")
