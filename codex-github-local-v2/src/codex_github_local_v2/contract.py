from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

TaskType = Literal[
    "audit-readonly",
    "code-change",
    "bugfix",
    "ui-prototype",
    "refactor",
    "data-check",
    "documentation",
]
Effort = Literal["low", "medium", "high", "xhigh"]
NetworkMode = Literal["deny", "allowlist", "allow"]
PublicationMode = Literal["pr", "draft_pr", "none"]

_TASK_TYPES = {
    "audit-readonly",
    "code-change",
    "bugfix",
    "ui-prototype",
    "refactor",
    "data-check",
    "documentation",
}
_EFFORTS = {"low", "medium", "high", "xhigh"}
_NETWORK = {"deny", "allowlist", "allow"}
_PUBLICATION = {"pr", "draft_pr", "none"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_ID = re.compile(r"^GH-[1-9][0-9]*$")


class ContractError(ValueError):
    pass


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def _list_of_str(value: Any, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{name} must be a {'possibly empty ' if allow_empty else ''}list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractError(f"{name} must contain non-empty strings")
    return tuple(value)


@dataclass(frozen=True)
class ModelChoice:
    name: str
    effort: Effort = "medium"

    @classmethod
    def from_dict(cls, value: Any) -> "ModelChoice":
        data = _dict(value, "model choice")
        name = data.get("name")
        effort = data.get("effort", "medium")
        if not isinstance(name, str) or not name.strip():
            raise ContractError("model choice name must be a non-empty string")
        if effort not in _EFFORTS:
            raise ContractError(f"unsupported reasoning effort: {effort!r}")
        return cls(name=name, effort=effort)


@dataclass(frozen=True)
class RoleModelPolicy:
    primary: ModelChoice
    fallbacks: tuple[ModelChoice, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "RoleModelPolicy":
        data = _dict(value, "role model policy")
        primary = ModelChoice.from_dict(data.get("primary"))
        raw_fallbacks = data.get("fallbacks", [])
        if not isinstance(raw_fallbacks, list):
            raise ContractError("fallbacks must be a list")
        return cls(primary=primary, fallbacks=tuple(ModelChoice.from_dict(x) for x in raw_fallbacks))


@dataclass(frozen=True)
class ModelPolicy:
    executor: RoleModelPolicy
    reviewer: RoleModelPolicy

    @classmethod
    def from_dict(cls, value: Any) -> "ModelPolicy":
        data = _dict(value, "model_policy")
        return cls(
            executor=RoleModelPolicy.from_dict(data.get("executor")),
            reviewer=RoleModelPolicy.from_dict(data.get("reviewer")),
        )


@dataclass(frozen=True)
class Budget:
    max_rounds: int = 2
    max_minutes: int = 45
    review_rounds: int = 1

    @classmethod
    def from_dict(cls, value: Any) -> "Budget":
        data = _dict(value, "budget")
        max_rounds = data.get("max_rounds", 2)
        max_minutes = data.get("max_minutes", 45)
        review_rounds = data.get("review_rounds", 1)
        for name, number, upper in (
            ("max_rounds", max_rounds, 5),
            ("max_minutes", max_minutes, 240),
            ("review_rounds", review_rounds, 5),
        ):
            if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= upper:
                raise ContractError(f"{name} must be an integer in 1..{upper}")
        return cls(max_rounds=max_rounds, max_minutes=max_minutes, review_rounds=review_rounds)


@dataclass(frozen=True)
class PublicationPolicy:
    mode: PublicationMode = "pr"
    draft_on_incomplete_validation: bool = True

    @classmethod
    def from_dict(cls, value: Any) -> "PublicationPolicy":
        data = _dict(value, "publication")
        mode = data.get("mode", "pr")
        draft = data.get("draft_on_incomplete_validation", True)
        if mode not in _PUBLICATION:
            raise ContractError(f"unsupported publication mode: {mode!r}")
        if type(draft) is not bool:
            raise ContractError("draft_on_incomplete_validation must be boolean")
        return cls(mode=mode, draft_on_incomplete_validation=draft)


@dataclass(frozen=True)
class TaskContract:
    version: int
    repository: str
    base_sha: str
    task_id: str
    task_type: TaskType
    title: str
    goal: str
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    checks: tuple[str, ...]
    acceptance: tuple[str, ...]
    model_policy: ModelPolicy
    budget: Budget
    network: NetworkMode
    production: Literal["deny"]
    publication: PublicationPolicy
    context: str = ""

    @classmethod
    def from_dict(cls, value: Any) -> "TaskContract":
        envelope = _dict(value, "contract")
        if envelope.get("version") != 2:
            raise ContractError("v2 prototype requires version=2")
        repository = envelope.get("repository")
        base_sha = envelope.get("base_sha")
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ContractError("repository must be OWNER/REPO")
        if not isinstance(base_sha, str) or not _SHA40.fullmatch(base_sha):
            raise ContractError("base_sha must be a lowercase 40-character commit SHA")

        task = _dict(envelope.get("task"), "task")
        task_id = task.get("id")
        task_type = task.get("type")
        title = task.get("title")
        goal = task.get("goal")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ContractError("task.id must look like GH-N")
        if task_type not in _TASK_TYPES:
            raise ContractError(f"unsupported task type: {task_type!r}")
        if not isinstance(title, str) or not title.strip():
            raise ContractError("task.title must be non-empty")
        if not isinstance(goal, str) or not goal.strip():
            raise ContractError("task.goal must be non-empty")

        network = task.get("network", "deny")
        production = task.get("production", "deny")
        if network not in _NETWORK:
            raise ContractError(f"unsupported network mode: {network!r}")
        if production != "deny":
            raise ContractError("prototype only accepts production='deny'")

        context = task.get("context", "")
        if not isinstance(context, str):
            raise ContractError("task.context must be a string")

        return cls(
            version=2,
            repository=repository,
            base_sha=base_sha,
            task_id=task_id,
            task_type=task_type,
            title=title,
            goal=goal,
            read_scope=_list_of_str(task.get("read_scope"), "task.read_scope"),
            write_scope=_list_of_str(task.get("write_scope"), "task.write_scope", allow_empty=True),
            checks=_list_of_str(task.get("checks", []), "task.checks", allow_empty=True),
            acceptance=_list_of_str(task.get("acceptance"), "task.acceptance"),
            model_policy=ModelPolicy.from_dict(task.get("model_policy")),
            budget=Budget.from_dict(task.get("budget", {})),
            network=network,
            production=production,
            publication=PublicationPolicy.from_dict(task.get("publication", {})),
            context=context,
        )
