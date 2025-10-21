"""Deprecated: use `python scripts/dev_smoke.py provider-check`.

Wrapper retained for one release cycle; prints deprecation notice unless
suppressed by G6_SUPPRESS_DEPRECATIONS. Delegates to dev_smoke subcommand.
"""
from __future__ import annotations

import os
import runpy
import sys

if not os.getenv("G6_SUPPRESS_DEPRECATIONS"):
    try:
        print("DEPRECATION: quick_provider_check.py -> dev_smoke.py provider-check")
    except Exception:
        pass

try:
    from scripts import dev_smoke  # type: ignore
except Exception:
    sys.argv = [sys.argv[0], 'provider-check']
    runpy.run_module('scripts.dev_smoke', run_name='__main__')
    raise SystemExit(0)

raise SystemExit(dev_smoke.main(['provider-check']))
