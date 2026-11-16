import ipaddress
import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_only_the_tailscale_service_publishes_and_only_on_a_private_lan_address():
    services = yaml.safe_load((DEPLOY / "compose.yaml").read_text())["services"]
    published = {name: s["ports"] for name, s in services.items() if s.get("ports")}
    assert set(published) == {"tailscale"}
    for port in published["tailscale"]:
        host_ip, host_port, container_port = port.split(":")
        assert ipaddress.ip_address(host_ip).is_private and not ipaddress.ip_address(host_ip).is_unspecified
        assert host_port == container_port and host_port in {"443", "8443"}


def test_caddy_answers_private_sources_only():
    caddyfile = (DEPLOY / "caddy" / "Caddyfile").read_text()
    guard = re.search(r"@outside not remote_ip (.+)", caddyfile).group(1).split()
    nets = [ipaddress.ip_network(n) for n in guard]
    assert all(n.is_private or n == ipaddress.ip_network("100.64.0.0/10") for n in nets)
    assert ipaddress.ip_network("100.64.0.0/10") in nets and ipaddress.ip_network("192.168.0.0/16") in nets
    assert caddyfile.count("import private") == 2 and "abort @outside" in caddyfile


# ---- The NAS's shared rules ----

BUDGET_MIB = 2560


def mib(limit: str) -> int:
    number, unit = re.fullmatch(r"(\d+)([mg])", str(limit)).groups()
    return int(number) * (1024 if unit == "g" else 1)


def test_every_service_is_capped_and_the_desk_stays_within_its_share_of_the_nas():
    services = yaml.safe_load((DEPLOY / "compose.yaml").read_text())["services"]
    limits = {name: mib(s["mem_limit"]) for name, s in services.items()}
    assert set(limits) == set(services) and sum(limits.values()) <= BUDGET_MIB
    assert limits == {"tailscale": 128, "caddy": 64, "api": 192, "cron": 544, "ntfy": 96, "lab": 512, "eval": 1024}
    for name, s in services.items():
        assert s["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}, name
        heap = re.search(r"--max-old-space-size=(\d+)", str((s.get("environment") or {}).get("NODE_OPTIONS", "")))
        if heap:
            assert int(heap.group(1)) < limits[name], name
    assert {name for name, s in services.items() if "NODE_OPTIONS" in (s.get("environment") or {})} == {"cron", "eval"}
    assert services["lab"]["command"][:6] == ["nice", "-n", "10", "ionice", "-c3", "-t"]


def test_the_image_caps_build_memory_and_serves_the_api_with_one_recycled_worker():
    dockerfile = (DEPLOY.parent / "Dockerfile").read_text()
    assert "ENV NODE_OPTIONS=--max-old-space-size=1024" in dockerfile and "MAKEFLAGS=-j2" in dockerfile and " util-linux " in dockerfile
    assert dockerfile.rstrip().endswith('CMD ["python", "-m", "desk.api.serve"]')
