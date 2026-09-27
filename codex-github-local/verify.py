#!/usr/bin/env python3
"""Offline tests only: fake GitHub, fake models, temporary Git repositories."""
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest


def main():
    root = Path(__file__).resolve().parent
    log = io.StringIO()
    start = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), "test_*.py")
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    evidence = root / "validation"
    evidence.mkdir(exist_ok=True)
    system = "posix" if os.name == "posix" else "windows"
    (evidence / f"{system}-offline-tests.log").write_text(log.getvalue(), encoding="utf-8")
    report = {"platform": sys.platform, "python": sys.version.split()[0], "tests_discovered": result.testsRun,
              "tests_executed": result.testsRun - len(result.skipped), "skipped": len(result.skipped),
              "failures": len(result.failures), "errors": len(result.errors), "passed": result.wasSuccessful(),
              "elapsed_seconds": round(time.monotonic() - start, 3), "real_models": False, "real_github": False,
              "posix_execution_covered": os.name == "posix" and not result.skipped}
    (evidence / f"{system}-offline-summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(log.getvalue() if not result.wasSuccessful() else "Offline checks completed.")
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
