"""Run the original 30 tests against the minimally adapted execution engine."""
from pathlib import Path
import os
import sys
import unittest

FIXTURE = Path(__file__).resolve().parent / "upstream/automation/testing"


def load_tests(loader, tests, pattern):
    sys.path.insert(0, str(FIXTURE))
    import test_runner
    import test_reliability
    import test_cli_exit_codes
    modules = (test_runner, test_reliability, test_cli_exit_codes)
    if os.name != "posix":
        classes = (test_runner.IntegrationTests, test_reliability.ReliabilityIntegrationTests,
                   test_reliability.ProcessCleanupTests, test_cli_exit_codes.ExitCodeCLIIntegrationTests)
        for cls in classes:
            unittest.skip("Requires actual POSIX locking/process groups; run in Ubuntu/WSL")(cls)
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite
