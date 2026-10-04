from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from codex_github_local_v2.mvp0_runner import Execution, MvpError
from codex_github_local_v2.mvp1 import AccountStore, Repository
from codex_github_local_v2.mvp2_contract import DesktopConfig, MARKER, TITLE_PREFIX, parse_desktop_task
from codex_github_local_v2.mvp2 import DesktopStore, DesktopPoller, Publisher, branch_name, receipt
from codex_github_local_v2.mvp2_runner import FileTools, SessionCodexRunner, validate_cli_session
from codex_github_local_v2.workbench import DesktopReader

BASE = 'a' * 40
RID = '6c9134d1-f6ae-49f3-bdfd-e3681c19e183'
SID = '56384b35-4a58-42eb-a9d3-3b203d29a3b9'


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.models = self.root / 'models.json'
        self.models.write_text('{"providers": {}}')
        self.config = DesktopConfig('owner', 'desktop', self.root / 'work', self.root / 'state',
                                    hub_repo='owner/codex-cli', models_file=self.models)
        self.source, self.target = Repository(10, 'owner/codex-cli', 'main'), Repository(20, 'owner/project', 'main')
        self.issue = {'id': 101, 'number': 3, 'state': 'open', 'title': TITLE_PREFIX + ' test', 'user': {'login': 'owner'}}
        self.payload = {'request_id': RID, 'host_id': 'desktop', 'repo': 'owner/project', 'base_sha': BASE,
            'task': {'prompt': 'write docs/check.txt', 'write_paths': ['docs/check.txt']},
            'session': {'mode': 'new'}, 'models': {'mode': 'gpt', 'primary': {'provider': 'codex', 'model': 'gpt-5.4', 'effort': 'high'}}}
        self.comment = {'id': 111, 'created_at': '2026-10-04T00:00:00Z', 'updated_at': '2026-10-04T00:00:00Z', 'user': {'login': 'owner'}}

    def parse(self, payload=None, source=None, issue=None, comment=None):
        comment = {**self.comment, 'body': MARKER + '\n```json\n' + json.dumps(payload or self.payload) + '\n```', **(comment or {})}
        return parse_desktop_task(issue or self.issue, [comment], source or self.source, self.config)

    def store(self):
        s = DesktopStore(self.config.state_dir / 'mvp2.sqlite3')
        self.addCleanup(s.close)
        s.bind(self.config, 9)
        return s


