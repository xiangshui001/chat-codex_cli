from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time


class RunState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    PREFLIGHT = "preflight"
    EXECUTING = "executing"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    PUBLISH_READY = "publish_ready"
    PR_OPEN = "pr_open"
    ACCEPTED = "accepted"

    POLICY_BLOCKED = "policy_blocked"
    MODEL_UNAVAILABLE = "model_unavailable"
    EXECUTION_FAILED = "execution_failed"
    VALIDATION_INCOMPLETE = "validation_incomplete"
    REVIEW_REJECTED = "review_rejected"
    PUBLICATION_FAILED = "publication_failed"
    CANCELLED = "cancelled"


TERMINAL = {
    RunState.ACCEPTED,
    RunState.POLICY_BLOCKED,
    RunState.MODEL_UNAVAILABLE,
    RunState.EXECUTION_FAILED,
    RunState.VALIDATION_INCOMPLETE,
    RunState.REVIEW_REJECTED,
    RunState.PUBLICATION_FAILED,
    RunState.CANCELLED,
}

_ALLOWED = {
    RunState.QUEUED: {RunState.CLAIMED, RunState.CANCELLED},
    RunState.CLAIMED: {RunState.PREFLIGHT, RunState.POLICY_BLOCKED, RunState.CANCELLED},
    RunState.PREFLIGHT: {RunState.EXECUTING, RunState.MODEL_UNAVAILABLE, RunState.POLICY_BLOCKED, RunState.CANCELLED},
    RunState.EXECUTING: {RunState.VALIDATING, RunState.EXECUTION_FAILED, RunState.CANCELLED},
    RunState.VALIDATING: {
        RunState.REVIEWING,
        RunState.MANUAL_REVIEW_REQUIRED,
        RunState.EXECUTING,
        RunState.VALIDATION_INCOMPLETE,
        RunState.CANCELLED,
    },
    RunState.MANUAL_REVIEW_REQUIRED: {RunState.REVIEWING, RunState.PUBLISH_READY, RunState.CANCELLED},
    RunState.REVIEWING: {RunState.PUBLISH_READY, RunState.EXECUTING, RunState.REVIEW_REJECTED, RunState.CANCELLED},
    RunState.PUBLISH_READY: {RunState.PR_OPEN, RunState.ACCEPTED, RunState.PUBLICATION_FAILED, RunState.CANCELLED},
    RunState.PR_OPEN: {RunState.ACCEPTED, RunState.CANCELLED},
}


class StateError(RuntimeError):
    pass


@dataclass
class Event:
    state: RunState
    at: float
    detail: str = ""


@dataclass
class RunRecord:
    task_id: str
    state: RunState = RunState.QUEUED
    events: list[Event] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.events:
            self.events.append(Event(self.state, time(), "created"))

    def transition(self, target: RunState, detail: str = "") -> None:
        allowed = _ALLOWED.get(self.state, set())
        if target not in allowed:
            raise StateError(f"invalid transition: {self.state.value} -> {target.value}")
        self.state = target
        self.events.append(Event(target, time(), detail))

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL
