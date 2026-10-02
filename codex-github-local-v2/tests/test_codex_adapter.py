from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.codex_adapter import (
    CodexAdapterError,
    ExecSpec,
    build_exec_argv,
    classify_jsonl_line,
    probe_argv,
)
from codex_github_local_v2.contract import ModelChoice


class CodexAdapterTests(unittest.TestCase):
    def test_executor_uses_workspace_write_and_explicit_model(self):
        argv = build_exec_argv(
            ["codex"],
            ExecSpec(
                role="executor",
                choice=ModelChoice("model-x", "high"),
                sandbox="workspace-write",
                schema=Path("/tmp/worker.json"),
                output=Path("/tmp/out.json"),
            ),
        )
        self.assertIn("workspace-write", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "model-x")
        self.assertIn('model_reasoning_effort="high"', argv)

    def test_auto_model_omits_model_flag(self):
        argv = probe_argv(["codex"], ModelChoice("auto", "medium"))
        self.assertNotIn("--model", argv)
        self.assertIn("read-only", argv)

    def test_jsonl_error_is_terminal(self):
        event = classify_jsonl_line('{"type":"turn.failed","message":"unsupported model"}')
        self.assertTrue(event.terminal)
        self.assertEqual(event.error, "unsupported model")

    def test_invalid_jsonl_is_rejected(self):
        with self.assertRaises(CodexAdapterError):
            classify_jsonl_line("not-json")


if __name__ == "__main__":
    unittest.main()
