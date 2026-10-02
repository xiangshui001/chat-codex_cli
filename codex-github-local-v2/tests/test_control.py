from pathlib import Path
import sys
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


def command(action="set-default-model", **extra):
    control = {"id": "GH-43", "action": action}
    control.update(extra)
    return ControlCommand.from_dict(
        {"version": 2, "repository": "owner/repo", "control": control}
    )


class ControlTests(unittest.TestCase):
    def test_change_both_default_models(self):
        settings = RuntimeSettings()
        result = apply_control(
            settings,
            command(role="both", model="supported-model", effort="high"),
        )
        self.assertTrue(result.changed)
        self.assertEqual(result.settings.executor_model, "supported-model")
        self.assertEqual(result.settings.reviewer_model, "supported-model")
        self.assertEqual(result.settings.executor_effort, "high")
        self.assertEqual(result.settings.revision, 1)

    def test_change_executor_only(self):
        settings = RuntimeSettings(reviewer_model="review-model")
        result = apply_control(
            settings,
            command(role="executor", model="worker-model", effort="medium"),
        )
        self.assertEqual(result.settings.executor_model, "worker-model")
        self.assertEqual(result.settings.reviewer_model, "review-model")

    def test_pause_and_resume(self):
        paused = apply_control(
            RuntimeSettings(),
            command("pause"),
        ).settings
        self.assertTrue(paused.paused)
        resumed_command = ControlCommand.from_dict(
            {
                "version": 2,
                "repository": "owner/repo",
                "control": {"id": "GH-44", "action": "resume"},
            }
        )
        resumed = apply_control(paused, resumed_command).settings
        self.assertFalse(resumed.paused)

    def test_duplicate_control_is_idempotent(self):
        settings = RuntimeSettings(last_control_id="GH-43", revision=4)
        result = apply_control(
            settings,
            command(role="both", model="other", effort="xhigh"),
        )
        self.assertFalse(result.changed)
        self.assertIs(result.settings, settings)
        self.assertEqual(result.settings.revision, 4)

    def test_non_model_actions_reject_model_fields(self):
        with self.assertRaises(ControlError):
            command("pause", model="should-not-be-here")

    def test_parse_exact_control_comment(self):
        body = """\
/codex-local control
~~~json
{
  "version": 2,
  "repository": "owner/repo",
  "control": {
    "id": "GH-43",
    "action": "set-default-model",
    "role": "executor",
    "model": "supported",
    "effort": "medium"
  }
}
~~~"""
        parsed = parse_control_comment(body)
        self.assertEqual(parsed.action, "set-default-model")
        self.assertEqual(parsed.model, "supported")


if __name__ == "__main__":
    unittest.main()
