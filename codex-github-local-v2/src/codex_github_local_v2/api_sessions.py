"""Explicit recovery of a failed file-agent conversation; never replay its task."""
import json

from .mvp0 import read_json
from .mvp0_runner import MvpError, utc_now
from .mvp2_contract import canonical_id
from .mvp2_runner import discover_session


def recover_api_session(store, config, registry, request_id):
    canonical_id(request_id, 'invalid_request_id')
    row = store.db.execute('SELECT * FROM tasks WHERE request_id=?', (request_id,)).fetchone()
    if row is None or row['state'] != 'failed' or row['host_id'] != config.host_id:
        raise MvpError('failed_api_task_required')
    options = json.loads(store.delivery(row['id'])['options_json'])
    if options['models']['mode'] != 'api' or row['error'] not in {
            'incomplete_model_response', 'empty_model_response', 'model_turn_limit', 'model_request_timeout',
            'model_transport_failed', 'invalid_model_response', 'invalid_model_tool_call', 'execution_timeout'}:
        raise MvpError('api_recovery_not_eligible')
    chosen = options['models']['primary']
    provider = registry.resolve(chosen, 'other')
    frozen = json.loads(store.delivery(row['id'])['config_snapshot'])['registry']['providers'][chosen['provider']]
    if provider['wire_api'] != frozen['wire_api']:
        raise MvpError('api_session_protocol_changed')
    evidence = config.state_dir / 'runs' / request_id
    for name in ('context.json', 'execution.json', 'stdout.jsonl'):
        path = evidence / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(config.state_dir.resolve()):
            raise MvpError('invalid_api_context')
    metadata = read_json((evidence / 'execution.json').read_text(encoding='utf-8'))
    session_id = canonical_id(metadata.get('session_id'))
    discover_session(evidence, session_id)
    if (metadata.get('backend'), metadata.get('model'), metadata.get('effort')) != ('api', chosen['model'], chosen['effort']):
        raise MvpError('api_session_metadata_mismatch')
    raw = (evidence / 'context.json').read_text(encoding='utf-8')
    history = read_json(raw)
    if not isinstance(history, list) or not history:
        raise MvpError('invalid_api_context')
    if provider['wire_api'] == 'chat_completions':
        pending = set()
        for message in history:
            if not isinstance(message, dict) or message.get('role') not in {'system', 'user', 'assistant', 'tool'}:
                raise MvpError('invalid_api_context')
            if message['role'] == 'tool':
                ident = message.get('tool_call_id')
                if ident not in pending:
                    raise MvpError('api_context_incomplete_tool_sequence')
                pending.remove(ident)
            else:
                if pending:
                    raise MvpError('api_context_incomplete_tool_sequence')
                if message['role'] == 'assistant':
                    calls = message.get('tool_calls', [])
                    if not isinstance(calls, list):
                        raise MvpError('invalid_api_context')
                    for call in calls:
                        ident = call.get('id') if isinstance(call, dict) else None
                        if not isinstance(ident, str) or ident in pending:
                            raise MvpError('invalid_api_context')
                        pending.add(ident)
        if pending:
            raise MvpError('api_context_incomplete_tool_sequence')
    elif any(not isinstance(item, dict) for item in history):
        raise MvpError('invalid_api_context')
    delivery = store.delivery(row['id'])
    binding = (delivery['target_id'], row['host_id'], chosen['provider'])
    with store.transaction():
        existing = store.db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if existing:
            if (existing['target_id'], existing['host_id'], existing['backend']) != binding:
                raise MvpError('session_binding_mismatch')
            return session_id
        # Diagnostic history is immutable; later successful resumes point to a new run's history.
        store.db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                         (session_id, *binding, str(evidence / 'context.json'), utc_now()))
        store.event(row['id'], 'api_session_recovered', {'session_id': session_id, 'message_count': len(history)})
    return session_id
