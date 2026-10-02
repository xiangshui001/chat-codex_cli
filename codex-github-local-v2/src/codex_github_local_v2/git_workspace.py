from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from .policy import PolicyEngine, PolicyError

_TASK_ID = re.compile(r"^GH-[1-9][0-9]*$")


class GitWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Worktree:
    task_id: str
    branch: str
    path: Path
    base_sha: str


class GitWorkspace:
    """Deterministic git/worktree adapter. It never fetches, pushes or merges."""

    def __init__(self, root: str | Path, worktrees_root: str | Path, branch_prefix: str = "feature/"):
        self.root = Path(root).resolve()
        self.worktrees_root = Path(worktrees_root).resolve()
        self.branch_prefix = branch_prefix

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=cwd or self.root,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            raise GitWorkspaceError(f"git could not start: {exc}") from exc
        output = completed.stdout or ""
        if check and completed.returncode:
            raise GitWorkspaceError(
                f"git {' '.join(args)} failed with exit {completed.returncode}: {output.strip()[:1000]}"
            )
        return output.strip()

    def assert_clean_base(self, expected_branch: str, expected_sha: str) -> None:
        branch = self.git("branch", "--show-current")
        if branch != expected_branch:
            raise GitWorkspaceError(f"expected branch {expected_branch}, found {branch}")
        if self.git("status", "--porcelain"):
            raise GitWorkspaceError("base checkout is not clean")
        current = self.git("rev-parse", "HEAD")
        if current != expected_sha:
            raise GitWorkspaceError(f"base SHA changed: expected {expected_sha}, found {current}")

    def create(self, task_id: str, base_sha: str) -> Worktree:
        if not _TASK_ID.fullmatch(task_id):
            raise GitWorkspaceError("task_id must match GH-N")
        resolved = self.git("rev-parse", f"{base_sha}^{{commit}}")
        if resolved != base_sha:
            raise GitWorkspaceError("base_sha did not resolve exactly")

        branch = self.branch_prefix + task_id
        exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self.root,
            check=False,
        ).returncode == 0
        if exists:
            raise GitWorkspaceError(f"task branch already exists: {branch}")

        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_root / task_id
        if path.exists():
            raise GitWorkspaceError(f"worktree path already exists: {path}")

        self.git("worktree", "add", "-b", branch, str(path), base_sha)
        return Worktree(task_id=task_id, branch=branch, path=path, base_sha=base_sha)

    def changed_paths(self, wt: Worktree) -> list[str]:
        tracked = self.git(
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            wt.base_sha,
            cwd=wt.path,
        )
        untracked = self.git(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            cwd=wt.path,
        )
        values = []
        for block in (tracked, untracked):
            values.extend(part for part in block.split("\0") if part)
        return sorted(set(values))

    def guard_changes(self, wt: Worktree, policy: PolicyEngine) -> list[str]:
        paths = self.changed_paths(wt)
        try:
            policy.assert_changes(paths)
        except PolicyError as exc:
            raise GitWorkspaceError(str(exc)) from exc
        for rel in paths:
            target = (wt.path / rel)
            if target.is_symlink():
                raise GitWorkspaceError(f"symlink changes are not accepted: {rel}")
            if target.exists() and not target.resolve().is_relative_to(wt.path.resolve()):
                raise GitWorkspaceError(f"changed path escapes worktree: {rel}")
        return paths

    def commit_candidate(self, wt: Worktree, message: str) -> str:
        if not isinstance(message, str) or not message.strip():
            raise GitWorkspaceError("commit message must be non-empty")
        self.git("add", "--all", cwd=wt.path)
        staged = self.git("diff", "--cached", "--name-only", cwd=wt.path)
        if not staged:
            raise GitWorkspaceError("no staged candidate changes")
        self.git("diff", "--cached", "--check", cwd=wt.path)
        before = self.git("rev-parse", "HEAD", cwd=wt.path)
        if before != wt.base_sha:
            raise GitWorkspaceError("executor changed git history before controller commit")
        self.git("commit", "-m", message, cwd=wt.path)
        return self.git("rev-parse", "HEAD", cwd=wt.path)

    def remove(self, wt: Worktree, *, delete_branch: bool = False) -> None:
        # Call only after an explicit lifecycle decision. Failed jobs may deliberately
        # retain their worktree for inspection.
        self.git("worktree", "remove", "--force", str(wt.path))
        if delete_branch:
            self.git("branch", "-D", wt.branch)
