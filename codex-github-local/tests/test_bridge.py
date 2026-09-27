import contextlib
import copy
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge as b


def git(cwd, *args):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, encoding="utf-8",
                                   stderr=subprocess.DEVNULL).strip()


class FakeGitHub:
    def __init__(self, remote, task):
        self.remote = remote
        self.issue = {"number": 7, "title": "[codex] Documentation smoke test", "state": "open",
                      "user": {"login": "owner"}}
        self.comment = {"id": 71, "user": {"login": "owner"}, "created_at": "2026-09-27T01:00:00Z",
                        "updated_at": "2026-09-27T01:00:00Z", "body": b.MARKER + "\n```json\n" +
                        json.dumps({"version": 1, "repository": "owner/repo", "base_sha": git(remote, "rev-parse", "main"),
                                    "task": task}) + "\n```"}
        self.pr = None
        self.extra_comments = []
        self.fail_create_before = False
        self.fail_create_after = False
        self.writes = []

    def api(self, endpoint, method="GET", data=None):
        if method != "GET":
            self.writes.append((endpoint, method))
        if endpoint == "user":
            return {"login": "owner", "id": 1}
        if endpoint == "repos/owner/repo":
            return {"permissions": {"push": True}, "has_issues": True, "default_branch": "main"}
        if "/git/ref/heads/" in endpoint:
            return {"object": {"sha": git(self.remote, "rev-parse", "main")}}
        if endpoint.endswith("/issues/7"):
            return copy.deepcopy(self.issue)
        if endpoint.endswith("/issues/7/comments") and method == "POST":
            value = {"id": 1000 + len(self.extra_comments), "user": {"login": "owner"}, "body": data["body"]}
            self.extra_comments.append(value)
            return value
        if endpoint.endswith("/pulls") and method == "POST":
            if self.fail_create_before:
                self.fail_create_before = False
                raise b.Halt("Simulated network failure before PR creation")
            self.pr = {"number": 80, "html_url": "https://github.com/owner/repo/pull/80", "state": "open",
                       "merged": False, "body": data["body"],
                       "head": {"sha": git(self.remote, "rev-parse", data["head"]), "ref": data["head"],
                                "repo": {"full_name": "owner/repo"}},
                       "base": {"ref": "main", "repo": {"full_name": "owner/repo"}}}
            if self.fail_create_after:
                self.fail_create_after = False
                raise b.Halt("Simulated lost response after PR creation")
            return copy.deepcopy(self.pr)
        if endpoint.endswith("/pulls/80"):
            return copy.deepcopy(self.pr)
        raise AssertionError(endpoint)

    def pages(self, endpoint):
        if "/issues?" in endpoint:
            return [copy.deepcopy(self.issue)] if self.issue["state"] == "open" else []
        if endpoint.endswith("/comments"):
            return copy.deepcopy([self.comment] + self.extra_comments)
        if "/pulls?" in endpoint:
            return [copy.deepcopy(self.pr)] if self.pr else []
        raise AssertionError(endpoint)

    def merge(self, squash=False):
        head = self.pr["head"]["sha"]
        base = git(self.remote, "rev-parse", "main")
        tree = git(self.remote, "rev-parse", head + "^{tree}")
        args = ["commit-tree", tree, "-p", base]
        if not squash:
            args += ["-p", head]
        commit = git(self.remote, *args, "-m", "Simulated human merge")
        git(self.remote, "update-ref", "refs/heads/main", commit)
        self.pr.update(merged=True, state="closed", merge_commit_sha=commit)
        self.issue["state"] = "closed"
        return commit


class BridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.remote = self.tmp / "remote.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "-b", "main")
        git(self.remote, "config", "user.name", "Test")
        git(self.remote, "config", "user.email", "test@example.invalid")
        self.root = self.tmp / "clone"
        self.root.mkdir()
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        (self.root / "README.md").write_text("Fixture\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "baseline")
        git(self.root, "push", str(self.remote), "main")
        self.base = git(self.root, "rev-parse", "HEAD")
        cfg = b.core.read_json(b.BUNDLE / "profiles/example.json")
        cfg.update(repository="owner/repo", authorized_users=["owner"], root=str(self.root),
                   runtime=str(self.tmp / "runtime"), required_checks=["task_handoff"])
        cfg["checks"] = {"task_handoff": {"argv": ["{python}", str(b.BUNDLE / "handoff_check.py"), "{task_id}"],
                                          "timeout_seconds": 10}}
        self.config = self.tmp / "config.json"
        b.core.write_json(self.config, cfg)
        self.task = {"id": "GH-7", "title": "Smoke test", "goal": "Write the handoff", "context": "Synthetic fixture",
                     "inputs": [], "allowed_paths": ["tasks/GH-7/"], "checks": ["task_handoff"],
                     "acceptance": ["A complete handoff exists"], "depends_on": []}
        self.api = FakeGitHub(self.remote, self.task)
        self.calls = []
        self.mutate_during_worker = None

        def model(runner, role, prompt, wt, outdir, attempt):
            self.calls.append(role)
            if role == "worker":
                folder = Path(wt) / "tasks/GH-7"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "handoff.md").write_text(
                    "# 任务 GH-7\n基线：" + self.base + "\n修改：合成交接文件。\n检查：仅合成检查。\n"
                    "未运行：真实模型、网络和产品检查。\n风险：本测试不证明线上运行。\n部署：未部署，未人工接纳。\n" * 2,
                    encoding="utf-8")
                if self.mutate_during_worker:
                    self.mutate_during_worker()
            result = {"status" if role == "worker" else "verdict": "completed" if role == "worker" else "pass",
                      "summary": "offline fixture", "issues": [], "evidence": []}
            b.core.write_json(outdir / f"{role}-{attempt}.json", result)
            return result

        def doctor(runner, refresh=True):
            if refresh:
                runner.load_config()
            runner.clean_main()
            return {"codex": "offline fixture", "base": runner.git("rev-parse", "HEAD")}

        patches = [patch.object(b.Bridge, "remote", property(lambda _: str(self.remote))),
                   patch.object(b.core.Runner, "model", model), patch.object(b.core.Runner, "doctor", doctor)]
        if os.name != "posix":
            # These tests exercise real Git state and API logic, not POSIX locking.
            patches.append(patch.object(b.core.Runner, "lock", lambda _: contextlib.nullcontext()))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def bridge(self):
        return b.Bridge(self.config, self.api)

    def test_publish_manual_merge_and_dedup(self):
        worker = self.bridge()
        self.assertTrue(worker.tick().startswith("PR:"))
        self.assertEqual(self.calls, ["worker", "reviewer"])
        candidate = worker.state["current"]["candidate"]
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.remote, "rev-parse", "feature/GH-7"), candidate)
        self.assertEqual(self.bridge().tick(), "waiting_review")
        merged = self.api.merge()
        self.assertEqual(self.bridge().tick(), "accepted")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), merged)
        self.assertEqual(self.bridge().r.state("GH-7")["status"], "accepted")
        self.api.issue["state"] = "open"
        self.assertEqual(self.bridge().tick(), "idle")
        self.assertEqual(self.calls, ["worker", "reviewer"])

    def test_idle_never_calls_model_or_writes_github(self):
        self.api.comment["body"] = "ordinary discussion"
        self.assertEqual(self.bridge().tick(), "idle")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.api.writes, [])

    def test_untrusted_comment_is_not_a_task(self):
        self.api.comment["user"]["login"] = "stranger"
        self.assertEqual(self.bridge().tick(), "idle")
        self.assertEqual(self.calls, [])

    def test_edited_comment_blocks_without_model(self):
        self.api.comment["updated_at"] = "2026-09-27T02:00:00Z"
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])

    def test_duplicate_authorizations_block_without_model(self):
        self.api.extra_comments = [copy.deepcopy(self.api.comment)]
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])

    def test_stale_base_stops_before_worktree_or_model(self):
        self.api.comment["body"] = self.api.comment["body"].replace(self.base, "0" * 40)
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.tmp / "runtime/worktrees/GH-7").exists())
        self.assertEqual(self.bridge().state["current"]["stage"], "blocked")

    def test_content_change_during_worker_prevents_publication(self):
        self.mutate_during_worker = lambda: self.api.comment.update(body=self.api.comment["body"] + "edited")
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, ["worker"])
        self.assertEqual(self.bridge().r.state("GH-7")["status"], "blocked")
        self.assertIsNone(self.api.pr)

    def test_out_of_policy_path_never_calls_model(self):
        self.api.comment["body"] = self.api.comment["body"].replace('"tasks/GH-7/"', '"app/", "tasks/GH-7/"')
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])

    def test_missing_required_check_never_calls_model(self):
        envelope = json.loads(self.api.comment["body"].split("```json\n")[1].split("\n```")[0])
        envelope["task"]["checks"] = []
        self.api.comment["body"] = b.MARKER + "\n```json\n" + json.dumps(envelope) + "\n```"
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])

    def test_publish_retry_does_not_rerun_model(self):
        self.api.fail_create_before = True
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.bridge().state["current"]["stage"], "publishing")
        self.assertTrue(self.bridge().tick().startswith("PR:"))
        self.assertEqual(self.calls, ["worker", "reviewer"])

    def test_lost_pr_response_is_deduplicated_even_after_human_merge(self):
        self.api.fail_create_after = True
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.api.merge()
        self.assertTrue(self.bridge().tick().startswith("PR:"))
        self.assertEqual(self.bridge().tick(), "accepted")
        self.assertEqual(sum(endpoint.endswith("/pulls") for endpoint, _ in self.api.writes), 1)
        self.assertEqual(self.calls, ["worker", "reviewer"])

    def test_squash_merge_is_not_falsely_accepted(self):
        self.bridge().tick()
        self.api.merge(squash=True)
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.bridge().r.state("GH-7")["status"], "needs_review")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base)

    def test_changed_pr_head_is_not_accepted(self):
        self.bridge().tick()
        self.api.pr["head"]["sha"] = self.base
        with self.assertRaises(b.Halt):
            self.bridge().tick()

    def test_configuration_change_prevents_publish_retry(self):
        self.api.fail_create_before = True
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        cfg = b.core.read_json(self.config)
        cfg["max_changed_files"] += 1
        b.core.write_json(self.config, cfg)
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertIsNone(self.api.pr)

    def test_tampered_final_check_prevents_publish_retry(self):
        self.api.fail_create_before = True
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        path = self.tmp / "runtime/outbox/GH-7/checks-1.json"
        b.core.write_json(path, [])
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertIsNone(self.api.pr)

    def test_interrupted_claim_is_not_replayed(self):
        worker = self.bridge()
        record = b.parse_task(self.api.issue, [self.api.comment], worker.cfg)
        record.update(stage="running", config_sha256=worker.r.config_hash)
        worker.state["current"] = record
        worker.save()
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, [])

    def test_closed_pr_is_rejected_without_merge(self):
        self.bridge().tick()
        self.api.pr["state"] = "closed"
        self.assertEqual(self.bridge().tick(), "rejected")
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.base)

    def test_config_change_during_worker_blocks_without_review_or_push(self):
        def change():
            cfg = b.core.read_json(self.config)
            cfg["max_changed_files"] += 1
            b.core.write_json(self.config, cfg)
        self.mutate_during_worker = change
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, ["worker"])
        self.assertIsNone(self.api.pr)

    def test_status_receipt_is_not_duplicated_while_waiting(self):
        self.bridge().tick()
        count = len(self.api.extra_comments)
        self.bridge().tick()
        self.bridge().tick()
        self.assertEqual(len(self.api.extra_comments), count)

    def test_publication_never_targets_main_even_if_local_state_changed(self):
        self.api.fail_create_before = True
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        worker = self.bridge()
        state = worker.r.state("GH-7")
        worker.r.save_state(state, branch="main")
        worker.r.report(state)
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.base)
        self.assertIsNone(self.api.pr)

    def test_cli_blocked_exit_nonzero_and_persistent_error(self):
        self.api.comment["body"] = self.api.comment["body"].replace(self.base, "0" * 40)
        with patch.object(b, "GitHub", return_value=self.api), \
                patch.object(b, "APP", self.tmp / "app-state"), \
                patch.object(b, "global_lock", contextlib.nullcontext), \
                contextlib.redirect_stderr(io.StringIO()):
            code = b.main(["--config", str(self.config), "run-once"])
        self.assertEqual(code, 1)
        self.assertEqual(b.core.read_json(self.tmp / "app-state/last-error.json")["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_cli_idle_exit_zero(self):
        self.api.comment["body"] = "ordinary discussion"
        with patch.object(b, "GitHub", return_value=self.api), \
                patch.object(b, "global_lock", contextlib.nullcontext), \
                contextlib.redirect_stdout(io.StringIO()):
            code = b.main(["--config", str(self.config), "run-once"])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])

    def test_main_advance_while_waiting_pauses_without_another_model_run(self):
        self.bridge().tick()
        tree = git(self.remote, "rev-parse", self.base + "^{tree}")
        changed = git(self.remote, "commit-tree", tree, "-p", self.base, "-m", "Another coordinator")
        git(self.remote, "update-ref", "refs/heads/main", changed)
        with self.assertRaises(b.Halt):
            self.bridge().tick()
        self.assertEqual(self.calls, ["worker", "reviewer"])
        self.assertTrue(any("pr_stale" in c["body"] for c in self.api.extra_comments))


if __name__ == "__main__":
    unittest.main()
