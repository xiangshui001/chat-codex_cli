import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from codex_github_local_v2.mvp1 import AccountConfig, AccountStore
from codex_github_local_v2.mvp0 import Task
from codex_github_local_v2.workbench import Reader, clean, create_server, progress


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = AccountConfig('owner', 'host', self.root / 'workspaces', self.root / 'state')
        self.store = AccountStore(self.config.state_dir / 'mvp1.sqlite3')
        self.addCleanup(self.store.close)
        self.store.bind(self.config, 123)
        self.rid = str(uuid.uuid4())
        task = Task(self.rid, 'host', 'owner/repo', 'a' * 40, 'create a document', ('docs/check.txt',), 7, 'hash')
        self.task_id = self.store.claim(45, {'id': 67, 'number': 8}, task)
        self.reader = Reader(self.config)
        self.evidence = self.config.state_dir / 'runs' / self.rid
        self.evidence.mkdir(parents=True)

    def test_overview_uses_actual_states_and_does_not_write(self):
        before = self.store.db.total_changes
        view = self.reader.overview()
        self.assertEqual(view['source'], 'local-mvp1')
        self.assertEqual(view['counts'], {'queued': 1})
        self.assertEqual(view['tasks'][0]['issue_url'], 'https://github.com/owner/repo/issues/8')
        self.assertEqual(before, self.store.db.total_changes)
        db = self.reader.connect()
        with self.assertRaises(sqlite3.OperationalError):
            db.execute('DELETE FROM tasks')
        db.close()

    def test_missing_database_is_not_created(self):
        config = AccountConfig('owner', 'host', self.root / 'other', self.root / 'missing')
        with self.assertRaises(sqlite3.OperationalError):
            Reader(config).overview()
        self.assertFalse(config.state_dir.exists())

    def test_binding_mismatch_refused(self):
        config = AccountConfig('other', 'host', self.config.workspace_root, self.config.state_dir)
        with self.assertRaises(ValueError):
            Reader(config).overview()

    def test_unknown_and_invalid_task(self):
        with self.assertRaises(ValueError):
            self.reader.detail('../../secret')
        with self.assertRaises(KeyError):
            self.reader.detail(str(uuid.uuid4()))

    def test_progress_stream_updates_deduplicate_and_omit_reasoning(self):
        path = self.evidence / 'stdout.jsonl'
        events = [{'type': 'thread.started'}, {'type': 'item.started', 'item': {'id': '1', 'type': 'command_execution', 'command': 'echo hi', 'status': 'in_progress'}},
                  {'type': 'item.completed', 'item': {'id': '1', 'type': 'command_execution', 'command': 'echo hi', 'aggregated_output': 'hi', 'exit_code': 0}},
                  {'type': 'item.completed', 'item': {'id': '2', 'type': 'reasoning', 'text': 'PRIVATE REASONING'}},
                  {'type': 'turn.completed'}]
        path.write_text('\n'.join(json.dumps(x) for x in events) + '\n{"type":')
        result = self.reader.detail(self.rid)
        self.assertEqual(len(result['progress']['items']), 3)
        self.assertEqual(result['progress']['items'][1]['text'], 'hi')
        self.assertNotIn('PRIVATE REASONING', json.dumps(result))
        self.assertEqual(result['progress']['partial_lines'], 1)
        self.assertEqual(result['files'], [])

    def test_secret_redaction(self):
        for secret in ['ghp_abcdefghijklmnop', 'github_pat_abcdef123456', 'sk-abcdefghijklmnop']:
            self.assertNotIn(secret, clean(secret))
        self.assertEqual(clean('Bearer private-value'), 'Bearer [REDACTED]')

    def test_empty_and_bounded_logs(self):
        path = self.evidence / 'stdout.jsonl'
        self.assertEqual(progress(path)['items'], [])
        line = json.dumps({'type': 'item.completed', 'item': {'id': 'one', 'type': 'agent_message', 'text': 'x' * 9000}})
        path.write_text((line + '\n') * 100)
        result = progress(path)
        self.assertTrue(result['truncated'])
        self.assertLess(len(result['items'][0]['text']), 8100)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX symlink')
    def test_symlink_logs_not_read(self):
        outside = self.root / 'private.txt'
        outside.write_text('private content')
        (self.evidence / 'stderr.log').symlink_to(outside)
        self.assertEqual(self.reader.detail(self.rid)['stderr'], '')
        workspace = self.config.workspace_root / '45' / self.rid
        workspace.parent.mkdir(parents=True)
        workspace.symlink_to(self.root, target_is_directory=True)
        self.assertIsNotNone(self.reader.detail(self.rid)['files_error'])

    def test_server_is_readonly_same_origin_and_static_confined(self):
        dist = self.root / 'dist'; dist.mkdir(); (dist / 'index.html').write_text('<h1>test</h1>')
        server = create_server(self.reader, dist, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def get(path, headers=None, method='GET'):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse(); data = response.read(); code = response.status; conn.close()
            return code, data
        marker = {'X-Chat-Codex-Local': '1'}
        self.assertEqual(get('/api/mvp1/overview')[0], 403)
        self.assertEqual(get('/api/mvp1/overview', {**marker, 'Host': 'evil.example'})[0], 403)
        self.assertEqual(get('/api/mvp1/overview', {**marker, 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(get('/api/mvp1/overview', marker)[0], 200)
        self.assertEqual(get('/api/mvp1/tasks/' + self.rid, marker)[0], 200)
        self.assertEqual(get('/api/mvp1/overview', marker, 'POST')[0], 405)
        self.assertEqual(get('/%2e%2e/state/mvp1.sqlite3')[0], 404)
        self.assertEqual(get('/?view=live')[0], 200)
        self.assertEqual(get('/')[0], 302)
        self.assertEqual(get('/api/mvp1/tasks/unknown', marker)[0], 404)


if __name__ == '__main__':
    unittest.main()
