"""Minimal test runner for diagnosing collection hangs.

Usage:
    python -m scripts.run_tests_minimal            # run full suite minimal mode
    python -m scripts.run_tests_minimal -k pattern # pass through args

Effects:
  - Sets PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 to avoid third-party plugin side effects.
  - Sets G6_TEST_MINIMAL=1 to skip heavy autouse fixtures (timing guard, metrics reset).
  - Falls back to normal exit code from pytest.
"""
from __future__ import annotations

import os
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Preserve explicit user choices if already set.
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("G6_TEST_MINIMAL", "1")
    print("[run-tests-minimal] Using minimal mode (no external pytest plugins, reduced fixtures)")
    cmd = [sys.executable, "-m", "pytest"] + argv
    return subprocess.call(cmd)

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
