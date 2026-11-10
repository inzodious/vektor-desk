import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from desk import boxrun

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

host_only = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None or os.geteuid() != 0, reason="needs bash, jq and root, like the box")


def alive(cfg, at=None):
    folder = boxrun.box_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "host.alive").write_text(boxrun.stamp(at or boxrun.now_utc()))


def test_get_box_lists_the_nine_actions(client, cfg):
    body = client.get("/api/box").json()
    assert set(body) == {"now", "host_alive", "pickup_seconds", "script", "compose", "actions"}
    assert body["host_alive"] is False and body["pickup_seconds"] == 300 and body["script"] is None and body["compose"] is None
    assert [a["name"] for a in body["actions"]] == [
        "redeploy",
        "status",
        "check",
        "backup",
        "restore-test",
        "logs",
        "update-script",
        "deploy-now",
        "apply-compose",
    ]
    first = body["actions"][0]
    assert set(first) == {"name", "title", "what", "cooldown_seconds", "running", "queued", "queued_at", "last_run", "cooldown_until", "can_run"}
    assert first["can_run"] is True and first["last_run"] is None


def test_box_request_queues_once_cools_down_and_is_logged(client, cfg):
    assert client.post("/api/box/backup/run").json()["error"] == "host_down"
    alive(cfg)
    assert client.post("/api/box/rm/run").status_code == 404
    assert client.post("/api/box/..%2Fx/run").status_code == 404
    assert not (cfg.data_dir / "run" / "x").exists()
    ok = client.post("/api/box/backup/run")
    assert ok.status_code == 202 and ok.json()["action"] == "backup" and ok.json()["request_id"]
    assert client.post("/api/box/backup/run").json()["error"] == "queued"
    (boxrun.requests_dir(cfg) / "backup.json").unlink()
    cool = client.post("/api/box/backup/run")
    assert cool.status_code == 429 and int(cool.headers["Retry-After"]) > 0
    log = [json.loads(line)["outcome"] for line in (cfg.data_dir / "run" / "box-requests.log").read_text().splitlines()]
    assert log == ["host_down", "unknown_action", "queued", "queued", "cooldown"]


def test_running_action_is_refused_and_a_stale_one_is_not(cfg):
    alive(cfg)
    now = boxrun.now_utc()
    folder = boxrun.box_dir(cfg)
    (folder / "check.json").write_text(json.dumps({"action": "check", "started": boxrun.stamp(now), "finished": None}))
    assert boxrun.request_action(cfg, "check", now=now)[1]["error"] == "running"
    later = now + timedelta(hours=3)
    alive(cfg, later)
    assert boxrun.request_action(cfg, "check", now=later)[0] == 202


def host(tmp_path: Path, *requests: str, symlink: bool = False) -> tuple[subprocess.CompletedProcess, Path]:
    root = tmp_path / "root"
    reqs = root / "data" / "run" / "box" / "requests"
    reqs.mkdir(parents=True)
    for name in requests:
        (reqs / f"{name}.json").write_text(json.dumps({"id": "abc123", "command": "rm -rf /"}))
    (reqs / "evil.json").write_text("{}")
    if symlink:
        (tmp_path / "secret").write_text("root only")
        (reqs / "logs.json").symlink_to(tmp_path / "secret")
    (root / "desk.env").write_text("TIINGO_API_KEY=" + "x" * 6 + "secret0123456789\n")
    calls = tmp_path / "calls"
    stub = tmp_path / "self.sh"
    stub.write_text(
        f'echo "$1" >> {calls}\n'
        'case "$1" in status) echo "App: RUNNING, key ' + "x" * 6 + 'secret0123456789" ;; check) echo nope; exit 3 ;; backup) exit 75 ;; esac\n'
    )
    env = {"DESK_ROOT": str(root), "DESK_SELF": str(stub), "PATH": "/usr/bin:/bin"}
    res = subprocess.run(["bash", "-c", f'source "{DEPLOY}"; LOG={tmp_path}/deploy.log; box_requests'], capture_output=True, text=True, env=env, timeout=30)
    return res, root / "data" / "run" / "box"


@host_only
def test_host_runs_only_allowlisted_actions_and_stores_redacted_results(tmp_path):
    res, box = host(tmp_path, "status", "check", "backup")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "calls").read_text().split() == ["status", "check", "backup"]
    status = json.loads((box / "status.json").read_text())
    assert status["result"] == "ok" and status["exit_code"] == 0 and status["request_id"] == "abc123" and status["finished"]
    assert "secret0123456789" not in status["output"] and "[redacted]" in status["output"]
    assert json.loads((box / "check.json").read_text())["result"] == "failed"
    assert json.loads((box / "backup.json").read_text())["result"] == "skipped"
    assert not list((box / "requests").iterdir())
    assert (box / "host.alive").read_text().strip().endswith("Z")
    assert json.loads((box / "script.json").read_text())["pinned"] is False
    assert json.loads((box / "compose.json").read_text())["state"] == "unknown"


@host_only
def test_host_ignores_symlinked_requests_and_a_symlinked_box_folder(tmp_path):
    res, box = host(tmp_path, symlink=True)
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / "calls").exists()
    assert (tmp_path / "secret").read_text() == "root only"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.rmtree(box)
    box.symlink_to(elsewhere)
    env = {"DESK_ROOT": str(tmp_path / "root"), "DESK_SELF": "/bin/false", "PATH": "/usr/bin:/bin"}
    res = subprocess.run(["bash", "-c", f'source "{DEPLOY}"; LOG={tmp_path}/deploy.log; box_requests'], capture_output=True, text=True, env=env, timeout=30)
    assert res.returncode == 0 and not any(elsewhere.iterdir())
    assert "isn't a plain folder" in (tmp_path / "deploy.log").read_text()
