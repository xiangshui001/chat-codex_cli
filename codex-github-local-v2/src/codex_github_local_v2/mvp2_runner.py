"""Persistent CLI sessions, and a file-tool agent for other API models."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

from .model_api import ModelClient, tool_result
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
                          "-c", "mcp_servers.collaborators.required=true",
                          "-c", "mcp_servers.collaborators.tool_timeout_sec=" + str(registry.limits["request_timeout"])]
        argv = [*self.command, "--ask-for-approval", "never", *overrides, "exec", "--json",
                "--color", "never", "--cd", str(workspace), "--model", chosen["model"]]
        if task.session["mode"] == "resume":
            # -C sets the root for this task even if the old chat was in another clone.
            validate_cli_session(task.session["id"])
            argv += ["resume", "--model", chosen["model"], task.session["id"]]
        argv += ["-"]
        metadata.update(argv=argv, mode=task.models["mode"], model=chosen["model"], effort=chosen["effort"])
        return metadata


FILE_TOOLS = [
    {"name": "list_files", "description": "List up to 300 repository files; Git internals and secrets are excluded.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "read_file", "description": "Read one UTF-8 repository file (maximum 64 KiB).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "write_file", "description": "Write one UTF-8 file inside the authorized write paths (maximum 64 KiB).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"], "additionalProperties": False}},
    {"name": "delete_file", "description": "Delete one regular file inside the authorized write paths.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
]


class FileTools:
    def __init__(self, workspace, write_paths):
        self.workspace = Path(workspace).resolve()
        self.write_paths = write_paths

    def path(self, raw, *, write=False):
        name = write_path(raw)
        parts = Path(name).parts
        if any(p.startswith(".env") or p.lower() in {"auth.json", "credentials", "credentials.json"} for p in parts):
            raise MvpError("secret_file_not_allowed")
        dest = self.workspace / name
        if not dest.resolve().is_relative_to(self.workspace):
            raise MvpError("tool_path_escape")
        for p in (dest, *dest.parents):
            if p == self.workspace:
                break
            if p.is_symlink():
                raise MvpError("symlink_tool_path")
        if write and not any(name == scope.rstrip("/") or (scope.endswith("/") and name.startswith(scope)) for scope in self.write_paths):
            raise MvpError("write_scope_violation")
        return dest

    def call(self, name, args):
        if name == "list_files":
            fields(args, set())
            # Do not traverse .git, symlinks, dependency trees or hidden secret directories.
            files = []
            for base, dirs, names in os.walk(self.workspace, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "venv"}
                                 and not (Path(base) / d).is_symlink())
                for item in sorted(names):
                    path = (Path(base) / item).relative_to(self.workspace).as_posix()
                    try:
                        self.path(path)
                    except MvpError:
                        continue
                    files.append(path)
                    if len(files) >= 300:
                        return {"files": files, "truncated": True}
            return {"files": files, "truncated": False}
        if name not in {"read_file", "write_file", "delete_file"}:
            raise MvpError("model_tool_not_allowed")
        fields(args, {"path", "content"} if name == "write_file" else {"path"})
        path = self.path(args["path"], write=name != "read_file")
        if name == "read_file":
            if not path.is_file() or path.stat().st_size > 65536:
                raise MvpError("file_missing_or_too_large")
            return {"content": path.read_text(encoding="utf-8")}
        if name == "write_file":
            content = args["content"]
            if not isinstance(content, str) or len(content.encode()) > 65536:
                raise MvpError("invalid_file_content")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        else:
            if not path.is_file():
                raise MvpError("regular_file_required")
            path.unlink()
        return {"path": args["path"], "status": "ok"}


class ApiFileRunner:
    """The other-model mode never starts Codex or calls GPT."""
    def __init__(self, registry, client=None):
        self.registry, self.client = registry, client or ModelClient(registry)

    def run_task(self, task, workspace, evidence, timeout, record, history=None, session_id=None):
        evidence.mkdir(parents=True, exist_ok=False, mode=0o700)
        chosen = task.models["primary"]
        session_id = session_id or str(uuid.uuid4())
        history = list(history or [])
        history += [{"role": "system", "content": "Complete the user's task using repository file tools. Do not claim tests ran. "
            "The controller handles Git commits, PRs and Issue receipts after successful execution. "
            "Group independent tool calls in one response. Write requested artifacts before your final answer. "
            "If review coverage is incomplete, disclose exactly what was not reviewed in the report. "
            "This is the current workspace and current write authorization; previous turns do not grant extra paths. Allowed paths: "
            + json.dumps(task.write_paths)}, {"role": "user", "content": task.prompt}]
        files = FileTools(workspace, task.write_paths)
        deadline = time.monotonic() + timeout
        log = evidence / "stdout.jsonl"
        def event(kind, **values):
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n")
        event("thread.started", thread_id=session_id)
        event("turn.started")
        turns_used = 0
        max_turns = self.registry.limits["max_turns"]
        try:
            while max_turns is None or turns_used < max_turns:
                remaining = max_turns - turns_used if max_turns is not None else None
                if remaining is not None and remaining <= 3:
                    history.append({"role": "system", "content":
                        f"Only {remaining} model responses remain, including this one. "
                        "Finish required artifact writes now, then give your final answer without tool calls. "
                        "Prioritize delivery over further exploration; disclose incomplete coverage rather than invent findings."})
                turns_used += 1
                record('api_model_request', {'turn': turns_used, 'max_turns': max_turns})
                result = self.client.call(chosen, history, FILE_TOOLS, timeout=deadline-time.monotonic())
                record('api_model_response', {'turn': turns_used, 'max_turns': max_turns})
                history.extend(result["history"])
                if len(json.dumps(history, ensure_ascii=False).encode()) > 1024 * 1024:
                    raise MvpError("api_context_limit")
                if not result["calls"]:
                    if not result["text"].strip():
                        raise MvpError("empty_model_response")
                    event("item.completed", item={"id": "final", "type": "agent_message", "text": result["text"]})
                    event("turn.completed")
                    return Execution(0, None), session_id, history
                for call in result["calls"]:
                    if time.monotonic() >= deadline:
                        raise MvpError("execution_timeout")
                    try:
                        arguments = read_json(call["arguments"])
                        value = files.call(call["name"], arguments)
                    except (MvpError, OSError, UnicodeError) as exc:
                        value = {"error": str(exc) if isinstance(exc, MvpError) else "file_tool_failed"}
                    record("api_file_tool", {"name": call["name"], "turn": turns_used,
                                             "max_turns": max_turns, "ok": "error" not in value,
                                             **({'path': arguments['path']} if 'error' not in value and 'path' in arguments else {}),
                                             **({"error": value["error"]} if "error" in value else {})})
                    history.append(tool_result(result["wire_api"], call["id"], value))
                    if call["name"] in {"write_file", "delete_file"} and "error" not in value:
                        event("item.completed", item={"id": call["id"], "type": "file_change", "changes": [{"path": value["path"]}]})
            raise MvpError("model_turn_limit")
        except MvpError as exc:
            event("turn.failed", message=str(exc))
            return Execution(1, str(exc)), session_id, None
        finally:
            # Private diagnostic history; failed sessions remain ineligible for automatic resume.
            context = json.dumps(history, ensure_ascii=False)
            if len(context.encode()) <= 1024 * 1024:
                (evidence / "context.json").write_text(context, encoding="utf-8")
            (evidence / "execution.json").write_text(json.dumps({"backend": "api", "model": chosen["model"],
                "effort": chosen["effort"], "session_id": session_id, "finished_at": utc_now(),
                "turns_used": turns_used, "max_turns": max_turns}), encoding="utf-8")
