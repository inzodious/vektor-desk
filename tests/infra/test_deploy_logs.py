import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("awk") is None, reason="needs bash and awk")


def redact(root: Path, text: str) -> str:
    script = f'source "{DEPLOY}"; list=$(mktemp); secret_values >"$list"; redact "$list"; rm -f "$list"'
    res = subprocess.run(["bash", "-c", script], input=text, capture_output=True, text=True, env={"DESK_ROOT": str(root), "PATH": "/usr/bin:/bin"}, check=True)
    return res.stdout


def test_log_export_redacts_env_values_and_token_shapes(tmp_path):
    claude = "sk-" + "ant-oat01-" + "Q" * 24
    tiingo = "t" * 6 + "0123456789abcdef"
    porkbun = "sk1_" + "a1b2c3d4" * 4
    tailnet = "tskey-" + "auth-kAbCdEf123-xyz"
    (tmp_path / "desk.env").write_text(f"CLAUDE_CODE_OAUTH_TOKEN={claude}\nTIINGO_API_KEY='{tiingo}'\nSHORT=abc\n")
    (tmp_path / "caddy.env").write_text(f'export PORKBUN_API_SECRET_KEY="{porkbun}"\n')
    lines = [
        f"auth failed for {claude}",
        f"GET https://api.tiingo.com/tiingo/daily/SPY/prices?startDate=2026-01-01&token={tiingo}",
        f"porkbun answered for {porkbun}",
        "GET https://finnhub.io/api/v1/quote?symbol=SPY&token=zzzzzzzzzzzz",
        "Authorization: Bearer abc.def.ghi",
        f"fresh {tailnet} in a log",
        'key file {"private_key_id": "0f0f0f", "client_email": "reader@example.iam.gserviceaccount.com"}',
        "session token " + "eyJ" + "hbGciOi.eyJzdWIi.c2lnbmF0dXJl",
        "SHORT stays abc, and an ordinary line stays as it is",
    ]
    out = redact(tmp_path, "\n".join(lines) + "\n")
    for secret in (claude, tiingo, porkbun, "zzzzzzzzzzzz", "abc.def.ghi", "kAbCdEf123", "0f0f0f", "c2lnbmF0dXJl"):
        assert secret not in out
    assert out.count("[redacted]") >= 8
    assert "SHORT stays abc, and an ordinary line stays as it is" in out
    assert "reader@example.iam.gserviceaccount.com" in out
    assert "symbol=SPY" in out


def test_sourcing_deploy_sh_runs_nothing(tmp_path):
    res = subprocess.run(
        ["bash", "-c", f'source "{DEPLOY}"; echo sourced'], capture_output=True, text=True, env={"DESK_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"}
    )
    assert res.returncode == 0 and res.stdout.strip() == "sourced"
    assert not any(tmp_path.iterdir())


def busy(tmp_path: Path, rc: int, out: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "docker").write_text(f"#!/bin/sh\nprintf '%s' '{out}'\nexit {rc}\n")
    (stub / "docker").chmod(0o755)
    script = f'source "{DEPLOY}"; PATH="{stub}:$PATH"; if why=$(busy); then echo "busy:$why"; else echo idle; fi'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"DESK_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"})


def test_busy_only_when_runlock_says_so(tmp_path):
    assert busy(tmp_path, 0, "").stdout.strip() == "idle"
    assert busy(tmp_path, 75, "mirror (since 09:00)").stdout.strip() == "busy:mirror (since 09:00)"
    assert busy(tmp_path, 1, "Error: No such container").stdout.strip() == "idle"


def test_app_card_sets_icon_and_web_ui_then_rebuilds_the_app_list_once(tmp_path):
    yaml = pytest.importorskip("yaml")
    configs = tmp_path / "ix-apps" / "app_configs"
    app = configs / "vektor-desk"
    app.mkdir(parents=True)
    meta = app / "metadata.yaml"
    meta.write_text("custom_app: true\nmetadata:\n  app_version: custom\n  title: Custom App\nportals: {}\nversion: 1.0.0\n")
    collective = tmp_path / "ix-apps" / "metadata.yaml"
    collective.write_text("vektor-desk:\n  metadata:\n    title: Custom App\n  portals: {}\n")
    calls = tmp_path / "midclt-calls"
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "midclt").write_text(
        f'#!/bin/sh\necho "$*" >> {calls}\n'
        f"python3 -c \"import yaml; m = yaml.safe_load(open('{meta}')); yaml.safe_dump({{'vektor-desk': m}}, open('{collective}', 'w'))\"\n"
    )
    (stub / "midclt").chmod(0o755)
    env = {"DESK_ROOT": str(tmp_path), "DESK_APP_CONFIGS": str(configs), "PATH": "/usr/local/bin:/usr/bin:/bin"}

    def run():
        return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; PATH="{stub}:$PATH"; app_card'], capture_output=True, text=True, env=env, check=True)

    assert "set" in run().stdout
    data = yaml.safe_load(meta.read_text())
    assert data["metadata"]["icon"] == "https://desk-lan.escape-vektor.com/icon-512.png"
    assert data["metadata"]["title"] == "Custom App" and data["custom_app"] is True
    assert data["portals"] == {"Web UI": "https://desk-lan.escape-vektor.com/"}
    assert calls.read_text().split() == ["call", "app.metadata.generate"]
    assert yaml.safe_load(collective.read_text())["vektor-desk"]["portals"] == {"Web UI": "https://desk-lan.escape-vektor.com/"}
    assert run().stdout == ""
    assert calls.read_text().count("app.metadata.generate") == 1


def test_logs_export_includes_the_eval_debug_log_redacted_and_caps_it(tmp_path):
    claude = "sk-" + "ant-oat01-" + "R" * 24
    (tmp_path / "data").mkdir()
    (tmp_path / "desk.env").write_text(f"CLAUDE_CODE_OAUTH_TOKEN={claude}\n")
    logs = tmp_path / "eval" / "home" / "logs"
    logs.mkdir(parents=True)
    debug = logs / "remote-control.log"
    debug.write_text("".join(f"line {i}\n" for i in range(1500)) + f"[bridge:work] Declined session cse_1: token {claude}\n")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "docker").write_text('#!/bin/sh\necho "docker $*"\n')
    (stub / "docker").chmod(0o755)
    (stub / "chown").write_text("#!/bin/sh\nexit 0\n")
    (stub / "chown").chmod(0o755)
    env = {"DESK_ROOT": str(tmp_path), "DESK_DEBUG_MAX": "100", "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", "-c", f'source "{DEPLOY}"; PATH="{stub}:$PATH"; logs_export'], capture_output=True, text=True, env=env, check=True)
    out = tmp_path / "data" / "run" / "logs"
    exported = (out / "eval-debug.log").read_text()
    assert "Declined session cse_1" in exported and claude not in exported
    assert len(exported.splitlines()) == 1000
    assert "vektor-desk-eval" in (out / "eval.log").read_text()
    assert debug.stat().st_size == 0
