import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

START = Path(__file__).resolve().parents[2] / "deploy" / "eval" / "start.sh"
COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose.yaml"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")


def start(tmp_path: Path, config: dict | None) -> tuple[subprocess.CompletedProcess, Path, Path]:
    home, src, work, stub = tmp_path / "home", tmp_path / "src", tmp_path / "work", tmp_path / "bin"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth": {}}')
    if config is not None:
        (home / ".claude.json").write_text(json.dumps(config))
        (home / ".claude.json").chmod(0o644)
    (src / "deploy" / "eval").mkdir(parents=True)
    (src / "deploy" / "eval" / "CLAUDE.md").write_text("# rules\n")
    work.mkdir()
    stub.mkdir()
    args = tmp_path / "claude-args"
    (stub / "claude").write_text(f'#!/bin/sh\necho "$*" > {args}\nenv > {args}.env\n')
    (stub / "claude").chmod(0o755)
    (stub / "python").symlink_to(sys.executable)
    (home / "logs").mkdir()
    (home / "logs" / "remote-control.log").write_text("last run\n")
    env = {
        "HOME": str(home),
        "EVAL_SRC": str(src),
        "EVAL_WORK": str(work),
        "PATH": f"{stub}:/usr/bin:/bin",
        "DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    res = subprocess.run(["sh", str(START)], capture_output=True, text=True, env=env, timeout=30)
    return res, home / ".claude.json", args


def test_start_answers_the_trust_and_remote_control_prompts_then_starts_remote_control(tmp_path):
    res, config, args = start(tmp_path, {"userID": "u", "projects": {"/elsewhere": {"allowedTools": []}}})
    assert res.returncode == 0, res.stderr
    data = json.loads(config.read_text())
    work = str(tmp_path / "work")
    assert data["projects"][work]["hasTrustDialogAccepted"] is True
    assert data["remoteDialogSeen"] is True
    assert data["userID"] == "u" and data["projects"]["/elsewhere"] == {"allowedTools": []}
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    log = tmp_path / "home" / "logs" / "remote-control.log"
    assert args.read_text().split() == ["remote-control", "--name", "vektor-desk-eval", "--debug-file", str(log)]
    assert (tmp_path / "home" / "logs" / "remote-control.log.1").read_text() == "last run\n"
    assert (tmp_path / "work" / "CLAUDE.md").read_text() == "# rules\n"


def test_start_turns_feature_flags_back_on_for_remote_control(tmp_path):
    res, _, args = start(tmp_path, {})
    assert res.returncode == 0, res.stderr
    names = {line.split("=", 1)[0] for line in Path(f"{args}.env").read_text().splitlines()}
    assert not names & {"DISABLE_TELEMETRY", "DO_NOT_TRACK", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"}
    assert "DISABLE_AUTOUPDATER" in names


def test_start_writes_a_private_config_when_there_is_none(tmp_path):
    res, config, args = start(tmp_path, None)
    assert res.returncode == 0, res.stderr
    data = json.loads(config.read_text())
    assert data["projects"][str(tmp_path / "work")]["hasTrustDialogAccepted"] is True and data["remoteDialogSeen"] is True
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert args.exists()


def test_compose_runs_the_eval_start_script():
    import yaml

    svc = yaml.safe_load(COMPOSE.read_text())["services"]["eval"]
    assert svc["command"] == ["sh", "/src/deploy/eval/start.sh"]
    assert svc["environment"]["HOME"] == "/home/eval" and svc["working_dir"] == "/work"
