from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.control import (
    ControlCommand, ControlLedger, LedgerError, RuntimeSettings,
    command_fingerprint, status_receipt,
)
from codex_github_local_v2.github_protocol import CommentView
from codex_github_local_v2.ledger_migration import migrate_control_ledger
from codex_github_local_v2.locking import AlreadyRunning, single_instance_lock


class LedgerMigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "control-ledger.json"
        command = ControlCommand.from_dict({"version": 2, "repository": "owner/repo",
                  "control": {"id": "GH-43", "action": "pause"}})
        self.old = {"version": 1, "records": {"GH-43": {
            "fingerprint": command_fingerprint(command), "outcome": "applied",
            "message": "queue paused", "revision": 1, "recorded_at": 100.0}}}
        self.settings = RuntimeSettings(paused=True, revision=1, last_control_id="GH-43")
        self.evidence = {"GH-43": {"settings": self.settings.to_dict(), "receipt_comment": None}}
        self.original = (json.dumps(self.old, indent=2) + "\n").encode()
        self.path.write_bytes(self.original)

    def migrate(self):
        return migrate_control_ledger(self.path, self.evidence, authorized_users=["owner"])

    def test_pending_result_gets_durable_receipt_and_exact_backup(self):
        result = self.migrate()
        self.assertEqual(result.status, "migrated")
        self.assertEqual(result.backup.read_bytes(), self.original)
        ledger = ControlLedger(self.path)
        row = ledger.get("GH-43")
        self.assertEqual(row["fingerprint"], self.old["records"]["GH-43"]["fingerprint"])
        self.assertEqual(row["revision"], 1)
        self.assertIn("paused: true", row["receipt"])
        self.assertEqual(len(ledger.pending_receipts()), 1)

    def test_verified_legacy_receipt_is_not_sent_again(self):
        body = status_receipt(self.settings, outcome="applied", message="queue paused")
        self.evidence["GH-43"]["receipt_comment"] = asdict(CommentView(
            5, "owner", "2026-10-02T00:00:00Z", "2026-10-02T00:00:00Z", body))
        self.migrate()
        self.assertEqual(ControlLedger(self.path).pending_receipts(), [])

    def test_repeated_migration_does_not_change_bytes_or_create_another_backup(self):
        first = self.migrate()
        before = self.path.read_bytes()
        second = self.migrate()
        self.assertEqual(second.status, "already_migrated")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [first.backup])

    def test_missing_reconciliation_leaves_old_file_unchanged(self):
        self.evidence = {}
        with self.assertRaises(LedgerError):
            self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_incomplete_snapshot_is_not_filled_with_current_defaults(self):
        del self.evidence["GH-43"]["settings"]["reviewer"]
        with self.assertRaises(LedgerError):
            self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_revision_mismatch_is_rejected(self):
        self.evidence["GH-43"]["settings"]["revision"] = 9
        with self.assertRaises(LedgerError):
            self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_untrusted_or_edited_receipt_is_rejected(self):
        body = status_receipt(self.settings, outcome="applied", message="queue paused")
        for author, updated in (("stranger", "2026-10-02T00:00:00Z"),
                                ("owner", "2026-10-02T00:00:01Z")):
            with self.subTest(author=author):
                self.evidence["GH-43"]["receipt_comment"] = asdict(CommentView(
                    5, author, "2026-10-02T00:00:00Z", updated, body))
                with self.assertRaises(LedgerError):
                    self.migrate()
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_atomic_replace_failure_retains_old_file_and_backup(self):
        with patch("codex_github_local_v2.control.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(next(self.path.parent.glob("*.bak")).read_bytes(), self.original)
        self.assertEqual(self.migrate().status, "migrated")

    def test_backup_write_failure_does_not_touch_old_file(self):
        with patch("codex_github_local_v2.ledger_migration.os.open", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_watcher_lock_prevents_migration(self):
        with single_instance_lock(self.path.parent / "control.lock"):
            with self.assertRaises(AlreadyRunning):
                self.migrate()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unknown_schema_and_corrupt_schema2_fail_closed(self):
        for data in ({"version": 99, "records": {}}, {"version": 2, "records": {"GH-43": {}}}):
            with self.subTest(data=data):
                before = json.dumps(data).encode()
                self.path.write_bytes(before)
                with self.assertRaises(LedgerError):
                    self.migrate()
                self.assertEqual(self.path.read_bytes(), before)

    def test_symlink_is_not_followed(self):
        link = self.path.parent / "linked.json"
        link.symlink_to(self.path)
        with self.assertRaises(LedgerError):
            migrate_control_ledger(link, self.evidence, authorized_users=["owner"])
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
