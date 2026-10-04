from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from codex_github_local_v2.mvp0 import Store, parse_task
from codex_github_local_v2.mvp0_runner import Execution, MvpError
from codex_github_local_v2.mvp1 import (AccountConfig, AccountGitHub, AccountPoller, AccountStore,
    MARKER, TITLE_PREFIX, ManagedWorkspace, ReliableGitHub, Repository, run_git)

BASE = "a" * 40
FIRST = "6c9134d1-f6ae-49f3-bdfd-e3681c19e183"
SECOND = "56384b35-4a58-42eb-a9d3-3b203d29a3b9"


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.config = AccountConfig("owner", "host-one", self.root / "workspaces", self.root / "state")
        self.repo = Repository(10, "owner/first", "main")
        self.other = Repository(20, "owner/new", "main")

    def metadata(self, **changes):
        return {"id": 10, "full_name": "owner/first", "owner": {"id": 9, "login": "owner", "type": "User"},
                "default_branch": "main", "archived": False, "has_issues": True, **changes}

    def issue(self, id=101):
        return {"id": id, "number": 1, "state": "open", "title": TITLE_PREFIX + " docs", "user": {"login": "owner"}}

    def comment(self, repo="owner/first", request=FIRST):
        payload = {"request_id": request, "host_id": "host-one", "repo": repo, "base_sha": BASE,
                   "task": {"prompt": "Create docs/check.txt", "write_paths": ["docs/check.txt"]}}
        return {"id": 111, "created_at": "2026-10-04T00:00:00Z", "updated_at": "2026-10-04T00:00:00Z",
                "user": {"login": "owner"}, "body": MARKER + "\n" + json.dumps(payload)}

    def task(self):
        return parse_task(self.issue(), [self.comment()], self.repo.task_config(self.config),
                          title_prefix=TITLE_PREFIX, marker=MARKER)

    def store(self):
        store = AccountStore(self.config.state_dir / "mvp1.sqlite3")
        self.addCleanup(store.close)
        store.bind(self.config, 9)
        return store