class ContractTests(Fixture):
    def test_hub_and_direct_issue_route_to_target(self):
        self.assertEqual(self.parse().repo, self.target.full_name)
        self.assertEqual(self.parse(source=self.target).host_id, 'desktop')

    def test_host_mismatch_not_claimed(self):
        for host in ['laptop', 'Desktop', '*']:
            with self.subTest(host=host), self.assertRaisesRegex(MvpError, 'wrong_host'):
                self.parse({**self.payload, 'host_id': host})

    def test_foreign_source_and_target_rejected(self):
        with self.assertRaisesRegex(MvpError, 'source_not_allowed'):
            self.parse(source=Repository(30, 'owner/unrelated', 'main'))
        with self.assertRaisesRegex(MvpError, 'target_owner'):
            self.parse({**self.payload, 'repo': 'someone/project'})

    def test_edited_or_foreign_authorization_rejected(self):
        for comment in [{'updated_at': 'later'}, {'user': {'login': 'stranger'}}]:
            with self.subTest(comment=comment), self.assertRaises(MvpError):
                self.parse(comment=comment)

    def test_unknown_fields_and_write_escape(self):
        for payload in [{**self.payload, 'api_key': 'secret'}, {**self.payload, 'task': {'prompt': 'x', 'write_paths': ['../x']}},
                        {**self.payload, 'session': {'mode': 'resume', 'id': 'last'}},
                        {**self.payload, 'session': {'mode': 'new', 'id': SID}}]:
            with self.subTest(payload=payload), self.assertRaises(MvpError):
                self.parse(payload)

    def test_three_modes_and_strict_gpt_leader(self):
        self.parse()
        other = {'provider': 'other', 'model': 'other-model', 'effort': 'medium'}
        self.parse({**self.payload, 'models': {'mode': 'api', 'primary': other}})
        self.parse({**self.payload, 'models': {**self.payload['models'], 'mode': 'gpt-led', 'collaborators': [other]}})
        for models in [{'mode': 'gpt', 'primary': other}, {'mode': 'api', 'primary': self.payload['models']['primary']},
                       {**self.payload['models'], 'mode': 'gpt-led'}, {**self.payload['models'], 'collaborators': [other]}]:
            with self.subTest(models=models), self.assertRaises(MvpError):
                self.parse({**self.payload, 'models': models})

    def test_new_schema_rejects_old_database(self):
        path = self.root / 'old.sqlite3'
        AccountStore(path).close()
        with self.assertRaisesRegex(MvpError, 'unsupported_mvp_schema'):
            DesktopStore(path)

    def test_atomic_claim_dedup_and_source_identity(self):
        s, task = self.store(), self.parse()
        ident = s.claim_desktop(self.source, self.target, self.issue, task, {})
        self.assertIsNotNone(s.delivery(ident))
        self.assertEqual(s.get(ident)['repository_id'], self.source.id)
        self.assertEqual(s.delivery(ident)['target_id'], self.target.id)
        self.assertIsNone(s.claim_desktop(self.target, self.target, {**self.issue, 'id': 999}, task, {}))
        with self.assertRaisesRegex(MvpError, 'unfinished'):
            s.claim_desktop(self.target, self.target, {**self.issue, 'id': 999}, replace(task, request_id=SID), {})

    def test_resume_binding_to_host_repo_backend(self):
        s = self.store()
        ident = s.claim_desktop(self.source, self.target, self.issue, self.parse(), {})
        s.save_session(ident, SID, 'codex')
        poller = DesktopPoller(self.config, s)
        task = replace(self.parse(), session={'mode': 'resume', 'id': SID})
        self.assertEqual(poller.check_session(task, self.target)['backend'], 'codex')
        with self.assertRaisesRegex(MvpError, 'session_binding'):
            poller.check_session(task, Repository(99, 'owner/other', 'main'))

    def test_workbench_hub_url_and_delivery_fields(self):
        s = self.store()
        ident = s.claim_desktop(self.source, self.target, self.issue, self.parse(), {})
        s.save_session(ident, SID, 'codex')
        s.publication(ident, pr_url='https://github.com/owner/project/pull/5')
        view = DesktopReader(self.config).overview()
        self.assertEqual(view['source'], 'local-mvp2')
        task = view['tasks'][0]
        self.assertEqual(task['issue_url'], 'https://github.com/owner/codex-cli/issues/3')
        self.assertEqual(task['session_id'], SID)
        self.assertEqual(task['model'], 'gpt-5.4')

    def test_workbench_default_command_reads_current_database(self):
        from codex_github_local_v2.workbench import main
        self.store()
        config_file = self.root / 'config.json'
        config_file.write_text(json.dumps({
            'owner': self.config.owner, 'host_id': self.config.host_id,
            'workspace_root': str(self.config.workspace_root), 'state_dir': str(self.config.state_dir),
            'hub_repo': self.config.hub_repo, 'models_file': str(self.models)
        }))
        dist = self.root / 'dist'
        dist.mkdir()
        (dist / 'index.html').write_text('<html></html>')
        with patch('codex_github_local_v2.workbench.create_server') as create:
            create.return_value.__enter__.return_value.server_port = 8791
            with patch('builtins.print'):
                self.assertEqual(main(['--config', str(config_file), '--dist', str(dist)]), 0)
        reader = create.call_args.args[0]
        self.assertEqual(reader.overview()['source'], 'local-mvp2')
        self.assertFalse((self.config.state_dir / 'mvp1.sqlite3').exists())


class PollerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.gh = Mock(owner_id=9)
        self.gh.repositories.return_value = [self.source, self.target]
        self.clients = {10: Mock(), 20: Mock()}
        self.clients[10].issues.return_value = [self.issue]
        self.clients[20].issues.return_value = []
        self.clients[10].api.return_value = self.issue
        for c in self.clients.values():
            c.comments.side_effect = lambda number: [{**self.comment, 'body': MARKER + '\n' + json.dumps(self.payload)}]
            c.post_receipt.return_value = 300
        self.gh.client.side_effect = lambda repo: self.clients[repo.id]
        self.gh.repository.side_effect = lambda name, rid: self.source if rid == 10 else self.target
        self.ws = Mock()
        self.ws.changes.return_value = ['docs/check.txt']
        self.runner = Mock()
        self.runner.prepare_task.side_effect = lambda workspace, *_: {'cli_version': 'FAKE', 'argv': ['fake'], 'cwd': str(workspace)}
        def run(metadata, prompt, evidence, timeout, record):
            evidence.mkdir(parents=True)
            (evidence / 'stdout.jsonl').write_text(json.dumps({'type': 'thread.started', 'thread_id': SID}) + '\n')
            return Execution(0, None)
        self.runner.run.side_effect = run
        self.pub = Mock()
        self.pub.publish.return_value = 'https://github.com/owner/project/pull/5'
        self.p = DesktopPoller(self.config, self.s, self.gh, runner=self.runner,
                               workspace_factory=Mock(return_value=self.ws), publisher=self.pub)

    def test_execute_hub_task_receipt_to_source(self):
        self.assertEqual(self.p.once(), 1)
        row = self.s.get(1)
        self.assertEqual(row['state'], 'succeeded')
        self.clients[10].post_receipt.assert_called_once()
        self.clients[20].post_receipt.assert_not_called()
        self.assertIn('pull/5', self.clients[10].post_receipt.call_args.args[1])
        self.assertEqual(self.s.delivery(1)['session_id'], SID)
        self.assertEqual(self.p.once(), 0)
        self.runner.run.assert_called_once()

    def test_wrong_host_never_claimed_or_executed(self):
        self.payload['host_id'] = 'laptop'
        self.assertEqual(self.p.once(), 0)
        self.assertIsNone(self.s.unfinished())
        self.runner.run.assert_not_called()
        self.assertEqual(DesktopReader(self.config).overview()['monitor']['rejected'], [])

    def test_unregistered_model_is_visible_without_claim_or_execution(self):
        self.models.write_text(json.dumps({'providers': {'other': {
            'kind': 'other', 'base_url': 'http://127.0.0.1:8317/v1', 'api_key_env': 'TEST_KEY',
            'wire_api': 'chat_completions', 'models': ['example-model'], 'effort_map': {'high': 'high'}}}}))
        from codex_github_local_v2.model_api import ModelRegistry
        self.p.registry = ModelRegistry(self.models)
        self.payload['models'] = {'mode': 'api', 'primary': {'provider': 'other', 'model': 'Example-Model', 'effort': 'max'}}
        self.assertEqual(self.p.once(), 0)
        view = DesktopReader(self.config).overview()
        self.assertEqual(view['counts'], {})
        self.assertEqual(view['monitor']['phase'], 'idle')
        rejection = view['monitor']['rejected'][0]
        self.assertEqual(rejection['issue_url'], 'https://github.com/owner/codex-cli/issues/3')
        self.assertEqual(rejection['reason'], 'model_not_allowed')
        self.assertEqual(rejection['suggested_model'], 'example-model')
        self.assertEqual(rejection['allowed_efforts'], ['high'])
        self.runner.run.assert_not_called()

    def test_poll_network_error_is_visible_and_still_raises(self):
        self.gh.repositories.side_effect = MvpError('github_api_failed')
        with self.assertRaisesRegex(MvpError, 'github_api_failed'):
            self.p.once()
        monitor = DesktopReader(self.config).overview()['monitor']
        self.assertEqual(monitor['phase'], 'error')
        self.assertEqual(monitor['last_error'], 'github_api_failed')

    def test_monitor_optional_bound_and_operational_activity_redacted(self):
        reader = DesktopReader(self.config)
        self.assertIsNone(reader.overview()['monitor'])
        self.p.status.begin()
        self.p.status.finish()
        path = self.config.state_dir / 'listener-status.json'
        data = json.loads(path.read_text())
        data['owner'] = 'foreign'
        path.write_text(json.dumps(data))
        self.assertIsNone(reader.overview()['monitor'])
        ident = self.s.claim_desktop(self.source, self.target, self.issue, self.parse(), {})
        self.s.start(ident, {'cli_version': 'TEST', 'argv': [], 'cwd': str(self.root)})
        self.s.event(ident, 'api_model_request', {'turn': 2, 'max_turns': 40, 'prompt': 'private prompt'})
        view = reader.overview()
        self.assertEqual(view['tasks'][0]['activity']['label'], '正在等待模型回复（第 2/40 轮）')
        self.assertNotIn('private prompt', json.dumps(view))
        self.s.event(ident, 'api_file_tool', {'name': 'read_file', 'path': 'source.py', 'turn': 2, 'max_turns': 40, 'ok': True, 'content': 'private file'})
        detail = reader.detail(RID)
        self.assertIn('source.py', detail['activity']['label'])
        self.assertNotIn('private file', json.dumps(detail))
        evidence = self.config.state_dir / 'runs' / RID
        evidence.mkdir(parents=True)
        (evidence / 'stdout.jsonl').write_text('{"type":"item.completed","item":{"type":"reasoning","text":"private reasoning"}}')
        os.utime(evidence / 'stdout.jsonl', (time.time() + 2, time.time() + 2))
        updated = reader.overview()
        self.assertEqual(updated['tasks'][0]['activity']['label'], '执行日志有更新')
        self.assertNotIn('private reasoning', json.dumps(updated))
        os.utime(evidence / 'stdout.jsonl', (0, 0))
        self.s.event(ident, 'api_model_request', {'turn': 65, 'max_turns': None})
        self.assertEqual(reader.overview()['tasks'][0]['activity']['label'], '正在等待模型回复（第 65 轮，无操作次数上限）')

    def test_scope_failure_keeps_files_and_no_pr(self):
        self.ws.check_changes.side_effect = MvpError('write_scope_violation')
        self.p.once()
        self.assertEqual(self.s.get(1)['state'], 'failed')
        self.pub.publish.assert_not_called()
        self.ws.git.assert_not_called()

    def test_publication_lost_response_retries_without_model(self):
        self.pub.publish.side_effect = [MvpError('github_transport_unavailable'), 'https://github.com/owner/project/pull/5']
        self.p.once()
        self.assertEqual(self.s.get(1)['state'], 'running')
        self.assertEqual(self.s.delivery(1)['execution_completed'], 1)
        self.p.once()
        self.assertEqual(self.s.get(1)['state'], 'succeeded')
        self.runner.run.assert_called_once()

    def test_crashed_execution_and_uncertain_commit_never_replayed(self):
        ident = self.s.claim_desktop(self.source, self.target, self.issue, self.parse(), {})
        with self.assertRaisesRegex(MvpError, 'manual_inspection'):
            self.p.once()
        self.s.completed_execution(ident)
        self.s.publication(ident, publication_state='committing')
        with self.assertRaisesRegex(MvpError, 'manual_inspection'):
            self.p.once()
        self.runner.run.assert_not_called()

    def test_contract_changed_before_claim(self):
        calls = 0
        def comments(_):
            nonlocal calls
            calls += 1
            data = json.loads(json.dumps(self.payload))
            if calls > 1:
                data['task']['prompt'] = 'different'
            return [{**self.comment, 'body': MARKER + '\n' + json.dumps(data)}]
        self.clients[10].comments.side_effect = comments
        self.p.once()
        self.runner.run.assert_not_called()

    def test_process_cleanup_failure_blocks_next_task(self):
        self.runner.run.side_effect = MvpError('process_cleanup_failed')
        with self.assertRaisesRegex(MvpError, 'cleanup_failed'):
            self.p.once()
        self.assertEqual(self.s.get(1)['state'], 'running')
        self.pub.publish.assert_not_called()


