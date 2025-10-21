"""Post-initialization recovery helpers for `MetricsRegistry`.

This module centralizes late fallback logic for a few metrics whose
registration can be skipped in rare edge cases (predicate gating,
import ordering failures, or optional subsystem inactivity during
startup). The goal is to keep `metrics.py` lean while preserving
observability guarantees expected by tests and operators.

Current responsibilities (minimal by design):
- panel_diff_truncated counter: ensures presence when panel diff
  instrumentation group was enabled but spec/group path skipped.
- vol_surface_quality_score gauge: only when analytics_vol_surface
  group is allowed (avoids spurious series when analytics disabled).
- events_last_full_unixtime gauge: provides a fresh timestamp even if
  the event bus lazy registration hasn't yet occurred before a test
  inspects the registry.

Design principles:
1. Idempotent: All operations check attribute existence before creating.
2. Best-effort: Swallow unexpected exceptions unless strict mode is enabled.
3. Narrow scope: Do not add broader category/performance recovery here—those
   are handled deterministically earlier in initialization.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

STRICT = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}


def post_init_recovery(registry: Any) -> None:
    """Apply minimal late recovery to ensure critical fallback metrics exist.

    Parameters
    ----------
    registry : MetricsRegistry
        Instance on which metric attributes may be attached.
    """
    # panel_diff_truncated counter
    try:
        if not hasattr(registry, 'panel_diff_truncated'):
            from prometheus_client import Counter as _C
            registry._maybe_register(  # type: ignore[attr-defined]
                'panel_diff',
                'panel_diff_truncated',
                _C,
                'g6_panel_diff_truncated_total',
                'Panel diff truncation events'
            )
    except Exception as e:  # pragma: no cover
        if STRICT:
            raise
        logger.error("panel_diff_truncated recovery failed: %s", e)

    # vol_surface_quality_score (only if group allowed)
    try:
        if getattr(registry, '_group_allowed', lambda g: False)('analytics_vol_surface') and not hasattr(registry, 'vol_surface_quality_score'):
            from prometheus_client import Gauge as _GV
            registry._maybe_register(  # type: ignore[attr-defined]
                'analytics_vol_surface',
                'vol_surface_quality_score',
                _GV,
                'g6_vol_surface_quality_score',
                'Vol surface quality score (0-100)',
                ['index']
            )
    except Exception as e:  # pragma: no cover
        if STRICT:
            raise
        logger.error("vol_surface_quality_score recovery failed: %s", e)

    # events_last_full_unixtime gauge & event bus import trigger
    try:
        try:
            import src.events.event_bus  # noqa: F401
        except Exception:
            pass
        # Avoid duplicate registration if metric name already exists in global registry even if attribute missing
        from prometheus_client import REGISTRY as _R
        names_map = getattr(_R, '_names_to_collectors', {})
        if not hasattr(registry, 'events_last_full_unixtime') and 'g6_events_last_full_unixtime' not in names_map:
            from prometheus_client import Gauge as _Ge
            registry.events_last_full_unixtime = _Ge(  # type: ignore[attr-defined]
                'g6_events_last_full_unixtime',
                'Last events full snapshot unix timestamp (s)'
            )
            try:  # set immediate timestamp value
                registry.events_last_full_unixtime.set(time.time())  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception as e:  # pragma: no cover
        if STRICT:
            raise
        logger.error("events_last_full_unixtime recovery failed: %s", e)


__all__ = ["post_init_recovery"]
