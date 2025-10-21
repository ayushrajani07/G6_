#!/usr/bin/env python
"""Convenience wrapper for the preferred orchestrator runner.

Rationale: Short, memorable entrypoint for operators and docs.
Delegates to `scripts/run_orchestrator_loop.py` preserving CLI arguments.

Examples:
  python scripts/g6_run.py --config config/g6_config.json --interval 30 --cycles 5
  python scripts/g6_run.py --config config/g6_config.json --interval 60

Notes:
-- The legacy --enhanced flag is deprecated (no-op) and intentionally omitted here.
-- Does not introduce new env flags; `--cycles` still maps to G6_LOOP_MAX_CYCLES internally via underlying runner.
-- Exists only as a UX alias; can be removed if project later introduces a packaged console script.
"""
from __future__ import annotations

import pathlib
import runpy
import sys

_R = pathlib.Path(__file__).resolve().parent / 'run_orchestrator_loop.py'
if not _R.exists():  # defensive
    raise SystemExit("run_orchestrator_loop.py not found; repository may be inconsistent")

# Execute the target script's __main__ logic with forwarded argv (excluding this wrapper name)
sys.argv[0] = str(_R)
runpy.run_path(str(_R), run_name='__main__')
