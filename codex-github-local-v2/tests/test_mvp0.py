from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from codex_github_local_v2.mvp0 import Config, GitHub, MARKER, Poller, Store, Task, Workspace, parse_task, receipt
from codex_github_local_v2.mvp0_runner import CodexRunner, Execution, MvpError

REQUEST = "6c9134d1-f6ae-49f3-bdfd-e3681c19e183"
SECOND = "56384b35-4a58-42eb-a9d3-3b203d29a3b9"
BASE = "a" * 40


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config = Config("host-one", "owner/repo", ("owner",), self.workspace, (self.workspace,), self.root / "state")
        self.issue = {"id": 101, "number": 3, "state": "open", "title": "[codex-v2-mvp] test", "user": {"login": "owner"}}
        self.envelope = {"request_id": REQUEST, "host_id": "host-one", "repo": "owner/repo", "base_sha": BASE,
                         "task": {"prompt": "Create a harmless test document.", "write_paths": ["docs/mvp0.txt"]}}

    def comment(self, envelope=None):
        return {"id": 111, "user": {"login": "owner"}, "created_at": "2026-10-04T00:00:00Z",
                "updated_at": "2026-10-04T00:00:00Z", "body": MARKER + "\n```json\n" + json.dumps(envelope or self.envelope) + "\n```"}

    def task(self):
        return parse_task(self.issue, [self.comment()], self.config)

    def store(self):
        store = Store(self.config.state_dir / "mvp0.sqlite3")
        self.addCleanup(store.close)
        return store


class ProtocolTests(Fixture):
    def test_valid_task(self):
        task = self.task()
        self.assertEqual(task.request_id, REQUEST)
        self.assertEqual(task.write_paths, ("docs/mvp0.txt",))

    def test_plain_json_is_also_accepted(self):
        c = self.comment(); c["body"] = MARKER + "\n" + json.dumps(self.envelope)
        self.assertEqual(parse_task(self.issue, [c], self.config).base_sha, BASE)

    def test_unknown_fields_rejected_at_both_levels(self):
        for target in ("root", "task"):
            with self.subTest(target=target):
                value = copy.deepcopy(self.envelope)
                (value if target == "root" else value["task"])["policy_digest"] = "ignored?"
                with self.assertRaisesRegex(MvpError, "invalid_fields"):
                    parse_task(self.issue, [self.comment(value)], self.config)

    def test_wrong_host(self):
        self.envelope["host_id"] = "someone-else"
        with self.assertRaisesRegex(MvpError, "wrong_host"):
            self.task()

    def test_wrong_repo(self):
        self.envelope["repo"] = "owner/other"
        with self.assertRaisesRegex(MvpError, "wrong_repo"):
            self.task()

    def test_each_required_field_validated(self):
        cases = [("request_id", "../oops"), ("request_id", True), ("base_sha", "HEAD"),
                 ("host_id", []), ("repo", {}), ("prompt", ""), ("prompt", 9),
                 ("write_paths", []), ("write_paths", "docs/x"), ("write_paths", ["../x"]),
                 ("write_paths", ["/tmp/x"]), ("write_paths", [".git/config"]),
                 ("write_paths", ["docs//"]), ("write_paths", ["docs/*.txt"])]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                envelope = copy.deepcopy(self.envelope)
                (envelope["task"] if key in {"prompt", "write_paths"} else envelope)[key] = value
                with self.assertRaises(MvpError):
                    parse_task(self.issue, [self.comment(envelope)], self.config)

    def test_both_authors_must_be_allowed(self):
        for target in ("issue", "comment"):
            with self.subTest(target=target):
                issue, comment = copy.deepcopy(self.issue), self.comment()
                (issue if target == "issue" else comment)["user"]["login"] = "intruder"
                with self.assertRaisesRegex(MvpError, "author_not_allowed"):
                    parse_task(issue, [comment], self.config)

    def test_duplicate_or_edited_authorization_refused(self):
        c = self.comment()
        with self.assertRaisesRegex(MvpError, "exactly_one"):
            parse_task(self.issue, [c, c], self.config)
        c["updated_at"] = "2026-10-04T00:01:00Z"
        with self.assertRaisesRegex(MvpError, "edited_authorization"):
            parse_task(self.issue, [c], self.config)

    def test_duplicate_json_keys_rejected(self):
        c = self.comment()
        c["body"] = c["body"].replace('"host_id": "host-one"', '"host_id": "host-one", "host_id": "host-one"')
        with self.assertRaisesRegex(MvpError, "duplicate_json_key"):
            parse_task(self.issue, [c], self.config)

    def test_v1_and_complete_v2_prefixes_and_prs_ignored(self):
        for title in ("[codex] test", "[codex-v2] test", "[codex-control] test"):
            with self.subTest(title=title), self.assertRaisesRegex(MvpError, "not_mvp_issue"):
                parse_task({**self.issue, "title": title}, [self.comment()], self.config)
        with self.assertRaisesRegex(MvpError, "not_mvp_issue"):
            parse_task({**self.issue, "pull_request": {}}, [self.comment()], self.config)

    def test_workspace_allowlist_required(self):
        config = {"host_id": "host-one", "repo": "owner/repo", "allowed_authors": ["owner"],
                  "workspace": str(self.workspace), "workspace_allowlist": [str(self.root / "elsewhere")],
                  "state_dir": str(self.config.state_dir)}
        path = self.root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(MvpError, "workspace_not_allowed"):
            Config.load(path)
        config["workspace_allowlist"] = [str(self.workspace)]
        path.write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(Config.load(path).workspace, self.workspace)


