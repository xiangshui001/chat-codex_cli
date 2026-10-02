from __future__ import annotations

import json
import re
from typing import Iterable

from .contract import ContractError, TaskContract
from .github_control import CommentView, IssueView

TASK_TITLE_PREFIX = "[codex] "
TASK_MARKER = "/codex-local run"


class GitHubTaskError(ValueError):
    pass


class GitHubTaskPending(GitHubTaskError):
    pass


def parse_task_comment(body: str) -> TaskContract:
    if not isinstance(body, str):
        raise GitHubTaskError("task comment body must be text")
    lines = body.splitlines()
    if not lines or lines[0].strip() != TASK_MARKER:
        raise GitHubTaskError("first line must be /codex-local run")
    rest = "\n".join(lines[1:]).strip()
    match = re.fullmatch(
        r"(?P<fence>\`\`\`|~~~)json\s*\n(?P<body>.*?)\n(?P=fence)",
        rest,
        flags=re.DOTALL,
    )
    if not match:
        raise GitHubTaskError("task comment must contain exactly one json block and no extra text")
    try:
        payload = json.loads(match.group("body"))
    except json.JSONDecodeError as exc:
        raise GitHubTaskError(f"invalid task json: {exc.msg}") from exc
    try:
        return TaskContract.from_dict(payload)
    except ContractError as exc:
        raise GitHubTaskError(str(exc)) from exc


def validate_task_issue(
    issue: IssueView,
    comments: Iterable[CommentView],
    *,
    repository: str,
    authorized_users: Iterable[str],
) -> TaskContract:
    users = set(authorized_users)
    if issue.state != "open":
        raise GitHubTaskError("task issue must be open")
    if not issue.title.startswith(TASK_TITLE_PREFIX):
        raise GitHubTaskError("task issue title must start with [codex] ")
    if issue.author not in users:
        raise GitHubTaskError("task issue author is not authorized")

    candidates = [
        comment
        for comment in comments
        if comment.body.splitlines()[:1] == [TASK_MARKER]
    ]
    if not candidates:
        raise GitHubTaskPending("task authorization comment has not been posted yet")
    if len(candidates) != 1:
        raise GitHubTaskError("task issue must contain exactly one task authorization comment")

    comment = candidates[0]
    if comment.author not in users:
        raise GitHubTaskError("task comment author is not authorized")
    if comment.created_at != comment.updated_at:
        raise GitHubTaskError("edited task comments are not accepted")

    task = parse_task_comment(comment.body)
    expected_id = f"GH-{issue.number}"
    if task.task_id != expected_id:
        raise GitHubTaskError(f"task.id mismatch: expected {expected_id}, got {task.task_id}")
    if task.repository != repository:
        raise GitHubTaskError("task repository does not match local registration")
    return task
