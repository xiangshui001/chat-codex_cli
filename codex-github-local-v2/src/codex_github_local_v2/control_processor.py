from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .control import CONTROL_MARKER, RuntimeSettings
from .control_ledger import ControlLedger, command_fingerprint
from .github_control import (
    CommentView,
    GitHubControlError,
    GitHubControlPending,
    IssueView,
    validate_control_issue,
)
from .runtime_settings import RuntimeControlService, RuntimeSettingsError


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
    """Redacted GitHub receipt. Never include local paths, tokens or raw logs."""

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
    """Serially process one valid control Issue per tick."""

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
        issues = sorted(self.source.list_open_control_issues(), key=lambda issue: issue.number)
        if not issues:
            return TickResult("idle")

        for issue in issues:
            comments = list(self.source.list_comments(issue.number))
            marker_comments = [
                comment
                for comment in comments
                if comment.body.splitlines()[:1] == [CONTROL_MARKER]
            ]
            if not marker_comments:
                continue

            try:
                command = validate_control_issue(
                    issue,
                    comments,
                    repository=self.repository,
                    authorized_users=self.authorized_users,
                )
            except GitHubControlPending:
                continue
            except GitHubControlError as exc:
                return TickResult("rejected", issue.number, str(exc))

            existing = self.ledger.get(command.control_id)
            fingerprint = command_fingerprint(command)
            if existing:
                if existing.get("fingerprint") != fingerprint:
                    return TickResult(
                        "rejected",
                        issue.number,
                        "processed control id reappeared with different content",
                    )
                return TickResult(
                    "already_processed",
                    issue.number,
                    str(existing.get("outcome", "unknown")),
                )

            try:
                applied = self.runtime.apply(command)
            except RuntimeSettingsError as exc:
                current = self.runtime.store.load()
                row = self.ledger.record(
                    command,
                    outcome="model_unavailable",
                    message=str(exc),
                    revision=current.revision,
                )
                self.source.post_comment(
                    issue.number,
                    status_receipt(
                        current,
                        outcome=row["outcome"],
                        message=row["message"],
                    ),
                )
                return TickResult("model_unavailable", issue.number, str(exc))

            settings = applied.result.settings
            outcome = "applied"
            row = self.ledger.record(
                command,
                outcome=outcome,
                message=applied.result.message,
                revision=settings.revision,
            )
            self.source.post_comment(
                issue.number,
                status_receipt(
                    settings,
                    outcome=outcome,
                    message=row["message"],
                ),
            )
            return TickResult(outcome, issue.number, applied.result.message)

        return TickResult("pending")
