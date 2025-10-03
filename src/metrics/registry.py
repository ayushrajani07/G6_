"""Metrics registry scaffold.

Phase 2 scaffold: This module will gradually absorb parts of the previous monolithic
`metrics.py` to separate concerns (construction vs. grouping vs. derived updates).

Current state: Provides a thin wrapper that delegates to existing `MetricsRegistry`
from `metrics.metrics` so imports can be migrated incrementally:

    from src.metrics.registry import get_registry

Long-term:
- Expose a factory building a slimmed registry object.
- Provide interfaces for group registration & derived metric updates.
- Support custom CollectorRegistry injection for tests.
"""
from __future__ import annotations

from typing import Tuple, Callable
from . import metrics as _legacy

MetricsRegistry = _legacy.MetricsRegistry  # re-export for compatibility

_singleton: MetricsRegistry | None = None

def get_registry(reset: bool = False) -> MetricsRegistry:
    """Return process-wide MetricsRegistry (delegates to legacy setup initially).

    Parameters
    ----------
    reset : bool
        If True, forces recreation (dev/test only)."""
    global _singleton
    if _singleton is not None and not reset:
        return _singleton
    # Leverage legacy setup function (without starting HTTP server again).
    # We call underlying constructor directly to avoid side effects.
    _singleton = MetricsRegistry()
    return _singleton

__all__ = ["MetricsRegistry", "get_registry"]
