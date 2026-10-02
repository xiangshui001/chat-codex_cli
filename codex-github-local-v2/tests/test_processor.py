from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.contract import TaskContract
from codex_github_local_v2.control import RuntimeSettings
from codex_github_local_v2.control_ledger import ControlLedger
from codex_github_local_v2.control_processor import ControlProcessor
from codex_github_local_v2.github_control import CommentView, IssueView
from codex_github_local_v2.resolution import resolve_task_models
from codex_github_local_v2.routing import ProbeResult
from codex_github_local_v2.runtime_settings import RuntimeControlService, RuntimeSettingsStore


def task_contract():
    return TaskContract.from_dict(
        {
            "version": 2,
            "repository": "owner/repo",
            "base_sha": "a" * 40,
            "task": {
                "id": "GH-7",
                "type": "documentation",
                "title": "Fixture",
                "goal": "Fixture task.",
                "read_scope": ["**"],
                "write_scope": ["docs/"],
                "checks": [],
                "acceptance": ["fixture"],
                "model_policy": {
                    "executor": {
                        "primary": {"name": "runtime-default", "effort": "low"},
                        "fallbacks": [{"name": "fallback-worker", "effort": "medium"}]
                    },
                    "reviewer": {
                        "primary": {"name": "runtime-default", "effort": "low"},
                        "fallbacks": []
                    }
                },
                "budget": {"max_rounds": 1, "max_minutes": 10, "review_rounds": 1},
                "network": "deny",
                "production": "deny",
                "publication": {"mode": "pr", "draft_on_incomplete_validation": True}
            }
        }
    )


class ResolutionTests(unittest.TestCase):
    def test_runtime_defaults_are_frozen_into_claimed_task(self):
        settings = RuntimeSettings(
            executor_model="worker-new",
            executor_effort="high",
            reviewer_model="review-new",
            reviewer_effort="medium",
        )
        resolved = resolve_task_models(task_contract(), settings)
        self.assertEqual(resolved.model_policy.executor.primary.name, "worker-new")
        self.assertEqual(resolved.model_policy.executor.primary.effort, "high")
        self.assertEqual(resolved.model_policy.reviewer.primary.name, "review-new")
        self.assertEqual(resolved.model_policy.reviewer.primary.effort, "medium")
        self.assertEqual(resolved.model_policy.executor.fallbacks[0].name, "fallback-worker")


class FakeSource:
    def __init__(self):
        self.issues = []
        self.comments = {}
        self.posted = []

    def list_open_control_issues(self):
        return list(self.issues)

    def list_comments(self, issue_number):
        return list(self.comments.get(issue_number, []))

    def post_comment(self, issue_number, body):
        self.posted.append((issue_number, body))


def body(issue, action, extra=""):
    if action == "set-default-model":
        control = f'''"id": "GH-{issue}", "action": "set-default-model", "role": "both", "model": "new-model", "effort": "high"'''
    else:
        control = f'''"id": "GH-{issue}", "action": "{action}"'''
    return f"""/codex-local control
~~~json
{{
  "version": 2,
  "repository": "owner/repo",
  "control": {{{control}}}
}}
~~~"""


def comment(issue, action):
    return CommentView(
        comment_id=1000 + issue,
        author="owner",
        created_at="2026-10-02T00:00:00Z",
        updated_at="2026-10-02T00:00:00Z",
        body=body(issue, action),
    )


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = FakeSource()
        self.store = RuntimeSettingsStore(root / "runtime-settings.json")
        self.ledger = ControlLedger(root / "control-ledger.json")

        def probe(role, choice):
            return ProbeResult(True, "fixture")

        self.processor = ControlProcessor(
            repository="owner/repo",
            authorized_users=["owner"],
            source=self.source,
            runtime=RuntimeControlService(self.store, probe),
            ledger=self.ledger,
        )

    def add(self, issue, action):
        self.source.issues.append(
            IssueView(issue, f"[codex-control] {action}", "open", "owner")
        )
        self.source.comments[issue] = [comment(issue, action)]

    def test_model_control_changes_future_defaults_and_posts_receipt(self):
        self.add(43, "set-default-model")
        result = self.processor.tick()
        self.assertEqual(result.status, "applied")
        settings = self.store.load()
        self.assertEqual(settings.executor_model, "new-model")
        self.assertEqual(settings.reviewer_model, "new-model")
        self.assertEqual(len(self.source.posted), 1)
        self.assertIn("revision: 1", self.source.posted[0][1])

    def test_processed_old_issue_does_not_starve_new_issue(self):
        self.add(43, "pause")
        self.assertEqual(self.processor.tick().status, "applied")
        self.add(44, "resume")
        second = self.processor.tick()
        self.assertEqual(second.issue_number, 44)
        self.assertEqual(second.status, "applied")
        self.assertFalse(self.store.load().paused)

    def test_issue_without_comment_is_pending_not_rejected(self):
        self.source.issues.append(
            IssueView(43, "[codex-control] pause", "open", "owner")
        )
        result = self.processor.tick()
        self.assertEqual(result.status, "pending")
        self.assertEqual(self.source.posted, [])

    def test_untrusted_control_issue_does_not_starve_authorized_one(self):
        self.source.issues.append(
            IssueView(1, "[codex-control] pause", "open", "stranger")
        )
        self.source.comments[1] = [
            CommentView(
                comment_id=1,
                author="stranger",
                created_at="2026-10-02T00:00:00Z",
                updated_at="2026-10-02T00:00:00Z",
                body=body(1, "pause"),
            )
        ]
        self.add(43, "pause")
        result = self.processor.tick()
        self.assertEqual(result.issue_number, 43)
        self.assertEqual(result.status, "applied")

    def test_malformed_authorized_issue_does_not_starve_newer_valid_one(self):
        self.source.issues.append(
            IssueView(42, "[codex-control] malformed", "open", "owner")
        )
        self.source.comments[42] = [
            CommentView(
                comment_id=42,
                author="owner",
                created_at="2026-10-02T00:00:00Z",
                updated_at="2026-10-02T00:00:00Z",
                body="/codex-local control\n~~~json\n{}\n~~~",
            )
        ]
        self.add(43, "pause")
        result = self.processor.tick()
        self.assertEqual(result.issue_number, 43)
        self.assertEqual(result.status, "applied")


if __name__ == "__main__":
    unittest.main()
