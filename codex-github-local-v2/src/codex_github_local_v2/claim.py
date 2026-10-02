from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .contract import TaskContract
from .evidence import EvidenceStore
from .resolution import resolve_task_models
from .runtime_settings import RuntimeSettingsStore


class ClaimPaused(RuntimeError):
    pass


def freeze_claim(
    task: TaskContract,
    *,
    settings_store: RuntimeSettingsStore,
    evidence: EvidenceStore,
) -> TaskContract:
    """Resolve mutable runtime defaults exactly once when a task is claimed."""

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
