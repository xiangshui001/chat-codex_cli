from dataclasses import replace
import json
import time
import unittest
from unittest.mock import Mock, patch

import test_model_api as model_fixtures
import test_mvp2 as task_fixtures
from codex_github_local_v2.api_recovery import ResponseRecovery
from codex_github_local_v2.api_sessions import recover_api_session
from codex_github_local_v2.model_api import Collaboration, ModelClient, ModelRegistry
from codex_github_local_v2.mvp0_runner import MvpError
from codex_github_local_v2.mvp2_contract import DesktopTask
from codex_github_local_v2.mvp2_runner import ApiFileRunner


class ContinuationTests(model_fixtures.ApiFixture):
    def task(self):
        return DesktopTask(task_fixtures.RID, 'desktop', 'owner/project', 'a'*40,
                           'Write docs/report.md', ('docs/report.md',), 1, 'hash',
                           {'mode': 'new'}, {'mode': 'api', 'primary': self.other})

    def test_truncated_tool_is_never_executed_and_history_continues(self):
        workspace = self.root / 'project'; workspace.mkdir()
        truncated = model_fixtures.chat('Partial findings', [model_fixtures.function('write_file',
            {'path': 'docs/report.md', 'content': 'should never be written'}, 'truncated')], finish='length')
        self.queue = [truncated, model_fixtures.chat(None, [model_fixtures.function('write_file',
            {'path': 'docs/report.md', 'content': 'Complete report'}, 'complete')]), model_fixtures.chat('Done')]
        events = []
        result, _, history = ApiFileRunner(self.registry).run_task(self.task(), workspace, self.root/'run', 10,
                                                                  lambda kind, detail: events.append((kind, detail)))
        self.assertIsNone(result.error)
        self.assertEqual((workspace/'docs/report.md').read_text(), 'Complete report')
        self.assertEqual(len([e for e in events if e[0]=='api_file_tool']), 1)
        next_history = self.requests[1][1]['messages']
        self.assertIn('Partial findings', json.dumps(next_history))
        self.assertNotIn('should never be written', json.dumps(next_history))
        self.assertEqual(self.requests[1][1]['max_tokens'], 16384)
        self.assertEqual(next(detail for kind,detail in events if kind=='api_response_recovery')['reason'], 'output_limit')
        self.assertTrue(history)

    def test_missing_finish_marker_and_empty_response_continue(self):
        missing = model_fixtures.chat('Useful partial answer'); missing['choices'][0]['finish_reason'] = None
        self.queue = [missing, model_fixtures.chat(''), model_fixtures.chat('Complete answer')]
        with patch('codex_github_local_v2.api_recovery.time.sleep'):
            answer = Collaboration(self.registry, {'mode': 'api', 'primary': self.other}).respond('Question')
        self.assertEqual(answer['text'], 'Complete answer')
        self.assertIn('Useful partial answer', json.dumps(self.requests[-1][1]['messages']))

    def test_responses_incomplete_drops_partial_calls_and_raises_budget(self):
        self.queue = [{'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                       'output': [{'type': 'function_call', 'call_id': 'partial', 'name': 'unsafe', 'arguments': '{'}]},
                      model_fixtures.responses('Complete answer')]
        with patch('codex_github_local_v2.api_recovery.time.sleep'):
            answer = Collaboration(self.registry, {'mode': 'gpt', 'primary': self.gpt}).respond('Question')
        self.assertEqual(answer['text'], 'Complete answer')
        self.assertEqual(self.requests[1][1]['max_output_tokens'], 16384)
        self.assertNotIn('unsafe', json.dumps(self.requests[1][1]['input']))

    def test_collaborator_continues_and_counts_one_logical_consultation(self):
        self.queue = [model_fixtures.chat('partial', finish='length'), model_fixtures.chat('Complete advice')]
        bridge = Collaboration(self.registry, {'mode': 'gpt-led', 'primary': self.gpt, 'collaborators': [self.other]})
        self.assertEqual(bridge.consult(0, 'Question')['text'], 'Complete advice')
        self.assertEqual(bridge.calls, 1)

    def test_timeout_and_authentication_error_retain_progress_for_recovery(self):
        client = Mock()
        client.call.side_effect = [MvpError('model_request_timeout'), {'text': 'Done', 'calls': [], 'history': []}]
        recovery = ResponseRecovery(self.registry)
        history = []
        deadline = time.monotonic() + 10
        with patch('codex_github_local_v2.api_recovery.time.sleep'):
            partial = recovery.call(client, self.other, history, (), deadline)
            self.assertTrue(recovery.continue_response(partial, history, deadline))
            self.assertEqual(recovery.call(client, self.other, history, (), deadline)['text'], 'Done')
        client.call.side_effect = MvpError('model_http_401')
        self.assertEqual(recovery.call(client,self.other,history,(),deadline)['incomplete_reason'],'model_http_401')

    def test_recovery_budget_ceiling_and_deadline_are_enforced(self):
        self.file.write_text(json.dumps({'providers': self.providers, 'max_output_tokens': 8192,
                                        'recovery_max_output_tokens': 16384}))
        registry = ModelRegistry(self.file)
        recovery = ResponseRecovery(registry)
        partial = {'text': 'partial', 'calls': [], 'history': [], 'incomplete_reason': 'output_limit'}
        history = []
        for _ in range(3):
            recovery.continue_response(partial, history, time.monotonic() + 5)
        self.assertEqual(recovery.output_limit, 16384)
        with self.assertRaisesRegex(MvpError, 'execution_timeout'):
            recovery.call(Mock(), self.other, history, (), time.monotonic() - 1)
        self.queue = [model_fixtures.chat('Blocked', finish='content_filter')]
        with self.assertRaisesRegex(MvpError, 'model_content_filtered'):
            ModelClient(registry).call(self.other, [])


class FailedSessionTests(task_fixtures.Fixture):
    def failed_api(self):
        self.models.write_text(json.dumps({'max_output_tokens': 8192, 'recovery_max_output_tokens': 32768, 'providers': {'other': {
            'kind': 'other', 'base_url': 'http://127.0.0.1:8317/v1', 'api_key_env': 'TEST_KEY',
            'wire_api': 'chat_completions', 'models': ['test-model'], 'effort_map': {'high': 'high'}}}}))
        registry = ModelRegistry(self.models)
        task = replace(self.parse(), models={'mode': 'api', 'primary': {
            'provider': 'other', 'model': 'test-model', 'effort': 'high'}, 'collaborators': []})
        store = self.store()
        ident = store.claim_desktop(self.source, self.target, self.issue, task,
                                    {'registry': {'providers': registry.providers, **registry.limits}})
        store.finish(ident, 'failed', 1, 'incomplete_model_response', False, 'retained')
        evidence = self.config.state_dir / 'runs' / task.request_id
        evidence.mkdir(parents=True)
        (evidence/'execution.json').write_text(json.dumps({'backend': 'api', 'session_id': task_fixtures.SID,
                                                          'model': 'test-model', 'effort': 'high'}))
        (evidence/'stdout.jsonl').write_text(json.dumps({'type': 'thread.started', 'thread_id': task_fixtures.SID})+'\n')
        (evidence/'context.json').write_text(json.dumps([{'role': 'user', 'content': 'retained review evidence'}]))
        return store, registry, evidence

    def test_explicit_recovery_registers_context_without_changing_old_task_or_delivery(self):
        store, registry, evidence = self.failed_api()
        before, delivery = dict(store.get(1)), dict(store.delivery(1))
        self.assertEqual(recover_api_session(store, self.config, registry, task_fixtures.RID), task_fixtures.SID)
        self.assertEqual(dict(store.get(1)), before)
        self.assertEqual(dict(store.delivery(1)), delivery)
        saved = store.db.execute('SELECT * FROM sessions').fetchone()
        self.assertEqual(saved['context_path'], str(evidence/'context.json'))
        self.assertEqual(recover_api_session(store, self.config, registry, task_fixtures.RID), task_fixtures.SID)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 1)

    def test_unknown_execution_and_incomplete_tool_history_are_not_registered(self):
        store, registry, evidence = self.failed_api()
        store.db.execute("UPDATE tasks SET error='process_cleanup_failed'")
        with self.assertRaisesRegex(MvpError, 'api_recovery_not_eligible'):
            recover_api_session(store, self.config, registry, task_fixtures.RID)
        store.db.execute("UPDATE tasks SET error='incomplete_model_response'")
        (evidence/'context.json').write_text(json.dumps([{'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'pending', 'function': {'name': 'write_file', 'arguments': '{}'}}]}]))
        with self.assertRaisesRegex(MvpError, 'incomplete_tool_sequence'):
            recover_api_session(store, self.config, registry, task_fixtures.RID)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)

    def test_different_wire_protocol_cannot_reinterpret_retained_history(self):
        store, registry, _ = self.failed_api()
        registry.providers['other'] = {**registry.providers['other'], 'wire_api': 'responses'}
        with self.assertRaisesRegex(MvpError, 'protocol_changed'):
            recover_api_session(store, self.config, registry, task_fixtures.RID)


if __name__ == '__main__':
    unittest.main()
