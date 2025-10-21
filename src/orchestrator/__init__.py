"""Orchestration package public surface.

Historically this attempted to import a heavy Orchestrator implementation from
``.orchestrator`` at import time. That module is currently absent during the
progressive modularization (context/bootstrap/cycle/loop/status_writer waves).

The unconditional import caused a ``ModuleNotFoundError`` which prevented
lightweight utilities like ``status_writer`` from being imported, blocking
runtime status generation (e.g. LTP population). We now guard this import so
leaf modules can function independently. When/if an Orchestrator object is
introduced, this guard can be relaxed or replaced with a feature flag.
"""

from __future__ import annotations

import logging
from importlib import import_module

logger = logging.getLogger(__name__)

Orchestrator = None  # type: ignore  # Will be replaced if module becomes available.

try:
	# Deferred import: optional during refactor phase.
	_mod = import_module('.orchestrator', __name__)
	Orchestrator = getattr(_mod, 'Orchestrator', None)
	if Orchestrator is None:
		logger.debug("orchestrator.__init__: '.orchestrator' module loaded but no Orchestrator symbol found")
except ModuleNotFoundError:
	# Silent (debug-level) to avoid noisy logs in normal operation; surfaced during diagnostics earlier.
	logger.debug("orchestrator.__init__: optional '.orchestrator' module not present (expected during refactor)")
except Exception as e:  # pragma: no cover - defensive
	logger.warning("orchestrator.__init__: unexpected exception importing optional '.orchestrator': %s", e)

__all__ = ["Orchestrator"]
