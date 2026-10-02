from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterable, Literal, Protocol

from .contract import ContractError, Effort, ModelChoice
from .github_protocol import (
    CommentView,
    GitHubProtocolError,
    GitHubProtocolPending,
    IssueProtocol,
    IssueView,
    validate_issue,
)
from .routing import ProbeResult

CONTROL_TITLE_PREFIX = "[codex-control] "
CONTROL_MARKER = "/codex-local control"


class ControlError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeSettings:
    paused: bool = False
    executor_model: str = "auto"
    executor_effort: Effort = "medium"
    reviewer_model: str = "auto"
    reviewer_effort: Effort = "high"
    revision: int = 0
    last_control_id: str | None = None

    def model_for(self, role: Literal["executor", "reviewer"]) -> ModelChoice:
        name, effort = {
            "executor": (self.executor_model, self.executor_effort),
            "reviewer": (self.reviewer_model, self.reviewer_effort),
        }[role]
        return ModelChoice(name, effort)

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
        if not isinstance(value, dict) or set(value) != {"version", "repository", "control"}:
            raise ControlError("control envelope must contain version, repository and control")
        if value["version"] != 2:
            raise ControlError("control envelope requires version=2")
        repository = value["repository"]
        if not isinstance(repository, str) or repository.count("/") != 1:
            raise ControlError("repository must be OWNER/REPO")
        raw = value["control"]
        if not isinstance(raw, dict):
            raise ControlError("control must be an object")
        parser = _ACTION_PARSERS.get(raw.get("action"))
        if parser is None:
            raise ControlError(f"unsupported control action: {raw.get('action')!r}")
        common = _parse_common(raw)
        role, model, effort = parser(raw)
        return cls(
            version=2,
            repository=repository,
            control_id=common["id"],
            action=raw["action"],
            role=role,
            model=model,
            effort=effort,
            reason=common["reason"],
        )


def _parse_common(raw: dict[str, Any]) -> dict[str, str]:
    control_id = raw.get("id")
    if (
        not isinstance(control_id, str)
        or not control_id.startswith("GH-")
        or not control_id[3:].isdigit()
        or control_id == "GH-0"
    ):
        raise ControlError("control.id must match GH-N")
    reason = raw.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 500:
        raise ControlError("control.reason must be a string up to 500 characters")
    return {"id": control_id, "reason": reason}


def _parse_simple(raw: dict[str, Any]):
    if set(raw) - {"id", "action", "reason"}:
        raise ControlError("simple control action contains unknown fields")
    return None, None, None


def _parse_model(raw: dict[str, Any]):
    required = {"id", "action", "role", "model", "effort"}
    allowed = required | {"reason"}
    if not required.issubset(raw) or set(raw) - allowed:
        raise ControlError("set-default-model requires role, model and effort only")
    role = raw["role"]
    if role not in {"executor", "reviewer", "both"}:
        raise ControlError("role must be executor, reviewer or both")
    try:
        choice = ModelChoice.from_dict({"name": raw["model"], "effort": raw["effort"]})
    except ContractError as exc:
        raise ControlError(str(exc)) from exc
    return role, choice.name, choice.effort


_ACTION_PARSERS = {
    "set-default-model": _parse_model,
    "pause": _parse_simple,
    "resume": _parse_simple,
    "status": _parse_simple,
}


@dataclass(frozen=True)
class ControlResult:
    settings: RuntimeSettings
    changed: bool
    message: str


