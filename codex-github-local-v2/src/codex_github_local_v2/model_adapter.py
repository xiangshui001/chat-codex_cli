"""Provider I/O boundary. The current runtime needs availability probes only.

Adapters own provider commands, endpoints, credentials and provider error mapping.
Routing and control own policy and state; neither selects a provider by name.
Generation/streaming is intentionally deferred until a real backend needs it.
"""
from dataclasses import dataclass
from typing import Literal, Protocol

from .contract import ModelChoice

ModelRole = Literal["executor", "reviewer"]


@dataclass(frozen=True)
class ProbeResult:
    available: bool
    reason: str = ""


class ModelAdapter(Protocol):
    def __call__(self, role: ModelRole, choice: ModelChoice) -> ProbeResult: ...
