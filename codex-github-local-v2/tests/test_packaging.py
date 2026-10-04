import importlib
from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class PackagingTests(unittest.TestCase):
    def test_metadata_and_console_entrypoints_are_valid(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        from codex_github_local_v2 import __version__
        self.assertEqual(metadata["project"]["version"], __version__)
        scripts = metadata["project"]["scripts"]
        self.assertEqual(set(scripts), {"codex-github-local-v2", "codex-github-local-v2-control",
                                       "codex-github-local-v2-mvp0", "codex-github-local-v2-mvp1"})
        for target in scripts.values():
            module, function = target.split(":")
            self.assertTrue(callable(getattr(importlib.import_module(module), function)))


if __name__ == "__main__":
    unittest.main()
