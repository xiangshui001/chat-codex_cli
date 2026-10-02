from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.control import (
    ControlCommand,
    ControlError,
    RuntimeSettings,
    apply_control,
    parse_control_comment,
)
from codex_github_local_v2.evidence import EvidenceStore
from codex_github_local_v2.github_control import (
    CommentView,
    GitHubControlError,
    IssueView,
    validate_control_issue,
)
from codex_github_local_v2.routing import ProbeResult
from codex_github_local_v2.runtime_settings import (
    RuntimeControlService,
    RuntimeSettingsError,
    RuntimeSettingsStore,
)


def model_command(issue=43, role="both", model="supported-model", effort="high"):
    return ControlCommand.from_dict(
        {
            "version": 2,
            "repository": "owner/repo",
            "control": {
                "id": f"GH-{issue}",
                "action": "set-default-model",
                "role": role,
                "model": model,
                "effort": effort,
            },
        }
    )


class StrictControlTests(unittest.TestCase):
    def test_markdown_fence_is_accepted(self):
        body = """\
/codex-local control
~~~json
{
  "version": 2,
  "repository": "owner/repo",
  "control": {
    "id": "GH-43",
    "action": "status"
  }
}
~~~"""
        parsed = parse_control_comment(body)
        self.assertEqual(parsed.action, "status")

    def test_unknown_control_field_is_rejected(self):
        with self.assertRaises(ControlError):
            ControlCommand.from_dict(
                {
                    "version": 2,
                    "repository": "owner/repo",
                    "control": {
                        "id": "GH-43",
                        "action": "pause",
                        "shell": "rm -rf /",
                    },
                }
            )

    def test_status_does_not_change_settings_revision(self):
        settings = RuntimeSettings(revision=9)
        status = ControlCommand.from_dict(
            {
                "version": 2,
                "repository": "owner/repo",
                "control": {"id": "GH-43", "action": "status"},
            }
        )
        result = apply_control(settings, status)
        self.assertFalse(result.changed)
        self.assertEqual(result.settings.revision, 9)
        self.assertEqual(result.settings.last_control_id, "GH-43")


class GitHubControlProtocolTests(unittest.TestCase):
    def comment(self, body, *, author="owner", edited=False):
        return CommentView(
            comment_id=100,
            author=author,
            created_at="2026-10-02T00:00:00Z",
            updated_at=("2026-10-02T00:01:00Z" if edited else "2026-10-02T00:00:00Z"),
            body=body,
        )

    def body(self):
        return """\
/codex-local control
~~~json
{
  "version": 2,
  "repository": "owner/repo",
  "control": {
    "id": "GH-43",
    "action": "pause"
  }
}
~~~"""

    def test_authorized_immutable_issue_is_accepted(self):
        command = validate_control_issue(
            IssueView(43, "[codex-control] pause queue", "open", "owner"),
            [self.comment(self.body())],
            repository="owner/repo",
            authorized_users=["owner"],
        )
        self.assertEqual(command.action, "pause")

    def test_edited_control_comment_is_rejected(self):
        with self.assertRaises(GitHubControlError):
            validate_control_issue(
                IssueView(43, "[codex-control] pause queue", "open", "owner"),
                [self.comment(self.body(), edited=True)],
                repository="owner/repo",
                authorized_users=["owner"],
            )

    def test_issue_number_must_match_control_id(self):
        with self.assertRaises(GitHubControlError):
            validate_control_issue(
                IssueView(44, "[codex-control] pause queue", "open", "owner"),
                [self.comment(self.body())],
                repository="owner/repo",
                authorized_users=["owner"],
            )


class RuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime-settings.json"
        self.store = RuntimeSettingsStore(self.path)

    def test_model_change_preflights_both_roles_then_persists(self):
        seen = []

        def probe(role, choice):
            seen.append((role, choice.name, choice.effort))
            return ProbeResult(True, "fixture")

        applied = RuntimeControlService(self.store, probe).apply(model_command())
        self.assertEqual([row[0] for row in seen], ["executor", "reviewer"])
        self.assertEqual(applied.result.settings.executor_model, "supported-model")
        self.assertEqual(applied.result.settings.reviewer_model, "supported-model")
        self.assertTrue(self.path.is_file())
        loaded = self.store.load()
        self.assertEqual(loaded.revision, 1)
        self.assertEqual(loaded.last_control_id, "GH-43")

    def test_failed_preflight_keeps_previous_file_unchanged(self):
        previous = RuntimeSettings(executor_model="old", reviewer_model="old", revision=4)
        self.store.save(previous)
        before = self.path.read_bytes()

        def probe(role, choice):
            return ProbeResult(role != "reviewer", "not entitled")

        with self.assertRaises(RuntimeSettingsError):
            RuntimeControlService(self.store, probe).apply(model_command())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.load().executor_model, "old")

    def test_duplicate_control_does_not_probe_again(self):
        current = RuntimeSettings(last_control_id="GH-43", revision=3)
        self.store.save(current)
        calls = []

        def probe(role, choice):
            calls.append(role)
            return ProbeResult(True, "fixture")

        result = RuntimeControlService(self.store, probe).apply(model_command())
        self.assertEqual(calls, [])
        self.assertFalse(result.result.changed)


class EvidenceTests(unittest.TestCase):
    def test_bundle_is_created_under_task_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(tmp)
            task = store.write_json("GH-7", "task.json", {"id": "GH-7"})
            store.append_event("GH-7", "claimed", {"source": "github"})
            self.assertEqual(task.parent.name, "GH-7")
            rows = (task.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(rows[0])["event"], "claimed")


if __name__ == "__main__":
    unittest.main()
