from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.claim import ClaimPaused, freeze_claim
from codex_github_local_v2.contract import TaskContract
from codex_github_local_v2.control import RuntimeSettings, RuntimeSettingsStore
from codex_github_local_v2.evidence import EvidenceStore


def task():
    return TaskContract.from_dict(
        {
            "version": 2,
            "repository": "owner/repo",
            "base_sha": "b" * 40,
            "task": {
                "id": "GH-9",
                "type": "documentation",
                "title": "Claim fixture",
                "goal": "Verify model defaults are frozen at claim.",
                "read_scope": ["**"],
                "write_scope": ["docs/"],
                "checks": [],
                "acceptance": ["fixture"],
                "model_policy": {
                    "executor": {
                        "primary": {"name": "runtime-default", "effort": "low"},
                        "fallbacks": []
                    },
                    "reviewer": {
                        "primary": {"name": "runtime-default", "effort": "low"},
                        "fallbacks": []
                    }
                },
                "budget": {"max_rounds": 1, "max_minutes": 10, "review_rounds": 1},
                "network": "deny",
                "production": "deny",
                "publication": {"mode": "none", "draft_on_incomplete_validation": True}
            }
        }
    )


class ClaimTests(unittest.TestCase):
    def test_claim_freezes_current_runtime_models_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = RuntimeSettingsStore(root / "runtime-settings.json")
            settings.save(
                RuntimeSettings(
                    executor_model="worker-a",
                    executor_effort="high",
                    reviewer_model="review-a",
                    reviewer_effort="medium",
                    revision=7,
                )
            )
            evidence = EvidenceStore(root / "runtime")
            resolved = freeze_claim(task(), settings_store=settings, evidence=evidence)
            self.assertEqual(resolved.model_policy.executor.primary.name, "worker-a")
            self.assertEqual(resolved.model_policy.reviewer.primary.name, "review-a")

            # Later remote controls cannot mutate this already-returned snapshot.
            settings.save(
                RuntimeSettings(
                    executor_model="worker-b",
                    reviewer_model="review-b",
                    revision=8,
                )
            )
            self.assertEqual(resolved.model_policy.executor.primary.name, "worker-a")
            job = root / "runtime" / "jobs" / "GH-9"
            self.assertTrue((job / "task.raw.json").is_file())
            self.assertTrue((job / "task.resolved.json").is_file())
            self.assertTrue((job / "runtime-settings.snapshot.json").is_file())

    def test_pause_prevents_new_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = RuntimeSettingsStore(root / "runtime-settings.json")
            settings.save(RuntimeSettings(paused=True))
            with self.assertRaises(ClaimPaused):
                freeze_claim(
                    task(),
                    settings_store=settings,
                    evidence=EvidenceStore(root / "runtime"),
                )


if __name__ == "__main__":
    unittest.main()