class StoreTests(Fixture):
    def test_only_two_tables_and_version(self):
        s = self.store()
        self.assertEqual(s.db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual({r[0] for r in s.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}, {"tasks", "events"})

    def test_unique_request_and_issue_and_single_active(self):
        s = self.store(); task = self.task()
        self.assertIsNotNone(s.claim(1, self.issue, task))
        self.assertIsNone(s.claim(1, {**self.issue, "id": 102, "number": 4}, task))
        self.envelope["request_id"] = SECOND
        self.assertIsNone(s.claim(1, self.issue, self.task()))
        with self.assertRaisesRegex(MvpError, "unfinished"):
            s.claim(1, {**self.issue, "id": 102, "number": 4}, self.task())

    def test_claim_and_event_are_atomic(self):
        s = self.store()
        with patch.object(s, "event", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                s.claim(1, self.issue, self.task())
        self.assertEqual(s.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_concurrent_same_request_has_one_winner(self):
        s = self.store(); task = self.task()
        def claim(_):
            other = Store(self.config.state_dir / "mvp0.sqlite3")
            try:
                return other.claim(1, self.issue, task)
            finally:
                other.close()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(s.db.execute("SELECT COUNT(*) FROM events WHERE kind='claimed'").fetchone()[0], 1)

    def test_unknown_schema_refused(self):
        path = self.root / "future.db"
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
        db.close()
        with self.assertRaisesRegex(MvpError, "unsupported_mvp_schema"):
            Store(path)


class PollerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.gh = Mock()
        self.gh.identity.return_value = 1
        self.gh.issues.return_value = [self.issue]
        self.gh.comments.return_value = [self.comment()]
        self.gh.post_receipt.return_value = 123
        self.runner = Mock()
        self.runner.prepare.return_value = {"cli_version": "OFFLINE FIXTURE", "argv": ["fixture", "--json"], "cwd": str(self.workspace)}
        self.runner.run.return_value = Execution(0, None)
        self.ws = Mock()
        self.ws.changes.return_value = ["docs/mvp0.txt"]
        self.poller = Poller(self.config, self.s, self.gh, self.runner, self.ws)

    def test_success_and_receipt(self):
        self.assertEqual(self.poller.once(), 1)
        row = self.s.by_issue(1, 101)
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(row["exit_code"], 0)
        self.assertIsNotNone(row["started_at"])
        body = self.gh.post_receipt.call_args.args[1]
        for expected in (REQUEST, "claimed:", "started:", "finished:", "exit code: 0", "true"):
            self.assertIn(expected, body)
        self.assertNotIn(str(self.workspace), body)
        self.assertNotIn(self.envelope["task"]["prompt"], body)

    def test_repeated_poll_and_reopened_database_do_not_run_twice(self):
        self.poller.once(); self.poller.once()
        other = self.store()
        Poller(self.config, other, self.gh, self.runner, self.ws).once()
        self.runner.run.assert_called_once()

    def test_duplicate_request_on_different_issue_does_not_run(self):
        self.poller.once()
        self.gh.issues.return_value = [{**self.issue, "id": 102, "number": 4}]
        self.assertEqual(self.poller.once(), 0)
        self.runner.run.assert_called_once()

    def test_stale_base_does_not_execute(self):
        self.ws.preflight.side_effect = MvpError("stale_base")
        self.poller.once()
        self.runner.run.assert_not_called()
        row = self.s.by_issue(1, 101)
        self.assertEqual(row["state"], "stale_base")
        self.assertIsNone(row["started_at"])
        self.assertIn("stale_base", self.gh.post_receipt.call_args.args[1])

    def test_codex_failure_is_terminal(self):
        self.runner.run.return_value = Execution(7, "codex_nonzero_exit")
        self.poller.once(); self.poller.once()
        row = self.s.by_issue(1, 101)
        self.assertEqual((row["state"], row["exit_code"]), ("failed", 7))
        self.runner.run.assert_called_once()
        self.assertIn("codex_nonzero_exit", receipt(row))

    def test_receipt_failure_retries_receipt_only(self):
        self.gh.post_receipt.side_effect = [MvpError("github_http_503"), 123]
        self.poller.once(); self.poller.once()
        self.runner.run.assert_called_once()
        self.assertEqual(self.gh.post_receipt.call_count, 2)
        self.assertEqual(self.s.by_issue(1, 101)["receipt_comment_id"], 123)

    def test_restart_with_claim_never_auto_replays(self):
        self.s.claim(1, self.issue, self.task())
        with self.assertRaisesRegex(MvpError, "unfinished"):
            self.poller.once()
        self.runner.run.assert_not_called()

    def test_scope_violation_is_failed(self):
        self.ws.check_changes.side_effect = MvpError("write_scope_violation")
        self.poller.once()
        self.assertEqual(self.s.by_issue(1, 101)["state"], "failed")

    def test_cleanup_failure_keeps_slot_occupied(self):
        self.runner.run.side_effect = MvpError("process_cleanup_failed")
        with self.assertRaisesRegex(MvpError, "process_cleanup_failed"):
            self.poller.once()
        self.assertEqual(self.s.by_issue(1, 101)["state"], "running")
        with self.assertRaisesRegex(MvpError, "unfinished"):
            self.poller.once()

    def test_interrupt_without_confirmed_cleanup_keeps_slot(self):
        self.runner.run.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.poller.once()
        self.assertEqual(self.s.by_issue(1, 101)["state"], "running")
        self.gh.post_receipt.assert_not_called()
        with self.assertRaisesRegex(MvpError, "unfinished"):
            self.poller.once()

    def test_confirmed_interrupt_records_failure_and_stops_polling(self):
        self.runner.run.return_value = Execution(-15, "interrupted")
        with self.assertRaises(KeyboardInterrupt):
            self.poller.once()
        row = self.s.by_issue(1, 101)
        self.assertEqual((row["state"], row["exit_code"], row["error"]), ("failed", -15, "interrupted"))
        self.gh.post_receipt.assert_called_once()
        self.poller.once()
        self.runner.run.assert_called_once()


class GitHubTests(Fixture):
    def test_paginated_rest_and_pr_filter(self):
        gh = GitHub("owner/repo")
        page = [{**self.issue, "id": n + 1, "pull_request": {}} for n in range(100)]
        gh.api = Mock(side_effect=[page, [self.issue]])
        self.assertEqual(gh.issues(), [self.issue])
        self.assertIn("page=2", gh.api.call_args.args[0])
        self.assertNotIn("search", gh.api.call_args.args[0])

    def test_comment_pagination(self):
        gh = GitHub("owner/repo")
        gh.api = Mock(side_effect=[[self.comment()] * 100, [self.comment()]])
        self.assertEqual(len(gh.comments(3)), 101)

    def test_lost_receipt_response_reuses_own_comment(self):
        gh = GitHub("owner/repo"); gh.writer_id = 42
        gh.comments = Mock(return_value=[{"id": 500, "user": {"id": 42}, "body": "receipt"}])
        gh.api = Mock()
        self.assertEqual(gh.post_receipt(3, "receipt"), 500)
        gh.api.assert_not_called()

    def test_copied_receipt_is_not_trusted(self):
        gh = GitHub("owner/repo"); gh.writer_id = 42
        gh.comments = Mock(return_value=[{"id": 500, "user": {"id": 99}, "body": "receipt"}])
        gh.api = Mock(return_value={"id": 501})
        self.assertEqual(gh.post_receipt(3, "receipt"), 501)

    def test_cli_post_body_uses_stdin_and_errors_do_not_leak(self):
        gh = GitHub("owner/repo")
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"id": 1}', '')) as run:
            gh.api("repos/owner/repo/issues/3/comments", {"body": "text $(no shell)"})
        self.assertIn("--input", run.call_args.args[0])
        self.assertNotIn("text $(no shell)", run.call_args.args[0])
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, '', 'HTTP 401 secret-token')):
            with self.assertRaisesRegex(MvpError, "^github_http_401$"):
                gh.api("user")


class WorkspaceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.ws = Workspace(self.config)

    def test_changed_local_or_remote_baseline(self):
        for values in (("b" * 40,), (BASE, "b" * 40 + "\trefs/heads/main")):
            with self.subTest(values=values):
                self.ws.git = Mock(side_effect=values)
                with self.assertRaisesRegex(MvpError, "stale_base"):
                    self.ws.baseline(self.task())

    def test_workspace_root_and_remote_are_checked(self):
        self.ws.git = Mock(side_effect=[str(self.workspace), "https://github.com/owner/repo.git"])
        self.ws.registered()
        self.ws.git = Mock(side_effect=[str(self.workspace), "https://github.com/other/repo.git"])
        with self.assertRaisesRegex(MvpError, "workspace_remote_mismatch"):
            self.ws.registered()

    def test_outside_write_scope(self):
        self.ws.git = Mock(return_value=BASE)
        with self.assertRaisesRegex(MvpError, "write_scope_violation"):
            self.ws.check_changes(self.task(), ["src/production.py"])

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_symlink_path_rejected(self):
        (self.workspace / "docs").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(MvpError):
            self.ws.safe_path("docs/mvp0.txt")


@unittest.skipUnless(os.name == "posix", "MVP execution target is Linux/WSL")
class RunnerProcessTests(Fixture):
    def run_fixture(self, mode, *, timeout=10, limit=None):
        runner = CodexRunner((sys.executable, str(ROOT / "tests/fixtures/mvp0_codex.py"), mode), max_log_bytes=limit)
        metadata = runner.prepare(self.workspace)
        record = Mock()
        evidence = self.root / "evidence"
        result = runner.run(metadata, "sent only on stdin", evidence, timeout, record)
        return result, evidence, record

    def test_subprocess_success_separate_logs_and_audit(self):
        result, evidence, record = self.run_fixture("success")
        self.assertEqual(result, Execution(0, None))
        self.assertEqual((self.workspace / "received-prompt.txt").read_text(), "sent only on stdin")
        self.assertIn("fixture stderr only", (evidence / "stderr.log").read_text())
        self.assertNotIn("fixture stderr only", (evidence / "stdout.jsonl").read_text())
        audit = json.loads((evidence / "execution.json").read_text())
        self.assertEqual(audit["exit_code"], 0)
        self.assertIn("finished_at", audit)
        record.assert_called_once()

    def test_subprocess_failure(self):
        result, _, _ = self.run_fixture("failure")
        self.assertEqual(result.exit_code, 7)
        self.assertIsNotNone(result.error)

    def test_item_completed_does_not_mean_task_success(self):
        result, _, _ = self.run_fixture("item_only")
        self.assertEqual(result.error, "missing_turn_completed")

    def test_invalid_jsonl(self):
        result, _, _ = self.run_fixture("invalid")
        self.assertEqual(result.error, "invalid_jsonl")

    def test_log_limit(self):
        result, _, _ = self.run_fixture("flood", limit=1024)
        self.assertEqual(result.error, "log_limit_exceeded")

    def test_default_log_budget_is_unlimited(self):
        self.assertIsNone(CodexRunner().max_log_bytes)
        result, evidence, _ = self.run_fixture("large_log", timeout=30)
        self.assertGreater((evidence / 'stdout.jsonl').stat().st_size, 16 * 1024 * 1024)
        self.assertIsNone(result.error)
        self.assertEqual(result.exit_code, 0)

    def test_timeout_cleans_descendant(self):
        result, evidence, _ = self.run_fixture("timeout", timeout=1)
        self.assertEqual(result.error, "execution_timeout")
        child = int((self.workspace / "child.pid").read_text())
        # A killed orphan can briefly remain a zombie until the OS reaps it.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            stat = Path(f"/proc/{child}/stat")
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            self.fail("fixture child is still alive")
        self.assertIn("process_group_terminated", (evidence / "execution.json").read_text())


if __name__ == "__main__":
    unittest.main()