class ConfigAndStateTests(Fixture):
    def test_account_config_has_no_per_repo_registration(self):
        data = {"owner": "OWNER", "host_id": "host-one", "workspace_root": str(self.config.workspace_root),
                "state_dir": str(self.config.state_dir)}
        file = self.root / "config.json"
        file.write_text(json.dumps(data))
        self.assertEqual(AccountConfig.load(file), self.config)
        data["arbitrary_cwd"] = "/tmp"
        file.write_text(json.dumps(data))
        with self.assertRaisesRegex(MvpError, "invalid_fields"):
            AccountConfig.load(file)

    def test_nested_state_and_workspace_rejected(self):
        data = {"owner": "owner", "host_id": "host-one", "workspace_root": str(self.root),
                "state_dir": str(self.root / "state")}
        file = self.root / "config.json"
        file.write_text(json.dumps(data))
        with self.assertRaisesRegex(MvpError, "must_be_separate"):
            AccountConfig.load(file)

    def test_schema_and_identity_binding(self):
        store = self.store()
        self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual({r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                         {"tasks", "events", "settings"})
        for config, owner in ((replace(self.config, host_id="other"), 9),
                              (replace(self.config, workspace_root=self.root / "other"), 9), (self.config, 99)):
            with self.subTest(config=config, owner=owner), self.assertRaisesRegex(MvpError, "binding_mismatch"):
                store.bind(config, owner)

    def test_old_database_is_not_migrated_or_replayed(self):
        path = self.root / "old.sqlite3"
        old = Store(path); old.close()
        with self.assertRaisesRegex(MvpError, "unsupported_mvp_schema"):
            AccountStore(path)

    def test_mvp0_cannot_open_mvp1_database(self):
        self.store()
        with self.assertRaisesRegex(MvpError, "unsupported_mvp_schema"):
            Store(self.config.state_dir / "mvp1.sqlite3")

    def test_one_active_task_across_repositories(self):
        store = self.store()
        store.claim(10, self.issue(), self.task())
        other = replace(self.task(), request_id=SECOND, repo="owner/new")
        with self.assertRaisesRegex(MvpError, "unfinished"):
            store.claim(20, self.issue(102), other)

    def test_old_protocol_not_accepted_by_new_entrypoint(self):
        issue = {**self.issue(), "title": "[codex-v2-mvp] old task"}
        with self.assertRaisesRegex(MvpError, "not_mvp_issue"):
            parse_task(issue, [self.comment()], self.repo.task_config(self.config),
                       title_prefix=TITLE_PREFIX, marker=MARKER)


class DiscoveryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.transport = Mock()
        self.transport.api.return_value = {"login": "owner", "id": 9, "type": "User"}
        self.github = AccountGitHub(self.config, self.transport)

    def test_owner_and_all_pages_endpoint(self):
        self.transport.pages.return_value = [self.metadata(), self.metadata(id=20, full_name="owner/new")]
        self.assertEqual(self.github.repositories(), [self.repo, self.other])
        self.assertIn("affiliation=owner", self.transport.pages.call_args.args[0])
        self.assertNotIn("search", self.transport.pages.call_args.args[0])

    def test_new_repository_discovered_on_next_poll(self):
        self.transport.pages.side_effect = [[self.metadata()], [self.metadata(), self.metadata(id=20, full_name="owner/new")]]
        self.assertEqual(len(self.github.repositories()), 1)
        self.assertEqual(len(self.github.repositories()), 2)

    def test_foreign_transferred_archived_and_disabled_repositories_skipped(self):
        self.transport.pages.return_value = [self.metadata(), self.metadata(id=20, archived=True),
            self.metadata(id=30, has_issues=False), self.metadata(id=40, disabled=True),
            self.metadata(id=50, owner={"login": "owner", "id": 99, "type": "User"}),
            self.metadata(id=60, full_name="someone/other")]
        self.assertEqual(self.github.repositories(), [self.repo])

    def test_wrong_login_rejected_before_listing(self):
        self.transport.api.return_value = {"login": "someone", "id": 9, "type": "User"}
        with self.assertRaisesRegex(MvpError, "login_must_match_owner"):
            self.github.repositories()
        self.transport.pages.assert_not_called()

    def test_repository_name_reuse_does_not_retarget_receipts(self):
        self.github.owner_id = 9
        self.transport.api.return_value = self.metadata(id=99)
        with self.assertRaisesRegex(MvpError, "identity_changed"):
            self.github.repository("owner/first", 10)

    def test_base_and_default_branch_change_stop_before_clone(self):
        self.github.owner_id = 9
        for response in (self.metadata(default_branch="other"), self.metadata()):
            self.transport.api.side_effect = [response, {"sha": "b" * 40}]
            with self.subTest(response=response), self.assertRaisesRegex(MvpError, "stale_base"):
                self.github.check_base(self.repo, self.task())

    def test_empty_repository_has_explicit_diagnostic(self):
        self.github.owner_id = 9
        self.transport.api.side_effect = [self.metadata(), MvpError("github_http_409")]
        with self.assertRaisesRegex(MvpError, "initial_commit"):
            self.github.check_base(self.repo, self.task())

    def test_transient_reads_retry_but_post_never_retries(self):
        gh = ReliableGitHub("owner/first")
        with patch("codex_github_local_v2.mvp0.GitHub.api", side_effect=[MvpError("github_cli_failed"), {"id": 9}]) as api, patch("time.sleep"):
            self.assertEqual(gh.api("user"), {"id": 9})
            self.assertEqual(api.call_count, 2)
        with patch("codex_github_local_v2.mvp0.GitHub.api", side_effect=MvpError("github_cli_failed")) as api:
            with self.assertRaises(MvpError): gh.api("comments", {"body": "receipt"})
            api.assert_called_once()


class AccountPollerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.github = Mock(owner_id=9)
        self.github.repositories.return_value = [self.repo, self.other]
        self.clients = {10: Mock(), 20: Mock()}
        self.clients[10].issues.return_value = [self.issue(200)]
        self.clients[20].issues.return_value = [self.issue(100)]
        self.clients[10].comments.return_value = [self.comment()]
        self.clients[20].comments.return_value = [self.comment("owner/new", SECOND)]
        for client in self.clients.values(): client.post_receipt.return_value = 300
        self.github.client.side_effect = lambda repo: self.clients[repo.id]
        self.github.repository.side_effect = lambda name, id: self.repo if id==10 else self.other
        self.runner = Mock()
        self.runner.prepare.side_effect = lambda path: {"cli_version": "OFFLINE", "argv": ["fixture"], "cwd": str(path)}
        self.runner.run.return_value = Execution(0, None)
        self.ws = Mock()
        self.ws.changes.return_value = ["docs/check.txt"]
        self.factory = Mock(return_value=self.ws)
        self.poller = AccountPoller(self.config, self.s, self.github, self.runner, self.factory)

    def test_global_oldest_first_one_execution_per_poll(self):
        self.assertEqual(self.poller.once(), 1)
        self.assertIsNotNone(self.s.by_issue(20, 100))
        self.assertIsNone(self.s.by_issue(10, 200))
        self.runner.run.assert_called_once()
        self.poller.once()
        self.assertEqual(self.runner.run.call_count, 2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 2)

    def test_repeat_poll_does_not_clone_or_execute_again(self):
        self.poller.once(); self.poller.once(); self.poller.once()
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.runner.run.call_count, 2)
        other = self.store()
        AccountPoller(self.config, other, self.github, self.runner, self.factory).once()
        self.assertEqual(self.runner.run.call_count, 2)

    def test_repeated_request_id_across_repositories_is_global(self):
        self.clients[10].comments.return_value = [self.comment(request=SECOND)]
        self.poller.once(); self.poller.once()
        self.runner.run.assert_called_once()
        self.factory.assert_called_once()

    def test_untrusted_author_never_prepares_workspace(self):
        for client in self.clients.values():
            client.issues.return_value = [{**self.issue(), "user": {"login": "intruder"}}]
        self.assertEqual(self.poller.once(), 0)
        self.factory.assert_not_called()
        self.runner.run.assert_not_called()

    def test_stale_base_creates_receipt_without_codex(self):
        self.ws.preflight.side_effect = MvpError("stale_base")
        self.poller.once()
        self.runner.run.assert_not_called()
        row=self.s.by_issue(20,100)
        self.assertEqual(row['state'], 'stale_base')
        self.assertIn('MVP-1', self.clients[20].post_receipt.call_args.args[1])

    def test_pending_receipt_uses_correct_repository(self):
        self.clients[20].post_receipt.side_effect = [MvpError("github_http_503"), 300]
        self.poller.once()
        self.clients[10].issues.return_value=[]
        self.poller.once()
        self.runner.run.assert_called_once()
        self.assertEqual(self.clients[20].post_receipt.call_count,2)
        self.clients[10].post_receipt.assert_not_called()

    def test_uncertain_cleanup_blocks_every_repository(self):
        self.runner.run.side_effect=MvpError('process_cleanup_failed')
        with self.assertRaisesRegex(MvpError,'cleanup_failed'): self.poller.once()
        with self.assertRaisesRegex(MvpError,'unfinished'): self.poller.once()
        self.factory.assert_called_once()

    def test_one_unavailable_repo_does_not_silently_look_healthy(self):
        self.clients[10].issues.side_effect=MvpError('github_http_403')
        self.assertEqual(self.poller.once(),1)
        self.assertEqual(self.poller.errors,1)

    def test_comment_transport_error_is_reported_without_execution(self):
        for client in self.clients.values():
            client.comments.side_effect=MvpError('github_http_503')
        self.assertEqual(self.poller.once(),0)
        self.assertEqual(self.poller.errors,2)
        self.factory.assert_not_called()


