from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from .contract import TaskContract


class PolicyError(ValueError):
    pass


def normalize_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\\" in path:
        raise PolicyError(f"invalid repository path: {path!r}")
    if path == "**":
        return path
    if path.startswith("/"):
        raise PolicyError(f"absolute path is not allowed: {path}")
    raw = path[:-1] if path.endswith("/") else path
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise PolicyError(f"unsafe repository path: {path}")
    return path


def covered(path: str, rule: str) -> bool:
    path = normalize_path(path)
    rule = normalize_path(rule)
    if rule == "**":
        return True
    if rule.endswith("/"):
        return path == rule[:-1] or path.startswith(rule)
    return path == rule


def _covered_by_any(path: str, rules: Iterable[str]) -> bool:
    return any(covered(path, rule) for rule in rules)


@dataclass(frozen=True)
class HostPolicy:
    read_roots: tuple[str, ...] = ("**",)
    write_roots: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for rule in (*self.read_roots, *self.write_roots, *self.protected_paths):
            normalize_path(rule)


class PolicyEngine:
    def __init__(self, host: HostPolicy, task: TaskContract):
        self.host = host
        self.task = task
        self._validate_requested_scope()

    def _scope_within(self, requested: str, allowed: tuple[str, ...]) -> bool:
        requested = normalize_path(requested)
        if requested == "**":
            return "**" in allowed
        return _covered_by_any(requested[:-1] if requested.endswith("/") else requested, allowed)

    def _validate_requested_scope(self) -> None:
        for rule in self.task.read_scope:
            normalize_path(rule)
            if not self._scope_within(rule, self.host.read_roots):
                raise PolicyError(f"task read scope exceeds host policy: {rule}")
        for rule in self.task.write_scope:
            normalize_path(rule)
            if not self._scope_within(rule, self.host.write_roots):
                raise PolicyError(f"task write scope exceeds host policy: {rule}")
            if rule == "**":
                if self.host.protected_paths:
                    raise PolicyError("task cannot request write_scope='**' while protected paths exist")
            elif any(covered(rule[:-1] if rule.endswith("/") else rule, p) or covered(p.rstrip("/"), rule) for p in self.host.protected_paths):
                raise PolicyError(f"task write scope intersects protected path: {rule}")

    def can_read(self, path: str) -> bool:
        path = normalize_path(path)
        return _covered_by_any(path, self.task.read_scope) and _covered_by_any(path, self.host.read_roots)

    def can_write(self, path: str) -> bool:
        path = normalize_path(path)
        if _covered_by_any(path, self.host.protected_paths):
            return False
        return _covered_by_any(path, self.task.write_scope) and _covered_by_any(path, self.host.write_roots)

    def assert_reads(self, paths: Iterable[str]) -> None:
        denied = [path for path in paths if not self.can_read(path)]
        if denied:
            raise PolicyError("read outside scope: " + ", ".join(sorted(denied)))

    def assert_changes(self, paths: Iterable[str]) -> None:
        denied = [path for path in paths if not self.can_write(path)]
        if denied:
            raise PolicyError("write outside scope: " + ", ".join(sorted(denied)))
