from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_processor import FakeSource, comment
from codex_github_local_v2.control import (
    ControlLedger, ControlProcessor, LedgerError, RuntimeControlService,
    RuntimeSettings, RuntimeSettingsStore,
)
from codex_github_local_v2.github_protocol import CommentView, IssueView
from codex_github_local_v2.routing import ProbeResult


class FaultSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.failure = None
        self.attempts = 0

    def post_comment(self, issue_number, body):
        self.attempts += 1
        failure, self.failure = self.failure, None
        if failure == "before":
            raise OSError("delivery failed")
        super().post_comment(issue_number, body)
        self.comments.setdefault(issue_number, []).append(
            CommentView(2000 + self.attempts, "owner", "now", "now", body)
        )
        if failure == "after":
            raise OSError("response lost")


class ReceiptRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = FaultSource()
        self.store = RuntimeSettingsStore(self.root / "settings.json")
        self.probes = []
        self.available = True

    def processor(self):
        def probe(role, choice):
            self.probes.append(role)
            return ProbeResult(self.available, "fixture")

        return ControlProcessor(
            repository="owner/repo", authorized_users=["owner"],
            source=self.source, runtime=RuntimeControlService(self.store, probe),
            ledger=ControlLedger(self.root / "ledger.json"),
        )

    def add(self, action="pause"):
        self.source.issues = [IssueView(43, f"[codex-control] {action}", "open", "owner")]
        self.source.comments[43] = [comment(43, action)]

    def fail_delivery(self, failure="before", action="pause"):
        self.add(action)
        self.source.failure = failure
        with self.assertRaises(OSError):
            self.processor().tick()

    def test_restart_retries_receipt_without_reapplying_control(self):
        self.fail_delivery(action="set-default-model")
        before = self.store.path.read_bytes()
        self.assertEqual(self.processor().tick().status, "applied")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.probes, ["executor", "reviewer"])
        self.assertEqual(self.source.attempts, 2)
        self.assertEqual(self.processor().tick().status, "pending")
        self.assertEqual(self.source.attempts, 2)

    def test_lost_response_does_not_duplicate_remote_comment(self):
        self.fail_delivery("after")
        self.assertEqual(self.processor().tick().status, "applied")
        self.assertEqual(len(self.source.posted), 1)
        self.assertEqual(self.source.attempts, 1)

    def test_crash_before_marking_delivered_recovers_from_remote_comment(self):
        self.add()
        processor = self.processor()
        with patch.object(processor.ledger, "mark_delivered", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                processor.tick()
        self.assertEqual(self.processor().tick().status, "applied")
        self.assertEqual(self.source.attempts, 1)

    def test_closed_issue_still_receives_pending_receipt(self):
        self.fail_delivery()
        self.source.issues = []
        self.assertEqual(self.processor().tick().issue_number, 43)
        self.assertEqual(len(self.source.posted), 1)

    def test_ledger_write_failure_after_settings_save_does_not_reapply(self):
        self.add("set-default-model")
        processor = self.processor()
        with patch.object(processor.ledger, "record", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                processor.tick()
        before = self.store.path.read_bytes()
        self.assertEqual(self.processor().tick().status, "applied")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.probes, ["executor", "reviewer"])

    def test_retry_preserves_original_settings_snapshot(self):
        self.fail_delivery()
        self.store.save(RuntimeSettings(revision=9, executor_model="later"))
        self.processor().tick()
        receipt = self.source.posted[0][1]
        self.assertIn("revision: 1", receipt)
        self.assertIn("paused: true", receipt)
        self.assertNotIn("later", receipt)
        self.assertEqual(self.store.load().revision, 9)

    def test_failed_model_preflight_receipt_retries_without_probing_again(self):
        self.available = False
        self.fail_delivery(action="set-default-model")
        self.assertEqual(self.processor().tick().status, "model_unavailable")
        self.assertEqual(self.probes, ["executor"])
        self.assertFalse(self.store.path.exists())

    def test_untrusted_copy_does_not_acknowledge_delivery(self):
        self.fail_delivery("after")
        receipt = self.source.comments[43][-1]
        self.source.comments[43][-1] = replace(receipt, author="stranger")
        self.processor().tick()
        self.assertEqual(self.source.attempts, 2)

    def test_old_ledger_is_rejected_without_overwriting_or_applying(self):
        self.add()
        path = self.root / "ledger.json"
        before = '{"version": 1, "records": {}}\n'
        path.write_text(before, encoding="utf-8")
        with self.assertRaises(LedgerError):
            self.processor().tick()
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertFalse(self.store.path.exists())

    def test_corrupt_receipt_fails_closed(self):
        self.fail_delivery()
        path = self.root / "ledger.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["records"]["GH-43"]["receipt"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(LedgerError):
            self.processor().tick()
        self.assertEqual(self.source.attempts, 1)


if __name__ == "__main__":
    unittest.main()
