"""MVP-2: account-wide Host routing, persistent chats, model modes and PR delivery."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
from urllib.parse import quote

from .model_api import ModelRegistry
from .mvp0 import exclusive_lock, positive_id, read_json
from .mvp0_runner import MvpError, utc_now
from .mvp1 import AccountGitHub, AccountStore, ManagedWorkspace, ReliableGitHub, run_git
from .mvp2_contract import DesktopConfig, MARKER, TITLE_PREFIX, parse_desktop_task
from .mvp2_runner import ApiFileRunner, SessionCodexRunner, discover_session, validate_cli_session

LOG = logging.getLogger("codex-v2-mvp2")


class DesktopStore(AccountStore):
    schema_version = 3

    def __init__(self, path):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS deliveries (
                task_id INTEGER PRIMARY KEY REFERENCES tasks(id), source_repo TEXT NOT NULL,
                target_id INTEGER NOT NULL, target_branch TEXT NOT NULL, options_json TEXT NOT NULL,
                config_snapshot TEXT NOT NULL, session_id TEXT, execution_completed INTEGER NOT NULL DEFAULT 0,
                publication_state TEXT NOT NULL DEFAULT 'not_started', commit_sha TEXT, pr_url TEXT);
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, target_id INTEGER NOT NULL, host_id TEXT NOT NULL,
                backend TEXT NOT NULL, context_path TEXT, updated_at TEXT NOT NULL);
        """)

    def claim_desktop(self, source, target, issue, task, snapshot):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM tasks WHERE request_id=? OR (repository_id=? AND issue_id=?)",
                               (task.request_id, source.id, issue["id"])).fetchone():
                return None
            if self.unfinished():
                raise MvpError("unfinished_task_requires_manual_inspection")
            cursor = self.db.execute("""INSERT INTO tasks(repository_id,issue_id,issue_number,request_id,
                host_id,repo,state,base_sha,prompt,write_paths,comment_id,contract_hash,created_at)
                VALUES(?,?,?,?,?,?,'queued',?,?,?,?,?,?)""",
                (source.id, issue["id"], issue["number"], task.request_id, task.host_id, target.full_name,
                 task.base_sha, task.prompt, json.dumps(task.write_paths), task.comment_id, task.contract_hash, utc_now()))
            task_id = cursor.lastrowid
            self.db.execute("INSERT INTO deliveries(task_id,source_repo,target_id,target_branch,options_json,config_snapshot) VALUES(?,?,?,?,?,?)",
                (task_id, source.full_name, target.id, target.default_branch,
                 json.dumps({"session": task.session, "models": task.models}), json.dumps(snapshot)))
            self.event(task_id, "claimed", {"source_repo": source.full_name, "target_repo": target.full_name,
                                           "mode": task.models["mode"]})
            return task_id

    def delivery(self, task_id):
        return self.db.execute("SELECT * FROM deliveries WHERE task_id=?", (task_id,)).fetchone()

    def save_session(self, task_id, session_id, backend, context_path=None):
        row, delivery = self.get(task_id), self.delivery(task_id)
        with self.transaction():
            existing = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if existing and (existing["target_id"], existing["host_id"], existing["backend"]) != (delivery["target_id"], row["host_id"], backend):
                raise MvpError("session_binding_mismatch")
            self.db.execute("""INSERT INTO sessions VALUES(?,?,?,?,?,?) ON CONFLICT(session_id)
                DO UPDATE SET context_path=excluded.context_path,updated_at=excluded.updated_at""",
                (session_id, delivery["target_id"], row["host_id"], backend, str(context_path) if context_path else None, utc_now()))
            self.db.execute("UPDATE deliveries SET session_id=? WHERE task_id=?", (session_id, task_id))
            self.event(task_id, "session_saved", {"session_id": session_id, "backend": backend})

    def completed_execution(self, task_id):
        with self.transaction():
            self.db.execute("UPDATE deliveries SET execution_completed=1,publication_state='pending' WHERE task_id=?", (task_id,))
            self.event(task_id, "execution_completed", {})

    def publication(self, task_id, **values):
        if not values or set(values) - {"publication_state", "commit_sha", "pr_url"}:
            raise MvpError("invalid_publication_update")
        with self.transaction():
            self.db.execute("UPDATE deliveries SET " + ",".join(k + "=?" for k in values) + " WHERE task_id=?",
                            (*values.values(), task_id))
            self.event(task_id, "publication_updated", values)


