#!/usr/bin/env python
"""DEPRECATED STUB: scripts/run_live.py

Superseded by: scripts/run_orchestrator_loop.py
Stub Added: 2025-09-30 (Phase 1 Cleanup)
Planned Removal: Next minor release (see DEPRECATIONS.md)

Behavior: Emits warning (unless suppressed) and exits 0.

Migration:
    python scripts/run_orchestrator_loop.py --help

Suppress Warning:
    set G6_SUPPRESS_DEPRECATIONS=1
"""
from __future__ import annotations
import os, sys, logging

_suppress_unified = os.environ.get('G6_SUPPRESS_DEPRECATIONS','').lower() in {'1','true','yes','on'}
if not _suppress_unified:
    logging.warning('DEPRECATED: run_live.py -> use scripts/run_orchestrator_loop.py (see DEPRECATIONS.md)')

def main() -> int:  # noqa: D401
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
