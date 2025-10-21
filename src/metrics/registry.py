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

from collections.abc import Callable  # noqa: F401 (retained for backward compat hints)

from . import _singleton as _anchor  # central anchor
from . import metrics as _legacy

MetricsRegistry = _legacy.MetricsRegistry  # re-export for compatibility

def _new_registry() -> MetricsRegistry:
    """Construct a fresh MetricsRegistry and publish to central anchor.

    Avoid starting HTTP server (tests generally don't need duplicate port binds).
    """
    reg = MetricsRegistry()
    try:  # publish to central anchor only if empty to avoid clobbering active server singleton
        _anchor.set_singleton(reg)
    except Exception:  # pragma: no cover - defensive
        pass
    return reg

def get_registry(reset: bool = False) -> MetricsRegistry:
    """Return process-wide MetricsRegistry unified with central singleton anchor.

    This replaces the earlier ad-hoc module-local singleton which produced a
    second registry instance (breaking identity tests) when code imported
    `src.metrics.registry` before calling the public `get_metrics()` facade.

    Parameters
    ----------
    reset : bool
        If True, forces creation of a new MetricsRegistry (publishes it to the
        central anchor only if no existing instance was present). Intended for
        isolated test scenarios; production code should avoid reset semantics.
    """
    existing = _anchor.get_singleton()
    if existing is not None and not reset:
        return existing  # already unified
    if reset:
        return _new_registry()
    # Defer to legacy bootstrap path (will set anchor); fallback to direct construction
    try:
        reg = _legacy.get_metrics_singleton()
        if reg is None:  # legacy path failed (should be rare) -> direct new registry
            reg = _new_registry()
        return reg
    except Exception:
        return _new_registry()

__all__ = ["MetricsRegistry", "get_registry"]
