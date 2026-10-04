"""MVP-1: discover one owner's repositories and prepare workspaces on demand."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import time
from urllib.parse import quote

from .mvp0 import (Config, GitHub, HOST, REPO, Poller, Store, Task, Workspace,
                   exclusive_lock, fields, parse_task, positive_id, read_json, receipt, text)
from .mvp0_runner import CodexRunner, MvpError

TITLE_PREFIX = "[codex-v2-mvp1]"
MARKER = "/codex-v2-mvp1 run"
LOG = logging.getLogger("codex-v2-mvp1")
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")


@dataclass(frozen=True)
class AccountConfig:
    owner: str
    host_id: str
    workspace_root: Path
    state_dir: Path
    poll_seconds: int = 60
    timeout_seconds: int = 900

    @classmethod
    def load(cls, path: Path) -> "AccountConfig":
        data = read_json(path.read_text(encoding="utf-8"))
        fields(data, {"owner", "host_id", "workspace_root", "state_dir"},
               {"poll_seconds", "timeout_seconds"})
        if not LOGIN.fullmatch(text(data["owner"], 39, "invalid_owner")):
            raise MvpError("invalid_owner")
        if not HOST.fullmatch(text(data["host_id"], 64, "invalid_host")):
            raise MvpError("invalid_host")
        paths = []
        for key in ("workspace_root", "state_dir"):
            p = Path(text(data[key], 4096, "invalid_local_path"))
            if not p.is_absolute() or p.is_symlink():
                raise MvpError("absolute_nonsymlink_directory_required")
            p = p.resolve()
            if p == Path(p.anchor) or (p.exists() and not p.is_dir()):
                raise MvpError("invalid_local_path")
            paths.append(p)
        root, state = paths
        if root == state or root in state.parents or state in root.parents:
            raise MvpError("state_and_workspaces_must_be_separate")
        for key, default, lower, upper in (("poll_seconds", 60, 10, 3600), ("timeout_seconds", 900, 1, 3600)):
            value = data.get(key, default)
            if type(value) is not int or not lower <= value <= upper:
                raise MvpError("invalid_" + key)
        return cls(data["owner"].lower(), data["host_id"], root, state,
                   data.get("poll_seconds", 60), data.get("timeout_seconds", 900))


class AccountStore(Store):
    # Deliberately refuses MVP-0 schema 1; there is no implicit migration/replay.
    schema_version = 2

    def bind(self, config: AccountConfig, owner_id: int):
        values = (config.owner, positive_id(owner_id), config.host_id, str(config.workspace_root))
        with self.transaction():
            self.db.execute("""CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, owner_id INTEGER NOT NULL,
                host_id TEXT NOT NULL, workspace_root TEXT NOT NULL)""")
            row = self.db.execute("SELECT owner,owner_id,host_id,workspace_root FROM settings WHERE id=1").fetchone()
            if row is None:
                if self.db.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
                    raise MvpError("missing_account_binding")
                self.db.execute("INSERT INTO settings VALUES(1,?,?,?,?)", values)
            elif tuple(row) != values:
                raise MvpError("account_state_binding_mismatch")


class ReliableGitHub(GitHub):
    title_prefix = TITLE_PREFIX

    def api(self, endpoint: str, body: dict | None = None):
        # Only idempotent reads retry. POST uses the existing receipt reconciliation.
        for attempt in range(3 if body is None else 1):
            try:
                return super().api(endpoint, body)
            except MvpError as exc:
                if body is not None or attempt == 2 or str(exc) not in {
                    "github_transport_unavailable", "github_cli_failed", "github_http_429",
                    "github_http_500", "github_http_502", "github_http_503", "github_http_504",
                }:
                    raise
                time.sleep(0.5 * (attempt + 1))


@dataclass(frozen=True)
class Repository:
    id: int
    full_name: str
    default_branch: str

    def task_config(self, account: AccountConfig, request_id: str = "pending") -> Config:
        workspace = account.workspace_root / str(self.id) / request_id
        return Config(account.host_id, self.full_name, (account.owner,), workspace, (workspace,),
                      account.state_dir, self.default_branch, account.poll_seconds, account.timeout_seconds)


class AccountGitHub:
    def __init__(self, config: AccountConfig, transport: ReliableGitHub | None = None):
        self.config = config
        self.transport = transport or ReliableGitHub("")
        self.owner_id = None

    def identity(self) -> int:
        user = self.transport.api("user")
        if (not isinstance(user, dict) or user.get("type") != "User"
                or str(user.get("login", "")).lower() != self.config.owner):
            raise MvpError("github_login_must_match_owner")
        self.owner_id = positive_id(user.get("id"))
        return self.owner_id

    def _repository(self, data: dict) -> Repository:
        if not isinstance(data, dict) or not isinstance(data.get("owner"), dict):
            raise MvpError("invalid_repository_metadata")
        owner = data["owner"]
        if (owner.get("id") != self.owner_id or str(owner.get("login", "")).lower() != self.config.owner
                or owner.get("type") != "User"):
            raise MvpError("repository_owner_not_allowed")
        name = text(data.get("full_name"), 200, "invalid_repo")
        if not REPO.fullmatch(name) or name.split("/")[0].lower() != self.config.owner:
            raise MvpError("repository_owner_not_allowed")
        if data.get("archived") is not False or data.get("disabled", False) or data.get("has_issues") is not True:
            raise MvpError("repository_not_eligible")
        branch = text(data.get("default_branch"), 200, "invalid_default_branch")
        if (branch.startswith("-") or branch.endswith(("/", ".", ".lock")) or ".." in branch
                or "//" in branch or "@{" in branch or any(c in branch for c in " ~^:?*[\\\n\r\t")):
            raise MvpError("invalid_default_branch")
        return Repository(positive_id(data.get("id")), name, branch)

    def repositories(self) -> list[Repository]:
        self.identity()
        rows = self.transport.pages("user/repos?affiliation=owner&sort=full_name&direction=asc")
        repos = {}
        for row in rows:
            try:
                repo = self._repository(row)
            except MvpError as exc:
                if str(exc) in {"repository_not_eligible", "repository_owner_not_allowed"}:
                    continue
                raise
            repos[repo.id] = repo
        return sorted(repos.values(), key=lambda r: r.id)

    def repository(self, name: str, expected_id: int) -> Repository:
        if not REPO.fullmatch(name) or name.split("/")[0].lower() != self.config.owner:
            raise MvpError("repository_owner_not_allowed")
        repo = self._repository(self.transport.api(f"repos/{name}"))
        if repo.id != expected_id:
            raise MvpError("repository_identity_changed")
        return repo

    def client(self, repo: Repository) -> ReliableGitHub:
        client = ReliableGitHub(repo.full_name, self.transport.command)
        client.repository_id, client.writer_id = repo.id, self.owner_id
        return client

    def check_base(self, repo: Repository, task: Task):
        current = self.repository(repo.full_name, repo.id)
        if current != repo:
            raise MvpError("stale_base")
        try:
            commit = self.transport.api(f"repos/{repo.full_name}/commits/{quote(repo.default_branch, safe='')}")
        except MvpError as exc:
            if str(exc) == "github_http_409":
                raise MvpError("empty_repository_requires_initial_commit") from exc
            raise
        if not isinstance(commit, dict) or commit.get("sha") != task.base_sha:
            raise MvpError("stale_base")


def run_git(cwd: Path, *args: str, timeout: int = 30) -> str:
    try:
        # Use the existing gh login; no token in argv, files or returned errors.
        return subprocess.run(["git", "-c", "credential.helper=", "-c",
            "credential.helper=!gh auth git-credential", "-C", str(cwd), *args],
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=timeout).stdout.rstrip("\r\n")
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise MvpError("workspace_git_failed") from exc


class ManagedWorkspace(Workspace):
    def __init__(self, config: Config, account: AccountConfig, repo: Repository,
                 github: AccountGitHub, record):
        super().__init__(config)
        self.account, self.repo, self.github, self.record = account, repo, github, record

    def git(self, *args: str) -> str:
        return run_git(self.config.workspace, *args)

    def preflight(self, task: Task):
        self.github.check_base(self.repo, task)
        root, workspace = self.account.workspace_root, self.config.workspace
        parent = workspace.parent
        if (root.is_symlink() or parent.is_symlink() or workspace.is_symlink()
                or not workspace.resolve().is_relative_to(root.resolve())):
            raise MvpError("managed_workspace_path_escape")
        if workspace.exists():
            raise MvpError("managed_workspace_already_exists")
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Reserve the exact destination before clone. Failed/abandoned clones stay for inspection.
        workspace.mkdir(mode=0o700)
        self.record("workspace_preparing", {"repository_id": self.repo.id, "cwd": str(workspace)})
        run_git(parent, "clone", "--no-checkout", "--single-branch", "--branch", self.repo.default_branch,
                "--", f"https://github.com/{self.repo.full_name}.git", str(workspace), timeout=120)
        if self.git("rev-parse", "HEAD") != task.base_sha:
            raise MvpError("stale_base")
        self.git("checkout", "-b", "codex-mvp1/" + task.request_id, task.base_sha)
        super().preflight(task)
        self.record("workspace_prepared", {"repository_id": self.repo.id, "base_sha": task.base_sha})

    def baseline(self, task: Task):
        # Repeat owner/ID/default-branch validation after execution as well.
        self.github.check_base(self.repo, task)
        super().baseline(task)


class AccountExecutor(Poller):
    receipt_label = "MVP-1"
    receipt_marker = "codex-v2-mvp1"


class AccountPoller:
    def __init__(self, config: AccountConfig, store: AccountStore, github: AccountGitHub,
                 runner: CodexRunner, workspace_factory=ManagedWorkspace):
        self.config, self.store, self.github, self.runner = config, store, github, runner
        self.workspace_factory = workspace_factory
        self.errors = 0

    def once(self) -> int:
        if self.store.unfinished():
            raise MvpError("unfinished_task_requires_manual_inspection")
        self.errors = 0
        repos = self.github.repositories()
        self.store.bind(self.config, self.github.owner_id)
        LOG.info("repositories_discovered count=%s", len(repos))
        for row in self.store.pending_receipts():
            try:
                repo = self.github.repository(row["repo"], row["repository_id"])
                client = self.github.client(repo)
                comment_id = client.post_receipt(row["issue_number"], receipt(
                    row, label="MVP-1", marker="codex-v2-mvp1"))
                self.store.receipt_sent(row["id"], comment_id)
            except MvpError as exc:
                self.errors += 1
                LOG.error("receipt_pending repository_id=%s issue=%s code=%s", row["repository_id"], row["issue_number"], exc)
        candidates = []
        for repo in repos:
            client = self.github.client(repo)
            try:
                issues = client.issues()
            except MvpError as exc:
                self.errors += 1
                LOG.error("repository_poll_failed repository_id=%s code=%s", repo.id, exc)
                continue
            for issue in issues:
                if not self.store.by_issue(repo.id, positive_id(issue.get("id"))):
                    candidates.append((positive_id(issue["id"]), repo, client, issue))
        # A single oldest-first queue across all discovered repositories.
        for _, repo, client, issue in sorted(candidates, key=lambda c: c[0]):
            try:
                comments = client.comments(positive_id(issue.get("number")))
            except MvpError as exc:
                self.errors += 1
                LOG.error("comments_unavailable repository_id=%s issue=%s code=%s", repo.id, issue.get("number"), exc)
                continue
            try:
                task = parse_task(issue, comments,
                                  repo.task_config(self.config), title_prefix=TITLE_PREFIX, marker=MARKER)
                task_id = self.store.claim(repo.id, issue, task)
            except MvpError as exc:
                LOG.warning("task_rejected repository_id=%s issue=%s code=%s", repo.id, issue.get("number"), exc)
                continue
            if task_id is None:
                continue
            config = repo.task_config(self.config, task.request_id)
            workspace = self.workspace_factory(config, self.config, repo, self.github,
                lambda kind, detail: self.store.event(task_id, kind, detail))
            AccountExecutor(config, self.store, client, self.runner, workspace).execute(task_id, task)
            return 1
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--list-repos", action="store_true", help="read-only discovery; does not clone or execute")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.name != "posix":
        LOG.error("linux_or_wsl_required")
        return 2
    os.umask(0o077)
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        config = AccountConfig.load(args.config)
        github = AccountGitHub(config)
        if args.list_repos:
            print(json.dumps([{"repository_id": r.id, "repo": r.full_name, "base_branch": r.default_branch}
                              for r in github.repositories()], ensure_ascii=False, indent=2))
            return 0
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_lock(config.state_dir / "poller.lock"), exclusive_lock(config.workspace_root / ".mvp1.lock"):
            store = AccountStore(config.state_dir / "mvp1.sqlite3")
            try:
                poller = AccountPoller(config, store, github, CodexRunner())
                while True:
                    try:
                        count = poller.once()
                        LOG.info("poll_complete new_tasks=%s repository_errors=%s", count, poller.errors)
                    except MvpError as exc:
                        LOG.error("poll_failed code=%s", exc)
                        if args.once or store.unfinished():
                            return 1
                    else:
                        if args.once:
                            last = store.db.execute("SELECT state FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
                            return int(bool(poller.errors or store.pending_receipts())
                                       or bool(count and last["state"] != "succeeded"))
                    time.sleep(config.poll_seconds)
            finally:
                store.close()
    except KeyboardInterrupt:
        return 130
    except (MvpError, OSError, sqlite3.Error) as exc:
        LOG.error("%s", str(exc) if isinstance(exc, MvpError) else "local_state_or_config_error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
