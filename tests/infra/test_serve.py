import os
import socket
import subprocess
import sys
import time
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_api_runs_one_worker_and_replaces_it_after_its_request_limit(tmp_path):
    port = free_port()
    env = os.environ | {
        "DESK_DATA_DIR": str(tmp_path / "data"),
        "DESK_API_HOST": "127.0.0.1",
        "DESK_API_PORT": str(port),
        "DESK_API_MAX_REQUESTS": "3",
        "DESK_API_MAX_REQUESTS_JITTER": "0",
    }
    proc = subprocess.Popen([sys.executable, "-m", "desk.api.serve"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        answers = []
        deadline = time.monotonic() + 60
        while len(answers) < 8 and time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=20) as res:
                    answers.append(res.status)
            except OSError:
                pass
            time.sleep(0.4)
        assert answers == [200] * 8
        assert all((tmp_path / "data" / folder).is_dir() for folder in ("home", "inbox/fidelity", "run"))
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=30)
    assert out.count("Started server process") >= 2 and out.count("Maximum request limit of 3 exceeded") >= 1 and "died" in out, out
    assert "Started parent process" in out and proc.returncode == 0
