import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy"
SETUP = DEPLOY_DIR / "setup-truenas.sh"
DEPLOY = DEPLOY_DIR / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or os.geteuid() != 0, reason="needs bash, run as root like on the box")


def set_key(tmp_path: Path, key: str, typed: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "deploy-stub.sh"
    stub.write_text(f'echo "$*" >> {tmp_path / "deploy-calls"}\n')
    env = {"DESK_ROOT": str(tmp_path), "DESK_SRC": str(tmp_path / "src"), "DESK_DEPLOY": str(stub), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", str(SETUP), "set", key], input=typed + "\n", capture_output=True, text=True, env=env, timeout=30)


def test_set_keeps_spaces_changes_one_key_and_redeploys(tmp_path):
    claude = "sk-" + "ant-oat01-" + "Z" * 24
    desk = tmp_path / "desk.env"
    desk.write_text(f"CLAUDE_CODE_OAUTH_TOKEN={claude}\nTIINGO_API_KEY=t1\nDESK_SEC_USER_AGENT=VektorDeskme@example.com\n")
    res = set_key(tmp_path, "DESK_SEC_USER_AGENT", "  Vektor Desk me@example.com  ")
    assert res.returncode == 0, res.stderr
    assert desk.read_text().splitlines() == [f"CLAUDE_CODE_OAUTH_TOKEN={claude}", "TIINGO_API_KEY=t1", "DESK_SEC_USER_AGENT='Vektor Desk me@example.com'"]
    assert stat.S_IMODE(desk.stat().st_mode) == 0o600
    assert (tmp_path / "deploy-calls").read_text().split() == ["redeploy"]


def test_set_strips_whitespace_from_secrets_and_adds_missing_keys(tmp_path):
    (tmp_path / "desk.env").write_text("TIINGO_API_KEY=old\n")
    assert set_key(tmp_path, "FRED_API_KEY", " abc123 def ").returncode == 0
    assert (tmp_path / "desk.env").read_text().splitlines() == ["TIINGO_API_KEY=old", "FRED_API_KEY=abc123def"]
    assert set_key(tmp_path, "DESK_MARGIN_RATE_PCT", "12.075").returncode == 0
    assert (tmp_path / "settings.env").read_text().splitlines() == ["DESK_MARGIN_RATE_PCT=12.075"]


def test_set_refuses_a_bad_key_name(tmp_path):
    res = set_key(tmp_path, "lower-case", "x")
    assert res.returncode == 2 and "usage" in res.stderr
    assert not (tmp_path / "deploy-calls").exists()


def redeploy(tmp_path: Path, runlock_rc: int) -> subprocess.CompletedProcess:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    docker_cases = (
        f"*runlock*) echo 'mirror (since 09:00)'; exit {runlock_rc} ;; *revision*) echo abc1234 ;; *Health*caddy) echo running ;; *Health*) echo healthy ;;"
    )
    midclt_cases = """app.redeploy) echo 7 ;; core.get_jobs) echo '[{"state": "SUCCESS"}]' ;; *) echo '[]' ;;"""
    (stub / "docker").write_text(f'#!/bin/sh\necho "docker $*" >> {calls}\ncase "$*" in {docker_cases} esac\n')
    (stub / "midclt").write_text(f'#!/bin/sh\necho "midclt $*" >> {calls}\ncase "$2" in {midclt_cases} esac\n')
    for f in ("docker", "midclt"):
        (stub / f).chmod(0o755)
    env = {"DESK_ROOT": str(tmp_path), "DESK_APP_CONFIGS": str(tmp_path / "none"), "PATH": "/usr/bin:/bin"}
    script = f'source "{DEPLOY}"; LOCK={tmp_path}/lock; PATH="{stub}:$PATH"; main redeploy'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=20)


def test_redeploy_recreates_the_app_on_the_live_images(tmp_path):
    res = redeploy(tmp_path, 0)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = (tmp_path / "calls").read_text()
    assert "midclt call app.redeploy vektor-desk" in calls
    assert "Live again: abc1234" in res.stdout


def test_redeploy_waits_for_a_running_desk_job(tmp_path):
    res = redeploy(tmp_path, 75)
    assert res.returncode == 75
    assert "mirror (since 09:00)" in res.stdout + res.stderr
    assert "app.redeploy" not in (tmp_path / "calls").read_text()
