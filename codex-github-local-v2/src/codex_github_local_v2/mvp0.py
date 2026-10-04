"""MVP-0: one registered repository, SQLite claim, local Codex, Issue receipt."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import signal
import sqlite3
import subprocess
import time
import uuid

from .mvp0_runner import CodexRunner, MvpError, utc_now

TITLE_PREFIX = "[codex-v2-mvp]"
MARKER = "/codex-v2-mvp run"
TERMINAL = ("succeeded", "failed", "stale_base")
LOG = logging.getLogger("codex-v2-mvp0")
REPO = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise MvpError("duplicate_json_key")
        result[key] = value
    return result


def read_json(raw: str):
    def reject_constant(_):
        raise MvpError("nonfinite_json_number")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise MvpError("invalid_json") from exc


def fields(value, required: set[str], optional: set[str] = frozenset()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise MvpError("invalid_fields")


def text(value, limit: int, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise MvpError(code)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise MvpError(code) from exc
    return value


def positive_id(value) -> int:
    if type(value) is not int or value < 1:
        raise MvpError("invalid_github_id")
    return value


def write_path(value: str) -> str:
    value = text(value, 300, "invalid_write_paths")
    path = PurePosixPath(value)
    if (path.is_absolute() or "//" in value or value.rstrip("/") != path.as_posix() or value in {".", ""}
            or any(p in {"..", ".git", ".codex"} for p in (part.lower() for part in path.parts))
            or any(c in value for c in "\\:*?[]\n\r\t") or any(ord(c) < 32 for c in value)):
        raise MvpError("invalid_write_paths")
    return value


@dataclass(frozen=True)
class Config:
    host_id: str
    repo: str
    allowed_authors: tuple[str, ...]
    workspace: Path
    workspace_allowlist: tuple[Path, ...]
    state_dir: Path
    base_branch: str = "main"
    poll_seconds: int = 60
    timeout_seconds: int = 900

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = read_json(path.read_text(encoding="utf-8"))
        fields(data, {"host_id", "repo", "allowed_authors", "workspace", "workspace_allowlist", "state_dir"},
               {"base_branch", "poll_seconds", "timeout_seconds"})
        if not HOST.fullmatch(text(data["host_id"], 64, "invalid_host")):
            raise MvpError("invalid_host")
        if not REPO.fullmatch(text(data["repo"], 200, "invalid_repo")):
            raise MvpError("invalid_repo")
        authors = data["allowed_authors"]
        if not isinstance(authors, list) or not authors or any(
                not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", a) for a in authors):
            raise MvpError("invalid_authors")
        def absolute(raw):
            p = Path(text(raw, 4096, "invalid_local_path"))
            if not p.is_absolute():
                raise MvpError("absolute_local_path_required")
            return p.resolve()
        workspace, state_dir = absolute(data["workspace"]), absolute(data["state_dir"])
        allowed = data["workspace_allowlist"]
        if not isinstance(allowed, list) or not allowed:
            raise MvpError("invalid_workspace_allowlist")
        allowlist = tuple(absolute(p) for p in allowed)
        if not workspace.is_dir() or workspace not in allowlist:
            raise MvpError("workspace_not_allowed")
        if state_dir == workspace or workspace in state_dir.parents:
            raise MvpError("state_dir_must_be_outside_workspace")
        branch = data.get("base_branch", "main")
        if (not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}", branch)
                or ".." in branch or "//" in branch or branch.endswith(("/", ".", ".lock"))):
            raise MvpError("invalid_base_branch")
        for key, default, lower, upper in (("poll_seconds", 60, 10, 3600), ("timeout_seconds", 900, 1, 3600)):
            value = data.get(key, default)
            if type(value) is not int or not lower <= value <= upper:
                raise MvpError("invalid_" + key)
        return cls(data["host_id"], data["repo"], tuple(a.lower() for a in authors), workspace,
                   allowlist, state_dir, branch, data.get("poll_seconds", 60), data.get("timeout_seconds", 900))


@dataclass(frozen=True)
class Task:
    request_id: str
    host_id: str
    repo: str
    base_sha: str
    prompt: str
    write_paths: tuple[str, ...]
    comment_id: int
    contract_hash: str


def parse_task(issue: dict, comments: list[dict], config: Config) -> Task:
    if (not isinstance(issue, dict) or "pull_request" in issue or issue.get("state") != "open"
            or not str(issue.get("title", "")).startswith(TITLE_PREFIX)):
        raise MvpError("not_mvp_issue")
    if str((issue.get("user") or {}).get("login", "")).lower() not in config.allowed_authors:
        raise MvpError("issue_author_not_allowed")
    positive_id(issue.get("id")); positive_id(issue.get("number"))
    authorized = [c for c in comments if isinstance(c.get("body"), str)
                  and c["body"].splitlines() and c["body"].splitlines()[0] == MARKER]
    if len(authorized) != 1:
        raise MvpError("exactly_one_authorization_required")
    comment = authorized[0]
    if str((comment.get("user") or {}).get("login", "")).lower() not in config.allowed_authors:
        raise MvpError("comment_author_not_allowed")
    comment_id = positive_id(comment.get("id"))
    if not comment.get("created_at") or comment.get("created_at") != comment.get("updated_at"):
        raise MvpError("edited_authorization")
    body = text(comment["body"], 20000, "authorization_too_large")
    payload = body.split("\n", 1)[1].strip() if "\n" in body else ""
    if payload.startswith("```"):
        match = re.fullmatch(r"```json\s*\n([\s\S]+)\n```", payload)
        if not match:
            raise MvpError("invalid_json_fence")
        payload = match[1]
    data = read_json(payload)
    fields(data, {"request_id", "host_id", "repo", "base_sha", "task"})
    request_id = text(data["request_id"], 36, "invalid_request_id")
    try:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError
    except ValueError as exc:
        raise MvpError("invalid_request_id") from exc
    if text(data["host_id"], 64, "invalid_host") != config.host_id:
        raise MvpError("wrong_host")
    if text(data["repo"], 200, "invalid_repo").lower() != config.repo.lower():
        raise MvpError("wrong_repo")
    if not re.fullmatch(r"[0-9a-f]{40}", text(data["base_sha"], 40, "invalid_base_sha")):
        raise MvpError("invalid_base_sha")
    fields(data["task"], {"prompt", "write_paths"})
    prompt = text(data["task"]["prompt"], 12000, "invalid_prompt")
    paths = data["task"]["write_paths"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise MvpError("invalid_write_paths")
    paths = tuple(write_path(p) for p in paths)
    if len(set(paths)) != len(paths):
        raise MvpError("duplicate_write_path")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return Task(request_id, data["host_id"], data["repo"], data["base_sha"], prompt, paths, comment_id, digest)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise MvpError("unsupported_mvp_schema")
        if version == 0:
            if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                self.db.close()
                raise MvpError("nonempty_unversioned_database")
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY, repository_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
                    issue_number INTEGER NOT NULL, request_id TEXT NOT NULL UNIQUE, host_id TEXT NOT NULL,
                    repo TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN
                        ('queued','running','succeeded','failed','stale_base')),
                    base_sha TEXT NOT NULL, prompt TEXT NOT NULL, write_paths TEXT NOT NULL,
                    comment_id INTEGER NOT NULL, contract_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    exit_code INTEGER, cli_version TEXT, argv TEXT, cwd TEXT,
                    error TEXT, summary TEXT, diff_nonempty INTEGER, receipt_comment_id INTEGER,
                    UNIQUE(repository_id, issue_id)
                );
                CREATE UNIQUE INDEX one_active_task ON tasks((1)) WHERE state IN ('queued','running');
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                    kind TEXT NOT NULL, at TEXT NOT NULL, detail TEXT NOT NULL
                );
                PRAGMA user_version=1;
                COMMIT;
            """)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def event(self, task_id: int, kind: str, detail: dict):
        self.db.execute("INSERT INTO events(task_id,kind,at,detail) VALUES(?,?,?,?)",
                        (task_id, kind, utc_now(), json.dumps(detail, ensure_ascii=False)))

    def get(self, task_id: int):
        return self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def by_issue(self, repository_id: int, issue_id: int):
        return self.db.execute("SELECT * FROM tasks WHERE repository_id=? AND issue_id=?",
                               (repository_id, issue_id)).fetchone()

    def unfinished(self):
        return self.db.execute("SELECT * FROM tasks WHERE state IN ('queued','running')").fetchone()

    def pending_receipts(self):
        return self.db.execute("SELECT * FROM tasks WHERE finished_at IS NOT NULL AND receipt_comment_id IS NULL ORDER BY id").fetchall()

    def claim(self, repository_id: int, issue: dict, task: Task) -> int | None:
        with self.transaction():
            if self.db.execute("SELECT 1 FROM tasks WHERE request_id=? OR (repository_id=? AND issue_id=?)",
                               (task.request_id, repository_id, issue["id"])).fetchone():
                return None
            if self.unfinished():
                raise MvpError("unfinished_task_requires_manual_inspection")
            cursor = self.db.execute("""INSERT INTO tasks(repository_id,issue_id,issue_number,request_id,
                host_id,repo,state,base_sha,prompt,write_paths,comment_id,contract_hash,created_at)
                VALUES(?,?,?,?,?,?,'queued',?,?,?,?,?,?)""",
                (repository_id, issue["id"], issue["number"], task.request_id, task.host_id, task.repo,
                 task.base_sha, task.prompt, json.dumps(task.write_paths), task.comment_id, task.contract_hash, utc_now()))
            self.event(cursor.lastrowid, "claimed", {})
            return cursor.lastrowid

    def start(self, task_id: int, metadata: dict):
        with self.transaction():
            updated = self.db.execute("""UPDATE tasks SET state='running',started_at=?,cli_version=?,argv=?,cwd=?
                WHERE id=? AND state='queued'""", (utc_now(), metadata["cli_version"], json.dumps(metadata["argv"]), metadata["cwd"], task_id))
            if updated.rowcount != 1:
                raise MvpError("invalid_start_transition")
            self.event(task_id, "started", metadata)

    def finish(self, task_id: int, state: str, exit_code: int | None, error: str | None,
               diff_nonempty: bool | None, summary: str):
        if state not in TERMINAL:
            raise MvpError("invalid_terminal_state")
        with self.transaction():
            updated = self.db.execute("""UPDATE tasks SET state=?,finished_at=?,exit_code=?,error=?,
                diff_nonempty=?,summary=? WHERE id=? AND state IN ('queued','running')""",
                (state, utc_now(), exit_code, error, diff_nonempty, summary, task_id))
            if updated.rowcount != 1:
                raise MvpError("invalid_finish_transition")
            self.event(task_id, "finished", {"state": state, "exit_code": exit_code, "error": error})

    def receipt_sent(self, task_id: int, comment_id: int):
        with self.transaction():
            self.db.execute("UPDATE tasks SET receipt_comment_id=? WHERE id=?", (comment_id, task_id))
            self.event(task_id, "receipt_sent", {"comment_id": comment_id})


