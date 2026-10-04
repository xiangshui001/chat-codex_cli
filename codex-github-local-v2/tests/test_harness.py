import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.control import ControlCommand, RuntimeSettings
from codex_github_local_v2.harness import Harness, create_server


class HarnessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.root = root / "smoke"
        self.dist = root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("frontend")
        self.harness = Harness(self.root, "local/smoke")
        self.server = create_server(self.harness, self.dist, 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, body=None, *, headers=None):
        request = Request(self.base + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"X-Chat-Codex-Local": "1", "Content-Type": "application/json",
                                   **(headers or {})})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def control(self, action="pause", request_id="test-1", **extra):
        return {"request_id": request_id, "repository": "local/smoke",
                "intent": {"action": action, **extra}}

    def test_http_control_calls_core_and_persists_actual_state(self):
        self.assertFalse(self.request("/api/v2/runtime")["settings"]["paused"])
        receipt = self.request("/api/v2/controls", self.control())
        self.assertEqual(receipt["outcome"], "applied")
        self.assertIsNone(receipt["control_id"])
        self.assertEqual(self.harness.store.load().revision, 1)
        self.assertTrue(self.harness.store.load().paused)
        self.assertEqual(self.request("/api/v2/session")["execution_mode"], "local-smoke")

    def test_repeat_request_and_conflicting_identity(self):
        request = self.control()
        first = self.request("/api/v2/controls", request)
        self.assertEqual(self.request("/api/v2/controls", request), first)
        self.assertEqual(self.harness.store.load().revision, 1)
        with self.assertRaises(HTTPError) as exc:
            self.request("/api/v2/controls", self.control("resume"))
        self.assertEqual(exc.exception.code, 400)
        self.assertTrue(self.harness.store.load().paused)

    def test_receipt_failure_reconnect_recovers_without_reapplying(self):
        data = self.harness.source.load()
        data["fail_next_receipt"] = True
        self.harness.source.path.write_text(json.dumps(data))
        request = self.control()
        self.assertEqual(self.request("/api/v2/controls", request)["outcome"], "unknown")
        before = self.harness.store.path.read_bytes()
        self.assertEqual(self.request("/api/v2/session")["pending_control"], request)
        restarted = Harness(self.root, "local/smoke")
        result = restarted.get("/api/v2/controls/test-1")
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(restarted.store.path.read_bytes(), before)
        self.assertIsNone(restarted.get("/api/v2/session")["pending_control"])
        self.assertEqual(len(restarted.source.list_comments(1)), 2)

    def test_model_preflight_failure_preserves_settings(self):
        request = self.control("set-default-model", role="both", model="unavailable", effort="high")
        self.assertEqual(self.request("/api/v2/controls", request)["outcome"], "model_unavailable")
        self.assertEqual(self.harness.store.load(), RuntimeSettings())

    def test_runtime_observes_core_changes(self):
        self.harness.processor.runtime.apply(ControlCommand.from_dict({"version": 2, "repository": "local/smoke",
                                   "control": {"id": "GH-90", "action": "pause"}}))
        self.assertTrue(self.request("/api/v2/runtime")["settings"]["paused"])

    def test_unavailable_data_is_not_filled_with_fixtures(self):
        self.assertEqual(self.request("/api/v2/tasks"), [])
        self.assertEqual(self.request("/api/v2/hosts"), [])
        with self.assertRaises(HTTPError) as exc:
            self.request("/api/v2/tasks/GH-41")
        self.assertEqual(exc.exception.code, 404)

    def test_cross_origin_and_rebinding_are_rejected(self):
        for headers in ({"Origin": "https://example.com"}, {"Host": "attacker.example"},
                        {"X-Chat-Codex-Local": "0"}):
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as exc:
                self.request("/api/v2/controls", self.control(), headers=headers)
            self.assertEqual(exc.exception.code, 403)
        self.assertFalse(self.harness.store.path.exists())

    def test_repository_and_action_validation(self):
        for request in ({**self.control(), "repository": "other/repo"}, self.control("shell")):
            with self.subTest(request=request), self.assertRaises(HTTPError) as exc:
                self.request("/api/v2/controls", request)
            self.assertEqual(exc.exception.code, 400)
        self.assertFalse(self.harness.store.path.exists())

    def test_existing_user_state_is_not_adopted(self):
        root = self.root.parent / "user-state"
        root.mkdir()
        old = root / "runtime-settings.json"
        old.write_text('{"revision": 10}')
        with self.assertRaises(ValueError):
            Harness(root, "local/smoke")
        self.assertEqual(old.read_text(), '{"revision": 10}')


if __name__ == "__main__":
    unittest.main()
