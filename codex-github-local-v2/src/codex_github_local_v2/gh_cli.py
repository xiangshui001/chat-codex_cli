from __future__ import annotations

import json
import subprocess
from typing import Callable

from .control import CONTROL_TITLE_PREFIX
from .github_protocol import CommentView, IssueView


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
        try:
            return json.loads(self.runner([*self.gh_command, *argv]))
        except json.JSONDecodeError as exc:
            raise GhCliError("gh returned invalid JSON") from exc

    def list_open_control_issues(self) -> list[IssueView]:
        rows = self._json(
            [
                "issue", "list",
                "--repo", self.repository,
                "--state", "open",
                "--limit", "1000",
                "--json", "number,title,state,author",
            ]
        )
        result = []
        for row in rows:
            if not str(row.get("title", "")).startswith(CONTROL_TITLE_PREFIX):
                continue
            result.append(
                IssueView(
                    number=int(row["number"]),
                    title=str(row["title"]),
                    state=str(row["state"]).lower(),
                    author=str(row["author"]["login"]),
                )
            )
        return result

    def list_comments(self, issue_number: int) -> list[CommentView]:
        rows = []
        for page in range(1, 101):
            batch = self._json([
                "api", f"repos/{self.repository}/issues/{issue_number}/comments?per_page=100&page={page}"
            ])
            if not isinstance(batch, list):
                raise GhCliError("gh returned an invalid comments page")
            rows.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise GhCliError("comment pagination limit reached; refusing incomplete receipt reconciliation")
        return [
            CommentView(
                comment_id=int(row["id"]),
                author=str(row["user"]["login"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                body=str(row.get("body") or ""),
            )
            for row in rows
        ]

    def post_comment(self, issue_number: int, body: str) -> None:
        if not body:
            raise GhCliError("refusing to post an empty control receipt")
        self._json(
            [
                "api", "--method", "POST",
                f"repos/{self.repository}/issues/{issue_number}/comments",
                "-f", f"body={body}",
            ]
        )
