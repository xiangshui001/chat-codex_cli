from __future__ import annotations

from dataclasses import asdict, replace

from .contract import ModelChoice, ModelPolicy, RoleModelPolicy, TaskContract
from .control import RuntimeSettings, RuntimeSettingsStore
from .evidence import EvidenceStore

RUNTIME_DEFAULT = "runtime-default"


class ClaimPaused(RuntimeError):
    pass


def _resolve_role(policy: RoleModelPolicy, default: ModelChoice) -> RoleModelPolicy:
    resolve = lambda choice: default if choice.name == RUNTIME_DEFAULT else choice
    return RoleModelPolicy(
        primary=resolve(policy.primary),
        fallbacks=tuple(resolve(choice) for choice in policy.fallbacks),
    )


def resolve_task_models(task: TaskContract, settings: RuntimeSettings) -> TaskContract:
    return replace(
        task,
        model_policy=ModelPolicy(
            executor=_resolve_role(task.model_policy.executor, settings.model_for("executor")),
            reviewer=_resolve_role(task.model_policy.reviewer, settings.model_for("reviewer")),
        ),
    )


def freeze_claim(
    task: TaskContract,
    *,
    settings_store: RuntimeSettingsStore,
    evidence: EvidenceStore,
) -> TaskContract:
    settings = settings_store.load()
    if settings.paused:
        raise ClaimPaused("runtime is paused; new tasks are not claimed")

    resolved = resolve_task_models(task, settings)
    evidence.write_json(task.task_id, "task.raw.json", asdict(task))
    evidence.write_json(task.task_id, "runtime-settings.snapshot.json", settings.to_dict())
    evidence.write_json(task.task_id, "task.resolved.json", asdict(resolved))
    evidence.append_event(
        task.task_id,
        "claimed",
        {
            "runtime_revision": settings.revision,
            "executor_model": resolved.model_policy.executor.primary.name,
            "executor_effort": resolved.model_policy.executor.primary.effort,
            "reviewer_model": resolved.model_policy.reviewer.primary.name,
            "reviewer_effort": resolved.model_policy.reviewer.primary.effort,
        },
    )
    return resolved
