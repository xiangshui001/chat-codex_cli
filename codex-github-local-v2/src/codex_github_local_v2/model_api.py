"""Bounded OpenAI-compatible model calls and GPT-directed consultation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .mvp0 import fields, read_json, text
from .mvp0_runner import MvpError
from .mvp2_contract import NAME, model_options, selection
from .api_recovery import ResponseRecovery

MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Authorization to another endpoint.


class ModelRegistry:
    def __init__(self, path: Path):
        data = read_json(path.read_text(encoding="utf-8"))
        fields(data, {"providers"}, {"max_turns", "max_calls", "request_timeout", "max_output_tokens", "recovery_max_output_tokens"})
        self.providers = data["providers"]
        if not isinstance(self.providers, dict):
            raise MvpError("invalid_providers")
        self.limits = {}
        for key in ('max_turns', 'max_calls'):
            val = data.get(key)
            if val is not None and (type(val) is not int or val < 1):
                raise MvpError('invalid_model_limit')
            self.limits[key] = val  # null/omitted: no operation-count limit.
        for key, default, upper in (("request_timeout", 600, 3600), ("max_output_tokens", 8192, 32768),
                                    ("recovery_max_output_tokens", 32768, 32768)):
            val = data.get(key, default)
            if type(val) is not int or not 1 <= val <= upper:
                raise MvpError("invalid_model_limit")
            self.limits[key] = val
        if self.limits['recovery_max_output_tokens'] < self.limits['max_output_tokens']:
            raise MvpError('invalid_model_limit')
        for name, provider in self.providers.items():
            if not NAME.fullmatch(name) or name == "codex":
                raise MvpError("invalid_provider_name")
            fields(provider, {"kind", "base_url", "api_key_env", "models", "wire_api", "effort_map"},
                   {"reasoning_parameter"})
            url = urlsplit(text(provider["base_url"], 2048, "invalid_provider_url"))
            if (url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password
                    or url.query or url.fragment or
                    (url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"})):
                raise MvpError("invalid_provider_url")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", text(provider["api_key_env"], 128, "invalid_key_env")):
                raise MvpError("invalid_key_env")
            if text(provider["kind"], 16, "invalid_provider_protocol") not in {"gpt", "other"} or text(provider["wire_api"], 32, "invalid_provider_protocol") not in {"responses", "chat_completions"}:
                raise MvpError("invalid_provider_protocol")
            models = provider["models"]
            if not isinstance(models, list) or not models or any(not isinstance(m, str) or not NAME.fullmatch(m) for m in models):
                raise MvpError("invalid_provider_models")
            mapping = provider["effort_map"]
            if not isinstance(mapping, dict) or not mapping or any(
                    not isinstance(k, str) or not isinstance(v, (str, int, bool, type(None))) for k, v in mapping.items()):
                raise MvpError("invalid_effort_map")
            param = provider.get("reasoning_parameter", "reasoning.effort" if provider["wire_api"] == "responses" else "reasoning_effort")
            if not isinstance(param, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}", param):
                raise MvpError("invalid_reasoning_parameter")
            # Only the dedicated reasoning field may be assigned; no override of model/tools/input.
            if param.split(".")[0] in {"model", "tools", "input", "messages", "stream", "store"}:
                raise MvpError("invalid_reasoning_parameter")
            provider["reasoning_parameter"] = param

    def resolve(self, chosen, kind=None):
        chosen = selection(chosen)
        p = self.providers.get(chosen["provider"])
        if p is None or (kind is not None and p["kind"] != kind):
            raise MvpError("provider_not_allowed")
        if chosen["model"] not in p["models"]:
            raise MvpError("model_not_allowed")
        if chosen["effort"] not in p["effort_map"]:
            raise MvpError("effort_not_supported")
        return p

    def validate(self, options, *, cli=False, require_keys=True):
        options = model_options(options, cli=cli)
        choices = [(options["primary"], "other" if options["mode"] == "api" else "gpt")]
        choices += [(c, "other") for c in options["collaborators"]]
        for chosen, kind in choices:
            if cli and chosen["provider"] == "codex":
                continue
            p = self.resolve(chosen, kind)
            if require_keys and not os.environ.get(p["api_key_env"]):
                raise MvpError("model_api_key_missing")
        return options


class ModelClient:
    def __init__(self, registry, *, opener=None):
        self.registry = registry
        self.opener = opener or build_opener(NoRedirect())

    def call(self, chosen, history, tools=(), *, timeout=None, max_output_tokens=None):
        provider = self.registry.resolve(chosen)
        key = os.environ.get(provider["api_key_env"])
        if not key:
            raise MvpError("model_api_key_missing")
        responses = provider["wire_api"] == "responses"
        payload = {"model": chosen["model"], "stream": False}
        output_limit = max_output_tokens if max_output_tokens is not None else self.registry.limits['max_output_tokens']
        if type(output_limit) is not int or not 1 <= output_limit <= self.registry.limits['recovery_max_output_tokens']:
            raise MvpError('invalid_model_limit')
        if responses:
            payload.update(input=history, store=False, include=["reasoning.encrypted_content"],
                           max_output_tokens=output_limit)
        else:
            payload.update(messages=history, max_tokens=output_limit)
        mapped = provider["effort_map"][chosen["effort"]]
        if mapped is not None:
            obj = payload
            parts = provider["reasoning_parameter"].split(".")
            for part in parts[:-1]:
                obj = obj.setdefault(part, {})
            obj[parts[-1]] = mapped
        if tools:
            payload["tools"] = [{"type": "function", **t} if responses else {"type": "function", "function": t} for t in tools]
        url = provider["base_url"].rstrip("/") + ("/responses" if responses else "/chat/completions")
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
        deadline = min(timeout if timeout is not None else self.registry.limits["request_timeout"], self.registry.limits["request_timeout"])
        if deadline <= 0:
            raise MvpError("execution_timeout")
        try:
            with self.opener.open(request, timeout=deadline) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise MvpError("model_response_too_large")
            data = read_json(raw.decode("utf-8"))
        except HTTPError as exc:
            raise MvpError("model_http_" + str(exc.code)) from None
        except TimeoutError:
            raise MvpError('model_request_timeout') from None
        except URLError as exc:
            raise MvpError('model_request_timeout' if isinstance(exc.reason, TimeoutError) else 'model_transport_failed') from None
        except (OSError, UnicodeError, ValueError) as exc:
            raise MvpError("model_transport_failed") from None
        # No retry: a lost response may already have incurred a bill or produced a tool call.
        if not isinstance(data, dict) or data.get("error"):
            raise MvpError("invalid_model_response")
        if responses:
            if not isinstance(data.get("output"), list):
                raise MvpError("incomplete_model_response")
            items = data["output"]
            if any(not isinstance(i, dict) for i in items):
                raise MvpError("invalid_model_response")
            for item in items:
                if item.get('type') == 'message':
                    content_items = item.get('content', [])
                    if not isinstance(content_items, list) or any(not isinstance(c, dict) or (
                            c.get('type') == 'output_text' and not isinstance(c.get('text'), str)) for c in content_items):
                        raise MvpError('invalid_model_response')
            calls = [{"id": i.get("call_id"), "name": i.get("name"), "arguments": i.get("arguments")}
                     for i in items if i.get("type") == "function_call"]
            content = "\n".join(c.get("text", "") for i in items if i.get("type") == "message"
                                for c in i.get("content", []) if c.get("type") == "output_text")
            if data.get('status') != 'completed' or any(i.get('status') in {'in_progress', 'incomplete'} for i in items):
                details = data.get('incomplete_details') or {}
                reason = details.get('reason') if isinstance(details, dict) else None
                if reason == 'content_filter':
                    raise MvpError('model_content_filtered')
                return partial_response(content, 'output_limit' if reason == 'max_output_tokens' else 'incomplete_status', 'responses')
            if any(not isinstance(c["id"], str) or not isinstance(c["name"], str) or not isinstance(c["arguments"], str) for c in calls):
                raise MvpError("invalid_model_tool_call")
            return {"text": content, "calls": calls, "history": items, "wire_api": "responses"}
        try:
            first = data["choices"][0]
            message = first["message"]
            if message.get('role') != 'assistant' or (message.get('content') is not None and not isinstance(message['content'], str)):
                raise ValueError()
            if first.get('finish_reason') == 'content_filter':
                raise MvpError('model_content_filtered')
            if first.get("finish_reason") not in {"stop", "tool_calls"}:
                reason = 'output_limit' if first.get('finish_reason') == 'length' else (
                    'missing_finish_reason' if first.get('finish_reason') is None else 'unexpected_finish_reason')
                return partial_response(message.get('content') or '', reason, 'chat_completions')
            calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                     for c in message.get("tool_calls", [])]
            # Do not persist provider-specific reasoning text in local replay history.
            replay = {k: v for k, v in message.items() if k in {"role", "content", "tool_calls"}}
            if replay.get("role") != "assistant" or (message.get("content") is not None and not isinstance(message["content"], str)):
                raise ValueError()
            return {"text": message.get("content") or "", "calls": calls, "history": [replay], "wire_api": "chat_completions"}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise MvpError("invalid_model_response") from None


def partial_response(content, reason, wire):
    # Never replay or execute tool calls from an incomplete response, even if a fragment parses.
    history = ([{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': content}]}]
               if wire == 'responses' else [{'role': 'assistant', 'content': content}]) if content else []
    return {'text': content, 'calls': [], 'history': history, 'wire_api': wire, 'incomplete_reason': reason}


def tool_result(wire, call_id, value):
    content = json.dumps(value, ensure_ascii=False)
    return ({"type": "function_call_output", "call_id": call_id, "output": content} if wire == "responses"
            else {"role": "tool", "tool_call_id": call_id, "content": content})


CONSULT_TOOL = {"name": "consult_model", "description": "Assign a focused question to one of the configured external models. The GPT leader evaluates its answer.",
    "parameters": {"type": "object", "properties": {"index": {"type": "integer"}, "prompt": {"type": "string"}},
                   "required": ["index", "prompt"], "additionalProperties": False}}


class Collaboration:
    def __init__(self, registry, options, *, client=None, record=lambda *_: None):
        self.registry, self.options = registry, registry.validate(options, cli=options["primary"]["provider"] == "codex")
        self.client, self.record = client or ModelClient(registry), record
        self.calls = 0

    def consult(self, index, prompt, *, timeout=None):
        if type(index) is not int or not 0 <= index < len(self.options["collaborators"]):
            raise MvpError("collaborator_not_allowed")
        prompt = text(prompt, 24000, "invalid_consultation_prompt")
        limit = self.registry.limits['max_calls']
        if limit is not None and self.calls >= limit:
            raise MvpError("collaboration_call_limit")
        self.calls += 1
        chosen = self.options["collaborators"][index]
        history = [{"role": "user", "content": prompt}]
        deadline = time.monotonic() + min(timeout if timeout is not None else self.registry.limits['request_timeout'],
                                          self.registry.limits['request_timeout'])
        recovery = ResponseRecovery(self.registry, self.record)
        turns = 0
        limit = self.registry.limits['max_turns']
        while limit is None or turns < limit:
            turns += 1
            result = recovery.call(self.client, chosen, history, (), deadline)
            if recovery.continue_response(result, history, deadline):
                continue
            if result['calls']:
                raise MvpError('invalid_consultation_response')
            self.record("model_consulted", {**chosen, "index": index})
            return {"model": chosen["model"], "text": result["text"][:24000]}
        raise MvpError('model_turn_limit')

    def respond(self, prompt):
        prompt = text(prompt, 24000, "invalid_prompt")
        history = [{"role": "system", "content": "You lead this task. External model replies are advice; decide and synthesize the final answer yourself."},
                   {"role": "user", "content": prompt}]
        deadline = time.monotonic() + self.registry.limits["request_timeout"]
        tools = [CONSULT_TOOL] if self.options["mode"] == "gpt-led" else []
        turns = 0
        limit = self.registry.limits['max_turns']
        recovery = ResponseRecovery(self.registry, self.record)
        while limit is None or turns < limit:
            turns += 1
            result = recovery.call(self.client, self.options["primary"], history, tools, deadline)
            if recovery.continue_response(result, history, deadline):
                continue
            history.extend(result["history"])
            if not result["calls"]:
                if not result["text"].strip():
                    raise MvpError("empty_model_response")
                return {"mode": self.options["mode"], "model": self.options["primary"]["model"],
                        "text": result["text"], "collaboration_calls": self.calls}
            for call in result["calls"]:
                if call["name"] != "consult_model" or not tools:
                    raise MvpError("model_tool_not_allowed")
                args = read_json(call["arguments"])
                fields(args, {"index", "prompt"})
                value = self.consult(args["index"], args["prompt"], timeout=deadline-time.monotonic())
                history.append(tool_result(result["wire_api"], call["id"], value))
        raise MvpError("model_turn_limit")
