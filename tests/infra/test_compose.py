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