def _apply_status(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    return ControlResult(
        replace(settings, last_control_id=command.control_id),
        False,
        "status requested; runtime defaults unchanged",
    )


def _apply_pause(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    updated = replace(
        settings,
        paused=True,
        revision=settings.revision + 1,
        last_control_id=command.control_id,
    )
    return ControlResult(updated, not settings.paused, "queue paused for new task claims")


def _apply_resume(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    updated = replace(
        settings,
        paused=False,
        revision=settings.revision + 1,
        last_control_id=command.control_id,
    )
    return ControlResult(updated, settings.paused, "queue resumed")


def _apply_model(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    assert command.role and command.model and command.effort
    fields = {
        "executor": {
            "executor_model": command.model,
            "executor_effort": command.effort,
        },
        "reviewer": {
            "reviewer_model": command.model,
            "reviewer_effort": command.effort,
        },
        "both": {
            "executor_model": command.model,
            "executor_effort": command.effort,
            "reviewer_model": command.model,
            "reviewer_effort": command.effort,
        },
    }[command.role]
    updated = replace(
        settings,
        **fields,
        revision=settings.revision + 1,
        last_control_id=command.control_id,
    )
    return ControlResult(updated, updated != settings, f"default model updated for {command.role}")


_ACTION_HANDLERS = {
    "set-default-model": _apply_model,
    "pause": _apply_pause,
    "resume": _apply_resume,
    "status": _apply_status,
}


def apply_control(settings: RuntimeSettings, command: ControlCommand) -> ControlResult:
    if settings.last_control_id == command.control_id:
        return ControlResult(settings, False, "duplicate control command ignored")
    return _ACTION_HANDLERS[command.action](settings, command)


CONTROL_PROTOCOL = IssueProtocol[ControlCommand](
    title_prefix=CONTROL_TITLE_PREFIX,
    marker=CONTROL_MARKER,
    decode=ControlCommand.from_dict,
    item_id=lambda command: command.control_id,
)


def validate_control_issue(
    issue: IssueView,
    comments: Iterable[CommentView],
    *,
    repository: str,
    authorized_users: Iterable[str],
) -> ControlCommand:
    return validate_issue(
        issue,
        comments,
        repository=repository,
        authorized_users=authorized_users,
        protocol=CONTROL_PROTOCOL,
    )


class RuntimeSettingsError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class RuntimeSettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> RuntimeSettings:
        if not self.path.exists():
            return RuntimeSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeSettingsError("runtime settings are unreadable") from exc
        return _settings_from_dict(data)

    def save(self, settings: RuntimeSettings) -> None:
        _atomic_json(self.path, settings.to_dict())


def _settings_from_dict(data: Any) -> RuntimeSettings:
    if not isinstance(data, dict):
        raise RuntimeSettingsError("runtime settings must be an object")
    allowed = {"paused", "executor", "reviewer", "revision", "last_control_id"}
    if set(data) - allowed or type(data.get("paused", False)) is not bool:
        raise RuntimeSettingsError("runtime settings contain invalid fields")

    roles = {}
    for name, default_effort in (("executor", "medium"), ("reviewer", "high")):
        value = data.get(name, {})
        if not isinstance(value, dict) or set(value) - {"model", "effort"}:
            raise RuntimeSettingsError(f"invalid {name} settings")
        try:
            roles[name] = ModelChoice.from_dict(
                {
                    "name": value.get("model", "auto"),
                    "effort": value.get("effort", default_effort),
                }
            )
        except ContractError as exc:
            raise RuntimeSettingsError(str(exc)) from exc

    revision = data.get("revision", 0)
    last = data.get("last_control_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise RuntimeSettingsError("revision must be a non-negative integer")
    if last is not None and (
        not isinstance(last, str) or not last.startswith("GH-") or not last[3:].isdigit()
    ):
        raise RuntimeSettingsError("last_control_id must be null or GH-N")

    return RuntimeSettings(
        paused=data.get("paused", False),
        executor_model=roles["executor"].name,
        executor_effort=roles["executor"].effort,
        reviewer_model=roles["reviewer"].name,
        reviewer_effort=roles["reviewer"].effort,
        revision=revision,
        last_control_id=last,
    )


Probe = Callable[[Literal["executor", "reviewer"], ModelChoice], ProbeResult]


@dataclass(frozen=True)
class AppliedControl:
    result: ControlResult
    probes: tuple[tuple[str, ModelChoice, ProbeResult], ...]


class RuntimeControlService:
    def __init__(self, store: RuntimeSettingsStore, probe: Probe):
        self.store = store
        self.probe = probe

    def apply(self, command: ControlCommand) -> AppliedControl:
        current = self.store.load()
        if current.last_control_id == command.control_id:
            return AppliedControl(ControlResult(current, False, "duplicate control command ignored"), ())
        probes = tuple(self._preflight(command))
        result = apply_control(current, command)
        self.store.save(result.settings)
        return AppliedControl(result, probes)

    def _preflight(self, command: ControlCommand):
        if command.action != "set-default-model":
            return
        assert command.role and command.model and command.effort
        choice = ModelChoice(command.model, command.effort)
        roles = {
            "executor": ("executor",),
            "reviewer": ("reviewer",),
            "both": ("executor", "reviewer"),
        }[command.role]
        for role in roles:
            result = self.probe(role, choice)
            yield role, choice, result
            if not result.available:
                raise RuntimeSettingsError(
                    f"model preflight failed for {role}: "
                    f"{choice.name}/{choice.effort}: {result.reason or 'unavailable'}"
                )


class LedgerError(RuntimeError):
    pass


def command_fingerprint(command: ControlCommand) -> str:
    payload = json.dumps(
        asdict(command),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ControlLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "records": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("records"), dict):
            raise LedgerError("invalid control ledger")
        return data

    def get(self, control_id: str) -> dict[str, Any] | None:
        return self._load()["records"].get(control_id)

    def record(
        self,
        command: ControlCommand,
        *,
        outcome: str,
        message: str,
        revision: int,
    ) -> dict[str, Any]:
        data = self._load()
        fingerprint = command_fingerprint(command)
        existing = data["records"].get(command.control_id)
        if existing:
            if existing.get("fingerprint") != fingerprint:
                raise LedgerError("control id reused with different content")
            return existing
        row = {
            "fingerprint": fingerprint,
            "outcome": outcome,
            "message": message,
            "revision": revision,
            "recorded_at": time.time(),
        }
        data["records"][command.control_id] = row
        _atomic_json(self.path, data)
        return row


class ControlSource(Protocol):
    def list_open_control_issues(self) -> Iterable[IssueView]: ...
    def list_comments(self, issue_number: int) -> Iterable[CommentView]: ...
    def post_comment(self, issue_number: int, body: str) -> None: ...


@dataclass(frozen=True)
class TickResult:
    status: str
    issue_number: int | None = None
    message: str = ""


def status_receipt(settings: RuntimeSettings, *, outcome: str, message: str) -> str:
    return (
        f"<!-- codex-local-control {outcome} -->\n\n"
        f"控制结果：{outcome}\n\n"
        f"- paused: {str(settings.paused).lower()}\n"
        f"- revision: {settings.revision}\n"
        f"- executor: {settings.executor_model} / {settings.executor_effort}\n"
        f"- reviewer: {settings.reviewer_model} / {settings.reviewer_effort}\n"
        f"- message: {message}\n"
    )


class ControlProcessor:
    def __init__(
        self,
        *,
        repository: str,
        authorized_users: Iterable[str],
        source: ControlSource,
        runtime: RuntimeControlService,
        ledger: ControlLedger,
    ):
        self.repository = repository
        self.authorized_users = tuple(authorized_users)
        self.source = source
        self.runtime = runtime
        self.ledger = ledger

    def tick(self) -> TickResult:
        rejection = None
        for issue in sorted(self.source.list_open_control_issues(), key=lambda x: x.number):
            if issue.author not in self.authorized_users:
                continue
            try:
                command = validate_control_issue(
                    issue,
                    list(self.source.list_comments(issue.number)),
                    repository=self.repository,
                    authorized_users=self.authorized_users,
                )
            except GitHubProtocolPending:
                continue
            except GitHubProtocolError as exc:
                rejection = TickResult("rejected", issue.number, str(exc))
                continue

            existing = self.ledger.get(command.control_id)
            if existing:
                if existing.get("fingerprint") != command_fingerprint(command):
                    return TickResult("rejected", issue.number, "control id reused with different content")
                continue
            return self._apply(issue.number, command)
        return rejection or TickResult("pending")

    def _apply(self, issue_number: int, command: ControlCommand) -> TickResult:
        try:
            applied = self.runtime.apply(command)
            settings = applied.result.settings
            outcome = "applied"
            message = applied.result.message
        except RuntimeSettingsError as exc:
            settings = self.runtime.store.load()
            outcome = "model_unavailable"
            message = str(exc)

        row = self.ledger.record(
            command,
            outcome=outcome,
            message=message,
            revision=settings.revision,
        )
        self.source.post_comment(
            issue_number,
            status_receipt(settings, outcome=outcome, message=row["message"]),
        )
        return TickResult(outcome, issue_number, message)
