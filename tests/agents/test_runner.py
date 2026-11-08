import json
import stat
import sys
import textwrap
from datetime import UTC, datetime

import pytest

from desk.agents import store
from desk.agents.adapter import AgentError, ClaudeCli, FakeAdapter, UsageLimitError, parse_output
from desk.agents.desks import DESKS, Desk, get
from desk.agents.jobs import JOBS
from desk.agents.runner import run_desk
from desk.agents.status import crew, next_run
from desk.runlock import job_lock

OK_JSON = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "done",
    "structured_output": {"kind": "alert"},
    "num_turns": 3,
    "duration_ms": 4200,
    "total_cost_usd": 0.12,
    "session_id": "s-1",
    "usage": {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5},
}


def test_registry_is_all_opus_and_jobs_only_for_live_desks():
    assert set(DESKS) == {"plan_keeper", "tax", "risk", "research", "skeptic", "scout", "strategy", "filings"}
    assert {d.model for d in DESKS.values()} == {"opus"}
    assert {d.name for d in DESKS.values() if d.tools} == {"research", "scout", "strategy"}
    assert all(line.endswith(f"run {d.name}") for d in DESKS.values() if d.live for line in JOBS if d.name in line)
    with pytest.raises(KeyError):
        get("nope")


def test_cli_command_matches_the_hemline_pattern(tmp_path):
    cli = ClaudeCli(binary="claude")
    plain = cli.command(get("plan_keeper"), tmp_path / "s.md", {"type": "object"})
    assert plain[:2] == ["claude", "-p"]
    assert "--bare" not in plain
    assert plain[plain.index("--tools") + 1] == ""
    assert plain[plain.index("--setting-sources") + 1] == ""
    assert plain[plain.index("--model") + 1] == "opus"
    assert plain[plain.index("--effort") + 1] == "high"
    assert "--strict-mcp-config" in plain and "--no-session-persistence" in plain
    assert plain[plain.index("--permission-mode") + 1] == "dontAsk"
    assert plain[plain.index("--json-schema") + 1] == '{"type":"object"}'
    assert "--allowedTools" not in plain
    web = cli.command(get("research"), tmp_path / "s.md", None)
    assert web[web.index("--tools") + 1] == "WebSearch,WebFetch"
    assert web[web.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert web[web.index("--effort") + 1] == "xhigh"
    assert "--json-schema" not in web


def test_parse_output_reads_usage_and_structured():
    r = parse_output(json.dumps(OK_JSON), model="opus")
    assert (r.structured, r.turns, r.tokens, r.cost_estimate, r.session_id) == ({"kind": "alert"}, 3, 165, 0.12, "s-1")
    assert r.model == "opus"
    served = OK_JSON | {"modelUsage": {"claude-haiku-x": {"outputTokens": 4}, "claude-opus-x": {"outputTokens": 90}}}
    assert parse_output(json.dumps(served), model="opus").model == "claude-opus-x"


def test_parse_output_classifies_limits_and_errors():
    with pytest.raises(UsageLimitError):
        parse_output(json.dumps({"is_error": True, "result": "Claude usage limit reached. Resets at 3am"}))
    with pytest.raises(AgentError) as e:
        parse_output(json.dumps({"is_error": True, "subtype": "error_max_turns", "result": ""}))
    assert not isinstance(e.value, UsageLimitError)
    with pytest.raises(AgentError):
        parse_output("not json")


def _fake_claude(tmp_path, body: str) -> str:
    path = tmp_path / "claude"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_cli_runs_binary_with_prompt_on_stdin_in_empty_dir(tmp_path):
    seen = tmp_path / "seen.json"
    binary = _fake_claude(
        tmp_path,
        f"""
        import json, os, sys
        prompt = sys.stdin.read()
        argv = sys.argv[1:]
        system = open(argv[argv.index("--system-prompt-file") + 1]).read()
        json.dump({{"prompt": prompt, "system": system, "cwd_files": os.listdir("."), "argv": argv}}, open({str(seen)!r}, "w"))
        sys.stdout.write({json.dumps(OK_JSON)!r})
        """,
    )
    result = ClaudeCli(binary=binary).run(get("plan_keeper"), "be careful", "brief here", {"type": "object"})
    got = json.loads(seen.read_text())
    assert (got["prompt"], got["system"], got["cwd_files"]) == ("brief here", "be careful", [])
    assert result.structured == {"kind": "alert"}


def test_cli_retries_dropped_connections_then_gives_up(tmp_path):
    binary = _fake_claude(tmp_path, 'import sys\nsys.stderr.write("ECONNRESET socket hang up")\nsys.exit(1)\n')
    waits = []
    with pytest.raises(AgentError):
        ClaudeCli(binary=binary, sleep=waits.append).run(get("tax"), "s", "p")
    assert waits == [5, 15, 30, 60]


def test_cli_raises_usage_limit_from_stderr_without_retry(tmp_path):
    binary = _fake_claude(tmp_path, 'import sys\nsys.stderr.write("429 rate limit")\nsys.exit(1)\n')
    waits = []
    with pytest.raises(UsageLimitError):
        ClaudeCli(binary=binary, sleep=waits.append).run(get("tax"), "s", "p")
    assert waits == []


def test_run_desk_logs_usage(cfg):
    fake = FakeAdapter({"plan_keeper": {"kind": "alert"}})
    out = run_desk(get("plan_keeper"), "sys", "brief", cfg=cfg, schema={"type": "object"}, adapter=fake)
    assert out.ok and out.result.structured == {"kind": "alert"}
    last = store.last_run(cfg, "plan_keeper")
    assert (last["status"], last["model"], last["effort"], last["turns"]) == ("ok", "opus", "high", 1)
    assert fake.calls[0]["prompt"] == "brief"


@pytest.mark.parametrize(
    ("answer", "status"),
    [(UsageLimitError("usage limit"), "deferred"), (AgentError("boom"), "failed"), ("plain text only", "failed")],
)
def test_run_desk_failures_are_logged(cfg, answer, status):
    out = run_desk(get("tax"), "s", "p", cfg=cfg, schema={"type": "object"}, adapter=FakeAdapter({"tax": answer}))
    assert out.status == status
    assert store.last_run(cfg, "tax")["status"] == status


def test_switches_and_weekly_cap(cfg):
    desk = Desk("tiny", "Tiny", "high", 9, 1, 1)
    fake = FakeAdapter()
    store.set_enabled(cfg, "tiny", False)
    assert run_desk(desk, "s", "p", cfg=cfg, adapter=fake).status == "disabled"
    store.set_enabled(cfg, "tiny", True)
    store.set_enabled(cfg, store.ALL, False)
    assert run_desk(desk, "s", "p", cfg=cfg, adapter=fake).status == "disabled"
    store.set_enabled(cfg, store.ALL, True)
    assert run_desk(desk, "s", "p", cfg=cfg, adapter=fake).status == "ok"
    assert run_desk(desk, "s", "p", cfg=cfg, adapter=fake).status == "over_budget"
    assert run_desk(desk, "s", "p", cfg=cfg, adapter=fake, trigger="console").status == "ok"
    assert len(fake.calls) == 2


def test_one_desk_at_a_time(cfg):
    with job_lock("agents", cfg=cfg):
        out = run_desk(get("risk"), "s", "p", cfg=cfg, adapter=FakeAdapter())
    assert out.status == "busy"


def test_next_run_respects_schedule_and_first_week():
    zone = __import__("zoneinfo").ZoneInfo("America/New_York")
    now = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    assert next_run(get("plan_keeper"), now, zone) == "2026-11-07T17:30:00-05:00"
    assert next_run(get("scout"), now, zone) == "2026-12-06T03:00:00-05:00"
    assert next_run(get("strategy"), now, zone) == "2026-11-08T05:45:00-05:00"
    assert next_run(get("skeptic"), now, zone) is None


def test_status_api(cfg, app_client):
    client = app_client(packages=["agents"])
    run_desk(get("plan_keeper"), "s", "p", cfg=cfg, adapter=FakeAdapter())
    body = client.get("/api/agents/status").json()
    tiles = {d["desk"]: d for d in body["desks"]}
    assert (body["enabled"], body["enabled_source"]) == (False, "desk.yaml") and list(tiles)[0] == "plan_keeper"
    assert (tiles["plan_keeper"]["source"], tiles["plan_keeper"]["yaml"], tiles["plan_keeper"]["app"]) == ("desk.yaml", False, None)
    assert body["guard"] | {"allowed": None} == {"on": False, "allowed": None, "ready": False, "why": "The Tax desk hasn't finished a run yet."}
    assert tiles["plan_keeper"]["last_run"]["status"] == "ok"
    assert tiles["plan_keeper"]["week"] == {"runs": 1, "turns": 1, "tokens": tiles["plan_keeper"]["last_run"]["tokens"], "cap": 10}
    assert client.put("/api/agents/tax/enabled", json={"enabled": False}).json() == {"desk": "tax", "enabled": False}
    assert client.put("/api/agents/nope/enabled", json={"enabled": False}).status_code == 404
    assert crew(cfg)["desks"][1]["enabled"] is False


def test_schema_applies_through_the_seam(desk_db):
    tables = {r[0] for r in desk_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agent_runs", "agent_settings"} <= tables


def test_cli_entrypoint(cfg, monkeypatch, capsys):
    from desk.agents.__main__ import main

    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    assert main(["status"]) == 0
    assert '"plan_keeper"' in capsys.readouterr().out
    assert main(["run", "skeptic"]) == 2
    assert "doesn't run on its own" in capsys.readouterr().out
