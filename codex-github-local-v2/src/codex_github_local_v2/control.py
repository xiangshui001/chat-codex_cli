from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from typing import Any, Literal

from .contract import ContractError, Effort, ModelChoice

CONTROL_TITLE_PREFIX = "[codex-control] "
CONTROL_MARKER = "/codex-local control"
_CONTROL_ID = re.compile(r"^GH-[1-9][0-9]*$")
_ACTIONS = {"set-default-model", "pause", "resume", "status"}
_ROLES = {"executor", "reviewer", "both"}


class ControlError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeSettings:
    """Mutable local defaults. Claimed tasks keep their frozen snapshot."""

    paused: bool = False
    executor_model: str = "auto"
    executor_effort: Effort = "medium"
    reviewer_model: str = "auto"
    reviewer_effort: Effort = "high"
    revision: int = 0
    last_control_id: str | None = None

    def model_for(self, role: Literal["executor", "reviewer"]) -> ModelChoice:
        if role == "executor":
            return ModelChoice(self.executor_model, self.executor_effort)
        return ModelChoice(self.reviewer_model, self.reviewer_effort)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "executor": {"model": self.executor_model, "effort": self.executor_effort},
            "reviewer": {"model": self.reviewer_model, "effort": self.reviewer_effort},
            "revision": self.revision,
            "last_control_id": self.last_control_id,
        }


@dataclass(frozen=True)
class ControlCommand:
    version: int
    repository: str
    control_id: str
    action: Literal["set-default-model", "pause", "resume", "status"]
    role: Literal["executor", "reviewer", "both"] | None = None
    model: str | None = None
    effort: Effort | None = None
    reason: str = ""

    @classmethod
    def from_dict(cls, value: Any) -> "ControlCommand":
        if not isinstance(value, dict) or value.get("version") != 2:
            raise ControlError("control envelope requires version=2")
        repository = value.get("repository")
        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or repository.startswith("/")
            or repository.endswith("/")
        ):
            raise ControlError("repository must be OWNER/REPO")
        raw = value.get("control")
        if not isinstance(raw, dict):
            raise ControlError("control must be an object")
        control_id = raw.get("id")
        action = raw.get("action")
        if not isinstance(control_id, str) or not _CONTROL_ID.fullmatch(control_id):
            raise ControlError("control.id must match GH-N")
        if action not in _ACTIONS:
            raise ControlError(f"unsupported control action: {action!r}")
        expected = ({"id", "action", "reason", "role", "model", "effort"}\n                    if action == "set-default-model" else {"id", "action", "reason"})\n        if not set(raw).issubset(expected) or not {"id", "action"}.issubset(raw):\n            raise ControlError("control contains missing or unknown fields")\n        reason = raw.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 500:
            raise ControlError("control.reason must be a string up to 500 characters")

        role = raw.get("role")
        model = raw.get("model")
        effort = raw.get("effort")
        if action == "set-default-model":
            if role not in _ROLES:
                raise ControlError("set-default-model requires role=executor|reviewer|both")
            try:
                choice = ModelChoice.from_dict({"name": model, "effort": effort})
            except ContractError as exc:
                raise ControlError(str(exc)) from exc
            model = choice.name
            effort = choice.effort
        else:
            if role is not None or model is not None or effort is not None:
                raise ControlError(f"{action} does not accept role/model/effort")
            role = model = effort = None

        return cls(
            version=2,
            repository=repository,
            control_id=control_id,
            action=action,
            role=role,
            model=model,
            effort=effort,
            reason=reason,
        )


@dataclass(frozen=True)
class ControlResult:
    settings: RuntimeSettings
    changed: bool
    message: str


def parse_control_comment(body: str) -> ControlCommand:
    if not isinstance(body, str):
        raise ControlError("comment body must be text")
    lines = body.splitlines()
    if not lines or lines[0].strip() != CONTROL_MARKER:
        raise ControlError("first line must be /codex-local control")
    rest = "\n".join(lines[1:]).strip()
    match = re.fullmatch(r"~~~json\s*\n(.*?)\n~~~", rest, flags=re.DOTALL)
    if not match:
        raise ControlError("control comment must contain exactly one json block and no extra text")
    try:
        payload = json.loads(match.group("body"))
    except json.JSONDecodeError as exc:
        raise ControlError(f"invalid control json: {exc.msg}") from exc
    return ControlCommand.from_dict(payload)


def apply_control(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    """Apply an authenticated command without mutating any already claimed task."""

    if settings.last_control_id == command.control_id:
        return ControlResult(settings, False, "duplicate control command ignored")

    if command.action == "status":
        updated = replace(
            settings,
            revision=settings.revision + 1,
            last_control_id=command.control_id,
        )
        return ControlResult(updated, False, "status requested; runtime defaults unchanged")

    if command.action == "pause":
        updated = replace(
            settings,
            paused=True,
            revision=settings.revision + 1,
            last_control_id=command.control_id,
        )
        return ControlResult(updated, not settings.paused, "queue paused for new task claims")

    if command.action == "resume":
        updated = replace(
            settings,
            paused=False,
            revision=settings.revision + 1,
            last_control_id=command.control_id,
        )
        return ControlResult(updated, settings.paused, "queue resumed")

    assert command.action == "set-default-model"
    assert command.role is not None and command.model is not None and command.effort is not None
    kwargs: dict[str, Any] = {
        "revision": settings.revision + 1,
        "last_control_id": command.control_id,
    }
    if command.role in {"executor", "both"}:
        kwargs.update(executor_model=command.model, executor_effort=command.effort)
    if command.role in {"reviewer", "both"}:
        kwargs.update(reviewer_model=command.model, reviewer_effort=command.effort)
    updated = replace(settings, **kwargs)
    return ControlResult(
        updated,
        updated != settings,
        f"default model updated for {command.role}; applies to tasks claimed after this control command",
    )
