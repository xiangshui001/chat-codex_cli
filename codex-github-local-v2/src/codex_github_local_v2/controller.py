from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .contract import ModelChoice, TaskContract
from .routing import ModelUnavailable, ProbeResult, select_model
from .state import RunRecord, RunState


@dataclass(frozen=True)
class ExecutionResult:
    completed: bool
    summary: str = ""


@dataclass(frozen=True)
class ValidationResult:
    status: Literal["pass", "fail", "unavailable"]
    summary: str = ""


@dataclass(frozen=True)
class ReviewResult:
    verdict: Literal["pass", "reject"]
    summary: str = ""


@dataclass(frozen=True)
class PublicationResult:
    ok: bool
    reference: str = ""


class Backend(Protocol):
    def probe_model(self, role: Literal["executor", "reviewer"], choice: ModelChoice) -> ProbeResult: ...
    def execute(self, task: TaskContract, model: ModelChoice, attempt: int) -> ExecutionResult: ...
    def validate(self, task: TaskContract, attempt: int) -> ValidationResult: ...
    def review(self, task: TaskContract, model: ModelChoice, attempt: int) -> ReviewResult: ...
    def publish(self, task: TaskContract, *, draft: bool) -> PublicationResult: ...


class Controller:
    """Small deterministic core. GitHub/Git/Codex details belong in adapters."""

    def __init__(self, backend: Backend):
        self.backend = backend

    def run(self, task: TaskContract) -> RunRecord:
        record = RunRecord(task.task_id)
        record.transition(RunState.CLAIMED)
        record.transition(RunState.PREFLIGHT)

        try:
            executor = select_model(
                task.model_policy.executor,
                lambda choice: self.backend.probe_model("executor", choice),
            )
            reviewer = select_model(
                task.model_policy.reviewer,
                lambda choice: self.backend.probe_model("reviewer", choice),
            )
        except ModelUnavailable as exc:
            record.transition(RunState.MODEL_UNAVAILABLE, str(exc))
            return record

        manual_validation = False
        for attempt in range(1, task.budget.max_rounds + 1):
            record.transition(
                RunState.EXECUTING,
                f"attempt={attempt}; model={executor.choice.name}; effort={executor.choice.effort}",
            )
            execution = self.backend.execute(task, executor.choice, attempt)
            if not execution.completed:
                record.transition(RunState.EXECUTION_FAILED, execution.summary)
                return record

            record.transition(RunState.VALIDATING, f"attempt={attempt}")
            validation = self.backend.validate(task, attempt)
            if validation.status == "fail":
                if attempt < task.budget.max_rounds:
                    record.transition(RunState.EXECUTING, "validation failed; retry")
                    # The loop will record the next concrete execution attempt.
                    # Move back to validating-compatible state by continuing from EXECUTING.
                    # We do not call execute twice here; normalize to a fresh attempt below.
                    record.state = RunState.VALIDATING
                    continue
                record.transition(RunState.VALIDATION_INCOMPLETE, validation.summary)
                return record

            manual_validation = validation.status == "unavailable"
            if manual_validation:
                record.transition(RunState.MANUAL_REVIEW_REQUIRED, validation.summary)
                record.transition(RunState.REVIEWING, "independent review despite unavailable validation")
            else:
                record.transition(RunState.REVIEWING)

            review = self.backend.review(task, reviewer.choice, attempt)
            if review.verdict == "reject":
                if attempt < task.budget.max_rounds:
                    record.transition(RunState.EXECUTING, "review rejected; retry")
                    record.state = RunState.VALIDATING
                    continue
                record.transition(RunState.REVIEW_REJECTED, review.summary)
                return record

            record.transition(RunState.PUBLISH_READY, review.summary)
            if task.publication.mode == "none":
                return record

            draft = task.publication.mode == "draft_pr" or (
                manual_validation and task.publication.draft_on_incomplete_validation
            )
            published = self.backend.publish(task, draft=draft)
            if not published.ok:
                record.transition(RunState.PUBLICATION_FAILED, published.reference)
                return record
            record.transition(RunState.PR_OPEN, published.reference)
            return record

        raise AssertionError("unreachable")
