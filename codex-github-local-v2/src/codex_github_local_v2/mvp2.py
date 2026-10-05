"""MVP-2: account-wide Host routing, persistent chats, model modes and PR delivery."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
from urllib.parse import quote

from .model_api import ModelRegistry
from .listener_status import ListenerStatus
from .mvp0 import exclusive_lock, positive_id, read_json
from .mvp0_runner import MvpError, utc_now
from .mvp1 import AccountGitHub, AccountStore, ManagedWorkspace, ReliableGitHub, run_git
from .mvp2_contract import DesktopConfig, MARKER, TITLE_PREFIX, parse_desktop_task
from .mvp2_runner import ApiFileRunner, SessionCodexRunner, discover_session, validate_cli_session
from .remote_store import RemoteStore, REMOTE_SQL
from .remote_git import RemoteWorkspace, run_remote_git

LOG = logging.getLogger("codex-v2-mvp2")


class DesktopStore(RemoteStore, AccountStore):
    schema_version = 5

    @classmethod
    def migrate(cls, path):
        """Explicit idle-only engine migration; frozen task rows remain unchanged."""
        with sqlite3.connect(path, isolation_level=None) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == cls.schema_version:
                return
            if version not in {3,4}:
                raise MvpError("unsupported_mvp_schema")
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM tasks WHERE state IN ('queued','running')").fetchone():
                    raise MvpError("migration_requires_idle")
                if version == 3:
                    db.execute("DROP INDEX one_active_task")
                    db.execute("CREATE INDEX active_tasks ON tasks(state) WHERE state IN ('queued','running')")
                for statement in REMOTE_SQL.split(';'):
                    if statement.strip():db.execute(statement)
                db.execute('INSERT OR IGNORE INTO remote_channels SELECT id,? FROM tasks',(utc_now(),))
                db.execute("PRAGMA user_version=5")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def __init__(self, path):
        super().__init__(path)
        self.path = path
        # A fresh Store creates the inherited serial index; schema 4 uses atomic capacity checks.
        with self.transaction():
            self.db.execute("DROP INDEX IF EXISTS one_active_task")
            self.db.execute("CREATE INDEX IF NOT EXISTS active_tasks ON tasks(state) WHERE state IN ('queued','running')")
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
        self.db.executescript(REMOTE_SQL)

    def active_tasks(self):
        return self.db.execute("SELECT * FROM tasks WHERE state IN ('queued','running') ORDER BY id").fetchall()

    def claim_desktop(self, source, target, issue, task, snapshot, max_parallel_tasks=1):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM tasks WHERE request_id=? OR (repository_id=? AND issue_id=?)",
                               (task.request_id, source.id, issue["id"])).fetchone():
                return None
            active = self.active_tasks()
            if len(active) >= max_parallel_tasks:
                raise MvpError("unfinished_task_requires_manual_inspection" if max_parallel_tasks == 1 else "parallel_capacity_reached")
            if task.session['mode'] == 'resume':
                for row in active:
                    delivery = self.delivery(row['id'])
                    session = json.loads(delivery['options_json'])['session']
                    if task.session['id'] in {session.get('id'), delivery['session_id']}:
                        raise MvpError("session_busy")
            cursor = self.db.execute("""INSERT INTO tasks(repository_id,issue_id,issue_number,request_id,
                host_id,repo,state,base_sha,prompt,write_paths,comment_id,contract_hash,created_at)
                VALUES(?,?,?,?,?,?,'queued',?,?,?,?,?,?)""",
                (source.id, issue["id"], issue["number"], task.request_id, task.host_id, target.full_name,
                 task.base_sha, task.prompt, json.dumps(task.write_paths), task.comment_id, task.contract_hash, utc_now()))
            task_id = cursor.lastrowid
            self.db.execute('INSERT INTO remote_channels VALUES(?,?)',(task_id,utc_now()))
            self.db.execute("INSERT INTO deliveries(task_id,source_repo,target_id,target_branch,options_json,config_snapshot) VALUES(?,?,?,?,?,?)",
                (task_id, source.full_name, target.id, target.default_branch,
                 json.dumps({"session": task.session, "models": task.models}), json.dumps(snapshot)))
            self.event(task_id, "claimed", {"source_repo": source.full_name, "target_repo": target.full_name,
                                           "mode": task.models["mode"]})
            self.queue_reply(task_id, 'claimed/' + task.request_id,
                f"本机 **{task.host_id}** 已领取任务，正在准备执行。\n\n模型：`{task.models['primary']['model']}` · 思考强度：`{task.models['primary']['effort']}`。\n\n直接在本 Issue 追加指示即可；询问进度可发送 `/codex status`，停止可发送 `/codex stop`。默认执行不设时间或数据大小上限。")
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


class RemoteGitHubClient(ReliableGitHub):
    def pages(self,endpoint):
        rows=[];page=1
        separator='&' if '?' in endpoint else '?'
        while True:
            batch=self.api(f'{endpoint}{separator}per_page=100&page={page}')
            if not isinstance(batch,list) or any(not isinstance(i,dict) for i in batch):raise MvpError('invalid_github_page')
            rows.extend(batch)
            if len(batch)<100:return rows
            page+=1

    def issues(self):
        return [i for i in self.pages(f'repos/{self.repo}/issues?state=open&sort=created&direction=asc')
                if 'pull_request' not in i and (str(i.get('title','')).startswith((TITLE_PREFIX,'[codex]'))
                    or str(i.get('body','')).startswith('/codex run '))]


class DesktopGitHub(AccountGitHub):
    def __init__(self,config,transport=None):
        super().__init__(config,transport or RemoteGitHubClient(''))
    def check_base(self,repo,task):
        # Verify the requested commit exists in this repository, rather than requiring main to freeze.
        self.repository(repo.full_name,repo.id)
        commit=self.client(repo).api(f'repos/{repo.full_name}/commits/{task.base_sha}')
        if not isinstance(commit,dict) or commit.get('sha')!=task.base_sha:raise MvpError('invalid_base_sha')

    def client(self, repo):
        client = RemoteGitHubClient(repo.full_name)
        client.repository_id=repo.id
        client.writer_id=self.owner_id
        client.title_prefix = TITLE_PREFIX
        return client


class DesktopWorkspace(ManagedWorkspace):
    pulse=staticmethod(lambda:None)
    evidence=None
    reference=None
    safe_path=RemoteWorkspace.safe_path
    check_changes=RemoteWorkspace.check_changes

    def git(self,*args):
        return run_remote_git(self.config.workspace,*args,pulse=self.pulse,evidence=self.evidence,record=self.record)

    def preflight(self, task):
        self.github.check_base(self.repo, task)
        root, workspace = self.account.workspace_root, self.config.workspace
        if root.is_symlink() or workspace.parent.is_symlink() or workspace.is_symlink() or not workspace.resolve().is_relative_to(root.resolve()):
            raise MvpError('managed_workspace_path_escape')
        if workspace.exists():
            raise MvpError('managed_workspace_already_exists')
        workspace.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace.mkdir(mode=0o700)
        self.record('workspace_preparing', {'repository_id': self.repo.id, 'cwd': str(workspace)})
        reference=[]
        if self.reference:
            remote=run_remote_git(self.reference,'remote','get-url','origin',pulse=self.pulse,evidence=self.evidence,record=self.record)
            if remote in {f'https://github.com/{self.repo.full_name}.git',f'https://github.com/{self.repo.full_name}'}:
                reference=['--reference-if-able',str(self.reference),'--dissociate']
        run_remote_git(workspace.parent, 'clone', '--no-checkout', '--single-branch',*reference,'--branch', self.repo.default_branch,
                '--', f'https://github.com/{self.repo.full_name}.git', str(workspace),pulse=self.pulse,evidence=self.evidence,record=self.record)
        # An older authorized commit remains valid if main advances while downloading.
        try:self.git('cat-file', '-e', task.base_sha + '^{commit}')
        except MvpError:
            self.git('fetch','origin',task.base_sha)
            self.git('cat-file','-e',task.base_sha+'^{commit}')
        self.git('checkout', '-b', branch_name(task.host_id, task.request_id), task.base_sha)
        self.registered()
        if self.git('status', '--porcelain=v1', '--untracked-files=all'):
            raise MvpError('workspace_not_clean')
        for scope in task.write_paths:
            self.safe_path(scope)
        self.record('workspace_prepared', {'repository_id': self.repo.id, 'base_sha': task.base_sha})

    def baseline(self, task):
        # Publishing a branch from its frozen commit is normal when other computers update main.
        self.registered()
        head=self.git('rev-parse','HEAD')
        if head!=task.base_sha:self.git('merge-base','--is-ancestor',task.base_sha,head)
        if self.git('symbolic-ref','--short','HEAD')!=branch_name(task.host_id,task.request_id):raise MvpError('publication_branch_mismatch')


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
        "成果与执行日志保存在本机。直接在此 Issue 追加指示可继续原对话；`/codex status` 查询进度，`/codex retry` 续跑，`/codex merge` 合并成果 PR。")


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
                    self.store.effective_paths(task_id), row["comment_id"], row["contract_hash"])
        workspace = Path(row["cwd"])
        config = Config(row["host_id"], row["repo"], (), workspace, (workspace,), Path("/"), d["target_branch"])
        def pulse():
            for msg in self.store.inbox(task_id):
                if msg['action']=='stop':
                    self.store.delivered_message(msg['id']);raise MvpError('cancelled_by_owner')
        ws = RemoteWorkspace(config,pulse,workspace.parent/'publication-evidence'/row['request_id'],lambda kind,detail:self.store.event(task_id,kind,detail))
        ws.registered()
        branch = branch_name(row["host_id"], row["request_id"])
        if ws.git("symbolic-ref", "--short", "HEAD") != branch:
            raise MvpError("publication_branch_mismatch")
        commit = d["commit_sha"]
        prior_commit=commit
        actual=ws.git('rev-parse','HEAD')
        expected=commit or task.base_sha
        if d['publication_state']=='committing' and actual!=expected:
            parent=ws.git('rev-parse','HEAD^')
            subject=ws.git('show','-s','--format=%s','HEAD')
            if parent!=expected or subject!='Codex task '+row['request_id'] or ws.changes():
                raise MvpError('publication_workspace_changed')
            changed=ws.git('diff','--name-only','--no-renames','-z',expected,actual,'--').split('\0')
            for path in filter(None,changed):
                ws.safe_path(path)
                if not any(s=='.' or path==s.rstrip('/') or (s.endswith('/') and path.startswith(s)) for s in task.write_paths):raise MvpError('write_scope_violation')
            commit=actual
            self.store.publication(task_id,commit_sha=actual,publication_state='committed')
        elif not commit and actual!=task.base_sha:
            ws.check_changes(task,ws.changes())
            commit=actual
            self.store.publication(task_id,commit_sha=commit,publication_state='committed')
        if commit and ws.git('rev-parse','HEAD')==commit and ws.changes():
            task=replace(task,base_sha=commit)
            commit=None
        if not commit:
            changes = ws.changes()
            ws.check_changes(task, changes)
            if not changes:
                self.store.publication(task_id, publication_state="no_changes")
                return None
            self.store.publication(task_id, publication_state="committing")
            ws.git("--literal-pathspecs", "add", "-A", "--", *changes)
            # Git hooks are not part of model output or the publication operation.
            ws.git("-c", "core.hooksPath=/dev/null", "-c", "user.name=" + row["host_id"] + " Codex",
                    "-c", "user.email=" + self.github.config.owner + "@users.noreply.github.com",
                    "commit", "-m", "Codex task " + row["request_id"])
            commit = ws.git("rev-parse", "HEAD")
            self.store.publication(task_id, commit_sha=commit, publication_state="committed")
        if ws.git("rev-parse", "HEAD") != commit or ws.git("status", "--porcelain=v1", "--untracked-files=all"):
            raise MvpError("publication_workspace_changed")
        # Never force push; refuse an unrelated branch already present at the destination.
        remote = ws.git("ls-remote", "origin", "refs/heads/" + branch)
        if remote and remote.split()[0] != commit:
            if not prior_commit or remote.split()[0]!=prior_commit:raise MvpError("publication_remote_branch_conflict")
            ws.git('merge-base','--is-ancestor',prior_commit,commit)
        if not remote or remote.split()[0]!=commit:
            ws.git("push", "origin", "HEAD:refs/heads/" + branch)
        self.store.publication(task_id, publication_state="pushed")
        client = self.github.client(target)
        head = self.github.config.owner + ":" + branch
        prs = client.pages(f"repos/{target.full_name}/pulls?state=all&head={quote(head, safe='')}")
        prs=[p for p in prs if p.get('state','open')=='open']
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
        self.status = ListenerStatus(config)
        self.workers = {}
        from .issue_control import IssueControl
        self.remote=IssueControl(config,store,self.github)

    def reap_workers(self):
        for task_id, process in list(self.workers.items()):
            if not process.is_alive():
                process.join()
                del self.workers[task_id]

    def start_worker(self, task_id, task, target, known_session):
        process = multiprocessing.get_context('fork').Process(
            target=self.worker_execute, args=(task_id, task, target, dict(known_session) if known_session else None))
        process.start()
        self.workers[task_id] = process

    def worker_execute(self, task_id, task, target, known_session):
        def stop(*_):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        path = self.store.path
        self.store.close()
        self.store = DesktopStore(path)
        from .process_identity import identity
        self.store.event(task_id,'worker_started',{'lease':identity(os.getpid())})
        from .issue_control import IssueControl
        self.remote=IssueControl(self.config,self.store,self.github)
        if isinstance(self.publisher, Publisher):
            self.publisher = Publisher(self.github, self.store)
        try:
            if task is None:self.finish_publication(task_id)
            else:self.execute(task_id, task, target, known_session)
        except KeyboardInterrupt:
            # execute/runner records interruption and cleanup; uncertain rows stay blocked.
            pass
        finally:
            self.store.close()

    def stop_workers(self):
        # Interrupt workers so each runner can terminate its own model process group.
        for process in self.workers.values():
            if process.is_alive():
                os.kill(process.pid, signal.SIGINT)
        for process in self.workers.values():
            process.join(timeout=10)
        if any(process.is_alive() for process in self.workers.values()):
            raise MvpError('process_cleanup_failed')
        self.workers.clear()

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
            "成果保存在本机，已上传分支并确认成果 PR。" if url else "任务完成，无文件变化，因此没有可创建的 PR。")
        self.send_receipt(self.store.get(task_id))

    def execute(self, task_id, task, target, known_session):
        evidence = self.config.state_dir / "runs" / task.request_id
        selected = self.config.state_dir / "selections" / task.request_id
        generation=self.store.generation(task_id)
        if generation:selected=selected/('continuation-'+str(generation))
        selected.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Freeze the registry for this run; never put API keys in this snapshot.
        d = self.store.delivery(task_id)
        snapshot = json.loads(d["config_snapshot"])
        if generation:snapshot['registry']={"providers":self.registry.providers,**self.registry.limits}
        models_path, options_path = selected / "models.json", selected / "options.json"
        if not models_path.exists():models_path.write_text(json.dumps(snapshot["registry"]), encoding="utf-8")
        if not options_path.exists():options_path.write_text(json.dumps(task.models), encoding="utf-8")
        config = replace(self.config, models_file=models_path)
        registry = ModelRegistry(models_path)
        workspace = target.task_config(config, task.request_id).workspace
        ws = self.workspace_factory(target.task_config(config, task.request_id), config, target, self.github,
                                    lambda kind, detail: self.store.event(task_id, kind, detail))
        code, error, changed = None, None, None
        def control():
            return self.store.inbox(task_id)
        def record(kind,detail):
            self.store.event(task_id,kind,detail)
            if kind=='remote_session_opened':
                self.store.save_session(task_id,detail['session_id'],task.models['primary']['provider'],detail.get('context_path'))
            if kind=='remote_agent_message' and detail.get('phase') in {None,'final_answer'}:
                import hashlib
                text=detail.get('text','')
                self.store.queue_reply(task_id,'model/'+task.request_id+'/'+hashlib.sha256(text.encode()).hexdigest(),text)
            if kind in {'remote_recovery','api_response_recovery'}:
                reason=detail.get('reason','connection_error')
                permanent=reason in {'model_http_400','model_http_401','model_http_403','model_http_404','model_api_key_missing'}
                self.store.queue_reply(task_id,'recovery/'+task.request_id+'/'+reason,
                    ('模型服务拒绝请求，正在保留现场等待接口恢复：`' if permanent else '执行遇到临时问题，正在保留对话恢复：`')+reason+'`。任务不会因次数或时间上限终止；可发送 `/codex status` 查看，或直接追加指示。'
                    + ('请核对模型名、接口参数或服务商的鉴权/额度。' if permanent else ''))
        def cancelled():
            for msg in control():
                if msg['action']=='stop':
                    self.store.delivered_message(msg['id']);raise MvpError('cancelled_by_owner')
        try:
            import time
            if isinstance(ws,DesktopWorkspace):ws.pulse=cancelled;ws.evidence=evidence/'git'
            attempt=0
            # Only directories reserved for this exact task may be recovered; originals are retained.
            while True:
                cancelled()
                try:
                    if workspace.exists() and self.store.get(task_id)['cwd']==str(workspace):
                        ws.registered()
                        if ws.git('symbolic-ref','--short','HEAD')!=branch_name(task.host_id,task.request_id):raise MvpError('publication_branch_mismatch')
                    else:
                        if workspace.exists():
                            owned=self.store.db.execute("SELECT 1 FROM events WHERE task_id=? AND kind='workspace_preparing'",(task_id,)).fetchone()
                            if not owned:raise MvpError('managed_workspace_already_exists')
                            backup=workspace.with_name(workspace.name+'-incomplete-'+str(time.time_ns()))
                            workspace.rename(backup)
                            record('workspace_recovery_backup',{'retained':str(backup)})
                            if isinstance(ws,DesktopWorkspace) and (backup/'.git').is_dir():ws.reference=backup
                        ws.preflight(task)
                    break
                except MvpError as exc:
                    if not (str(exc).startswith(('workspace_git_','github_'))):raise
                    attempt+=1;record('remote_recovery',{'reason':str(exc),'phase':'prepare','attempt':attempt})
                    wake=time.monotonic()+min(2**min(attempt,6),60)
                    while time.monotonic()<wake:cancelled();time.sleep(.2)
            task=replace(task,write_paths=self.store.effective_paths(task_id))
            prior_commit=self.store.delivery(task_id)['commit_sha']
            if prior_commit:task=replace(task,base_sha=prior_commit)
            saved=self.store.delivery(task_id)['session_id']
            if saved and task.models['mode']!='api':task=replace(task,session={'mode':'resume','id':saved})
            if task.models["mode"] == "api":
                history = None
                if known_session:
                    context = Path(known_session["context_path"])
                    if context.is_symlink() or not context.resolve().is_relative_to(self.config.state_dir):
                        raise MvpError("invalid_api_context")
                    history = read_json(context.read_text(encoding="utf-8"))
                metadata = {"cli_version": "api-agent/0.1.0", "argv": ["api-agent", task.models["primary"]["provider"]], "cwd": str(workspace)}
                if self.store.get(task_id)['state']=='queued':self.store.start(task_id, metadata)
                api_runner=ApiFileRunner(registry)
                api_runner.control=control;api_runner.ack=self.store.delivered_message
                api_runner.paths=lambda:self.store.effective_paths(task_id)
                if history is None and (evidence/'context.json').is_file():history=read_json((evidence/'context.json').read_text(encoding='utf-8'))
                result, session_id, context = api_runner.run_task(task, workspace, evidence, config.timeout_seconds,
                    record, history, self.store.delivery(task_id)['session_id'] or task.session.get("id"))
            else:
                metadata = self.runner.prepare_task(workspace, task, config, registry, options_path)
                if self.store.get(task_id)['state']=='queued':self.store.start(task_id, metadata)
                prompt = ("Complete the current authorized task in the CURRENT workspace: " + str(workspace)
                    + ". Old conversation paths/permissions are superseded. Only modify these relative paths: "
                    + json.dumps(task.write_paths) + ". Work on the current task branch. Local commands, tests and commits are allowed; do not change the repository identity, force push, publish PRs or deploy. "
                    + "The controller will validate and publish your changes.\n")
                if task.models["mode"] == "gpt-led":
                    prompt += ("You are the GPT leader. Use collaborators.consult_model to delegate focused questions to configured external models as needed; "
                        "It returns a background job_id; use collaborators.get_consultation to check progress/results while continuing independent work. "
                        "Wait for relevant consultations to finish before the final answer. Evaluate their replies, make the final decisions and perform the file changes yourself. Configured models: "
                        + json.dumps(task.models["collaborators"]) + "\n")
                else:
                    prompt += "Use only the selected GPT model; do not call external model APIs or spawn other models.\n"
                if isinstance(self.runner,SessionCodexRunner):
                    self.runner.control=control;self.runner.ack=self.store.delivered_message
                attempt=0
                while True:
                    result = self.runner.run(metadata, prompt + task.prompt, evidence, config.timeout_seconds,record)
                    if result.error not in {'codex_server_disconnected','codex_thread_unavailable'}:break
                    attempt+=1;record('remote_recovery',{'reason':result.error,'attempt':attempt})
                    saved=self.store.delivery(task_id)['session_id']
                    if saved:metadata['session_id']=saved
                    wake=time.monotonic()+min(2**min(attempt,6),60)
                    while time.monotonic()<wake:cancelled();time.sleep(.2)
                session_id = discover_session(evidence, task.session.get("id")) if result.error is None else self.store.delivery(task_id)['session_id']
                context = None
            code, error = result.exit_code, result.error
            changes = ws.changes()
            changed = bool(changes)
            if error is not None:
                raise MvpError(error)
            task=replace(task,write_paths=self.store.effective_paths(task_id))
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
                              "任务已保留现场。可在本 Issue 回复 /codex retry 从现有进度继续，或 /codex allow . 扩大到整个仓库。无需回到电脑前重新派单。")
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
        self.reap_workers()
        self.status.begin()
        try:
            count = self._once()
        except MvpError as exc:
            self.status.finish(self.errors, str(exc))
            raise
        self.status.finish(self.errors)
        if self.workers:
            self.status.update(phase='executing')
        return count

    def _once(self):
        self.errors = 0
        repos = self.github.repositories()
        self.status.update(repository_count=len(repos))
        self.store.bind(self.config, self.github.owner_id)
        self.remote.poll(repos)
        for active in self.store.active_tasks():
            if active['id'] in self.workers:
                continue
            d = self.store.delivery(active["id"])
            from .process_identity import alive,stop
            previous=self.store.db.execute("SELECT detail FROM events WHERE task_id=? AND kind='worker_started' ORDER BY id DESC LIMIT 1",(active['id'],)).fetchone()
            lease=json.loads(previous['detail']).get('lease') if previous else None
            if alive(lease):continue
            # Resume only publication, never replay a model execution after a crash.
            if not d or not d["execution_completed"]:
                # Never let one uncertain execution freeze every other Issue.
                pending=self.store.inbox(active['id'])
                can_resume=bool(previous) or (active['state']=='queued' and 'registry' in json.loads(d['config_snapshot'])) or any(m['action'] in {'retry','say','allow'} for m in pending)
                if not can_resume:
                    self.store.queue_reply(active['id'],'restart/'+active['request_id'],
                        '监听器重启后发现保留的执行现场。其它任务继续接单；本任务可回复 `/codex retry` 在原目录续跑。')
                    self.store.finish(active['id'],'failed',None,'execution_state_unknown',None,
                        '执行现场已保留，未盲目重复执行。直接回复 /codex retry 即可远程恢复，其它 Issue 正常执行。')
                    continue
                evidence=self.config.state_dir/'runs'/active['request_id']
                for audit in evidence.rglob('execution.json') if evidence.is_dir() else ():
                    try:
                        info=read_json(audit.read_text(encoding='utf-8'))
                        stop(info.get('lease'))
                    except (OSError,ValueError,MvpError):
                        self.store.queue_reply(active['id'],'cleanup/'+active['request_id'],'正在核对并清理此任务遗留进程，保留现场，其它任务继续接单。')
                        break
                else:
                    target=next((r for r in repos if r.id==d['target_id']),None)
                    if target is None:continue
                    from .mvp2_contract import DesktopTask
                    options=json.loads(d['options_json'])
                    restored=DesktopTask(active['request_id'],active['host_id'],active['repo'],active['base_sha'],active['prompt'],
                        self.store.effective_paths(active['id']),active['comment_id'],active['contract_hash'],options['session'],options['models'])
                    known=self.store.db.execute('SELECT * FROM sessions WHERE session_id=?',(d['session_id'],)).fetchone() if d['session_id'] else None
                    self.start_worker(active['id'],restored,target,known)
                continue
            self.status.update(phase='publishing')
            if isinstance(self.runner,SessionCodexRunner):self.start_worker(active['id'],None,None,None)
            else:self.finish_publication(active["id"])
        for row in self.store.pending_receipts():
            if row['id'] not in self.workers:
                self.send_receipt(row)
        candidates = []
        for index, source in enumerate(repos):
            client = self.github.client(source)
            try:
                candidates += [(positive_id(i.get("id")), source, client, i) for i in client.issues()
                               if not self.store.by_issue(source.id, positive_id(i.get("id")))]
            except MvpError as exc:
                self.errors += 1
                LOG.error("repository_poll_failed repository_id=%s code=%s", source.id, exc)
            self.status.update(checked_repositories=index + 1, error_count=self.errors)
        count = 0
        for _, source, client, issue in sorted(candidates, key=lambda c: c[0]):
            if len(self.store.active_tasks()) >= self.config.max_parallel_tasks:
                break
            task = None
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
                if not task.base_sha:
                    commit=self.github.client(target).api(f'repos/{target.full_name}/commits/{quote(target.default_branch,safe="")}')
                    if not isinstance(commit,dict) or not isinstance(commit.get('sha'),str):raise MvpError('invalid_base_sha')
                    task=replace(task,base_sha=commit['sha'])
                snapshot = {"host_id": self.config.host_id, "hub_repo": self.config.hub_repo,
                            "registry": {"providers": self.registry.providers, **self.registry.limits}}
                snapshot['max_parallel_tasks'] = self.config.max_parallel_tasks
                snapshot['auto_merge']=self.config.auto_merge
                task_id = self.store.claim_desktop(source, target, issue, task, snapshot, self.config.max_parallel_tasks)
            except MvpError as exc:
                if str(exc) != "wrong_host":
                    LOG.warning("task_rejected repository_id=%s issue=%s code=%s", source.id, issue.get("number"), exc)
                    self.status.reject(source, issue, str(exc), task, self.registry)
                    self.remote.reject(source,issue,str(exc),task)
                continue
            if task_id is not None:
                self.status.update(phase='executing')
                if self.config.max_parallel_tasks == 1 and not isinstance(self.runner,SessionCodexRunner):
                    self.execute(task_id, task, target, known_session)
                    return 1
                self.start_worker(task_id, task, target, known_session)
                count += 1
        self.remote.flush(repos)
        return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--list-repos", action="store_true")
    mode.add_argument("--migrate-state", action="store_true", help="Explicitly migrate idle MVP-2 engine state from schema 3/4 to 5")
    mode.add_argument('--recover-api-session', metavar='REQUEST_ID', help='Explicitly register retained context from one failed API task; does not execute it')
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
            if args.migrate_state:
                path = config.state_dir / 'mvp2.sqlite3'
                if not path.is_file() or path.is_symlink():
                    raise MvpError('state_database_missing')
                backup = path.with_name('mvp2-engine-backup-' + utc_now().replace(':', '-') + '.sqlite3')
                with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
                    source.backup(destination)
                DesktopStore.migrate(path)
                print('Engine state migrated to schema 5; existing tasks, sessions and frozen contracts retained.')
                return 0
            store = DesktopStore(config.state_dir / "mvp2.sqlite3")
            poller = None
            try:
                if args.recover_api_session:
                    from .api_sessions import recover_api_session
                    self_owner = github.identity()
                    store.bind(config, self_owner)
                    print(json.dumps({'session_id': recover_api_session(store, config, registry, args.recover_api_session)}))
                    return 0
                poller = DesktopPoller(config, store, github, registry)
                while True:
                    try:
                        count = poller.once()
                    except MvpError as exc:
                        LOG.error("poll_failed code=%s", exc)
                        if args.once:
                            return 1
                        import time
                        time.sleep(config.poll_seconds)
                        continue
                    LOG.info("poll_complete new_tasks=%s repository_errors=%s", count, poller.errors)
                    if args.once:
                        for process in poller.workers.values():
                            process.join()
                        poller.reap_workers()
                        return int(bool(poller.errors or store.unfinished() or store.pending_receipts()) or
                                   bool(count and store.db.execute("SELECT 1 FROM (SELECT state FROM tasks ORDER BY id DESC LIMIT ?) WHERE state!='succeeded'", (count,)).fetchone()))
                    import time
                    time.sleep(config.poll_seconds)
            finally:
                if poller is not None:
                    poller.stop_workers()
                store.close()
    except KeyboardInterrupt:
        return 130
    except (MvpError, OSError, sqlite3.Error) as exc:
        LOG.error("%s", str(exc) if isinstance(exc, MvpError) else "local_state_or_config_error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
