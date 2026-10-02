from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.codex_adapter import CodexProbeRunner
from codex_github_local_v2.contract import ModelChoice


class CodexProbeTests(unittest.TestCase):
    def test_successful_probe_reports_available(self):
        completed = subprocess.CompletedProcess(["codex"], 0, stdout='{"type":"turn.completed"}\\n')
        with patch("codex_github_local_v2.codex_adapter.subprocess.run", return_value=completed) as run:
            result = CodexProbeRunner(("codex",), 30)("executor", ModelChoice("model-x", "high"))
        self.assertTrue(result.available)
        argv = run.call_args.args[0]
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "model-x")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_failed_probe_returns_redacted_bounded_diagnostic(self):
        completed = subprocess.CompletedProcess(["codex"], 1, stdout="unsupported model\\n")
        with patch("codex_github_local_v2.codex_adapter.subprocess.run", return_value=completed):
            result = CodexProbeRunner(("codex",), 30)("reviewer", ModelChoice("bad", "medium"))
        self.assertFalse(result.available)
        self.assertIn("unsupported model", result.reason)


if __name__ == "__main__":
    unittest.main()
