from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable, Literal

from .contract import ModelChoice
from .model_adapter import ProbeResult


class CodexAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class ExecSpec:
    role: Literal["executor", "reviewer"]
    choice: ModelChoice
    sandbox: Literal["workspace-write", "read-only"]
    schema: Path
    output: Path


def _base_argv(codex_command: Iterable[str], choice: ModelChoice, sandbox: str) -> list[str]:
    prefix = list(codex_command)
    if not prefix:
        raise CodexAdapterError("codex_command must not be empty")
    argv = prefix + [
        "--ask-for-approval", "never",
        "exec",
        "--sandbox", sandbox,
        "--json",
        "-c", "agents.enabled=false",
    ]
    if choice.name != "auto":
        argv += ["--model", choice.name]
    return argv + ["-c", "model_reasoning_effort=" + json.dumps(choice.effort)]


def build_exec_argv(codex_command: Iterable[str], spec: ExecSpec) -> list[str]:
    return _base_argv(codex_command, spec.choice, spec.sandbox) + [
        "--output-schema", str(spec.schema),
        "--output-last-message", str(spec.output),
        "-",
    ]


def probe_argv(codex_command: Iterable[str], choice: ModelChoice) -> list[str]:
    return _base_argv(codex_command, choice, "read-only") + ["-"]


@dataclass(frozen=True)
class StreamEvent:
    raw_type: str
    meaningful_progress: bool
    terminal: bool
    error: str | None = None


def classify_jsonl_line(line: str) -> StreamEvent:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CodexAdapterError(f"invalid Codex JSONL: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise CodexAdapterError("Codex JSONL event must be an object")
    event_type = str(value.get("type", "unknown"))
    lowered = event_type.lower()
    failed = any(token in lowered for token in ("error", "failed"))
    terminal = failed or any(token in lowered for token in ("completed", "complete", "finished"))
    error = str(value.get("message") or value.get("error") or event_type) if failed else None
    return StreamEvent(event_type, True, terminal, error)


@dataclass
class CodexProbeRunner:
    codex_command: tuple[str, ...] = ("codex",)
    timeout_seconds: int = 90

    def __call__(
        self,
        role: Literal["executor", "reviewer"],
        choice: ModelChoice,
    ) -> ProbeResult:
        with tempfile.TemporaryDirectory(prefix="codex-model-probe-") as tmp:
            try:
                completed = subprocess.run(
                    probe_argv(self.codex_command, choice),
                    cwd=Path(tmp),
                    input=(
                        "This is a model availability probe. Reply with OK only. "
                        "Do not inspect files, use tools or modify anything."
                    ),
                    text=True,
                    encoding="utf-8",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return ProbeResult(False, f"probe could not complete: {type(exc).__name__}")

        if completed.returncode == 0:
            return ProbeResult(True, f"{role} preflight passed")
        output = " ".join((completed.stdout or "").split())
        return ProbeResult(
            False,
            f"codex exited {completed.returncode}: {(output[:600] or 'no diagnostic output')}",
        )
