"""Loopback HTTP API and task-scoped stdio MCP bridge for model collaboration."""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys

from .model_api import Collaboration, CONSULT_TOOL, ModelRegistry
from .consultation_jobs import ConsultationJobs
from .mvp0 import fields, read_json
from .mvp0_runner import MvpError
from . import __version__



def handler(registry, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            payload = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def allowed(self):
            host = self.headers.get("Host", "")
            expected = {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}
            if host not in expected or self.headers.get("Origin"):
                self.reply(403, {"error": "local_client_required"})
                return False
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            if self.path == "/health":
                self.reply(200, {"status": "ok", "modes": ["gpt", "api", "gpt-led"]})
            elif self.path == "/v1/models":
                self.reply(200, {"providers": {name: {"kind": p["kind"], "models": p["models"],
                    "efforts": list(p["effort_map"])} for name, p in registry.providers.items()}})
            else:
                self.reply(404, {"error": "not_found"})

        def do_POST(self):
            self.connection.settimeout(None)
            if not self.allowed():
                return
            if self.path != "/v1/respond":
                self.reply(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or size <= 0:
                    self.reply(413, {"error": "invalid_request_size"})
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.reply(415, {"error": "json_required"})
                    return
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise MvpError("incomplete_request")
                data = read_json(raw.decode())
                fields(data, {"prompt", "models"})
                self.connection.settimeout(registry.limits["request_timeout"])
                result = Collaboration(registry, data["models"]).respond(data["prompt"])
                self.reply(200, result)
            except MvpError as exc:
                self.reply(400, {"error": str(exc)})
            except (ValueError, UnicodeError, TypeError):
                self.reply(400, {"error": "invalid_request"})
            except (OSError, TimeoutError):
                self.close_connection = True
            except Exception:
                self.reply(502, {"error": "model_service_failed"})

        def do_OPTIONS(self):
            self.reply(403, {"error": "local_client_required"})

    return Handler


def mcp_dispatch(message, collaboration):
    method, params = message.get("method"), message.get("params", {})
    if method == "initialize":
        version = params.get("protocolVersion", "2024-11-05")
        if version not in {"2024-11-05", "2025-03-26", "2025-06-18"}:
            version = "2025-06-18"
        return {"protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "codex-model-collaboration", "version": __version__}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": CONSULT_TOOL["name"], "description": CONSULT_TOOL["description"]
                          + (" Starts a background consultation; use get_consultation with its job_id for progress/results. No implicit time ceiling." if getattr(collaboration,'async_consultations',False) else '')
                          + " Configured collaborators: " + json.dumps(collaboration.options["collaborators"]),
                          "inputSchema": CONSULT_TOOL["parameters"],
                          "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}},
                          {"name":"get_consultation","description":"Get a background collaborator's current status or complete answer. Returns immediately.",
                           "inputSchema":{"type":"object","properties":{"job_id":{"type":"string"}},"required":["job_id"],"additionalProperties":False},
                           "annotations":{"readOnlyHint":True,"destructiveHint":False}}]}
    if method == "tools/call":
        try:
            fields(params, {"name", "arguments"}, {"_meta"})
            if params['name']=='get_consultation':
                fields(params['arguments'],{'job_id'})
                result=collaboration.jobs.get(params['arguments']['job_id'],{'error':'consultation_not_found'})
                return {"content":[{"type":"text","text":json.dumps(result,ensure_ascii=False)}]}
            if params["name"] != "consult_model":
                raise MvpError("model_tool_not_allowed")
            args = params["arguments"]
            fields(args, {"index", "prompt"})
            if getattr(collaboration,'async_consultations',False):
                import threading
                import uuid
                job_id=str(uuid.uuid4())
                result={'job_id':job_id,'status':'running'}
                if isinstance(collaboration.jobs,ConsultationJobs):
                    collaboration.jobs.start(job_id,result,args)
                else:collaboration.jobs[job_id]=result
                def invoke():
                    try:collaboration.jobs[job_id]={'job_id':job_id,'status':'completed',**collaboration.consult(args['index'],args['prompt'])}
                    except Exception as exc:collaboration.jobs[job_id]={'job_id':job_id,'status':'failed','error':str(exc) if isinstance(exc,MvpError) else 'collaboration_failed'}
                threading.Thread(target=invoke,daemon=True).start()
            else:result = collaboration.consult(args["index"], args["prompt"])
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except MvpError as exc:
            return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    raise MvpError("method_not_found")


def serve_stdio(collaboration, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    while True:
        line = stdin.readline()
        if not line:
            return
        msg = None
        try:
            msg = read_json(line)
            if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                raise MvpError("invalid_rpc_request")
            if "id" not in msg:
                continue
            result = mcp_dispatch(msg, collaboration)
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        except (MvpError, ValueError, TypeError) as exc:
            reply = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                     "error": {"code": -32601 if str(exc) == "method_not_found" else -32600,
                               "message": "invalid_rpc_request"}}
        stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        stdout.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-file", type=Path, required=True)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--task-options", type=Path)
    parser.add_argument("--jobs-dir", type=Path)
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--token-env", default="CODEX_COLLABORATION_TOKEN")
    args = parser.parse_args(argv)
    try:
        registry = ModelRegistry(args.models_file)
        if args.stdio:
            if args.task_options is None:
                raise MvpError("task_options_required")
            options = read_json(args.task_options.read_text(encoding="utf-8"))
            bridge = Collaboration(registry, options)
            bridge.async_consultations=True
            bridge.jobs=ConsultationJobs(args.jobs_dir or args.task_options.parent/'collaboration-jobs')
            if options["mode"] != "gpt-led" or options["primary"]["provider"] != "codex":
                raise MvpError("gpt_led_cli_required")
            serve_stdio(bridge)
        else:
            token = os.environ.get(args.token_env, "")
            if len(token) < 32 or not token.isascii():
                raise MvpError("local_api_token_required_min_32_ascii")
            if not 0 <= args.port <= 65535:
                raise MvpError("invalid_port")
            with ThreadingHTTPServer(("127.0.0.1", args.port), handler(registry, token)) as server:
                print("Model collaboration API: http://127.0.0.1:" + str(server.server_port), flush=True)
                server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 130
    except (MvpError, OSError) as exc:
        print(str(exc) if isinstance(exc, MvpError) else "local_api_start_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
