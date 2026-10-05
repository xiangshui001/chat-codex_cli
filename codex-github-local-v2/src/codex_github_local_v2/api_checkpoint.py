"""Restore pending API tool sequences without blindly replaying side effects."""
import hashlib
import json
from .model_api import tool_result


def ledger_path(evidence,call_id):
    return evidence/'tool-results'/(hashlib.sha256(call_id.encode()).hexdigest()+'.json')


def save_result(evidence,call_id,value):
    path=ledger_path(evidence,call_id)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)


def restore_pending(history,wire,evidence):
    pending={}
    for message in history:
        if wire=='chat_completions':
            for call in message.get('tool_calls',[]):pending[call['id']]=call['function']['name']
            if message.get('role')=='tool':pending.pop(message.get('tool_call_id'),None)
        else:
            if message.get('type')=='function_call':pending[message['call_id']]=message['name']
            if message.get('type')=='function_call_output':pending.pop(message.get('call_id'),None)
    for ident,name in pending.items():
        path=ledger_path(evidence,ident)
        value=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {
            'error':'previous_tool_outcome_unconfirmed',
            'instruction':'Inspect existing files and retained command outputs before deciding what remains. Do not blindly repeat an append, delete or command; its effects may already exist.',
            'tool':name}
        history.append(tool_result(wire,ident,value))
    return bool(pending)
