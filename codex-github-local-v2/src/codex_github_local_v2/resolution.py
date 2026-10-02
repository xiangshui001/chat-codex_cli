from __future__ import annotations

from dataclasses import replace

from .contract import ModelChoice, ModelPolicy, RoleModelPolicy, TaskContract
from .control import RuntimeSettings

RUNTIME_DEFAULT = "runtime-default"


def _resolve_role(policy: RoleModelPolicy, default: ModelChoice) -> RoleModelPolicy:
    primary = default if policy.primary.name == RUNTIME_DEFAULT else policy.primary
    fallbacks = tuple(
        default if choice.name == RUNTIME_DEFAULT else choice
        for choice in policy.fallbacks
    )
    return RoleModelPolicy(primary=primary, fallbacks=fallbacks)


def resolve_task_models(task: TaskContract, settings: RuntimeSettings) -> TaskContract:
    """Freeze runtime defaults into a claimed task before any Codex call.

    The raw Issue contract may use model name "runtime-default". The resolved task
    contains concrete choices and should be written to the evidence snapshot.
    """

    resolved = ModelPolicy(
        executor=_resolve_role(
            task.model_policy.executor,
            settings.model_for("executor"),
        ),
        reviewer=_resolve_role(
            task.model_policy.reviewer,
            settings.model_for("reviewer"),
        ),
    )
    return replace(task, model_policy=resolved)
