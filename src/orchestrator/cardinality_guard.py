"""Cardinality guard to disable high-cardinality per-option metrics when thresholds exceeded.

Environment Variables
---------------------
G6_CARDINALITY_MAX_SERIES: int (default 200000)
    Approximate upper bound on total time series the process should expose. If exceeded,
    the guard will set context flag `per_option_metrics_disabled` and increment
    metrics.cardinality_guard_trips_total.
G6_CARDINALITY_MIN_DISABLE_SECONDS: int (default 600)
    Minimum seconds to keep per-option metrics disabled before re-evaluating.
G6_CARDINALITY_REENABLE_FRACTION: float (default 0.90)
    Reactivation threshold expressed as fraction of limit (e.g., if 0.9 and limit=200k,
    re-enable when current series < 180k).

The Prometheus python client does not provide an inexpensive public API for number
of time series. We approximate using internal REGISTRY data structures guarded by
try/except to avoid crashes if library internals change.
"""
from __future__ import annotations

import logging
import os
import time

from prometheus_client import REGISTRY  # type: ignore

logger = logging.getLogger(__name__)


def _estimate_series() -> int:
    try:  # best-effort estimation (internal structure)
        collectors = getattr(REGISTRY, '_names_to_collectors', {})  # type: ignore[attr-defined]
        total = 0
        for collector in collectors.values():
            try:
                for metric in collector.collect():  # type: ignore[attr-defined]
                    try:
                        samples = getattr(metric, 'samples', [])
                        total += len(samples)
                    except Exception:
                        pass
            except Exception:
                pass
        return int(total)
    except Exception:
        return 0


def evaluate_cardinality_guard(ctx, force: bool = False):
    """Evaluate and possibly toggle per-option metrics emission based on series count.

    Sets ctx flag 'per_option_metrics_disabled' to True when limit exceeded.
    Re-enables when below hysteresis threshold.
    """
    metrics = getattr(ctx, 'metrics', None)
    now = time.time()
    max_series = int(os.environ.get('G6_CARDINALITY_MAX_SERIES', '200000'))
    min_disable = int(os.environ.get('G6_CARDINALITY_MIN_DISABLE_SECONDS', '600'))
    reenable_frac = float(os.environ.get('G6_CARDINALITY_REENABLE_FRACTION', '0.90'))
    disabled = bool(ctx.flag('per_option_metrics_disabled', False))  # type: ignore[attr-defined]
    last_toggle = ctx.flag('cardinality_last_toggle', None)  # type: ignore[attr-defined]

    series = _estimate_series()
    limit = max_series
    reenable_threshold = int(limit * reenable_frac)
    action = None

    try:
        if not disabled and series > limit:
            action = 'disable'
            ctx.set_flag('per_option_metrics_disabled', True)  # type: ignore[attr-defined]
            ctx.set_flag('cardinality_last_toggle', now)  # type: ignore[attr-defined]
            if metrics and hasattr(metrics, 'cardinality_guard_trips'):
                try:
                    metrics.cardinality_guard_trips.inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
        elif disabled:
            allow_reenable = force or (last_toggle and (now - float(last_toggle) >= min_disable))
            if allow_reenable and series < reenable_threshold:
                action = 'reenable'
                ctx.set_flag('per_option_metrics_disabled', False)  # type: ignore[attr-defined]
                ctx.set_flag('cardinality_last_toggle', now)  # type: ignore[attr-defined]
    except Exception:
        logger.debug("cardinality guard evaluation error", exc_info=True)

    if action:
        logger.warning("Cardinality guard action=%s series=%s limit=%s disabled=%s", action, series, limit, disabled)
    return action, series

__all__ = ["evaluate_cardinality_guard"]
