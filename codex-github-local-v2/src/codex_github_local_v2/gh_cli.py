from __future__ import annotations

import json
import subprocess
from typing import Callable

from .control import CONTROL_TITLE_PREFIX
from .github_control import CommentView, IssueView


class GhCliError(RuntimeError):
    pass


Runner = Callable[[list[str]], str]


def default_runner(argv: list[str]) -> str:
    try:
        return subprocess.check_output(
            argv,
            text=True,
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "").strip()
        raise GhCliError(f"gh command failed with exit {exc.returncode}: {output[:1000]}") from exc


class GhCliControlSource:
    """Small gh(1) adapter for the remote-control plane."""

    def __init__(
        self,
        repository: str,
        *,
        gh_command: tuple[str, ...] = ("gh",),
        runner: Runner = default_runner,
    ):
        self.repository = repository
        self.gh_command = gh_command
        self.runner = runner

    def _json(self, argv: list[str]):
        text = self.runner([*self.gh_command, *argv])
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GhCliError("gh returned invalid JSON") from exc

    def list_open_control_issues(self) -> list[IssueView]:
        rows = self._json(
            [
                "issue",
                "list",
                "--repo",
                self.repository,
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "number,title,state,author",
            ]
        )
        if not isinstance(rows, list):
            raise GhCliError("gh issue list returned a non-list")
        result = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("title", "")).startswith(
                CONTROL_TITLE_PREFIX
            ):
                continue
            author = row.get("author") or {}
            login = author.get("login") if isinstance(author, dict) else None
            if not isinstance(login, str):
                raise GhCliError("issue author login missing")
            result.append(
                IssueView(
                    number=int(row["number"]),
                    title=str(row["title"]),
                    state=str(row["state"]).lower(),
                    author=login,
                )
            )
        return result

    def list_comments(self, issue_number: int) -> list[CommentView]:
        rows = self._json(
            [
                "api",
                f"repos/{self.repository}/issues/{issue_number}/comments?per_page=100",
            ]
        )
        if not isinstance(rows, list):
            raise GhCliError("gh comments endpoint returned a non-list")
        result = []
        for row in rows:
            user = row.get("user") or {}
            login = user.get("login") if isinstance(user, dict) else None
            if not isinstance(login, str):
                raise GhCliError("comment author login missing")
            result.append(
                CommentView(
                    comment_id=int(row["id"]),
                    author=login,
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                    body=str(row.get("body") or ""),
                )
            )
        return result

    def post_comment(self, issue_number: int, body: str) -> None:
        if not isinstance(body, str) or not body:
            raise GhCliError("refusing to post an empty control receipt")
        self._json(
            [
                "api",
                "--method",
                "POST",
                f"repos/{self.repository}/issues/{issue_number}/comments",
                "-f",
                f"body={body}",
            ]
        )
