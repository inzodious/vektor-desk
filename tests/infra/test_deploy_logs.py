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
        "SHORT stays abc, and an ordinary line stays as it is",
    ]
    out = redact(tmp_path, "\n".join(lines) + "\n")
    for secret in (claude, tiingo, porkbun, "zzzzzzzzzzzz", "abc.def.ghi", "kAbCdEf123", "0f0f0f"):
        assert secret not in out
    assert out.count("[redacted]") >= 7
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


def test_app_card_sets_icon_and_web_ui_once(tmp_path):
    yaml = pytest.importorskip("yaml")
    app = tmp_path / "configs" / "vektor-desk"
    app.mkdir(parents=True)
    meta = app / "metadata.yaml"
    meta.write_text("custom_app: true\nmetadata:\n  app_version: custom\n  title: Custom App\nportals: {}\nversion: 1.0.0\n")
    env = {"DESK_ROOT": str(tmp_path), "DESK_APP_CONFIGS": str(tmp_path / "configs"), "PATH": "/usr/local/bin:/usr/bin:/bin"}

    def run():
        return subprocess.run(["bash", "-c", f'source "{DEPLOY}"; app_card'], capture_output=True, text=True, env=env, check=True)

    assert "set" in run().stdout
    data = yaml.safe_load(meta.read_text())
    assert data["metadata"]["icon"] == "https://desk-lan.escape-vektor.com/icon-512.png"
    assert data["metadata"]["title"] == "Custom App" and data["custom_app"] is True
    assert data["portals"] == {"Web UI": "https://desk-lan.escape-vektor.com/"}
    assert run().stdout == ""