class DesktopGitHub(AccountGitHub):
    def client(self, repo):
        client = super().client(repo)
        client.title_prefix = TITLE_PREFIX
        return client


class DesktopWorkspace(ManagedWorkspace):
    def preflight(self, task):
        super().preflight(task)
        self.git("branch", "-m", branch_name(task.host_id, task.request_id))


def branch_name(host, request):
    return "codex-mvp2/" + host + "/" + request


def receipt(row, delivery):
    return (f"<!-- codex-v2-mvp2:{row['request_id']} -->\n"
        f"MVP-2 status: **{row['state']}**\n\n"
        f"- host_id: `{row['host_id']}`\n- request_id: `{row['request_id']}`\n"
        f"- target: `{row['repo']}`\n- finished: {row['finished_at']}\n"
        f"- mode: `{json.loads(delivery['options_json'])['models']['mode']}`\n"
        f"- session_id: `{delivery['session_id'] or 'not_available'}`\n"
        f"- commit: `{delivery['commit_sha'] or 'not_created'}`\n"
        f"- PR: {delivery['pr_url'] or 'not_created'}\n"
        f"- exit code: {row['exit_code'] if row['exit_code'] is not None else 'not_available'}\n"
        f"- reason: `{row['error'] or 'none'}`\n\n{row['summary']}\n\n"
        "成果与执行日志保存在本机。PR 由用户审查并人工合并。")


class Publisher:
    def __init__(self, github, store):
        self.github, self.store = github, store

    def publish(self, task_id):
        row, d = self.store.get(task_id), self.store.delivery(task_id)
        target = self.github.repository(row["repo"], d["target_id"])
        if target.default_branch != d["target_branch"]:
            raise MvpError("stale_base")
        from .mvp0 import Config, Task, Workspace
        task = Task(row["request_id"], row["host_id"], row["repo"], row["base_sha"], row["prompt"],
                    tuple(json.loads(row["write_paths"])), row["comment_id"], row["contract_hash"])
        workspace = Path(row["cwd"])
        config = Config(row["host_id"], row["repo"], (), workspace, (workspace,), Path("/"), d["target_branch"])
        ws = Workspace(config)
        ws.registered()
        branch = branch_name(row["host_id"], row["request_id"])
        if ws.git("symbolic-ref", "--short", "HEAD") != branch:
            raise MvpError("publication_branch_mismatch")
        self.github.check_base(target, task)
        commit = d["commit_sha"]
        if not commit:
            changes = ws.changes()
            ws.check_changes(task, changes)
            if not changes:
                self.store.publication(task_id, publication_state="no_changes")
                return None
            self.store.publication(task_id, publication_state="committing")
            run_git(workspace, "--literal-pathspecs", "add", "-A", "--", *changes)
            # Git hooks are not part of model output or the publication operation.
            run_git(workspace, "-c", "core.hooksPath=/dev/null", "-c", "user.name=" + row["host_id"] + " Codex",
                    "-c", "user.email=" + self.github.config.owner + "@users.noreply.github.com",
                    "commit", "-m", "Codex task " + row["request_id"])
            commit = ws.git("rev-parse", "HEAD")
            self.store.publication(task_id, commit_sha=commit, publication_state="committed")
        if ws.git("rev-parse", "HEAD") != commit or ws.git("status", "--porcelain=v1", "--untracked-files=all"):
            raise MvpError("publication_workspace_changed")
        # Never force push; refuse an unrelated branch already present at the destination.
        remote = run_git(workspace, "ls-remote", "origin", "refs/heads/" + branch)
        if remote and remote.split()[0] != commit:
            raise MvpError("publication_remote_branch_conflict")
        if not remote:
            run_git(workspace, "push", "origin", "HEAD:refs/heads/" + branch, timeout=120)
        self.store.publication(task_id, publication_state="pushed")
        client = self.github.client(target)
        head = self.github.config.owner + ":" + branch
        prs = client.pages(f"repos/{target.full_name}/pulls?state=all&head={quote(head, safe='')}")
        if prs:
            if len(prs) != 1 or prs[0].get("head", {}).get("sha") != commit or prs[0].get("base", {}).get("ref") != d["target_branch"]:
                raise MvpError("publication_pr_conflict")
            pr = prs[0]
        else:
            source = f"https://github.com/{d['source_repo']}/issues/{row['issue_number']}"
            pr = client.api(f"repos/{target.full_name}/pulls", {"title": "[Codex " + row["host_id"] + "] " + row["request_id"],
                "head": branch, "base": d["target_branch"], "draft": True,
                "body": "Completes the authorized task from " + source + ".\n\n"
                    + "Request: `" + row["request_id"] + "`\nHost: `" + row["host_id"] + "`\n"
                    + "Model execution and authorized-path checks completed. Review the changes before merging.\n"
                    + "Execution details remain on the local host; no raw prompts or model logs are published."})
        url = pr.get("html_url") if isinstance(pr, dict) else None
        if not isinstance(url, str) or not url.startswith("https://github.com/" + target.full_name + "/pull/") or not url.rsplit("/", 1)[-1].isdigit():
            raise MvpError("invalid_pr_response")
        self.store.publication(task_id, pr_url=url, publication_state="published")
        return url