class ManagedWorkspaceTests(Fixture):
    def make_workspace(self):
        self.github=Mock()
        self.record=Mock()
        self.cfg=self.repo.task_config(self.config,FIRST)
        return ManagedWorkspace(self.cfg,self.config,self.repo,self.github,self.record)

    def test_paths_derive_only_from_repository_id_and_uuid(self):
        cfg=self.repo.task_config(self.config,FIRST)
        self.assertEqual(cfg.workspace,self.config.workspace_root/'10'/FIRST)
        self.assertEqual(cfg.workspace_allowlist,(cfg.workspace,))

    def test_stale_base_does_not_create_a_clone(self):
        ws=self.make_workspace()
        self.github.check_base.side_effect=MvpError('stale_base')
        with patch('codex_github_local_v2.mvp1.run_git') as git:
            with self.assertRaisesRegex(MvpError,'stale_base'): ws.preflight(self.task())
        git.assert_not_called()
        self.assertFalse(self.config.workspace_root.exists())

    def test_existing_directory_is_never_overwritten(self):
        ws=self.make_workspace()
        self.cfg.workspace.mkdir(parents=True)
        file=self.cfg.workspace/'keep.txt'; file.write_text('keep')
        with self.assertRaisesRegex(MvpError,'already_exists'): ws.preflight(self.task())
        self.assertEqual(file.read_text(),'keep')

    @unittest.skipUnless(os.name=='posix','POSIX symlinks')
    def test_symlink_repo_directory_refused(self):
        ws=self.make_workspace()
        self.config.workspace_root.mkdir()
        (self.config.workspace_root/'10').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(MvpError,'path_escape'): ws.preflight(self.task())

    def test_real_git_clone_checkout_and_diff_in_isolated_directory(self):
        ws=self.make_workspace()
        seed=self.root/'seed'; seed.mkdir()
        def git(*args): return subprocess.check_output(['git','-C',str(seed),*args],stderr=subprocess.DEVNULL,text=True).strip()
        git('init','-b','main')
        (seed/'README.md').write_text('offline repository')
        git('add','README.md')
        git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','seed')
        task=replace(self.task(),base_sha=git('rev-parse','HEAD'))
        real_run_git=run_git
        def local_git(cwd,*args,**kwargs):
            # Only network transport is replaced; clone, checkout and validation use real Git.
            args=tuple(str(seed) if a=='https://github.com/owner/first.git' else a for a in args)
            if args==('remote','get-url','origin'): return 'https://github.com/owner/first.git'
            return real_run_git(cwd,*args,**kwargs)
        with patch('codex_github_local_v2.mvp1.run_git',side_effect=local_git):
            ws.preflight(task)
            self.assertEqual(ws.git('symbolic-ref','--short','HEAD'),'codex-mvp1/'+FIRST)
            self.assertEqual(ws.git('rev-parse','HEAD'),task.base_sha)
            (self.cfg.workspace/'docs').mkdir()
            (self.cfg.workspace/'docs/check.txt').write_text('offline edit')
            ws.check_changes(task,ws.changes())
        self.assertEqual([c.args[0] for c in self.record.call_args_list],['workspace_preparing','workspace_prepared'])


if __name__=='__main__':
    unittest.main()
