"""Small POSIX Codex process boundary. No model APIs or provider abstraction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MvpError(RuntimeError):
    """A controlled diagnostic code, safe to include in a public receipt."""


@dataclass(frozen=True)
class Execution:
    exit_code: int
    error: str | None


class CodexRunner:
    def __init__(self, command: tuple[str, ...] = ("codex",), *, max_log_bytes: int | None = None):
        self.command = command
        self.max_log_bytes = max_log_bytes

    def prepare(self, workspace: Path) -> dict:
        if os.name != "posix":
            raise MvpError("linux_or_wsl_required")
        try:
            version = subprocess.run(
                [*self.command, "--version"], capture_output=True, timeout=15,
                check=True, text=True, encoding="utf-8",
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise MvpError("codex_version_unavailable") from exc
        if not version or len(version) > 200:
            raise MvpError("invalid_codex_version")
        return {
            "cli_version": version,
            # The prompt is sent on stdin, never interpolated into shell/argv.
            "argv": [*self.command, "--ask-for-approval", "never", "exec", "--json",
                     "--sandbox", "workspace-write", "--color", "never", "-"],
            "cwd": str(workspace),
        }

    @staticmethod
    def _stop_group(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # Also stop descendants that outlived their session leader.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)

    def run(self, metadata: dict, prompt: str, evidence: Path, timeout: int,
            record: Callable[[str, dict], None]) -> Execution:
        evidence.mkdir(parents=True, exist_ok=False, mode=0o700)
        stdout_path, stderr_path = evidence / "stdout.jsonl", evidence / "stderr.log"
        audit = {**metadata, "started_at": utc_now(), "pid": None, "exit_code": None}
        audit_path = evidence / "execution.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        proc = None
        error = None
        env = dict(os.environ)
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            env.pop(key, None)
        try:
            # Direct files keep stdout/stderr independent and avoid a full pipe deadlock.
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                proc = subprocess.Popen(
                    metadata["argv"], cwd=metadata["cwd"], stdin=subprocess.PIPE,
                    stdout=stdout, stderr=stderr, env=env, start_new_session=True,
                )
                audit["pid"] = proc.pid
                record("process_started", {"pid": proc.pid, "at": utc_now()})
                deadline = time.monotonic() + timeout if timeout is not None else float("inf")
                first = True
                while True:
                    try:
                        proc.communicate(input=prompt.encode("utf-8") if first else None, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        first = False
                        if time.monotonic() >= deadline:
                            error = "execution_timeout"
                            break
                        if self.max_log_bytes is not None and stdout_path.stat().st_size + stderr_path.stat().st_size > self.max_log_bytes:
                            error = "log_limit_exceeded"
                            break
        except KeyboardInterrupt:
            error = "interrupted"
        except OSError as exc:
            error = "codex_process_io_failed"
            raise MvpError("codex_process_io_failed") from exc
        finally:
            if proc is not None:
                try:
                    self._stop_group(proc)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise MvpError("process_cleanup_failed") from exc
                audit["exit_code"] = proc.returncode
                audit["cleanup"] = "process_group_terminated"
            audit["finished_at"] = utc_now()
            audit["error"] = error
            audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        if proc is None:
            raise MvpError("codex_not_started")
        if self.max_log_bytes is not None and stdout_path.stat().st_size + stderr_path.stat().st_size > self.max_log_bytes:
            error = error or "log_limit_exceeded"
        if error:
            return Execution(proc.returncode, error)
        completed, failed = False, False
        try:
            with stdout_path.open(encoding="utf-8") as stream:
                for line in stream:
                    event = json.loads(line)
                    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                        raise ValueError("invalid event")
                    completed |= event["type"] == "turn.completed"
                    failed |= event["type"] in {"turn.failed", "error"}
        except (ValueError, UnicodeError):
            return Execution(proc.returncode, "invalid_jsonl")
        if proc.returncode != 0:
            return Execution(proc.returncode, "codex_nonzero_exit")
        if failed:
            return Execution(proc.returncode, "codex_turn_failed")
        if not completed:
            return Execution(proc.returncode, "missing_turn_completed")
        return Execution(proc.returncode, None)
