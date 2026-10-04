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

MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Authorization to another endpoint.


class ModelRegistry:
    def __init__(self, path: Path):
        data = read_json(path.read_text(encoding="utf-8"))
        fields(data, {"providers"}, {"max_turns", "max_calls", "request_timeout", "max_output_tokens"})
        self.providers = data["providers"]
        if not isinstance(self.providers, dict):
            raise MvpError("invalid_providers")
        self.limits = {}
        for key, default, upper in (("max_turns", 40, 50), ("max_calls", 8, 32),
                                    ("request_timeout", 120, 300), ("max_output_tokens", 8192, 32768)):
            val = data.get(key, default)
            if type(val) is not int or not 1 <= val <= upper:
                raise MvpError("invalid_model_limit")
            self.limits[key] = val
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

    def call(self, chosen, history, tools=(), *, timeout=None):
        provider = self.registry.resolve(chosen)
        key = os.environ.get(provider["api_key_env"])
        if not key:
            raise MvpError("model_api_key_missing")
        responses = provider["wire_api"] == "responses"
        payload = {"model": chosen["model"], "stream": False}
        if responses:
            payload.update(input=history, store=False, include=["reasoning.encrypted_content"],
                           max_output_tokens=self.registry.limits["max_output_tokens"])
        else:
            payload.update(messages=history, max_tokens=self.registry.limits["max_output_tokens"])
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
        except (URLError, OSError, UnicodeError, ValueError) as exc:
            raise MvpError("model_transport_failed") from None
        # No retry: a lost response may already have incurred a bill or produced a tool call.
        if not isinstance(data, dict) or data.get("error"):
            raise MvpError("invalid_model_response")
        if responses:
            if data.get("status") != "completed" or not isinstance(data.get("output"), list):
                raise MvpError("incomplete_model_response")
            items = data["output"]
            if any(not isinstance(i, dict) for i in items):
                raise MvpError("invalid_model_response")
            calls = [{"id": i.get("call_id"), "name": i.get("name"), "arguments": i.get("arguments")}
                     for i in items if i.get("type") == "function_call"]
            content = "\n".join(c.get("text", "") for i in items if i.get("type") == "message"
                                for c in i.get("content", []) if c.get("type") == "output_text")
            if any(not isinstance(c["id"], str) or not isinstance(c["name"], str) or not isinstance(c["arguments"], str) for c in calls):
                raise MvpError("invalid_model_tool_call")
            return {"text": content, "calls": calls, "history": items, "wire_api": "responses"}
        try:
            first = data["choices"][0]
            message = first["message"]
            if first.get("finish_reason") not in {"stop", "tool_calls"}:
                raise MvpError("incomplete_model_response")
            calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                     for c in message.get("tool_calls", [])]
            # Do not persist provider-specific reasoning text in local replay history.
            replay = {k: v for k, v in message.items() if k in {"role", "content", "tool_calls"}}
            if replay.get("role") != "assistant" or (message.get("content") is not None and not isinstance(message["content"], str)):
                raise ValueError()
            return {"text": message.get("content") or "", "calls": calls, "history": [replay], "wire_api": "chat_completions"}
        except (KeyError, IndexError, TypeError, ValueError):
            raise MvpError("invalid_model_response") from None


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
        if self.calls >= self.registry.limits["max_calls"]:
            raise MvpError("collaboration_call_limit")
        self.calls += 1
        chosen = self.options["collaborators"][index]
        result = self.client.call(chosen, [{"role": "user", "content": prompt}], timeout=timeout)
        if result["calls"] or not result["text"].strip():
            raise MvpError("invalid_consultation_response")
        self.record("model_consulted", {**chosen, "index": index})
        return {"model": chosen["model"], "text": result["text"][:24000]}

    def respond(self, prompt):
        prompt = text(prompt, 24000, "invalid_prompt")
        history = [{"role": "system", "content": "You lead this task. External model replies are advice; decide and synthesize the final answer yourself."},
                   {"role": "user", "content": prompt}]
        deadline = time.monotonic() + self.registry.limits["request_timeout"]
        tools = [CONSULT_TOOL] if self.options["mode"] == "gpt-led" else []
        for _ in range(self.registry.limits["max_turns"]):
            result = self.client.call(self.options["primary"], history, tools, timeout=deadline-time.monotonic())
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
