from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.github_protocol import CommentView, IssueView
from codex_github_local_v2.github_protocol import GitHubTaskError, GitHubTaskPending, TASK_MARKER, validate_task_issue


def payload(issue=51):
    return {
        "version": 2,
        "repository": "owner/repo",
        "base_sha": "c" * 40,
        "task": {
            "id": f"GH-{issue}",
            "type": "documentation",
            "title": "Fixture",
            "goal": "Write docs only.",
            "read_scope": ["**"],
            "write_scope": ["docs/"],
            "checks": [],
            "acceptance": ["fixture"],
            "model_policy": {
                "executor": {
                    "primary": {"name": "runtime-default", "effort": "medium"},
                    "fallbacks": []
                },
                "reviewer": {
                    "primary": {"name": "runtime-default", "effort": "high"},
                    "fallbacks": []
                }
            },
            "budget": {"max_rounds": 1, "max_minutes": 10, "review_rounds": 1},
            "network": "deny",
            "production": "deny",
            "publication": {"mode": "pr", "draft_on_incomplete_validation": True}
        }
    }


def body(issue=51):
    return (
        TASK_MARKER
        + "\n~~~json\n"
        + json.dumps(payload(issue), ensure_ascii=False)
        + "\n~~~"
    )


def comment(issue=51, edited=False):
    return CommentView(
        comment_id=900 + issue,
        author="owner",
        created_at="2026-10-02T00:00:00Z",
        updated_at=("2026-10-02T00:01:00Z" if edited else "2026-10-02T00:00:00Z"),
        body=body(issue),
    )


class GitHubTaskTests(unittest.TestCase):
    def test_valid_immutable_task_is_accepted(self):
        task = validate_task_issue(
            IssueView(51, "[codex] docs fixture", "open", "owner"),
            [comment(51)],
            repository="owner/repo",
            authorized_users=["owner"],
        )
        self.assertEqual(task.task_id, "GH-51")
        self.assertEqual(task.model_policy.executor.primary.name, "runtime-default")

    def test_missing_comment_is_pending(self):
        with self.assertRaises(GitHubTaskPending):
            validate_task_issue(
                IssueView(51, "[codex] docs fixture", "open", "owner"),
                [],
                repository="owner/repo",
                authorized_users=["owner"],
            )

    def test_edited_task_comment_is_rejected(self):
        with self.assertRaises(GitHubTaskError):
            validate_task_issue(
                IssueView(51, "[codex] docs fixture", "open", "owner"),
                [comment(51, edited=True)],
                repository="owner/repo",
                authorized_users=["owner"],
            )

    def test_issue_number_mismatch_is_rejected(self):
        with self.assertRaises(GitHubTaskError):
            validate_task_issue(
                IssueView(52, "[codex] docs fixture", "open", "owner"),
                [comment(51)],
                repository="owner/repo",
                authorized_users=["owner"],
            )


if __name__ == "__main__":
    unittest.main()
