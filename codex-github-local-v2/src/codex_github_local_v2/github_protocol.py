from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, Generic, Iterable, TypeVar

from .contract import ContractError, TaskContract

T = TypeVar("T")


class GitHubProtocolError(ValueError):
    pass


class GitHubProtocolPending(GitHubProtocolError):
    pass


# Named aliases keep call sites readable without duplicating implementations.
GitHubTaskError = GitHubProtocolError
GitHubTaskPending = GitHubProtocolPending
GitHubControlError = GitHubProtocolError
GitHubControlPending = GitHubProtocolPending


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


@dataclass(frozen=True)
class IssueProtocol(Generic[T]):
    title_prefix: str
    marker: str
    decode: Callable[[dict], T]
    item_id: Callable[[T], str]


_JSON_BLOCK = re.compile(
    r"(?P<fence>\x60\x60\x60|~~~)json\s*\n(?P<body>.*?)\n(?P=fence)",
    flags=re.DOTALL,
)


def parse_authorization(body: str, marker: str) -> dict:
    lines = body.splitlines()
    if not lines or lines[0].strip() != marker:
        raise GitHubProtocolError(f"first line must be {marker}")
    match = _JSON_BLOCK.fullmatch("\n".join(lines[1:]).strip())
    if not match:
        raise GitHubProtocolError("authorization must contain exactly one json block")
    try:
        value = json.loads(match.group("body"))
    except json.JSONDecodeError as exc:
        raise GitHubProtocolError(f"invalid authorization json: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise GitHubProtocolError("authorization json must be an object")
    return value


def validate_issue(
    issue: IssueView,
    comments: Iterable[CommentView],
    *,
    repository: str,
    authorized_users: Iterable[str],
    protocol: IssueProtocol[T],
) -> T:
    users = set(authorized_users)
    checks = (
        (issue.state == "open", "issue must be open"),
        (issue.title.startswith(protocol.title_prefix),
         f"issue title must start with {protocol.title_prefix}"),
        (issue.author in users, "issue author is not authorized"),
    )
    for ok, message in checks:
        if not ok:
            raise GitHubProtocolError(message)

    candidates = [
        comment for comment in comments
        if comment.body.splitlines()[:1] == [protocol.marker]
    ]
    if not candidates:
        raise GitHubProtocolPending("authorization comment has not been posted yet")
    if len(candidates) != 1:
        raise GitHubProtocolError("issue must contain exactly one authorization comment")

    comment = candidates[0]
    if comment.author not in users:
        raise GitHubProtocolError("authorization comment author is not authorized")
    if comment.created_at != comment.updated_at:
        raise GitHubProtocolError("edited authorization comments are not accepted")

    try:
        item = protocol.decode(parse_authorization(comment.body, protocol.marker))
    except GitHubProtocolError:
        raise
    except ValueError as exc:
        raise GitHubProtocolError(str(exc)) from exc

    expected_id = f"GH-{issue.number}"
    actual_id = protocol.item_id(item)
    if actual_id != expected_id:
        raise GitHubProtocolError(f"id mismatch: expected {expected_id}, got {actual_id}")
    if getattr(item, "repository", None) != repository:
        raise GitHubProtocolError("repository does not match local registration")
    return item


TASK_TITLE_PREFIX = "[codex] "
TASK_MARKER = "/codex-local run"

TASK_PROTOCOL = IssueProtocol[TaskContract](
    title_prefix=TASK_TITLE_PREFIX,
    marker=TASK_MARKER,
    decode=TaskContract.from_dict,
    item_id=lambda task: task.task_id,
)


def parse_task_comment(body: str) -> TaskContract:
    try:
        return TaskContract.from_dict(parse_authorization(body, TASK_MARKER))
    except ContractError as exc:
        raise GitHubProtocolError(str(exc)) from exc


def validate_task_issue(
    issue: IssueView,
    comments: Iterable[CommentView],
    *,
    repository: str,
    authorized_users: Iterable[str],
) -> TaskContract:
    return validate_issue(
        issue,
        comments,
        repository=repository,
        authorized_users=authorized_users,
        protocol=TASK_PROTOCOL,
    )
