import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from desk.agents.desks import Desk

LIMIT = re.compile(r"usage limit|rate limit|limit reached|resets? (at|in)|\b429\b|overloaded", re.IGNORECASE)
DROPPED = re.compile(r"ECONNRESET|socket hang up|connection (reset|refused|closed)|network error|ETIMEDOUT", re.IGNORECASE)
RETRY_WAITS = (5, 15, 30, 60)
TIMEOUT_S = 20 * 60


class AgentError(RuntimeError):
    pass


class UsageLimitError(AgentError):
    pass


class AgentTimeout(AgentError):
    pass


@dataclass
class AgentResult:
    text: str
    structured: dict | None
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    duration_ms: int = 0
    cost_estimate: float = 0.0
    session_id: str = ""
    model: str = ""

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_tokens


class Adapter(Protocol):
    def run(self, desk: Desk, system: str, prompt: str, schema: dict | None = None) -> AgentResult: ...


def parse_output(stdout: str, *, model: str = "") -> AgentResult:
    try:
        body = json.loads(stdout)
    except ValueError:
        raise AgentError(f"unreadable CLI output: {stdout[:200]!r}") from None
    if isinstance(body, list):
        body = next((m for m in reversed(body) if isinstance(m, dict) and m.get("type") == "result"), {})
    text = str(body.get("result") or "")
    if body.get("is_error") or body.get("subtype", "success") != "success":
        detail = text or str(body.get("subtype") or "error")
        if LIMIT.search(detail) or body.get("api_error_status") == 429:
            raise UsageLimitError(detail[:300])
        raise AgentError(detail[:300])
    usage = body.get("usage") or {}
    by_model = body.get("modelUsage") if isinstance(body.get("modelUsage"), dict) else {}
    served = max(by_model, key=lambda k: int((by_model[k] or {}).get("outputTokens") or 0), default="") if by_model else ""
    return AgentResult(
        text=text,
        structured=body.get("structured_output"),
        turns=int(body.get("num_turns") or 0),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_tokens=int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0),
        duration_ms=int(body.get("duration_ms") or 0),
        cost_estimate=float(body.get("total_cost_usd") or 0.0),
        session_id=str(body.get("session_id") or ""),
        model=str(served or model),
    )


@dataclass
class ClaudeCli:
    binary: str = field(default_factory=lambda: os.environ.get("DESK_CLAUDE_BIN", "claude"))
    timeout_s: int = TIMEOUT_S
    waits: tuple[int, ...] = RETRY_WAITS
    sleep: Callable[[float], None] = time.sleep

    def command(self, desk: Desk, system_file: Path, schema: dict | None) -> list[str]:
        tools = ",".join(desk.tools)
        cmd = [
            self.binary,
            "-p",
            "--model",
            desk.model,
            "--effort",
            desk.effort,
            "--tools",
            tools,
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--max-turns",
            str(desk.max_turns),
            "--no-session-persistence",
            "--output-format",
            "json",
            "--system-prompt-file",
            str(system_file),
        ]
        if tools:
            cmd += ["--allowedTools", tools]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
        return cmd

    def _once(self, cmd: list[str], prompt: str, cwd: Path) -> tuple[int, str, str]:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # noqa: S603
        try:
            out, err = proc.communicate(prompt, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)
            try:
                proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            raise AgentTimeout(f"no answer after {self.timeout_s // 60} minutes") from None
        return proc.returncode, out, err

    def run(self, desk: Desk, system: str, prompt: str, schema: dict | None = None) -> AgentResult:
        if shutil.which(self.binary) is None:
            raise AgentError(f"{self.binary} is not on PATH")
        with tempfile.TemporaryDirectory(prefix="desk-agent-") as tmp:
            cwd = Path(tmp) / "run"
            cwd.mkdir()
            system_file = Path(tmp) / "system.md"
            system_file.write_text(system)
            cmd = self.command(desk, system_file, schema)
            for attempt in range(len(self.waits) + 1):
                code, out, err = self._once(cmd, prompt, cwd)
                if out.strip():
                    return parse_output(out, model=desk.model)
                detail = (err or f"exit {code}").strip()
                if LIMIT.search(detail):
                    raise UsageLimitError(detail[:300])
                if not DROPPED.search(detail) or attempt == len(self.waits):
                    raise AgentError(detail[:300])
                self.sleep(self.waits[attempt])
        raise AgentError("unreachable")


@dataclass
class FakeAdapter:
    answers: dict[str, object] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def run(self, desk: Desk, system: str, prompt: str, schema: dict | None = None) -> AgentResult:
        self.calls.append({"desk": desk.name, "system": system, "prompt": prompt, "schema": schema})
        answer = self.answers.get(desk.name, {"ok": True})
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(prompt)
        structured = answer if isinstance(answer, dict) else None
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return AgentResult(text=text, structured=structured, turns=1, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4, model=desk.model)