class ToolAndSessionTests(Fixture):
    def test_file_tools_scope_and_no_git_or_secrets(self):
        self.root.joinpath('project').mkdir()
        tools = FileTools(self.root / 'project', ['docs/'])
        tools.call('write_file', {'path': 'docs/a.txt', 'content': 'ok'})
        self.assertEqual(tools.call('read_file', {'path': 'docs/a.txt'})['content'], 'ok')
        for name in ['../x', '.git/config', '.env', 'auth.json', 'outside.txt']:
            with self.subTest(name=name), self.assertRaises(MvpError):
                tools.call('write_file', {'path': name, 'content': 'bad'})
        with self.assertRaisesRegex(MvpError, 'not_allowed'):
            tools.call('run_command', {'command': 'echo arbitrary'})

    @unittest.skipIf(os.name != 'posix', 'POSIX symlink')
    def test_symlink_escape_rejected(self):
        (self.root / 'project').mkdir()
        (self.root / 'project' / 'docs').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(MvpError):
            FileTools(self.root / 'project', ['docs/']).call('write_file', {'path': 'docs/x', 'content': 'bad'})

    def test_exact_session_requires_local_rollout(self):
        home = self.root / 'codex'; (home / 'sessions').mkdir(parents=True)
        with patch.dict(os.environ, {'CODEX_HOME': str(home)}):
            with self.assertRaisesRegex(MvpError, 'not_found'):
                validate_cli_session(SID)
            (home / 'sessions' / ('rollout-' + SID + '.jsonl')).write_text(json.dumps(
                {'type': 'session_meta', 'payload': {'id': SID, 'cwd': str(self.root)}}) + '\n')
            self.assertEqual(validate_cli_session(SID)['cwd'], str(self.root))

    def test_cli_argv_new_and_resume_no_last(self):
        runner = SessionCodexRunner()
        registry = Mock(limits={'request_timeout': 10})
        with patch('codex_github_local_v2.mvp0_runner.subprocess.run', return_value=Mock(stdout='codex 0.160.0')):
            meta = runner.prepare_task(self.root, self.parse(), self.config, registry, self.root/'options.json')
            self.assertIn('gpt-5.4', meta['argv'])
            self.assertIn('model_reasoning_effort="high"', meta['argv'])
            self.assertNotIn('resume', meta['argv'])
            with patch('codex_github_local_v2.mvp2_runner.validate_cli_session'):
                resumed = runner.prepare_task(self.root, replace(self.parse(), session={'mode': 'resume', 'id': SID}),
                                              self.config, registry, self.root/'options.json')
            self.assertIn(SID, resumed['argv'])
            self.assertNotIn('--last', resumed['argv'])
            self.assertIn('resume', resumed['argv'])

    def test_cli_collaboration_forwards_only_selected_key_names(self):
        task = replace(self.parse(), models={**self.parse().models, 'mode': 'gpt-led',
            'collaborators': [{'provider': 'other', 'model': 'other-model', 'effort': 'medium'}]})
        registry = Mock(limits={'request_timeout': 30})
        registry.resolve.return_value = {'api_key_env': 'OTHER_TEST_API_KEY'}
        with (patch('codex_github_local_v2.mvp0_runner.subprocess.run', return_value=Mock(stdout='codex 0.160.0')),
              patch.dict(os.environ, {'OTHER_TEST_API_KEY': 'secret-never-in-argv'})):
            meta = SessionCodexRunner().prepare_task(self.root, task, self.config, registry, self.root/'options.json')
        self.assertIn('mcp_servers.collaborators.env_vars=["OTHER_TEST_API_KEY"]', meta['argv'])
        self.assertNotIn('secret-never-in-argv', ' '.join(meta['argv']))