class DesktopPoller:
    def __init__(self, config, store, github=None, registry=None, runner=None, workspace_factory=DesktopWorkspace, publisher=None):
        self.config, self.store = config, store
        self.github = github or DesktopGitHub(config)
        self.registry = registry or ModelRegistry(config.models_file)
        self.runner = runner or SessionCodexRunner()
        self.workspace_factory = workspace_factory
        self.publisher = publisher or Publisher(self.github, store)
        self.errors = 0

    def send_receipt(self, row):
        d = self.store.delivery(row["id"])
        try:
            source = self.github.repository(d["source_repo"], row["repository_id"])
            client = self.github.client(source)
            comment_id = client.post_receipt(row["issue_number"], receipt(row, d))
            self.store.receipt_sent(row["id"], comment_id)
        except MvpError as exc:
            self.errors += 1
            LOG.error("receipt_pending task_id=%s code=%s", row["id"], exc)

    def check_session(self, task, target):
        if task.session["mode"] == "new":
            return None
        session_id = task.session["id"]
        backend = task.models["primary"]["provider"]
        known = self.store.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if known:
            if (known["target_id"], known["host_id"], known["backend"]) != (target.id, task.host_id, backend):
                raise MvpError("session_binding_mismatch")
            return known
        if backend != "codex":
            raise MvpError("api_session_not_found")
        metadata = validate_cli_session(session_id)
        old = Path(metadata.get("cwd", ""))
        remote = run_git(old, "remote", "get-url", "origin")
        if remote not in {"https://github.com/" + target.full_name + ".git", "https://github.com/" + target.full_name,
                          "git@github.com:" + target.full_name + ".git"}:
            raise MvpError("imported_session_repo_mismatch")
        return None

    def finish_publication(self, task_id):
        try:
            url = self.publisher.publish(task_id)
        except MvpError as exc:
            error = str(exc)
            if error in {"stale_base", "publication_branch_mismatch", "publication_workspace_changed", "publication_remote_branch_conflict",
                         "publication_pr_conflict", "unexpected_head_change", "write_scope_violation", "symlink_write_path"}:
                self.store.finish(task_id, "stale_base" if error == "stale_base" else "failed", 0, error, True,
                                  "执行成果已留在本机；发布检查失败，需要人工核对。")
                self.send_receipt(self.store.get(task_id))
            else:
                self.errors += 1
                self.store.event(task_id, "publication_pending", {"error": error})
                LOG.error("publication_pending task_id=%s code=%s", task_id, error)
            return
        if url:
            self.store.publication(task_id, pr_url=url, publication_state="published")
        self.store.finish(task_id, "succeeded", 0, None, bool(url),
            "成果保存在本机，已提交分支并创建草稿 PR。" if url else "任务完成，无文件变化，因此没有可创建的 PR。")
        self.send_receipt(self.store.get(task_id))

    def execute(self, task_id, task, target, known_session):
        evidence = self.config.state_dir / "runs" / task.request_id
        selected = self.config.state_dir / "selections" / task.request_id
        selected.mkdir(parents=True, exist_ok=False, mode=0o700)
        # Freeze the registry for this run; never put API keys in this snapshot.
        d = self.store.delivery(task_id)
        snapshot = json.loads(d["config_snapshot"])
        models_path, options_path = selected / "models.json", selected / "options.json"
        models_path.write_text(json.dumps(snapshot["registry"]), encoding="utf-8")
        options_path.write_text(json.dumps(task.models), encoding="utf-8")
        config = replace(self.config, models_file=models_path)
        registry = ModelRegistry(models_path)
        workspace = target.task_config(config, task.request_id).workspace
        ws = self.workspace_factory(target.task_config(config, task.request_id), config, target, self.github,
                                    lambda kind, detail: self.store.event(task_id, kind, detail))
        code, error, changed = None, None, None
        try:
            ws.preflight(task)
            if task.models["mode"] == "api":
                history = None
                if known_session:
                    context = Path(known_session["context_path"])
                    if context.is_symlink() or not context.resolve().is_relative_to(self.config.state_dir) or context.stat().st_size > 1024*1024:
                        raise MvpError("invalid_api_context")
                    history = read_json(context.read_text(encoding="utf-8"))
                metadata = {"cli_version": "api-agent/0.1.0", "argv": ["api-agent", task.models["primary"]["provider"]], "cwd": str(workspace)}
                self.store.start(task_id, metadata)
                result, session_id, context = ApiFileRunner(registry).run_task(task, workspace, evidence, config.timeout_seconds,
                    lambda k, v: self.store.event(task_id, k, v), history, task.session.get("id"))
            else:
                metadata = self.runner.prepare_task(workspace, task, config, registry, options_path)
                self.store.start(task_id, metadata)
                prompt = ("Complete the current authorized task in the CURRENT workspace: " + str(workspace)
                    + ". Old conversation paths/permissions are superseded. Only modify these relative paths: "
                    + json.dumps(task.write_paths) + ". Do not commit, change branches, change Git configuration, push, create PRs, or deploy. "
                    + "The controller will validate and publish your changes.\n")
                if task.models["mode"] == "gpt-led":
                    prompt += ("You are the GPT leader. Use collaborators.consult_model to delegate focused questions to configured external models as needed; "
                        "evaluate their replies, make the final decisions and perform the file changes yourself. Configured models: "
                        + json.dumps(task.models["collaborators"]) + "\n")
                else:
                    prompt += "Use only the selected GPT model; do not call external model APIs or spawn other models.\n"
                result = self.runner.run(metadata, prompt + task.prompt, evidence, config.timeout_seconds,
                                         lambda k, v: self.store.event(task_id, k, v))
                session_id = discover_session(evidence, task.session.get("id")) if result.error is None else None
                context = None
            code, error = result.exit_code, result.error
            changes = ws.changes()
            changed = bool(changes)
            if error is not None:
                raise MvpError(error)
            ws.check_changes(task, changes)
            ws.baseline(task)
            self.store.save_session(task_id, session_id, task.models["primary"]["provider"],
                                    evidence / "context.json" if context is not None else None)
            self.store.completed_execution(task_id)
        except MvpError as exc:
            error = str(exc)
            if error == "process_cleanup_failed":
                self.store.event(task_id, "cleanup_failed", {})
                raise
            self.store.finish(task_id, "stale_base" if error == "stale_base" else "failed", code, error, changed,
                              "任务未完成；已有文件与诊断保存在本机。")
            self.send_receipt(self.store.get(task_id))
            if error == "interrupted":
                raise KeyboardInterrupt()
            return
        except KeyboardInterrupt:
            self.store.event(task_id, "interrupted_cleanup_unknown", {})
            raise
        except Exception:
            self.store.finish(task_id, "failed", code, "local_execution_error", changed, "任务未完成；请检查本机诊断。")
            self.send_receipt(self.store.get(task_id))
            LOG.exception("local_execution_error task_id=%s", task_id)
            return
        self.finish_publication(task_id)

    def once(self):
        self.errors = 0
        repos = self.github.repositories()
        self.store.bind(self.config, self.github.owner_id)
        active = self.store.unfinished()
        if active:
            d = self.store.delivery(active["id"])
            # Resume only publication, never replay a model execution after a crash.
            if not d or not d["execution_completed"] or d["publication_state"] == "committing":
                raise MvpError("unfinished_task_requires_manual_inspection")
            self.finish_publication(active["id"])
            return 0
        for row in self.store.pending_receipts():
            self.send_receipt(row)
        candidates = []
        for source in repos:
            client = self.github.client(source)
            try:
                candidates += [(positive_id(i.get("id")), source, client, i) for i in client.issues()
                               if not self.store.by_issue(source.id, positive_id(i.get("id")))]
            except MvpError as exc:
                self.errors += 1
                LOG.error("repository_poll_failed repository_id=%s code=%s", source.id, exc)
        for _, source, client, issue in sorted(candidates, key=lambda c: c[0]):
            try:
                comments = client.comments(positive_id(issue.get("number")))
                task = parse_desktop_task(issue, comments, source, self.config)
                target = next((r for r in repos if r.full_name.lower() == task.repo.lower()), None)
                if target is None:
                    raise MvpError("target_repository_not_visible")
                self.registry.validate(task.models, cli=True)
                known_session = self.check_session(task, target)
                # Confirm source/target IDs and the unedited contract immediately before claim.
                self.github.repository(source.full_name, source.id)
                current_issue = client.api(f"repos/{source.full_name}/issues/{issue['number']}")
                current = parse_desktop_task(current_issue, client.comments(issue["number"]), source, self.config)
                if current.contract_hash != task.contract_hash or current_issue.get("id") != issue.get("id"):
                    raise MvpError("authorization_changed")
                snapshot = {"host_id": self.config.host_id, "hub_repo": self.config.hub_repo,
                            "registry": {"providers": self.registry.providers, **self.registry.limits}}
                task_id = self.store.claim_desktop(source, target, issue, task, snapshot)
            except MvpError as exc:
                if str(exc) != "wrong_host":
                    LOG.warning("task_rejected repository_id=%s issue=%s code=%s", source.id, issue.get("number"), exc)
                continue
            if task_id is not None:
                self.execute(task_id, task, target, known_session)
                return 1
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--list-repos", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.name != "posix":
        LOG.error("linux_or_wsl_required")
        return 2
    os.umask(0o077)
    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    try:
        config = DesktopConfig.load(args.config)
        registry = ModelRegistry(config.models_file)
        github = DesktopGitHub(config)
        if args.list_repos:
            print(json.dumps([r.__dict__ for r in github.repositories()], ensure_ascii=False, indent=2))
            return 0
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # The same root lock as MVP-1 prevents competing controllers in a shared root.
        with exclusive_lock(config.state_dir / "poller.lock"), exclusive_lock(config.workspace_root / ".mvp1.lock"):
            store = DesktopStore(config.state_dir / "mvp2.sqlite3")
            try:
                poller = DesktopPoller(config, store, github, registry)
                while True:
                    try:
                        count = poller.once()
                    except MvpError as exc:
                        LOG.error("poll_failed code=%s", exc)
                        if args.once or store.unfinished():
                            return 1
                        import time
                        time.sleep(config.poll_seconds)
                        continue
                    LOG.info("poll_complete new_tasks=%s repository_errors=%s", count, poller.errors)
                    if args.once:
                        return int(bool(poller.errors or store.unfinished() or store.pending_receipts()) or
                                   bool(count and store.db.execute("SELECT state FROM tasks ORDER BY id DESC LIMIT 1").fetchone()[0] != "succeeded"))
                    import time
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
