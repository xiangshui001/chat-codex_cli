from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Literal

from .contract import Effort, ModelChoice
from .control import ControlCommand, ControlResult, RuntimeSettings, apply_control
from .routing import ProbeResult


class RuntimeSettingsError(RuntimeError):
    pass


Probe = Callable[[Literal["executor", "reviewer"], ModelChoice], ProbeResult]


@dataclass(frozen=True)
class AppliedControl:
    result: ControlResult
    probes: tuple[tuple[str, ModelChoice, ProbeResult], ...]


class RuntimeSettingsStore:
    """Atomic local runtime defaults; secrets and Codex auth never belong here."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> RuntimeSettings:
        if not self.path.exists():
            return RuntimeSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeSettingsError("runtime settings are unreadable or invalid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeSettingsError("runtime settings must be an object")
        allowed = {"paused", "executor", "reviewer", "revision", "last_control_id"}
        if set(data) - allowed:
            raise RuntimeSettingsError("runtime settings contain unknown fields")
        if type(data.get("paused", False)) is not bool:
            raise RuntimeSettingsError("paused must be boolean")
        executor = data.get("executor", {})
        reviewer = data.get("reviewer", {})
        if not isinstance(executor, dict) or not isinstance(reviewer, dict):
            raise RuntimeSettingsError("executor and reviewer settings must be objects")
        for name, role in (("executor", executor), ("reviewer", reviewer)):
            if set(role) - {"model", "effort"}:
                raise RuntimeSettingsError(f"{name} settings contain unknown fields")
            model = role.get("model", "auto")
            if not isinstance(model, str) or not model or len(model) > 160:
                raise RuntimeSettingsError(f"{name} model must be a non-empty string up to 160 characters")
        revision = data.get("revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise RuntimeSettingsError("revision must be a non-negative integer")
        last_control_id = data.get("last_control_id")
        if last_control_id is not None and (
            not isinstance(last_control_id, str)
            or not last_control_id.startswith("GH-")
            or not last_control_id[3:].isdigit()
        ):
            raise RuntimeSettingsError("last_control_id must be null or GH-N")
        return RuntimeSettings(
            paused=data.get("paused", False),
            executor_model=executor.get("model", "auto"),
            executor_effort=_effort(executor.get("effort", "medium")),
            reviewer_model=reviewer.get("model", "auto"),
            reviewer_effort=_effort(reviewer.get("effort", "high")),
            revision=revision,
            last_control_id=last_control_id,
        )

    def save(self, settings: RuntimeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=self.path.parent,
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)


class RuntimeControlService:
    """Preflight then atomically commit a GitHub control command."""

    def __init__(self, store: RuntimeSettingsStore, probe: Probe):
        self.store = store
        self.probe = probe

    def apply(self, command: ControlCommand) -> AppliedControl:
        current = self.store.load()
        if current.last_control_id == command.control_id:
            return AppliedControl(
                ControlResult(current, False, "duplicate control command ignored"),
                (),
            )

        probes: list[tuple[str, ModelChoice, ProbeResult]] = []
        if command.action == "set-default-model":
            assert command.model is not None and command.effort is not None and command.role is not None
            choice = ModelChoice(command.model, command.effort)
            roles = (
                ("executor", "reviewer")
                if command.role == "both"
                else (command.role,)
            )
            for role in roles:
                result = self.probe(role, choice)
                probes.append((role, choice, result))
                if not result.available:
                    reason = result.reason or "unavailable"
                    raise RuntimeSettingsError(
                        f"model preflight failed for {role}: {choice.name}/{choice.effort}: {reason}"
                    )

        result = apply_control(current, command)
        # Persist last_control_id even for status so replay is still idempotent.
        self.store.save(result.settings)
        return AppliedControl(result, tuple(probes))


def _effort(value: object) -> Effort:
    if value not in {"low", "medium", "high", "xhigh"}:
        raise RuntimeSettingsError(f"invalid stored reasoning effort: {value!r}")
    return value  # type: ignore[return-value]