class PublisherTests(Fixture):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.workspace = self.config.workspace_root / str(self.target.id) / RID
        self.workspace.mkdir(parents=True)
        def git(*args):
            return subprocess.run(['git', '-C', str(self.workspace), *args], capture_output=True, check=True, text=True).stdout.strip()
        self.git = git
        git('init', '-b', 'main'); git('config', 'user.name', 'Offline'); git('config', 'user.email', 'offline@example.com')
        (self.workspace / 'README.md').write_text('base')
        git('add', 'README.md'); git('commit', '-m', 'base')
        self.base = git('rev-parse', 'HEAD')
        git('remote', 'add', 'origin', 'https://github.com/owner/project.git')
        git('checkout', '-b', branch_name('desktop', RID))
        task = replace(self.parse(), base_sha=self.base)
        self.ident = self.s.claim_desktop(self.source, self.target, self.issue, task, {})
        self.s.start(self.ident, {'cli_version': 'FAKE', 'argv': [], 'cwd': str(self.workspace)})
        self.s.completed_execution(self.ident)
        self.gh = Mock(config=self.config)
        self.gh.repository.return_value = self.target
        self.client = Mock()
        self.client.pages.return_value = []
        self.client.api.return_value = {'html_url': 'https://github.com/owner/project/pull/5'}
        self.gh.client.return_value = self.client
        self.pub = Publisher(self.gh, self.s)
        self.remote = ''
        self.pushes = 0

    def transport(self, cwd, *args, **kwargs):
        if args[0] == 'ls-remote':
            return self.remote
        if args[0] == 'push':
            self.pushes += 1
            self.remote = self.git('rev-parse', 'HEAD') + '\trefs/heads/' + branch_name('desktop', RID)
            return ''
        return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, check=True, text=True).stdout.strip()

    def test_commit_push_and_draft_pr_and_reconciliation(self):
        (self.workspace / 'docs').mkdir(); (self.workspace / 'docs/check.txt').write_text('output')
        with patch('codex_github_local_v2.mvp2.run_git', side_effect=self.transport):
            self.assertEqual(self.pub.publish(self.ident), 'https://github.com/owner/project/pull/5')
            commit = self.s.delivery(self.ident)['commit_sha']
            self.assertNotEqual(commit, self.base)
            self.assertEqual(self.git('status', '--porcelain'), '')
            self.assertEqual(self.pushes, 1)
            body = self.client.api.call_args.args[1]
            self.assertTrue(body['draft'])
            self.assertIn('/owner/codex-cli/issues/3', body['body'])
            self.client.pages.return_value = [{'html_url': 'https://github.com/owner/project/pull/5',
                                               'head': {'sha': commit}, 'base': {'ref': 'main'}}]
            self.pub.publish(self.ident)
            self.assertEqual(self.pushes, 1)
            self.client.api.assert_called_once()

    def test_out_of_scope_not_staged_or_pushed(self):
        (self.workspace / 'private.txt').write_text('unauthorized')
        with patch('codex_github_local_v2.mvp2.run_git', side_effect=self.transport), self.assertRaisesRegex(MvpError, 'scope_violation'):
            self.pub.publish(self.ident)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        self.assertEqual(self.pushes, 0)

    def test_no_changes_no_empty_pr(self):
        self.assertIsNone(self.pub.publish(self.ident))
        self.client.api.assert_not_called()
        self.assertEqual(self.s.delivery(self.ident)['publication_state'], 'no_changes')


if __name__ == '__main__':
    unittest.main()
