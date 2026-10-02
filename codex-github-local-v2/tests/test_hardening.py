from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.locking import AlreadyRunning, single_instance_lock
from codex_github_local_v2.control import RuntimeSettingsError, RuntimeSettingsStore


class RuntimeSettingsHardeningTests(unittest.TestCase):
    def test_string_false_is_not_accepted_as_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "paused": "false",
                        "executor": {"model": "auto", "effort": "medium"},
                        "reviewer": {"model": "auto", "effort": "high"},
                        "revision": 0,
                        "last_control_id": None,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeSettingsError):
                RuntimeSettingsStore(path).load()

    def test_unknown_persisted_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "paused": False,
                        "executor": {"model": "auto", "effort": "medium"},
                        "reviewer": {"model": "auto", "effort": "high"},
                        "revision": 0,
                        "last_control_id": None,
                        "shell": "unexpected",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeSettingsError):
                RuntimeSettingsStore(path).load()


class LockTests(unittest.TestCase):
    def test_second_watcher_cannot_take_same_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.lock"
            with single_instance_lock(path):
                with self.assertRaises(AlreadyRunning):
                    with single_instance_lock(path):
                        pass


if __name__ == "__main__":
    unittest.main()
