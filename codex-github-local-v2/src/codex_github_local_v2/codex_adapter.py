from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Literal

from .contract import ModelChoice


class CodexAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class ExecSpec:
    role: Literal["executor", "reviewer"]
    choice: ModelChoice
    sandbox: Literal["workspace-write", "read-only"]
    schema: Path
    output: Path


def build_exec_argv(
    codex_command: Iterable[str],
    spec: ExecSpec,
) -> list[str]:
    """Build the same safe non-interactive shape used by the current 0.1.0 runner."""

    prefix = list(codex_command)
    if not prefix:
        raise CodexAdapterError("codex_command must not be empty")
    argv = prefix + [
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        spec.sandbox,
        "--json",
        "--output-schema",
        str(spec.schema),
        "--output-last-message",
        str(spec.output),
        "-c",
        "agents.enabled=false",
    ]
    if spec.choice.name != "auto":
        argv += ["--model", spec.choice.name]
    argv += [
        "-c",
        "model_reasoning_effort=" + json.dumps(spec.choice.effort),
        "-",
    ]
    return argv


def probe_argv(codex_command: Iterable[str], choice: ModelChoice) -> list[str]:
    """Minimal model entitlement probe.

    The real adapter should run this with a tiny prompt, read JSONL and discard any
    generated repository output. It must not execute inside a product worktree.
    """

    prefix = list(codex_command)
    if not prefix:
        raise CodexAdapterError("codex_command must not be empty")
    argv = prefix + [
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "read-only",
        "--json",
        "-c",
        "agents.enabled=false",
    ]
    if choice.name != "auto":
        argv += ["--model", choice.name]
    argv += [
        "-c",
        "model_reasoning_effort=" + json.dumps(choice.effort),
        "-",
    ]
    return argv


@dataclass(frozen=True)
class StreamEvent:
    raw_type: str
    meaningful_progress: bool
    terminal: bool
    error: str | None = None


def classify_jsonl_line(line: str) -> StreamEvent:
    """Classify Codex JSONL conservatively for future stall detection.

    Unknown well-formed events count as progress but are not treated as terminal.
    """

    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CodexAdapterError(f"invalid Codex JSONL: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise CodexAdapterError("Codex JSONL event must be an object")

    event_type = str(value.get("type", "unknown"))
    lowered = event_type.lower()
    error = None
    if "error" in lowered or "failed" in lowered:
        error = str(value.get("message") or value.get("error") or event_type)
    terminal = any(token in lowered for token in ("completed", "complete", "finished", "failed", "error"))
    return StreamEvent(
        raw_type=event_type,
        meaningful_progress=True,
        terminal=terminal,
        error=error,
    )
