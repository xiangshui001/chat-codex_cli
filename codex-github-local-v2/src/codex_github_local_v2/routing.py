from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contract import ModelChoice, RoleModelPolicy
from .model_adapter import ProbeResult


@dataclass(frozen=True)
class SelectedModel:
    choice: ModelChoice
    fallback_index: int
    probe: ProbeResult


class ModelUnavailable(RuntimeError):
    pass


Probe = Callable[[ModelChoice], ProbeResult]


def select_model(policy: RoleModelPolicy, probe: Probe) -> SelectedModel:
    candidates = (policy.primary, *policy.fallbacks)
    reasons: list[str] = []
    for index, choice in enumerate(candidates):
        result = probe(choice)
        if result.available:
            return SelectedModel(choice=choice, fallback_index=index, probe=result)
        reasons.append(f"{choice.name}/{choice.effort}: {result.reason or 'unavailable'}")
    raise ModelUnavailable("no configured model is available; " + "; ".join(reasons))
