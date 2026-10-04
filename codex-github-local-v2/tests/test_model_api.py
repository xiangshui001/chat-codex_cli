from http.server import BaseHTTPRequestHandler, HTTPServer
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from codex_github_local_v2.collaboration_api import handler, serve_stdio
from codex_github_local_v2.model_api import Collaboration, ModelClient, ModelRegistry
from codex_github_local_v2.mvp0_runner import MvpError
from codex_github_local_v2.mvp2_contract import DesktopTask
from codex_github_local_v2.mvp2_runner import ApiFileRunner


def chat(text='answer', calls=None, finish=None):
    return {'choices': [{'finish_reason': finish or ('tool_calls' if calls else 'stop'),
                         'message': {'role': 'assistant', 'content': text, **({'tool_calls': calls} if calls else {})}}]}


def function(name, args, ident='call-1'):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


def responses(text='GPT final', calls=None):
    return {'status': 'completed', 'output': calls or [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}]}


class ApiFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.queue, self.requests = [], []
        fixture = self
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append((self.path, data, self.headers['Authorization']))
                response = fixture.queue.pop(0)
                payload = json.dumps(response).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(payload))); self.end_headers()
                self.wfile.write(payload)
        self.server = HTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        url = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.providers = {
            'gpt': {'kind': 'gpt', 'base_url': url, 'api_key_env': 'TEST_GPT_KEY', 'wire_api': 'responses',
                    'models': ['gpt-test'], 'effort_map': {'high': 'high'}},
            'other': {'kind': 'other', 'base_url': url, 'api_key_env': 'TEST_OTHER_KEY', 'wire_api': 'chat_completions',
                      'models': ['other-test'], 'effort_map': {'high': 'high', 'none': None}},
        }
        self.file = self.root / 'models.json'
        self.file.write_text(json.dumps({'providers': self.providers, 'max_calls': 2, 'max_turns': 4}))
        self.registry = ModelRegistry(self.file)
        env = patch.dict(os.environ, {'TEST_GPT_KEY': 'test-gpt-secret', 'TEST_OTHER_KEY': 'test-other-secret'})
        env.start(); self.addCleanup(env.stop)
        self.gpt = {'provider': 'gpt', 'model': 'gpt-test', 'effort': 'high'}
        self.other = {'provider': 'other', 'model': 'other-test', 'effort': 'high'}


class ModelApiTests(ApiFixture):
    def test_gpt_mode_only_responses_and_reasoning(self):
        self.queue = [responses()]
        result = Collaboration(self.registry, {'mode': 'gpt', 'primary': self.gpt}).respond('question')
        self.assertEqual(result['text'], 'GPT final')
        path, payload, auth = self.requests[0]
        self.assertEqual(path, '/v1/responses')
        self.assertEqual(payload['reasoning'], {'effort': 'high'})
        self.assertFalse(payload['store'])
        self.assertNotIn('tools', payload)
        self.assertEqual(auth, 'Bearer test-gpt-secret')

    def test_api_only_no_gpt_calls(self):
        self.queue = [chat('Other final')]
        result = Collaboration(self.registry, {'mode': 'api', 'primary': self.other}).respond('question')
        self.assertEqual(result['text'], 'Other final')
        self.assertEqual([p[1]['model'] for p in self.requests], ['other-test'])
        self.assertEqual(self.requests[0][1]['reasoning_effort'], 'high')

    def test_gpt_directs_other_and_synthesizes_preserving_items(self):
        reasoning = {'type': 'reasoning', 'id': 'reason-1', 'encrypted_content': 'opaque', 'summary': []}
        call = {'type': 'function_call', 'call_id': 'call-1', 'name': 'consult_model',
                'arguments': json.dumps({'index': 0, 'prompt': 'Check this design'})}
        self.queue = [responses(calls=[reasoning, call]), chat('External advice'), responses('GPT judgment')]
        result = Collaboration(self.registry, {'mode': 'gpt-led', 'primary': self.gpt, 'collaborators': [self.other]}).respond('Build a design')
        self.assertEqual(result['text'], 'GPT judgment')
        self.assertEqual(result['collaboration_calls'], 1)
        self.assertEqual([r[1]['model'] for r in self.requests], ['gpt-test', 'other-test', 'gpt-test'])
        replay = self.requests[2][1]['input']
        self.assertIn(reasoning, replay)
        self.assertEqual(replay[-1]['call_id'], 'call-1')
        self.assertIn('External advice', replay[-1]['output'])

    def test_reject_unsupported_effort_before_request(self):
        with self.assertRaisesRegex(MvpError, 'effort_not_supported'):
            self.registry.resolve({**self.other, 'effort': 'ultra'})
        self.assertEqual(self.requests, [])

    def test_missing_key_and_unregistered_model(self):
        with patch.dict(os.environ, {'TEST_OTHER_KEY': ''}), self.assertRaisesRegex(MvpError, 'key_missing'):
            self.registry.validate({'mode': 'api', 'primary': self.other})
        with self.assertRaisesRegex(MvpError, 'model_not_allowed'):
            self.registry.resolve({**self.other, 'model': 'unregistered'})

    def test_config_cannot_redirect_or_embed_credentials(self):
        for url in ['http://external.example/v1', 'https://user:secret@provider.example/v1', 'https://provider.example/v1?api_key=x']:
            self.providers['other']['base_url'] = url
            self.file.write_text(json.dumps({'providers': self.providers}))
            with self.subTest(url=url), self.assertRaisesRegex(MvpError, 'provider_url'):
                ModelRegistry(self.file)

    def test_provider_parameter_mapping_and_explicit_omission(self):
        self.providers['other']['reasoning_parameter'] = 'reasoning.effort'
        self.providers['other']['effort_map']['high'] = 'deep'
        self.file.write_text(json.dumps({'providers': self.providers}))
        registry = ModelRegistry(self.file)
        self.queue = [chat(), chat()]
        client = ModelClient(registry)
        client.call(self.other, [{'role': 'user', 'content': 'q'}])
        client.call({**self.other, 'effort': 'none'}, [{'role': 'user', 'content': 'q'}])
        self.assertEqual(self.requests[0][1]['reasoning'], {'effort': 'deep'})
        self.assertNotIn('reasoning', self.requests[1][1])

    def test_truncated_model_response_fails(self):
        self.queue = [chat('partial', finish='length')]
        with self.assertRaisesRegex(MvpError, 'incomplete'):
            ModelClient(self.registry).call(self.other, [{'role': 'user', 'content': 'q'}])

    def test_request_timeout_is_distinguished_without_leaking_transport_detail(self):
        client = ModelClient(self.registry)
        for error in [TimeoutError('private transport detail'), URLError(TimeoutError('private transport detail'))]:
            with patch.object(client.opener, 'open', side_effect=error), self.assertRaisesRegex(MvpError, '^model_request_timeout$'):
                client.call(self.other, [{'role': 'user', 'content': 'q'}])

    def test_nullable_operation_budgets_and_positive_opt_in(self):
        for limits in [{}, {'max_turns': None, 'max_calls': None}, {'max_turns': 1000, 'max_calls': 1000}]:
            self.file.write_text(json.dumps({'providers': self.providers, **limits}))
            registry = ModelRegistry(self.file)
            self.assertEqual(registry.limits['max_turns'], limits.get('max_turns'))
        for value in [0, -1, True, 1.5]:
            self.file.write_text(json.dumps({'providers': self.providers, 'max_turns': value}))
            with self.assertRaisesRegex(MvpError, 'invalid_model_limit'):
                ModelRegistry(self.file)

    def test_unlimited_collaboration_calls_can_exceed_old_limit(self):
        self.file.write_text(json.dumps({'providers': self.providers, 'max_calls': None}))
        registry = ModelRegistry(self.file)
        self.queue = [chat('advice') for _ in range(40)]
        bridge = Collaboration(registry, {'mode': 'gpt-led', 'primary': self.gpt, 'collaborators': [self.other]})
        for _ in range(40):
            bridge.consult(0, 'question')
        self.assertEqual(bridge.calls, 40)

    def test_consultation_budget_and_no_arbitrary_provider(self):
        self.queue = [chat(), chat()]
        bridge = Collaboration(self.registry, {'mode': 'gpt-led', 'primary': self.gpt, 'collaborators': [self.other]})
        with self.assertRaisesRegex(MvpError, 'not_allowed'):
            bridge.consult(2, 'q')
        bridge.consult(0, 'q'); bridge.consult(0, 'q')
        with self.assertRaisesRegex(MvpError, 'call_limit'):
            bridge.consult(0, 'q')

    def test_mcp_initialize_list_call_and_errors(self):
        self.queue = [chat('advice')]
        bridge = Collaboration(self.registry, {'mode': 'gpt-led', 'primary': {'provider': 'codex', 'model': 'gpt-test', 'effort': 'high'},
                                              'collaborators': [self.other]})
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'consult_model', 'arguments': {'index': 0, 'prompt': 'q'}}},
                    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'consult_model', 'arguments': {'index': 99, 'prompt': 'q'}}}]
        output = io.StringIO()
        serve_stdio(bridge, io.StringIO('\n'.join(json.dumps(m) for m in messages)), output)
        replies = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertEqual(replies[0]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(replies[1]['result']['tools'][0]['name'], 'consult_model')
        self.assertIn('advice', replies[2]['result']['content'][0]['text'])
        self.assertTrue(replies[3]['result']['isError'])

    def test_http_bearer_origin_and_real_respond(self):
        token = 'local-test-token-with-at-least-32-characters'
        api = HTTPServer(('127.0.0.1', 0), handler(self.registry, token))
        threading.Thread(target=api.serve_forever, daemon=True).start()
        self.addCleanup(api.server_close); self.addCleanup(api.shutdown)
        def request(path, body=None, headers=None):
            conn = http.client.HTTPConnection('127.0.0.1', api.server_port, timeout=10)
            conn.request('POST' if body else 'GET', path, body=json.dumps(body) if body else None, headers=headers or {})
            result = conn.getresponse(); data = result.read(); conn.close()
            return result.status, json.loads(data)
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        self.assertEqual(request('/health')[0], 401)
        self.assertEqual(request('/health', headers={**headers, 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(request('/v1/models', headers=headers)[0], 200)
        self.queue = [chat('API result')]
        status, data = request('/v1/respond', {'prompt': 'question', 'models': {'mode': 'api', 'primary': self.other}}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(data['text'], 'API result')
        self.assertNotIn('secret', json.dumps(data))

    def test_file_agent_writes_and_resumes_history_without_gpt(self):
        workspace = self.root / 'project'; workspace.mkdir()
        task = DesktopTask('6c9134d1-f6ae-49f3-bdfd-e3681c19e183', 'desktop', 'owner/project', 'a'*40,
                           'Create docs/check.txt', ('docs/',), 1, 'hash', {'mode': 'new'}, {'mode': 'api', 'primary': self.other})
        self.queue = [chat(None, [function('write_file', {'path': 'docs/check.txt', 'content': 'API output'})]), chat('Done')]
        runner = ApiFileRunner(self.registry)
        result, session, history = runner.run_task(task, workspace, self.root/'run1', 10, lambda *_: None)
        self.assertIsNone(result.error)
        self.assertEqual((workspace/'docs/check.txt').read_text(), 'API output')
        self.queue = [chat('Remembered')]
        result, next_session, _ = runner.run_task(task, workspace, self.root/'run2', 10, lambda *_: None, history, session)
        self.assertEqual(next_session, session)
        self.assertEqual(self.requests[-1][1]['messages'][:len(history)], history)
        self.assertTrue(all(r[1]['model'] == 'other-test' for r in self.requests))

    def test_file_agent_reports_scope_error_to_model(self):
        workspace = self.root / 'project'; workspace.mkdir()
        task = DesktopTask('6c9134d1-f6ae-49f3-bdfd-e3681c19e183', 'desktop', 'owner/project', 'a'*40,
                           'Create docs/check.txt', ('docs/',), 1, 'hash', {'mode': 'new'}, {'mode': 'api', 'primary': self.other})
        self.queue = [chat(None, [function('write_file', {'path': '../escape', 'content': 'bad'})]), chat('Cannot write')]
        ApiFileRunner(self.registry).run_task(task, workspace, self.root/'run', 10, lambda *_: None)
        self.assertFalse((self.root/'escape').exists())
        tool_messages = [m for m in self.requests[-1][1]['messages'] if m['role'] == 'tool']
        self.assertIn('error', tool_messages[-1]['content'])

    def test_review_can_read_beyond_old_budget_then_write_report(self):
        self.file.write_text(json.dumps({'providers': self.providers}))
        registry = ModelRegistry(self.file)
        workspace = self.root / 'project'; workspace.mkdir()
        (workspace / 'source.txt').write_text('review evidence')
        task = DesktopTask('6c9134d1-f6ae-49f3-bdfd-e3681c19e183', 'desktop', 'owner/project', 'a'*40,
                           'Review repository', ('docs/report.md',), 1, 'hash', {'mode': 'new'},
                           {'mode': 'api', 'primary': self.other})
        self.queue = [chat(None, [function('read_file', {'path': 'source.txt'}, str(i))]) for i in range(60)]
        batch = [function('read_file', {'path': 'source.txt'}, 'batch-' + str(i)) for i in range(19)]
        batch += [function('write_file', {'path': 'docs/report.md', 'content': 'Evidence-based report'}, 'write-final')]
        self.queue += [chat(None, batch), chat('Done')]
        result, _, _ = ApiFileRunner(registry).run_task(task, workspace, self.root/'run', 10, lambda *_: None)
        self.assertIsNone(result.error)
        self.assertEqual((workspace/'docs/report.md').read_text(), 'Evidence-based report')
        self.assertEqual(len(self.requests), 62)
        self.assertFalse(any('responses remain' in (m.get('content') or '') for m in self.requests[-1][1]['messages']))

    def test_budget_reminder_and_failure_diagnostics_without_resume(self):
        workspace = self.root / 'project'; workspace.mkdir()
        task = DesktopTask('6c9134d1-f6ae-49f3-bdfd-e3681c19e183', 'desktop', 'owner/project', 'a'*40,
                           'Review repository', ('docs/report.md',), 1, 'hash', {'mode': 'new'},
                           {'mode': 'api', 'primary': self.other})
        self.queue = [chat(None, [function('read_file', {'path': 'missing.txt'}, str(i))]) for i in range(4)]
        recorded = []
        result, _, history = ApiFileRunner(self.registry).run_task(
            task, workspace, self.root/'run', 10, lambda kind, value: recorded.append(value) if kind == 'api_file_tool' else None)
        self.assertEqual(result.error, 'model_turn_limit')
        self.assertIsNone(history)
        self.assertFalse(any(item['ok'] for item in recorded))
        self.assertEqual(recorded[-1]['turn'], 4)
        saved = json.loads((self.root/'run/context.json').read_text())
        self.assertTrue(any('Only 1 model responses remain' in (m.get('content') or '') for m in saved))
        metadata = json.loads((self.root/'run/execution.json').read_text())
        self.assertEqual((metadata['turns_used'], metadata['max_turns']), (4, 4))
        self.assertFalse((workspace/'docs/report.md').exists())


if __name__ == '__main__':
    unittest.main()
