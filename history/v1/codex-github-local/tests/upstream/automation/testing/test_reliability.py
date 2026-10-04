"""Regression coverage for the three issues in the 2026-09-26 audit.

All model calls use the existing offline fixture. Process tests launch only
isolated, bounded fixture groups and always clean up their own children.
"""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_runner as fixtures

module = fixtures.module


class ReliabilityIntegrationTests(unittest.TestCase):
    # Share setup helpers without inheriting/rerunning the original ten tests.
    setUp = fixtures.IntegrationTests.setUp
    git = fixtures.IntegrationTests.git
    submit = fixtures.IntegrationTests.submit

    def commit_config(self, cfg):
        module.write_json(self.r.config_path, cfg)
        self.git("add", "automation/config.json")
        self.git("commit", "-m", "update fixture configuration")

    def test_waiting_runner_uses_new_check_and_records_same_snapshot(self):
        self.submit()  # The long-lived object has seen the original config.
        cfg = module.read_json(self.r.config_path)
        argv = [sys.executable, "-c", 'import sys; print("NEW_CHECK_MUST_FAIL"); sys.exit(23)']
        cfg["checks"]["query_contract"]["argv"] = argv
        self.commit_config(cfg)
        self.assertEqual(self.r.run_once(), "blocked")
        state = self.r.state("DICT-001")
        self.assertEqual(state["checks"][0]["exit_code"], 23)
        self.assertEqual(state["checks"][0]["argv"], argv)
        self.assertEqual(state["config_sha256"], module.digest(self.r.config_path))
        out = self.r.runtime / "outbox/DICT-001"
        self.assertEqual((out / "config.snapshot.json").read_bytes(), self.r.config_path.read_bytes())
        self.assertIn("NEW_CHECK_MUST_FAIL", (out / "check-query_contract-1.stdout.log").read_text())
        with self.assertRaises(module.Halt):
            module.Runner(self.root).accept("DICT-001")

    def test_mid_task_config_change_cannot_rebind_snapshot(self):
        self.submit()
        original = self.r.config_path.read_bytes()
        original_model = self.r.model

        def change_config_after_worker(role, *args):
            value = original_model(role, *args)
            if role == "worker":
                cfg = module.read_json(self.r.config_path)
                cfg["max_changed_files"] += 1
                module.write_json(self.r.config_path, cfg)
            return value

        with patch.object(self.r, "model", side_effect=change_config_after_worker):
            self.assertEqual(self.r.run_once(), "blocked")
        state = self.r.state("DICT-001")
        self.assertIn("配置发生变化", state["reason"])
        out = self.r.runtime / "outbox/DICT-001"
        self.assertEqual((out / "config.snapshot.json").read_bytes(), original)
        self.assertEqual(module.digest(out / "config.snapshot.json"), state["config_sha256"])
        self.assertNotEqual(module.digest(self.r.config_path), state["config_sha256"])
        self.assertFalse((out / "checks-1.json").exists())

    def test_accept_rejects_missing_or_modified_config_evidence(self):
        self.submit()
        self.assertEqual(self.r.run_once(), "needs_review")
        for directory in (self.r.job("DICT-001"), self.r.runtime / "outbox/DICT-001"):
            with self.subTest(snapshot=str(directory)):
                path = directory / "config.snapshot.json"
                original = path.read_bytes()
                path.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(module.Halt, "配置快照"):
                    module.Runner(self.root).accept("DICT-001")
                path.unlink()
                with self.assertRaisesRegex(module.Halt, "配置快照"):
                    module.Runner(self.root).accept("DICT-001")
                path.write_bytes(original)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)

    def test_legacy_result_requires_new_run(self):
        self.submit()
        self.assertEqual(self.r.run_once(), "needs_review")
        state = self.r.state("DICT-001")
        state.pop("protocol_version")
        self.r.save_state(state)
        with self.assertRaisesRegex(module.Halt, "旧任务"):
            module.Runner(self.root).accept("DICT-001")

    def test_missing_cli_persists_blocked_preflight_without_retry(self):
        cfg = module.read_json(self.r.config_path)
        cfg["codex_command"] = [str(Path(self.tmp.name) / "nonexistent_codex")]
        self.commit_config(cfg)
        self.submit()
        self.assertEqual(self.r.run_once(), "blocked")
        state = self.r.state("DICT-001")
        self.assertEqual(state["attempt"], 0)
        self.assertEqual(state["failure_stage"], "preflight")
        out = self.r.runtime / "outbox/DICT-001"
        self.assertIn("FileNotFoundError", (out / "review.md").read_text())
        self.assertEqual(module.read_json(out / "preflight.json")["error_type"], "FileNotFoundError")
        self.assertEqual(module.read_json(self.r.runtime / "scheduler.json")["status"], "blocked")
        self.assertFalse((self.r.runtime / "worktrees/DICT-001").exists())
        self.assertFalse(list(out.glob("worker-*")))
        self.assertIsNone(self.r.run_once())

    def test_auth_and_preflight_timeout_have_persistent_evidence(self):
        errors = (module.Halt("fixture login expired"), subprocess.TimeoutExpired("fixture", 1))
        for n, error in enumerate(errors):
            task_id = "PREFLIGHT-" + str(n)
            self.submit(task_id)
            with patch.object(self.r, "doctor", side_effect=error):
                self.assertEqual(self.r.run_once(), "blocked")
            state = self.r.state(task_id)
            self.assertEqual(state["attempt"], 0)
            self.assertEqual(state["failure_stage"], "preflight")
            evidence = module.read_json(self.r.runtime / "outbox" / task_id / "preflight.json")
            self.assertEqual(evidence["error_type"], type(error).__name__)

    def test_invalid_config_is_visible_even_to_status_command(self):
        self.submit()
        self.r.config_path.write_text("{malformed", encoding="utf-8")
        self.assertEqual(self.r.run_once(), "blocked")
        scheduler = module.read_json(self.r.runtime / "scheduler.json")
        self.assertEqual(scheduler["stage"], "configuration")
        self.assertEqual(scheduler["status"], "blocked")
        self.assertTrue((self.r.runtime / "outbox/scheduler.md").exists())
        output = subprocess.check_output([sys.executable, str(self.root / "automation/runner.py"),
                                          "--root", str(self.root), "status"], text=True)
        self.assertIn("调度器 blocked", output)
        self.assertIn("DICT-001 queued", output)


