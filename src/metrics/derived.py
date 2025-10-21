"""Derived metrics update helpers.

This module centralizes logic formerly embedded in MetricsRegistry.mark_cycle and
MetricsRegistry.mark_index_cycle without altering behavior or metric naming.
All exception swallowing, guards, and semantics preserved for resilience.
"""
from __future__ import annotations

import time
from typing import Any


# Type hint protocol (optional minimal) to satisfy static checkers without import cycle
class _RegistryLike:  # pragma: no cover - structural only
    _cycle_total: int
    _cycle_success: int
    _ema_cycle_time: float | None
    _ema_alpha: float
    _last_cycle_options: int
    _last_cycle_option_seconds: float


def update_cycle_metrics(registry: _RegistryLike, success: bool, cycle_seconds: float,
                         options_processed: int, option_processing_seconds: float) -> None:
    """Update rolling cycle statistics and derived gauges.

    Mirrors previous MetricsRegistry.mark_cycle body.
    """
    registry._cycle_total += 1
    if success:
        registry._cycle_success += 1
        try:
            registry.last_success_cycle_unixtime.set(time.time())  # type: ignore[attr-defined]
        except Exception:
            pass
    # EMA update
    if registry._ema_cycle_time is None:
        registry._ema_cycle_time = cycle_seconds
    else:
        registry._ema_cycle_time = (registry._ema_alpha * cycle_seconds) + (1 - registry._ema_alpha) * registry._ema_cycle_time
    # Derived gauges
    if registry._ema_cycle_time:
        try:
            registry.avg_cycle_time.set(registry._ema_cycle_time)  # type: ignore[attr-defined]
            if registry._ema_cycle_time > 0:
                registry.cycles_per_hour.set(3600.0 / registry._ema_cycle_time)  # type: ignore[attr-defined]
        except Exception:
            pass
    # Success rate
    try:
        if registry._cycle_total > 0:
            rate = (registry._cycle_success / registry._cycle_total) * 100.0
            registry.collection_success_rate.set(rate)  # type: ignore[attr-defined]
    except Exception:
        pass
    # Throughput
    registry._last_cycle_options = options_processed
    registry._last_cycle_option_seconds = option_processing_seconds
    try:
        if cycle_seconds > 0:
            per_min = (options_processed / cycle_seconds) * 60.0
            registry.options_per_minute.set(per_min)  # type: ignore[attr-defined]
        if options_processed > 0 and option_processing_seconds > 0:
            registry.processing_time_per_option.set(option_processing_seconds / options_processed)  # type: ignore[attr-defined]
    except Exception:
        pass


def update_index_cycle_metrics(registry: Any, index: str, attempts: int, failures: int) -> None:
    """Record per-index cycle attempts/failures and update success metrics.

    Mirrors previous MetricsRegistry.mark_index_cycle.
    """
    if attempts < 0 or failures < 0:
        return
    try:
        if attempts > 0:
            registry.index_attempts_total.labels(index=index).inc(attempts)
        if failures > 0:
            registry.index_failures_total.labels(index=index, error_type='cycle').inc(failures)
    except Exception:
        pass
    try:
        registry.index_cycle_attempts.labels(index=index).set(attempts)
        success_pct = None
        if attempts > 0:
            success_pct = (attempts - failures) / attempts * 100.0
            registry.index_cycle_success_percent.labels(index=index).set(success_pct)
        else:
            try:
                registry.index_cycle_success_percent.labels(index=index).set(float('nan'))
            except Exception:
                pass
    except Exception:
        pass
