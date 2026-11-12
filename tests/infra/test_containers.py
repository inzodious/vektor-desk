from datetime import UTC, datetime, timedelta

from desk import containers
from desk.status import status

NOW = datetime(2026, 11, 12, 1, 30, tzinfo=UTC)
UP = {
    "api": "Up 3 hours (healthy)",
    "cron": "Up 3 hours",
    "caddy": "Up 2 days",
    "ntfy": "Up 2 days",
    "tailscale": "Up 2 days",
    "lab": "Up 3 hours",
    "eval": "Up 3 hours",
}
GOOD_LOG = [
    "2026-11-10T01:00:01.000000000Z boot: 2026/11/10 01:00:01 Starting tailscaled",
    "2026-11-10T01:00:03.000000000Z 2026/11/10 01:00:03 Switching ipn state Starting -> Running (WantRunning=true, nm=true)",
    "2026-11-10T01:00:03.100000000Z 2026/11/10 01:00:03 peerapi: serving on http://100.64.0.7:41234",
    "2026-11-10T01:00:04.000000000Z boot: 2026/11/10 01:00:04 Startup complete, waiting for shutdown signal",
]


def export(cfg, states: dict[str, str], log: list[str] | None = None, at: datetime | None = None):
    out = containers.folder(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "containers.txt").write_text("".join(f"vektor-desk-{name}\t{state}\tvektor-desk:local\n" for name, state in states.items()))
    (out / "exported_at").write_text((at or NOW - timedelta(minutes=2)).astimezone().isoformat(timespec="seconds") + "\n")
    if log is not None:
        (out / "tailscale.log").write_text("\n".join(log) + "\n")


def test_docker_status_words_are_read_into_a_state_and_an_uptime():
    assert containers.state_of("Up 3 hours (healthy)") == "up" and containers.up_seconds("Up 3 hours (healthy)") == 10800
    assert containers.state_of("Up 2 minutes (unhealthy)") == "unhealthy" and containers.state_of("Up 5 seconds (health: starting)") == "starting"
    assert containers.state_of("Restarting (1) 4 seconds ago") == "restarting" and containers.exit_code("Restarting (1) 4 seconds ago") == 1
    assert containers.state_of("Exited (137) 2 hours ago") == "stopped" and containers.exit_code("Exited (137) 2 hours ago") == 137
    assert containers.up_seconds("Up About a minute") == 60 and containers.up_seconds("Up Less than a second") == 0
    assert containers.up_seconds("Up 2 weeks") == 1209600 and containers.up_seconds("Exited (0) 3 days ago") is None


def test_before_the_host_reports_the_state_is_unknown_and_says_so(cfg):
    got = containers.status(cfg, NOW)
    assert got["state"] == "unknown" and got["services"] == [] and "hasn't reported its services yet" in got["note"]
    assert got["tailnet"]["state"] == "unknown"


def test_every_service_running_reads_as_ok_with_the_tailnet_address(cfg):
    export(cfg, UP, GOOD_LOG)
    got = containers.status(cfg, NOW)
    assert got["state"] == "ok" and got["fresh"] and got["note"] == "All 7 desk services are running."
    assert [s["name"] for s in got["services"]] == ["api", "cron", "caddy", "ntfy", "tailscale", "lab", "eval"]
    link = next(s for s in got["services"] if s["name"] == "tailscale")
    assert link == {
        "name": "tailscale",
        "title": "the Tailscale link",
        "container": "vektor-desk-tailscale",
        "status": "Up 2 days",
        "state": "up",
        "up_seconds": 172800,
        "exit_code": None,
        "restarted_alone": False,
        "words": "The Tailscale link has been running for 2 days.",
    }
    assert got["tailnet"] == {
        "state": "ok",
        "kind": None,
        "words": "Tailscale is signed in and running on the box, at 100.64.0.7.",
        "address": "100.64.0.7",
        "line": None,
    }
    assert status(cfg, NOW)["containers"]["state"] == "ok"


def test_a_refused_sign_in_key_is_named_even_while_the_container_is_up(cfg):
    log = [
        *GOOD_LOG,
        "2026-11-12T01:20:00.000000000Z boot: failed to auth tailscale: tailscale up failed: backend error: invalid key: API key does not exist",
    ]
    export(cfg, UP | {"tailscale": "Up 9 minutes"}, log)
    got = containers.status(cfg, NOW)
    assert got["state"] == "trouble" and got["tailnet"]["kind"] == "key" and "invalid key" in got["tailnet"]["line"]
    assert got["note"].startswith("Every service is running, but the Tailscale address isn't answering: Tailscale refused the box's sign-in key")
    link = next(s for s in got["services"] if s["name"] == "tailscale")
    assert link["restarted_alone"] and link["words"] == "The Tailscale link restarted by itself 9 minutes ago."


def test_trouble_that_was_followed_by_a_good_start_is_not_reported(cfg):
    log = [
        "2026-11-09T01:00:00.000000000Z Received error: fetch control key: Get https://controlplane.tailscale.com/key: control dial timeout",
        *GOOD_LOG,
    ]
    export(cfg, UP, log)
    assert containers.status(cfg, NOW)["tailnet"]["state"] == "ok"
    for line, kind in (
        ("health(warnable=login-state): error: You are logged out. Last login error: none", "signed_out"),
        ("control: RegisterReq: node key has expired", "expired"),
        ('wgengine.NewUserspaceEngine(tun "tailscale0") error: tstun.New("tailscale0"): CreateTUN failed; /dev/net/tun does not exist', "device"),
        ('control: bootstrapDNS("derp") for "controlplane.tailscale.com" error: dial tcp: i/o timeout', "unreachable"),
    ):
        export(cfg, UP, [*GOOD_LOG, *[f"2026-11-12T01:20:00.000000000Z {line}"] * 3])
        assert containers.status(cfg, NOW)["tailnet"]["kind"] == kind
    blip = "2026-11-12T01:20:00.000000000Z control: bootstrapDNS error: dial tcp: i/o timeout"
    export(cfg, UP, [*GOOD_LOG, blip])
    assert containers.status(cfg, NOW)["tailnet"]["state"] == "ok"


def test_a_container_that_is_down_is_named_first_and_memory_is_called_out(cfg):
    export(cfg, UP | {"tailscale": "Restarting (137) 12 seconds ago", "ntfy": "Exited (1) 3 hours ago"}, GOOD_LOG)
    got = containers.status(cfg, NOW)
    assert got["state"] == "trouble"
    assert got["note"] == "Phone alerts is stopped. The Tailscale link keeps stopping and starting, out of memory."
    states = {s["name"]: s["state"] for s in got["services"]}
    assert states["tailscale"] == "restarting" and states["ntfy"] == "stopped" and states["api"] == "up"


def test_a_missing_core_container_is_trouble_and_a_missing_lab_is_not(cfg):
    only = {k: v for k, v in UP.items() if k not in ("tailscale", "lab", "eval")}
    export(cfg, only, GOOD_LOG)
    got = containers.status(cfg, NOW)
    assert got["state"] == "trouble" and got["note"] == "The Tailscale link has no container on the box."
    assert [s["name"] for s in got["services"]] == ["api", "cron", "caddy", "ntfy", "tailscale"]


def test_a_stale_report_says_how_old_it_is_instead_of_guessing(cfg):
    export(cfg, UP, GOOD_LOG, at=NOW - timedelta(hours=2))
    got = containers.status(cfg, NOW)
    assert got["state"] == "unknown" and not got["fresh"] and got["note"] == "The box last reported its services 2 hours ago, so this may be out of date."
    assert len(got["services"]) == 7
