"""Integration tests use temporary Git repositories and an offline CLI double."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("collab_runner", SOURCE / "automation/runner.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns(".git", "runtime", "__pycache__"))
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Collab Test")
        self.git("config", "user.email", "collab-test@example.invalid")
        cfg = module.read_json(self.root / "automation/config.json")
        cfg["codex_command"] = [sys.executable, str(SOURCE / "automation/testing/fake_codex.py")]
        module.write_json(self.root / "automation/config.json", cfg)
        self.git("add", ".")
        self.git("commit", "-m", "fixture baseline")
        self.base = self.git("rev-parse", "HEAD")
        self.r = module.Runner(self.root)
        self.env = patch.dict(os.environ, {"CODEX_API_KEY": "", "OPENAI_API_KEY": "", "COLLAB_TEST_MODE": "ok"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL,
                                       text=True).strip()

    def submit(self, task_id="DICT-001", deps=None):
        task = module.read_json(self.root / "automation/examples/DICT-001.json")
        task["id"] = task_id
        task["depends_on"] = deps or []
        path = Path(self.tmp.name) / (task_id + ".json")
        module.write_json(path, task)
        self.r.submit(path)
        return path

    def test_end_to_end_snapshot_and_accept(self):
        self.submit()
        self.assertEqual(self.r.run_once(), "needs_review")
        state = self.r.state("DICT-001")
        self.assertNotEqual(state["candidate"], self.base)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertTrue((self.r.runtime / "outbox/DICT-001/changes.patch").is_file())
        self.r.accept("DICT-001")
        self.assertEqual(self.git("rev-parse", "HEAD"), state["candidate"])
        self.assertEqual(self.r.state("DICT-001")["status"], "accepted")

    def test_failed_check_triggers_one_repair(self):
        self.submit()
        os.environ["COLLAB_TEST_MODE"] = "repair_once"
        self.assertEqual(self.r.run_once(), "needs_review")
        self.assertEqual(self.r.state("DICT-001")["attempt"], 2)
        self.assertFalse((self.r.runtime / "outbox/DICT-001/reviewer-1.json").exists())

    def test_permanent_failure_stops_at_budget(self):
        self.submit()
        os.environ["COLLAB_TEST_MODE"] = "always_fail"
        self.assertEqual(self.r.run_once(), "blocked")
        self.assertEqual(self.r.state("DICT-001")["attempt"], 2)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertIsNone(self.r.run_once())

    def test_protected_file_change_blocks_merge(self):
        self.submit()
        os.environ["COLLAB_TEST_MODE"] = "protected"
        self.assertEqual(self.r.run_once(), "blocked")
        self.assertIn("受保护", self.r.state("DICT-001")["reason"])
        with self.assertRaises(module.Halt):
            self.r.accept("DICT-001")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)

    def test_reviewer_revision_and_invalid_output(self):
        self.submit()
        os.environ["COLLAB_TEST_MODE"] = "review_revise"
        self.assertEqual(self.r.run_once(), "needs_review")
        self.assertEqual(self.r.state("DICT-001")["attempt"], 2)
        self.r.accept("DICT-001")
        self.submit("DICT-002")
        os.environ["COLLAB_TEST_MODE"] = "invalid_review"
        self.assertEqual(self.r.run_once(), "blocked")
        self.assertIn("协议", self.r.state("DICT-002")["reason"])

    def test_stale_main_cannot_accept(self):
        self.submit()
        self.assertEqual(self.r.run_once(), "needs_review")
        (self.root / "unrelated.txt").write_text("main advanced")
        self.git("add", "unrelated.txt")
        self.git("commit", "-m", "independent change")
        with self.assertRaisesRegex(module.Halt, "主分支已前进"):
            self.r.accept("DICT-001")

    def test_duplicate_and_changed_task_rejected(self):
        path = self.submit()
        with self.assertRaisesRegex(module.Halt, "已存在"):
            self.r.submit(path)
        task_path = self.r.job("DICT-001") / "task.json"
        task = module.read_json(task_path)
        task["depends_on"] = ["not-a-real-task"]
        module.write_json(task_path, task)
        self.assertEqual(self.r.run_once(), "blocked")

    def test_dependencies_wait_for_accepted_result(self):
        self.submit()
        self.submit("DICT-002", ["DICT-001"])
        self.assertEqual(self.r.run_once(), "needs_review")
        self.assertIsNone(self.r.run_once())
        self.r.accept("DICT-001")
        self.assertEqual(self.r.run_once(), "needs_review")
        self.assertEqual(self.r.state("DICT-002")["base"], self.git("rev-parse", "HEAD"))

    def test_infrastructure_failure_no_retry(self):
        self.submit()
        os.environ["COLLAB_TEST_MODE"] = "exit_error"
        self.assertEqual(self.r.run_once(), "blocked")
        self.assertEqual(self.r.state("DICT-001")["attempt"], 1)

    def test_rejection_unblocks_revised_task_without_merge(self):
        self.submit()
        self.assertEqual(self.r.run_once(), "needs_review")
        self.r.reject("DICT-001", "需要调整验收口径，改用新任务。")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual(self.r.state("DICT-001")["status"], "rejected")
        self.submit("DICT-002")
        self.assertEqual(self.r.run_once(), "needs_review")


if __name__ == "__main__":
    unittest.main()
