"""Loopback-only HTTP/Core smoke harness, never a production GitHub writer.

HTTP and runtime persistence are real. The source simulates GitHub delivery and
the model probe is deterministic. Synthetic GH IDs are internal test envelopes;
API receipts expose no GitHub identity or URL. All state must be isolated.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .control import (
    ControlCommand, ControlError, ControlLedger, ControlProcessor,
    RuntimeControlService, RuntimeSettingsStore, _atomic_json,
)
from .github_protocol import CommentView, IssueView
from .locking import single_instance_lock
from .model_adapter import ModelRole, ProbeResult
from .contract import ModelChoice

OWNER = "local-smoke"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeterministicProbe:
    def __call__(self, role: ModelRole, choice: ModelChoice) -> ProbeResult:
        return ProbeResult(choice.name in ("auto", "deterministic-test"),
                           f"local-smoke deterministic {role} probe; no model API called")


class LocalSmokeSource:
    """Durable deterministic GitHub-source substitute, only for isolated smoke."""

    def __init__(self, root: Path, repository: str):
        self.root = root
        self.repository = repository
        self.path = root / "local-controls.json"

    def load(self):
        if not self.path.exists():
            return {"requests": {}, "fail_next_receipt": False}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def event(self, kind: str, **details):
        with (self.root / "harness-events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": now(), "event": kind, **details}, ensure_ascii=False) + "\n")

    def register(self, request):
        if not isinstance(request, dict) or set(request) != {"request_id", "repository", "intent"}:
            raise ControlError("request requires request_id, repository and intent")
        request_id = request["request_id"]
        if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in request_id)):
            raise ControlError("invalid request_id")
        if request["repository"] != self.repository:
            raise ControlError("repository mismatch")
        if not isinstance(request["intent"], dict) or "id" in request["intent"]:
            raise ControlError("intent must not assign a control ID")
        data = self.load()
        existing = data["requests"].get(request_id)
        if existing:
            if existing["request"] != request:
                raise ControlError("request_id reused with different content")
            return existing
        number = len(data["requests"]) + 1
        envelope = {"version": 2, "repository": self.repository,
                    "control": {**request["intent"], "id": f"GH-{number}"}}
        command = ControlCommand.from_dict(envelope)
        timestamp = now()
        row = {"request": request, "number": number, "action": command.action,
               "comments": [asdict(CommentView(number, OWNER, timestamp, timestamp,
                    "/codex-local control\n~~~json\n" + json.dumps(envelope) + "\n~~~"))]}
        data["requests"][request_id] = row
        _atomic_json(self.path, data)
        self.event("control_received", request_id=request_id, intent=request["intent"],
                   backend="local-smoke")
        return row

    def list_open_control_issues(self):
        return [IssueView(row["number"], "[codex-control] " + row["action"], "open", OWNER)
                for row in self.load()["requests"].values()]

    def list_comments(self, issue_number):
        for row in self.load()["requests"].values():
            if row["number"] == issue_number:
                return [CommentView(**comment) for comment in row["comments"]]
        return []

    def post_comment(self, issue_number, body):
        data = self.load()
        if data["fail_next_receipt"]:
            data["fail_next_receipt"] = False
            _atomic_json(self.path, data)
            self.event("receipt_delivery_failed", number=issue_number)
            raise OSError("local-smoke injected receipt delivery failure")
        row = next(row for row in data["requests"].values() if row["number"] == issue_number)
        timestamp = now()
        row["comments"].append(asdict(CommentView(10000 + issue_number, OWNER, timestamp, timestamp, body)))
        _atomic_json(self.path, data)
        self.event("receipt_delivered", number=issue_number, body=body)


class Harness:
    def __init__(self, state_dir: Path, repository: str):
        state_dir.mkdir(parents=True, exist_ok=True)
        marker = state_dir / "harness-smoke.json"
        identity = {"mode": "local-smoke", "repository": repository}
        if marker.exists():
            if json.loads(marker.read_text()) != identity:
                raise ValueError("smoke state identity mismatch")
        else:
            if any(path.name != "control.lock" for path in state_dir.iterdir()):
                raise ValueError("refusing existing non-smoke state; use a dedicated empty directory")
            _atomic_json(marker, identity)
        self.repository = repository
        self.source = LocalSmokeSource(state_dir, repository)
        self.store = RuntimeSettingsStore(state_dir / "runtime-settings.json")
        self.ledger = ControlLedger(state_dir / "control-ledger.json")
        self.processor = ControlProcessor(
            repository=repository, authorized_users=[OWNER], source=self.source,
            runtime=RuntimeControlService(self.store, DeterministicProbe()), ledger=self.ledger,
        )
        self.ledger.pending_receipts()  # Fail closed before serving an invalid ledger.

    def runtime(self):
        return {"settings": self.store.load().to_dict(), "controller_state": "online",
                "current_task_id": None, "current_host_id": None, "observed_at": now(),
                "data_origin": "live", "execution_mode": "local-smoke"}

    def advance(self):
        try:
            result = self.processor.tick()
            self.source.event("core_tick", status=result.status, number=result.issue_number,
                              settings=self.store.load().to_dict())
            return None
        except OSError as exc:
            self.source.event("delivery_error", error=str(exc))
            return str(exc)

    def receipt(self, request_id: str, error=None):
        request = self.source.load()["requests"].get(request_id)
        if request is None:
            raise KeyError("unknown request_id")
        row = self.ledger.get(f"GH-{request['number']}")
        outcome = "pending"
        if row and row["delivered_at"] is not None:
            outcome = row["outcome"]
        elif error:
            outcome = "unknown"
        return {"request_id": request_id, "control_id": None, "issue_url": None,
                "outcome": outcome, "settings": None,
                "message": "[local-smoke] " + (error or (row["message"] if row else "queued"))}

    def get(self, path):
        if path == "/api/v2/session":
            pending = next((row["request"] for row in self.source.load()["requests"].values()
                            if (self.ledger.get(f"GH-{row['number']}") or {}).get("delivered_at") is None), None)
            return {"repository": self.repository, "role": "owner",
                    "capabilities": ["runtime:read", "control:write", "tasks:read", "hosts:read"],
                    "data_origin": "live", "execution_mode": "local-smoke", "pending_control": pending}
        if path == "/api/v2/runtime":
            return self.runtime()
        if path in ("/api/v2/tasks", "/api/v2/hosts"):
            return []  # No fabricated tasks or online hosts.
        if path == "/api/v2/models":
            return [{"id": "deterministic-test", "label": "Local deterministic probe",
                     "note": "本地确定性验证，不调用真实模型"}]
        prefix = "/api/v2/controls/"
        if path.startswith(prefix):
            request_id = unquote(path[len(prefix):])
            if request_id not in self.source.load()["requests"]:
                raise KeyError("unknown request_id")
            return self.receipt(request_id, self.advance())
        raise KeyError("API route not found")

    def submit(self, request):
        self.source.register(request)
        return self.receipt(request["request_id"], self.advance())


def create_server(harness: Harness, dist: Path, port: int) -> HTTPServer:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist), **kwargs)

        def log_message(self, format, *args):
            pass

        def reply(self, code, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            host = self.headers.get("Host", "")
            valid = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            return (host in valid and self.headers.get("X-Chat-Codex-Local") == "1"
                    and (origin is None or origin == f"http://{host}"))

        def api(self, action):
            if not self.allowed():
                self.reply(403, {"error": {"code": "forbidden", "message": "loopback same-origin smoke client required"}})
                return
            try:
                self.reply(200, action())
            except KeyError:
                self.reply(404, {"error": {"code": "not_found", "message": "API item not found"}})
            except (ControlError, ValueError) as exc:
                self.reply(400, {"error": {"code": "conflict", "message": str(exc)}})
            except Exception as exc:
                harness.source.event("api_error", error=type(exc).__name__)
                self.reply(503, {"error": {"code": "unavailable", "message": "local harness failed; inspect local evidence"}})

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                self.api(lambda: harness.get(path))
            else:
                super().do_GET()

        def do_POST(self):
            def submit():
                if urlsplit(self.path).path != "/api/v2/controls":
                    raise KeyError("route not found")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384 or self.headers.get_content_type() != "application/json":
                    raise ValueError("bounded application/json body required")
                return harness.submit(json.loads(self.rfile.read(size)))
            self.api(submit)

    return HTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Isolated local HTTP/core smoke harness; no real model/GitHub writes")
    parser.add_argument("--mode", choices=["local-smoke"], required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--repository", default="local/smoke")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--fail-first-receipt", action="store_true", help="explicit deterministic fault injection")
    args = parser.parse_args(argv)
    if not (args.dist / "index.html").is_file():
        parser.error("--dist must point to a production frontend build")
    harness = Harness(args.state_dir.expanduser().resolve(), args.repository)
    with single_instance_lock(args.state_dir.expanduser() / "control.lock"):
        if args.fail_first_receipt:
            data = harness.source.load()
            data["fail_next_receipt"] = True
            _atomic_json(harness.source.path, data)
        server = create_server(harness, args.dist.resolve(), args.port)
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/?harness=local-smoke",
                          "mode": "local-smoke", "models": "deterministic", "github": "local substitute"}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