class GitHub:
    """gh supplies the existing login. Direct paginated REST lists, never search."""
    def __init__(self, repo: str, command: tuple[str, ...] = ("gh",)):
        self.repo, self.command = repo, command
        self.repository_id = None
        self.writer_id = None

    def api(self, endpoint: str, body: dict | None = None):
        argv = [*self.command, "api", "--hostname", "github.com", endpoint]
        if body is not None:
            argv += ["--method", "POST", "--input", "-"]
        try:
            result = subprocess.run(argv, input=json.dumps(body) if body is not None else None,
                text=True, encoding="utf-8", capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise MvpError("github_transport_unavailable") from exc
        if result.returncode:
            # No raw stderr: it can include local paths, authorization or response bodies.
            status = re.search(r"HTTP (\d{3})", result.stderr)
            raise MvpError("github_http_" + status[1] if status else "github_cli_failed")
        return read_json(result.stdout)

    def identity(self) -> int:
        if self.repository_id is None:
            repo = self.api(f"repos/{self.repo}")
            if not isinstance(repo, dict) or str(repo.get("full_name", "")).lower() != self.repo.lower():
                raise MvpError("github_repository_mismatch")
            user = self.api("user")
            if not isinstance(user, dict):
                raise MvpError("invalid_github_user")
            self.repository_id = positive_id(repo.get("id"))
            self.writer_id = positive_id(user.get("id"))
        return self.repository_id

    def pages(self, endpoint: str) -> list[dict]:
        rows = []
        separator = "&" if "?" in endpoint else "?"
        for page in range(1, 101):
            batch = self.api(f"{endpoint}{separator}per_page=100&page={page}")
            if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                raise MvpError("invalid_github_page")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise MvpError("github_pagination_limit")

    def issues(self):
        return [i for i in self.pages(f"repos/{self.repo}/issues?state=open&sort=created&direction=asc")
                if "pull_request" not in i and str(i.get("title", "")).startswith(TITLE_PREFIX)]

    def comments(self, number: int):
        return self.pages(f"repos/{self.repo}/issues/{number}/comments")

    def post_receipt(self, number: int, body: str) -> int:
        # Minimal retry reconciliation; a lost response must never cause a model retry.
        for comment in self.comments(number):
            if (comment.get("user") or {}).get("id") == self.writer_id and comment.get("body") == body:
                return positive_id(comment.get("id"))
        result = self.api(f"repos/{self.repo}/issues/{number}/comments", {"body": body})
        if not isinstance(result, dict):
            raise MvpError("invalid_github_comment_response")
        return positive_id(result.get("id"))


class Workspace:
    def __init__(self, config: Config):
        self.config = config

    def git(self, *args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(self.config.workspace), *args], capture_output=True,
                check=True, timeout=30, text=True, encoding="utf-8").stdout.rstrip("\r\n")
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise MvpError("workspace_git_failed") from exc

    def registered(self):
        path = self.config.workspace.resolve()
        if path not in self.config.workspace_allowlist or Path(self.git("rev-parse", "--show-toplevel")).resolve() != path:
            raise MvpError("workspace_not_allowed")
        remote = self.git("remote", "get-url", "origin")
        match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^\s]+?)(?:\.git)?/?", remote)
        if not match or match[1].lower() != self.config.repo.lower():
            raise MvpError("workspace_remote_mismatch")

    def baseline(self, task: Task):
        if self.git("rev-parse", "HEAD") != task.base_sha:
            raise MvpError("stale_base")
        rows = self.git("ls-remote", "--exit-code", "origin", "refs/heads/" + self.config.base_branch).splitlines()
        if len(rows) != 1 or rows[0].split()[0] != task.base_sha:
            raise MvpError("stale_base")

    def safe_path(self, path: str):
        root = self.config.workspace
        candidate = root / path.rstrip("/")
        if not candidate.resolve().is_relative_to(root):
            raise MvpError("write_path_escapes_workspace")
        for item in (candidate, *candidate.parents):
            if item == root:
                break
            if item.is_symlink():
                raise MvpError("symlink_write_path")

    def preflight(self, task: Task):
        self.registered()
        self.baseline(task)
        if self.git("status", "--porcelain=v1", "--untracked-files=all"):
            raise MvpError("workspace_not_clean")
        branch = self.git("symbolic-ref", "--short", "HEAD")
        if branch == self.config.base_branch:
            raise MvpError("dedicated_test_branch_required")
        for path in task.write_paths:
            self.safe_path(path)

    def changes(self) -> list[str]:
        tracked = self.git("diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
        untracked = self.git("ls-files", "--others", "--exclude-standard", "-z")
        return sorted(set(filter(None, (tracked + "\0" + untracked).split("\0"))))

    def check_changes(self, task: Task, changes: list[str]):
        if self.git("rev-parse", "HEAD") != task.base_sha:
            raise MvpError("unexpected_head_change")
        for path in changes:
            self.safe_path(path)
            if not any(path == scope.rstrip("/") or (scope.endswith("/") and path.startswith(scope)) for scope in task.write_paths):
                raise MvpError("write_scope_violation")


def receipt(row) -> str:
    return (f"<!-- codex-v2-mvp:{row['request_id']} -->\n"
            f"MVP-0 status: **{row['state']}**\n\n"
            f"- request_id: `{row['request_id']}`\n"
            f"- claimed: {row['created_at']}\n"
            f"- started: {row['started_at'] or 'not_started'}\n"
            f"- finished: {row['finished_at'] or 'not_finished'}\n"
            f"- exit code: {row['exit_code'] if row['exit_code'] is not None else 'not_available'}\n"
            f"- git diff nonempty (including untracked): { {None: 'unknown', 0: 'false', 1: 'true'}[row['diff_nonempty']] }\n"
            f"- reason: {row['error'] or 'none'}\n\n{row['summary']}\n\n"
            "完整日志仅保存在本机。MVP-0 不提交代码、不创建 PR、不自动合并。")


class Poller:
    def __init__(self, config: Config, store: Store, github: GitHub, runner: CodexRunner,
                 workspace: Workspace | None = None):
        self.config, self.store, self.github, self.runner = config, store, github, runner
        self.workspace = workspace or Workspace(config)

    def send_receipt(self, row):
        try:
            comment_id = self.github.post_receipt(row["issue_number"], receipt(row))
            self.store.receipt_sent(row["id"], comment_id)
        except MvpError as exc:
            LOG.error("receipt_pending issue=%s code=%s", row["issue_number"], exc)

    def execute(self, task_id: int, task: Task):
        exit_code, diff_nonempty, error, state = None, None, None, "failed"
        summary = "任务未完成；请查看本机诊断。"
        interrupted = False
        try:
            self.workspace.preflight(task)
            metadata = self.runner.prepare(self.config.workspace)
            self.store.start(task_id, metadata)
            prompt = ("完成以下已授权测试任务。只修改列出的相对路径，目录以 / 结尾。"
                      "不要创建提交、切换分支、修改 Git 配置、push、创建 PR 或部署。\n"
                      + json.dumps(task.write_paths, ensure_ascii=False) + "\n\n" + task.prompt)
            result = self.runner.run(metadata, prompt, self.config.state_dir / "runs" / task.request_id,
                                     self.config.timeout_seconds,
                                     lambda kind, detail: self.store.event(task_id, kind, detail))
            exit_code, error = result.exit_code, result.error
            interrupted = error == "interrupted"
            changes = self.workspace.changes()
            diff_nonempty = bool(changes)
            if error is None:
                self.workspace.check_changes(task, changes)
                self.workspace.baseline(task)
                state = "succeeded"
                summary = f"Codex CLI 完成，检测到 {len(changes)} 项 Git 可见文件变化。"
        except MvpError as exc:
            error = str(exc)
            if error == "process_cleanup_failed":
                # Leave running intact: no next task until a human inspects the process tree.
                self.store.event(task_id, "cleanup_failed", {})
                raise
            state = "stale_base" if error == "stale_base" else "failed"
        except KeyboardInterrupt:
            if self.store.get(task_id)["state"] == "running":
                # An interrupt outside the runner's confirmed cleanup path is uncertain.
                self.store.event(task_id, "interrupted_cleanup_unknown", {})
                raise
            error, interrupted = "interrupted", True
        except Exception:
            # Persist a safe failure; keep the exception and local evidence off GitHub.
            error = "local_execution_error"
            LOG.error("local_execution_error task_id=%s", task_id)
        self.store.finish(task_id, state, exit_code, error, diff_nonempty, summary)
        LOG.info("task_finished task_id=%s state=%s exit_code=%s", task_id, state, exit_code)
        self.send_receipt(self.store.get(task_id))
        if interrupted:
            raise KeyboardInterrupt

    def once(self):
        if self.store.unfinished():
            raise MvpError("unfinished_task_requires_manual_inspection")
        repo_id = self.github.identity()
        mismatch = self.store.db.execute("SELECT 1 FROM tasks WHERE repository_id!=? OR host_id!=? LIMIT 1",
                                         (repo_id, self.config.host_id)).fetchone()
        if mismatch:
            raise MvpError("database_host_or_repo_mismatch")
        for row in self.store.pending_receipts():
            self.send_receipt(row)
        for issue in self.github.issues():
            if self.store.by_issue(repo_id, positive_id(issue.get("id"))):
                continue
            try:
                task = parse_task(issue, self.github.comments(positive_id(issue.get("number"))), self.config)
                task_id = self.store.claim(repo_id, issue, task)
            except MvpError as exc:
                LOG.warning("task_rejected issue=%s code=%s", issue.get("number"), exc)
                continue
            if task_id is not None:
                self.execute(task_id, task)
                return 1
        return 0


@contextmanager
def exclusive_lock(path: Path):
    import fcntl
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MvpError("another_mvp_poller_is_running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="poll once and execute at most one new task")
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
        config = Config.load(args.config)
        workspace = Workspace(config)
        workspace.registered()
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        common = Path(workspace.git("rev-parse", "--path-format=absolute", "--git-common-dir"))
        # Also lock the registered checkout, even if someone supplies a second state directory.
        with exclusive_lock(config.state_dir / "poller.lock"), exclusive_lock(common / "codex-v2-mvp0.lock"):
            store = Store(config.state_dir / "mvp0.sqlite3")
            try:
                poller = Poller(config, store, GitHub(config.repo), CodexRunner(), workspace)
                while True:
                    try:
                        count = poller.once()
                        LOG.info("poll_complete new_tasks=%s", count)
                    except MvpError as exc:
                        LOG.error("poll_failed code=%s", exc)
                        if args.once or store.unfinished():
                            return 1
                    if args.once:
                        last = store.db.execute("SELECT state FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
                        return int(bool(store.pending_receipts()) or bool(count and last["state"] != "succeeded"))
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