@unittest.skipUnless(os.name == "posix", "Process-group cleanup is POSIX-only")
class ProcessCleanupTests(unittest.TestCase):
    def start_group(self, leader_exits=False):
        child = ('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                 'print("READY",flush=True); time.sleep(20)')
        parent = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
                  + repr(child) + "]); time.sleep(" + ("0.15" if leader_exits else "20") + ")")
        p = subprocess.Popen([sys.executable, "-c", parent], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, start_new_session=True)

        def cleanup():
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate(timeout=3)
            p.stdout.close()

        self.addCleanup(cleanup)
        self.assertTrue(select.select([p.stdout], [], [], 3)[0], "fixture child was not ready")
        self.assertEqual(p.stdout.readline().strip(), "READY")
        if leader_exits:
            p.wait(timeout=3)
        return p

    def assert_child_pipe_closed(self, p):
        # The child holds this pipe while alive. EOF does not depend on /proc
        # PID namespace mappings or on how quickly the init process reaps it.
        self.assertTrue(select.select([p.stdout], [], [], 2)[0], "child still holds its pipe")
        self.assertEqual(p.stdout.read(), "")

    def test_sigterm_ignoring_child_is_killed_after_leader_exits(self):
        p = self.start_group()
        result = module.terminate_group(p, grace_seconds=0.15, kill_wait_seconds=1)
        self.assertTrue(result["kill_sent"])
        self.assertIsNotNone(result["leader_returncode"])
        self.assert_child_pipe_closed(p)

    def test_group_is_cleaned_even_if_leader_already_exited(self):
        p = self.start_group(leader_exits=True)
        self.assertEqual(p.returncode, 0)
        result = module.terminate_group(p, grace_seconds=0.15, kill_wait_seconds=1)
        self.assertTrue(result["kill_sent"])
        self.assert_child_pipe_closed(p)

    def test_timeout_writes_cleanup_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "fixture"
            with self.assertRaises(module.ProcessHalt) as caught:
                module.logged_process([sys.executable, "-c", "import time; time.sleep(20)"],
                                      directory, stem, timeout=0.1)
            evidence = module.read_json(stem.with_suffix(".cleanup.json"))
            self.assertEqual(evidence["trigger"], "timeout")
            self.assertTrue(evidence["confirmed"])
            self.assertEqual(evidence, caught.exception.cleanup)

    def test_unconfirmed_cleanup_does_not_claim_success(self):
        p = Mock()
        p.communicate.side_effect = subprocess.TimeoutExpired("fixture", 1)
        result = {"confirmed": False, "group_absent": False, "kill_sent": True}
        with patch.object(module, "terminate_group", return_value=result):
            with self.assertRaises(module.ProcessHalt) as caught:
                module.communicate(p, timeout=1)
        self.assertIn("无法确认", str(caught.exception))
        self.assertNotIn("已确认原进程组消失", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
