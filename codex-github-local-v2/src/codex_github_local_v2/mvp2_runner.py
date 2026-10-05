"""Persistent CLI sessions, and a file-tool agent for other API models."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

from .model_api import ModelClient, tool_result
from .api_recovery import ResponseRecovery
from .mvp0 import fields, read_json, text, write_path
from .mvp0_runner import CodexRunner, Execution, MvpError, utc_now
from .mvp2_contract import canonical_id


def cli_session_home():
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()


def validate_cli_session(session_id, workspace=None):
    """Reject unknown IDs before resume; Codex must not silently create a new chat."""
    canonical_id(session_id)
    found = None
    for directory in (cli_session_home() / "sessions", cli_session_home() / "archived_sessions"):
        if not directory.is_dir():
            continue
        for file in directory.rglob("*" + session_id + "*.jsonl"):
            if file.is_symlink():
                continue
            with file.open(encoding="utf-8") as stream:
                line = stream.readline(65537)
            try:
                meta = read_json(line)
            except MvpError:
                continue
            payload = meta.get("payload", {}) if isinstance(meta, dict) else {}
            if meta.get("type") == "session_meta" and payload.get("id") == session_id:
                found = payload
                break
    if found is None:
        raise MvpError("cli_session_not_found_on_this_host")
    if workspace is not None and Path(found.get("cwd", "")).resolve() != Path(workspace).resolve():
        raise MvpError("cli_session_workspace_mismatch")
    return found


def discover_session(evidence, expected=None):
    session_id = None
    with (evidence / "stdout.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            event = read_json(line)
            if event.get("type") == "thread.started":
                candidate = canonical_id(event.get("thread_id"))
                if session_id is not None and candidate != session_id:
                    raise MvpError("multiple_cli_sessions")
                session_id = candidate
    if not session_id or (expected is not None and session_id != expected):
        raise MvpError("cli_session_not_confirmed")
    return session_id


class SessionCodexRunner(CodexRunner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.control=lambda:[]
        self.ack=lambda *_:None

    def run(self,metadata,prompt,evidence,timeout,record):
        if metadata.get('transport')=='app_server':
            from .app_server_runner import AppServerRunner
            return AppServerRunner(self.control,self.ack).run(metadata,prompt,evidence,timeout,record)
        return super().run(metadata,prompt,evidence,timeout,record)

    def prepare_task(self, workspace, task, config, registry, options_path):
        metadata = super().prepare(workspace)
        chosen = task.models["primary"]
        # These overrides are generated here, never copied from an Issue's argv.
        overrides = ["-c", 'model_reasoning_effort=' + json.dumps(chosen["effort"]),
                     "-c", 'model_provider="openai"', "-c", 'sandbox_mode="workspace-write"',
                     "-c", "mcp_servers={}"]
        if task.models["mode"] == "gpt-led":
            args = ["-m", "codex_github_local_v2.collaboration_api", "--stdio", "--models-file",
                    str(config.models_file), "--task-options", str(options_path)]
            key_names = sorted({registry.resolve(c, "other")["api_key_env"] for c in task.models["collaborators"]})
            overrides += ["-c", "mcp_servers.collaborators.command=" + json.dumps(sys.executable),
                          "-c", "mcp_servers.collaborators.args=" + json.dumps(args),
                          "-c", "mcp_servers.collaborators.env_vars=" + json.dumps(key_names),
                          "-c", 'mcp_servers.collaborators.default_tools_approval_mode="auto"',
                          "-c", "mcp_servers.collaborators.required=true"]
        argv = [*self.command, "--ask-for-approval", "never", *overrides, "exec", "--json",
                "--color", "never", "--cd", str(workspace), "--model", chosen["model"]]
        if task.session["mode"] == "resume":
            # -C sets the root for this task even if the old chat was in another clone.
            validate_cli_session(task.session["id"])
            argv += ["resume", "--model", chosen["model"], task.session["id"]]
        argv += ["-"]
        metadata.update(argv=argv, mode=task.models["mode"], model=chosen["model"], effort=chosen["effort"])
        if config.full_access:
            overrides=[v.replace('sandbox_mode="workspace-write"','sandbox_mode="danger-full-access"') for v in overrides]
        metadata.update(argv=[*self.command,*overrides,'app-server','--listen','stdio://'],
                        transport='app_server',full_access=config.full_access,session_id=task.session.get('id'))
        return metadata


from .large_file_tools import FILE_TOOLS, RepositoryTools as FileTools


class ApiFileRunner:
    """The other-model mode never starts Codex or calls GPT."""
    def __init__(self, registry, client=None):
        self.registry, self.client = registry, client or ModelClient(registry)
        self.control=lambda:[]
        self.ack=lambda *_:None
        self.paths=lambda:None

    def run_task(self, task, workspace, evidence, timeout, record, history=None, session_id=None):
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        chosen = task.models["primary"]
        if session_id is None and (evidence/'execution.json').is_file():
            prior=read_json((evidence/'execution.json').read_text(encoding='utf-8'))
            if prior.get('backend')=='api':session_id=canonical_id(prior.get('session_id'))
        session_id = session_id or str(uuid.uuid4())
        history = list(history or [])
        from .api_checkpoint import restore_pending,save_result
        if history:restore_pending(history,self.registry.resolve(chosen)['wire_api'],evidence)
        history += [{"role": "system", "content": "Complete the user's task using repository tools. Run relevant commands and tests through run_command; report only observed results. "
            "The controller handles Git commits, PRs and Issue receipts after successful execution. "
            "Group independent tool calls in one response. Write requested artifacts before your final answer. "
            "If review coverage is incomplete, disclose exactly what was not reviewed in the report. "
            "This is the current workspace and current write authorization; previous turns do not grant extra paths. Allowed paths: "
            + json.dumps(task.write_paths)}, {"role": "user", "content": task.prompt}]
        received=[]
        def pulse():
            updated=self.paths()
            if updated is not None:files.write_paths=updated
            for msg in self.control():
                if msg['action']=='stop':self.ack(msg['id']);raise MvpError('cancelled_by_owner')
                if msg['action'] in {'say','allow','retry'}:
                    received.append(msg);self.ack(msg['id'])
        def append_received():
            if not received:return False
            for msg in received:
                history.append({'role':'user','content':msg['text'] if msg['action']=='say' else 'Continue with these authorized write paths: '+json.dumps(files.write_paths)})
                record('remote_instruction_applied',{'comment_id':msg['comment_id']})
            received.clear();return True
        files = FileTools(workspace, task.write_paths, evidence, pulse)
        deadline = time.monotonic() + timeout if timeout is not None else float("inf")
        log = evidence / "stdout.jsonl"
        def event(kind, **values):
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n")
        def checkpoint():
            path=evidence/'context.json'
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(history,ensure_ascii=False),encoding='utf-8')
            temporary.replace(path)
        metadata={"backend":"api","model":chosen['model'],"effort":chosen['effort'],"session_id":session_id,"started_at":utc_now()}
        (evidence/'execution.json').write_text(json.dumps(metadata),encoding='utf-8')
        checkpoint()
        event("thread.started", thread_id=session_id)
        record('remote_session_opened',{'session_id':session_id,'context_path':str(evidence/'context.json')})
        event("turn.started")
        turns_used = 0
        max_turns = self.registry.limits["max_turns"]
        recovery = ResponseRecovery(self.registry, record)
        recovery.pulse=pulse
        try:
            while max_turns is None or turns_used < max_turns:
                pulse();append_received();checkpoint()
                remaining = max_turns - turns_used if max_turns is not None else None
                if remaining is not None and remaining <= 3:
                    history.append({"role": "system", "content":
                        f"Only {remaining} model responses remain, including this one. "
                        "Finish required artifact writes now, then give your final answer without tool calls. "
                        "Prioritize delivery over further exploration; disclose incomplete coverage rather than invent findings."})
                turns_used += 1
                record('api_model_request', {'turn': turns_used, 'max_turns': max_turns})
                result = recovery.call(self.client, chosen, history, FILE_TOOLS, deadline)
                record('api_model_response', {'turn': turns_used, 'max_turns': max_turns})
                if recovery.continue_response(result, history, deadline):
                    checkpoint()
                    continue
                history.extend(result["history"])
                checkpoint()
                pulse()
                if received:
                    # New guidance arrived while HTTP waited. Do not execute stale tool requests.
                    for call in result['calls']:
                        history.append(tool_result(result['wire_api'],call['id'],{'error':'superseded_by_owner_instruction'}))
                    append_received();continue
                if not result["calls"]:
                    if not result["text"].strip():
                        raise MvpError("empty_model_response")
                    event("item.completed", item={"id": "final", "type": "agent_message", "text": result["text"]})
                    record('remote_agent_message',{'text':result['text'],'phase':'final_answer'})
                    event("turn.completed")
                    return Execution(0, None), session_id, history
                for index,call in enumerate(result["calls"]):
                    pulse()
                    if received:
                        for waiting in result['calls'][index:]:
                            history.append(tool_result(result['wire_api'],waiting['id'],{'error':'superseded_by_owner_instruction'}))
                        checkpoint();break
                    if time.monotonic() >= deadline:
                        raise MvpError("execution_timeout")
                    try:
                        arguments = read_json(call["arguments"])
                        save_result(evidence,call['id'],{'error':'tool_in_progress_at_last_checkpoint','tool':call['name'],'instruction':'Inspect existing files and outputs before repeating any side effect.'})
                        value = files.call(call["name"], arguments)
                    except (MvpError, OSError, UnicodeError) as exc:
                        if isinstance(exc,MvpError) and str(exc)=='cancelled_by_owner':raise
                        value = {"error": str(exc) if isinstance(exc, MvpError) else "file_tool_failed"}
                    save_result(evidence,call['id'],value)
                    record("api_file_tool", {"name": call["name"], "turn": turns_used,
                                             "max_turns": max_turns, "ok": "error" not in value,
                                             **({'path': arguments['path']} if 'error' not in value and 'path' in arguments else {}),
                                             **({"error": value["error"]} if "error" in value else {})})
                    history.append(tool_result(result["wire_api"], call["id"], value))
                    checkpoint()
                    if call["name"] in {"write_file", "delete_file"} and "error" not in value:
                        event("item.completed", item={"id": call["id"], "type": "file_change", "changes": [{"path": value["path"]}]})
            raise MvpError("model_turn_limit")
        except MvpError as exc:
            event("turn.failed", message=str(exc))
            return Execution(1, str(exc)), session_id, None
        finally:
            # Persist the full conversation even when the last request or command was interrupted.
            checkpoint()
            (evidence / "execution.json").write_text(json.dumps({"backend": "api", "model": chosen["model"],
                "effort": chosen["effort"], "session_id": session_id, "finished_at": utc_now(),
                "turns_used": turns_used, "max_turns": max_turns}), encoding="utf-8")
