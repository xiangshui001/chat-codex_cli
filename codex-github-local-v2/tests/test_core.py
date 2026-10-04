import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.contract import TaskContract
from codex_github_local_v2.controller import (
    Controller,
    ExecutionResult,
    PublicationResult,
    ReviewResult,
    ValidationResult,
)
from codex_github_local_v2.policy import HostPolicy, PolicyEngine, PolicyError
from codex_github_local_v2.routing import ProbeResult, select_model
from codex_github_local_v2.state import RunRecord, RunState, StateError


def contract():
    return TaskContract.from_dict(
        {
            "version": 2,
            "repository": "owner/repo",
            "base_sha": "a" * 40,
            "task": {
                "id": "GH-7",
                "type": "audit-readonly",
                "title": "Audit",
                "goal": "Read all code and write only the report.",
                "read_scope": ["**"],
                "write_scope": ["docs/report.md", "tasks/GH-7/"],
                "checks": ["handoff"],
                "acceptance": ["Only report files change"],
                "model_policy": {
                    "executor": {
                        "primary": {"name": "preferred", "effort": "medium"},
                        "fallbacks": [{"name": "fallback", "effort": "medium"}],
                    },
                    "reviewer": {
                        "primary": {"name": "reviewer", "effort": "high"},
                        "fallbacks": [],
                    },
                },
                "budget": {"max_rounds": 2, "max_minutes": 30, "review_rounds": 1},
                "network": "deny",
                "production": "deny",
                "publication": {"mode": "pr", "draft_on_incomplete_validation": True},
                "context": "fixture",
            },
        }
    )


class PolicyTests(unittest.TestCase):
    def test_read_all_write_narrow(self):
        task = contract()
        policy = PolicyEngine(
            HostPolicy(
                read_roots=("**",),
                write_roots=("docs/", "tasks/"),
                protected_paths=("secrets/",),
            ),
            task,
        )
        self.assertTrue(policy.can_read("app/server.py"))
        self.assertTrue(policy.can_write("docs/report.md"))
        self.assertTrue(policy.can_write("tasks/GH-7/handoff.md"))
        self.assertFalse(policy.can_write("app/server.py"))

    def test_host_policy_caps_task(self):
        task = contract()
        with self.assertRaises(PolicyError):
            PolicyEngine(
                HostPolicy(read_roots=("docs/",), write_roots=("docs/", "tasks/")),
                task,
            )


class StateTests(unittest.TestCase):
    def test_invalid_transition_is_rejected(self):
        record = RunRecord("GH-7")
        with self.assertRaises(StateError):
            record.transition(RunState.EXECUTING)


class RoutingTests(unittest.TestCase):
    def test_fallback_after_preflight_failure(self):
        task = contract()

        def probe(choice):
            return ProbeResult(choice.name == "fallback", "not entitled")

        selected = select_model(task.model_policy.executor, probe)
        self.assertEqual(selected.choice.name, "fallback")
        self.assertEqual(selected.fallback_index, 1)


class FakeBackend:
    def __init__(self, validation="pass"):
        self.validation = validation
        self.drafts = []

    def probe_model(self, role, choice):
        return ProbeResult(True, "fixture")

    def execute(self, task, model, attempt):
        return ExecutionResult(True, f"attempt {attempt}")

    def validate(self, task, attempt):
        return ValidationResult(self.validation, "browser unavailable" if self.validation == "unavailable" else "ok")

    def review(self, task, model, attempt):
        return ReviewResult("pass", "review pass")

    def publish(self, task, *, draft):
        self.drafts.append(draft)
        return PublicationResult(True, "PR #1")


class ControllerTests(unittest.TestCase):
    def test_happy_path_opens_pr(self):
        backend = FakeBackend()
        record = Controller(backend).run(contract())
        self.assertEqual(record.state, RunState.PR_OPEN)
        self.assertEqual(backend.drafts, [False])

    def test_unavailable_validation_becomes_draft_not_failure(self):
        backend = FakeBackend(validation="unavailable")
        record = Controller(backend).run(contract())
        self.assertEqual(record.state, RunState.PR_OPEN)
        self.assertEqual(backend.drafts, [True])
        self.assertIn(RunState.MANUAL_REVIEW_REQUIRED, [event.state for event in record.events])


if __name__ == "__main__":
    unittest.main()
