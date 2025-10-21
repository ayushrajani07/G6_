"""Deprecated: use `python scripts/dev_smoke.py import-check`.

Kept as a thin wrapper for one release cycle; emits a one-time deprecation
warning unless G6_SUPPRESS_DEPRECATIONS is set. Exit codes mirror the new
implementation (0 success, non-zero failure).
"""
from __future__ import annotations

import os
import runpy
import sys

if not os.getenv("G6_SUPPRESS_DEPRECATIONS"):
    try:
        print("DEPRECATION: quick_import_test.py -> dev_smoke.py import-check")
    except Exception:
        pass

# Delegate by executing dev_smoke with argv override
try:
    from scripts import dev_smoke  # type: ignore
except Exception:
    # Fallback to runpy if import path differences occur
    sys.argv = [sys.argv[0], 'import-check']
    runpy.run_module('scripts.dev_smoke', run_name='__main__')
    raise SystemExit(0)

raise SystemExit(dev_smoke.main(['import-check']))
