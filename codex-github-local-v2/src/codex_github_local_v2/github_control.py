from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .control import (
    CONTROL_MARKER,
    CONTROL_TITLE_PREFIX,
    ControlCommand,
    ControlError,
    parse_control_comment,
)


class GitHubControlError(ValueError):
    pass


@dataclass(frozen=True)
class IssueView:
    number: int
    title: str
    state: str
    author: str


@dataclass(frozen=True)
class CommentView:
    comment_id: int
    author: str
    created_at: str
    updated_at: str
    body: str


def _authorized(login: str, authorized_users: set[str]) -> bool:
    return login in authorized_users


def validate_control_issue(
    issue: IssueView,
    comments: Iterable[CommentView],
    *,
    repository: str,
    authorized_users: Iterable[str],
) -> ControlCommand:
    """Validate a GitHub control issue after the adapter has fetched it.

    This function is intentionally pure: it performs no GitHub writes and no model calls.
    """

    users = set(authorized_users)
    if issue.state != "open":
        raise GitHubControlError("control issue must be open")
    if not issue.title.startswith(CONTROL_TITLE_PREFIX):
        raise GitHubControlError("control issue title must start with [codex-control] ")
    if not _authorized(issue.author, users):
        raise GitHubControlError("control issue author is not authorized")

    candidates = [comment for comment in comments if comment.body.splitlines()[:1] == [CONTROL_MARKER]]
    if len(candidates) != 1:
        raise GitHubControlError("control issue must contain exactly one control authorization comment")

    comment = candidates[0]
    if not _authorized(comment.author, users):
        raise GitHubControlError("control comment author is not authorized")
    if comment.created_at != comment.updated_at:
        raise GitHubControlError("edited control comments are not accepted")

    try:
        command = parse_control_comment(comment.body)
    except ControlError as exc:
        raise GitHubControlError(str(exc)) from exc

    expected_id = f"GH-{issue.number}"
    if command.control_id != expected_id:
        raise GitHubControlError(
            f"control.id mismatch: expected {expected_id}, got {command.control_id}"
        )
    if command.repository != repository:
        raise GitHubControlError("control repository does not match local registration")
    return command
