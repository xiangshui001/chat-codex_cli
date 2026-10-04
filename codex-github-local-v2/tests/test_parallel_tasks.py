from dataclasses import replace
import json
import os
import sqlite3
import time
import sys
import unittest
import uuid
from unittest.mock import Mock

import test_mvp2 as fixtures
from codex_github_local_v2.mvp0_runner import CodexRunner, Execution, MvpError
from codex_github_local_v2.mvp2 import DesktopPoller, DesktopStore
from codex_github_local_v2.mvp2_contract import DesktopConfig, MARKER
from codex_github_local_v2.workbench import DesktopReader


class ParallelStoreTests(fixtures.Fixture):
    def test_capacity_dedup_and_same_session_are_atomic(self):
        store = self.store()
        first = replace(self.parse(), session={'mode': 'resume', 'id': fixtures.SID})
        store.claim_desktop(self.source, self.target, self.issue, first, {}, 2)
        second = replace(first, request_id=str(uuid.uuid4()))
        issue = {**self.issue, 'id': 102, 'number': 4}
        with self.assertRaisesRegex(MvpError, 'session_busy'):
            store.claim_desktop(self.source, self.target, issue, second, {}, 2)
        second = replace(second, session={'mode': 'new'})
        store.claim_desktop(self.source, self.target, issue, second, {}, 2)
        self.assertIsNone(store.claim_desktop(self.source, self.target, issue, second, {}, 2))
        with self.assertRaisesRegex(MvpError, 'parallel_capacity_reached'):
            store.claim_desktop(self.source, self.target, {**issue, 'id': 103},
                                replace(second, request_id=str(uuid.uuid4())), {}, 2)
        other = DesktopStore(store.path)
        try:
            self.assertEqual(len(other.active_tasks()), 2)
            with self.assertRaisesRegex(MvpError, 'parallel_capacity_reached'):
                other.claim_desktop(self.source, self.target, {**issue, 'id': 104},
                                    replace(second, request_id=str(uuid.uuid4())), {}, 2)
        finally:
            other.close()

    def legacy_database(self, active=False):
        store = self.store()
        ident = store.claim_desktop(self.source, self.target, self.issue, self.parse(), {})
        if not active:
            store.finish(ident, 'failed', 1, 'execution_timeout', False, 'retained')
        before = dict(store.get(ident))
        path = store.path
        # A valid old engine had the same tables and the serial partial index.
        store.db.execute('DROP INDEX active_tasks')
        store.db.execute("CREATE UNIQUE INDEX one_active_task ON tasks((1)) WHERE state IN ('queued','running')")
        store.db.execute('PRAGMA user_version=3')
        return store, path, before

    def test_explicit_idle_migration_retains_records_and_reader_compatibility(self):
        legacy, path, before = self.legacy_database()
        self.assertEqual(DesktopReader(self.config).overview()['counts'], {'failed': 1})
        with self.assertRaisesRegex(MvpError, 'unsupported_mvp_schema'):
            DesktopStore(path)
        DesktopStore.migrate(path)
        self.assertEqual(dict(legacy.get(1)), before)
        self.assertEqual(legacy.db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.assertEqual(DesktopReader(self.config).overview()['counts'], {'failed': 1})
        DesktopStore.migrate(path)

    def test_migration_refuses_active_old_execution_without_mutating_index(self):
        legacy, path, before = self.legacy_database(active=True)
        with self.assertRaisesRegex(MvpError, 'migration_requires_idle'):
            DesktopStore.migrate(path)
        self.assertEqual(dict(legacy.get(1)), before)
        self.assertEqual(legacy.db.execute('PRAGMA user_version').fetchone()[0], 3)
        self.assertIsNotNone(legacy.db.execute("SELECT 1 FROM sqlite_master WHERE name='one_active_task'").fetchone())

    def test_config_parallel_limits_and_legacy_default(self):
        path = self.root / 'config.json'
        data = {'owner': 'owner', 'host_id': 'desktop', 'hub_repo': 'owner/codex-cli',
                'models_file': str(self.models), 'workspace_root': str(self.config.workspace_root),
                'state_dir': str(self.config.state_dir)}
        path.write_text(json.dumps(data))
        self.assertEqual(DesktopConfig.load(path).max_parallel_tasks, 1)
        for value in (0, -1, 17, True, 2.5, '3'):
            path.write_text(json.dumps({**data, 'max_parallel_tasks': value}))
            with self.subTest(value=value), self.assertRaisesRegex(MvpError, 'invalid_max_parallel_tasks'):
                DesktopConfig.load(path)
        path.write_text(json.dumps({**data, 'max_parallel_tasks': 3}))
        self.assertEqual(DesktopConfig.load(path).max_parallel_tasks, 3)
        for timeout in (3601, 10800):
            path.write_text(json.dumps({**data, 'timeout_seconds': timeout}))
            self.assertEqual(DesktopConfig.load(path).timeout_seconds, timeout)
        for timeout in (0, 10801, True, 1.5, '10800'):
            path.write_text(json.dumps({**data, 'timeout_seconds': timeout}))
            with self.subTest(timeout=timeout), self.assertRaisesRegex(MvpError, 'invalid_timeout_seconds'):
                DesktopConfig.load(path)


@unittest.skipUnless(os.name == 'posix', 'Fork workers require Linux / WSL')
class ParallelProcessTests(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.gh = Mock(owner_id=9)
        self.gh.repositories.return_value = [self.source, self.target]
        self.clients = {10: Mock(), 20: Mock()}
        self.clients[20].issues.return_value = []
        self.clients[10].post_receipt.return_value = 300
        self.gh.client.side_effect = lambda repo: self.clients[repo.id]
        self.gh.repository.side_effect = lambda name, rid: self.source if rid == 10 else self.target
        self.ws = Mock()
        self.ws.changes.return_value = ['docs/check.txt']
        self.runner = Mock()
        self.runner.prepare_task.side_effect = lambda workspace, *_: {'cli_version': 'FAKE', 'argv': ['fake'], 'cwd': str(workspace)}
        def run(metadata, prompt, evidence, timeout, record):
            evidence.mkdir(parents=True)
            record('fake_model_started', {})
            selected = next(value for value in self.payloads.values() if value['request_id'] == evidence.name)
            session_id = selected['session'].get('id', evidence.name)
            (evidence / 'stdout.jsonl').write_text(json.dumps({'type': 'thread.started', 'thread_id': session_id}) + '\n')
            return Execution(0, None)
        self.runner.run.side_effect = run
        self.pub = Mock()
        self.pub.publish.return_value = 'https://github.com/owner/project/pull/5'
        self.config = replace(self.config, max_parallel_tasks=2)
        self.issues = [{**self.issue, 'id': 101 + i, 'number': 3 + i} for i in range(3)]
        self.payloads = {issue['number']: {**self.payload, 'request_id': str(uuid.uuid4())} for issue in self.issues}
        self.clients[10].issues.return_value = self.issues
        self.clients[10].api.side_effect = lambda endpoint: next(
            issue for issue in self.issues if endpoint.endswith('/' + str(issue['number'])))
        self.clients[10].comments.side_effect = lambda number: [{**self.comment,
            'body': MARKER + '\n' + json.dumps(self.payloads[number])}]
        original_run = self.runner.run.side_effect
        def slow_run(*args):
            time.sleep(0.6)
            return original_run(*args)
        self.runner.run.side_effect = slow_run
        self.p = DesktopPoller(self.config, self.s, self.gh, runner=self.runner,
                               workspace_factory=Mock(return_value=self.ws), publisher=self.pub)
        self.addCleanup(self.p.stop_workers)

    def wait_workers(self):
        for process in self.p.workers.values():
            process.join(timeout=5)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
        self.p.reap_workers()

    def test_two_real_processes_execute_and_third_waits_without_replay(self):
        self.assertEqual(self.p.once(), 2)
        self.assertEqual(len(self.p.workers), 2)
        self.assertEqual(len(self.s.active_tasks()), 2)
        self.assertFalse(self.s.by_issue(self.source.id, self.issues[2]['id']))
        self.wait_workers()
        self.assertEqual([r['state'] for r in self.s.db.execute('SELECT state FROM tasks')], ['succeeded'] * 2)
        self.assertEqual(self.p.once(), 1)
        self.wait_workers()
        self.assertEqual(self.p.once(), 0)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 3)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM events WHERE kind='execution_completed'").fetchone()[0], 3)

    def test_restart_does_not_replay_unowned_execution(self):
        self.s.claim_desktop(self.source, self.target, self.issue, self.parse(), {}, 2)
        with self.assertRaisesRegex(MvpError, 'manual_inspection'):
            self.p.once()
        self.assertEqual(self.p.workers, {})

    def test_busy_conversation_waits_while_unrelated_task_uses_free_slot(self):
        for number in (3, 4):
            self.payloads[number]['session'] = {'mode': 'resume', 'id': fixtures.SID}
        self.p.check_session = Mock(return_value=None)
        self.assertEqual(self.p.once(), 2)
        self.assertTrue(self.s.by_issue(self.source.id, 101))
        self.assertFalse(self.s.by_issue(self.source.id, 102))
        self.assertTrue(self.s.by_issue(self.source.id, 103))
        self.assertEqual(DesktopReader(self.config).overview()['monitor']['rejected'][0]['reason'], 'session_busy')
        self.wait_workers()
        self.assertEqual(self.p.once(), 1)
        self.wait_workers()
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 3)

    def test_shutdown_interrupts_runners_and_cleans_model_process_groups(self):
        self.runner.prepare_task.side_effect = lambda workspace, *_: {'cli_version': 'FAKE',
            'argv': [sys.executable, '-c', 'import time; time.sleep(60)'], 'cwd': str(self.root)}
        self.runner.run.side_effect = CodexRunner().run
        self.assertEqual(self.p.once(), 2)
        deadline = time.monotonic() + 5
        while self.s.db.execute("SELECT COUNT(*) FROM events WHERE kind='process_started'").fetchone()[0] != 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.p.stop_workers()
        self.assertFalse(self.s.active_tasks())
        rows = self.s.db.execute('SELECT request_id,state,error FROM tasks').fetchall()
        for row in rows:
            self.assertEqual((row['state'], row['error']), ('failed', 'interrupted'))
            audit = json.loads((self.config.state_dir / 'runs' / row['request_id'] / 'execution.json').read_text())
            self.assertEqual(audit['cleanup'], 'process_group_terminated')
            with self.assertRaises(ProcessLookupError):
                os.kill(audit['pid'], 0)

    def test_worker_failures_do_not_prevent_other_worker_completion(self):
        self.assertEqual(self.p.once(), 2)
        first = next(iter(self.p.workers.values()))
        first.kill()
        first.join(timeout=5)
        for process in list(self.p.workers.values())[1:]:
            process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)
        self.p.reap_workers()
        states = [r['state'] for r in self.s.db.execute('SELECT state FROM tasks')]
        self.assertIn('succeeded', states)
        self.assertTrue(self.s.unfinished())
        with self.assertRaisesRegex(MvpError, 'manual_inspection'):
            self.p.once()
        self.assertFalse(self.s.by_issue(self.source.id, self.issues[2]['id']))


if __name__ == '__main__':
    unittest.main()
