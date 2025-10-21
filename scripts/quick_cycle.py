"""Deprecated: use `python scripts/dev_smoke.py one-cycle`.

Former helper to run a single orchestrator cycle. Replaced by the multi-tool.
This file intentionally left minimal to reduce maintenance surface.
"""
from __future__ import annotations

import os
import runpy
import sys

if not os.getenv("G6_SUPPRESS_DEPRECATIONS"):
	try:
		print("DEPRECATION: quick_cycle.py -> dev_smoke.py one-cycle")
	except Exception:
		pass

try:
	from scripts import dev_smoke  # type: ignore
except Exception:
	sys.argv = [sys.argv[0], 'one-cycle']
	runpy.run_module('scripts.dev_smoke', run_name='__main__')
	raise SystemExit(0)

raise SystemExit(dev_smoke.main(['one-cycle']))
