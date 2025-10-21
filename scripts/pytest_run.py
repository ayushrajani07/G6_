#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def _clear_env(keys: list[str]) -> None:
    for k in keys:
        try:
            if k in os.environ:
                del os.environ[k]
        except Exception:
            pass

def main() -> int:
    try:
        import pytest  # type: ignore
    except Exception:
        print("pytest is not installed in this environment", file=sys.stderr)
        return 2
    mode = sys.argv[1] if len(sys.argv) > 1 else "serial"
    # Always sanitize known-problem env vars that inject args or disable plugins
    _clear_env(["PYTEST_ADDOPTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"])
    # We want full features & plugins; set G6_TEST_MINIMAL off explicitly
    os.environ["G6_TEST_MINIMAL"] = "0"
    # Influx optional during tests to avoid orchestration hard dependency
    os.environ.setdefault("G6_INFLUX_OPTIONAL", "1")

    if mode == "serial":
        args = ["-q", "-n", "0"]
    elif mode == "parallel-subset":
        args = ["-q", "-ra", "-n", "auto", "-m", "not serial", "--durations=10"]
    elif mode == "fast-inner":
        args = ["-q", "-ra", "-k", "not slow and not integration and not perf and not serial", "--durations=10"]
    else:
        # passthrough any remaining args after mode
        args = sys.argv[1:]
    try:
        return int(pytest.main(args))
    except SystemExit as e:  # pytest may call sys.exit()
        return int(getattr(e, "code", 1) or 0)


if __name__ == "__main__":
    sys.exit(main())
