import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or os.geteuid() != 0, reason="needs bash, git and root, like the box"
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


def setup(tmp_path: Path, script: str) -> tuple[Path, Path, dict]:
    origin, src = tmp_path / "origin.git", tmp_path / "src"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(src))
    (src / "deploy").mkdir()
    (src / "deploy" / "deploy.sh").write_text(script)
    git(src, "add", ".")
    git(src, "commit", "-q", "-m", "deploy.sh v2")
    git(src, "push", "-q", "origin", "HEAD:main")
    git(src, "fetch", "-q", "origin")
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


def self_pin(tmp_path: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; LOG={tmp_path}/deploy.log; self_pin'], capture_output=True, text=True, env=env, timeout=30)


def test_cron_copy_updates_itself_from_a_clean_checkout_at_main(tmp_path):
    src, pinned, env = setup(tmp_path, "echo v2\n")
    assert self_pin(tmp_path, env).returncode == 0
    assert pinned.read_text() == "echo v2\n"
    assert oct(pinned.stat().st_mode & 0o777) == "0o700"
    assert "updated itself" in (tmp_path / "deploy.log").read_text()
    assert not [p for p in pinned.parent.iterdir() if p.name.startswith(".")]


def test_it_stays_put_when_off_dirty_ahead_of_main_or_broken(tmp_path):
    src, pinned, env = setup(tmp_path, "echo v2\n")
    (Path(env["DESK_ROOT"]) / "deploy.no-self-pin").touch()
    self_pin(tmp_path, env)
    assert pinned.read_text() == "echo v1\n"
    (Path(env["DESK_ROOT"]) / "deploy.no-self-pin").unlink()
    (src / "deploy" / "deploy.sh").write_text("echo local edit\n")
    self_pin(tmp_path, env)
    assert pinned.read_text() == "echo v1\n"
    git(src, "commit", "-q", "-am", "unpushed")
    self_pin(tmp_path, env)
    assert pinned.read_text() == "echo v1\n"
    (src / "deploy" / "deploy.sh").write_text("if then fi (\n")
    git(src, "commit", "-q", "-am", "broken")
    git(src, "push", "-q", "origin", "HEAD:main")
    git(src, "fetch", "-q", "origin")
    assert self_pin(tmp_path, env).returncode != 0
    assert pinned.read_text() == "echo v1\n"
