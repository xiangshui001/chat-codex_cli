from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.control import ControlCommand, RuntimeControlService, RuntimeSettingsStore
from codex_github_local_v2.model_adapter import ProbeResult


class ModelAdapterContractTests(unittest.TestCase):
    def test_provider_neutral_model_choices_use_the_same_injected_contract(self):
        # A contract test, not a real provider. No HTTP/model request is made.
        seen = []

        def adapter(role, choice):
            seen.append((role, choice.name, choice.effort))
            return ProbeResult(True, "deterministic contract test")

        with tempfile.TemporaryDirectory() as tmp:
            service = RuntimeControlService(RuntimeSettingsStore(Path(tmp) / "settings.json"), adapter)
            for number, model in enumerate(("openai-compatible-model", "deepseek-chat", "qwen3"), 1):
                with self.subTest(model=model):
                    command = ControlCommand.from_dict({"version": 2, "repository": "local/smoke",
                        "control": {"id": f"GH-{number}", "action": "set-default-model",
                                    "role": "both", "model": model, "effort": "medium"}})
                    result = service.apply(command)
                    self.assertEqual(result.result.settings.executor_model, model)
                    self.assertEqual(seen[-2:], [("executor", model, "medium"), ("reviewer", model, "medium")])


if __name__ == "__main__":
    unittest.main()
