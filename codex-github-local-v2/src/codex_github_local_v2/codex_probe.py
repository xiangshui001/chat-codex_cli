from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable, Literal

from .codex_adapter import probe_argv
from .contract import ModelChoice
from .routing import ProbeResult


@dataclass
class CodexProbeRunner:
    codex_command: tuple[str, ...] = ("codex",)
    timeout_seconds: int = 90

    def __call__(
        self,
        role: Literal["executor", "reviewer"],
        choice: ModelChoice,
    ) -> ProbeResult:
        # Probe outside any product checkout so a model entitlement check cannot
        # accidentally modify the target repository.
        with tempfile.TemporaryDirectory(prefix="codex-model-probe-") as tmp:
            argv = probe_argv(self.codex_command, choice)
            prompt = (
                "This is a model availability probe. Reply with OK only. "
                "Do not inspect files, do not use tools, and do not modify anything."
            )
            try:
                completed = subprocess.run(
                    argv,
                    cwd=Path(tmp),
                    input=prompt,
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

        output = (completed.stdout or "").replace("\n", " ").strip()
        if len(output) > 600:
            output = output[:600] + "..."
        return ProbeResult(
            False,
            f"codex exited {completed.returncode}: {output or 'no diagnostic output'}",
        )
