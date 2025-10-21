"""Metrics updater extraction.

Provides focused helpers for updating Prometheus/metrics registry objects used
by unified collectors. Keeps unified_collectors lean while preserving all
original semantics and fallbacks.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    'update_per_index_metrics',
    'finalize_cycle_metrics',
]


def update_per_index_metrics(
    metrics: Any,
    *,
    index_symbol: str,
    per_index_start: float,
    per_index_option_count: int,
    per_index_option_processing_seconds: float,
    per_index_attempts: int,
    per_index_failures: int,
    per_index_success: bool,
    atm_strike: float,
) -> None:
    """Update metrics for a single index cycle.

    Mirrors original inline logic including error swallowing behavior.
    """
    if not metrics:
        return
    try:
        elapsed_index = time.time() - per_index_start
        _ = elapsed_index  # retained variable (could be used later for histogram)
        if per_index_option_count > 0:
            metrics.index_options_processed.labels(index=index_symbol).set(per_index_option_count)
            metrics.index_avg_processing_time.labels(index=index_symbol).set(
                per_index_option_processing_seconds / max(per_index_option_count, 1)
            )
        else:
            try:
                metrics.collection_errors.labels(index=index_symbol, error_type='no_options').inc()
            except Exception:
                pass
        metrics.index_last_collection_unixtime.labels(index=index_symbol).set(int(time.time()))
        metrics.index_current_atm.labels(index=index_symbol).set(float(atm_strike))
        try:
            metrics.mark_index_cycle(
                index=index_symbol, attempts=per_index_attempts, failures=per_index_failures
            )
        except Exception:
            rate = 100.0 if per_index_success else 0.0
            metrics.index_success_rate.labels(index=index_symbol).set(rate)
    except Exception:
        logger.debug(f"Failed index aggregate metrics for {index_symbol}", exc_info=True)


def finalize_cycle_metrics(
    metrics: Any,
    *,
    start_cycle_wall: float,
    cycle_start_ts: datetime.datetime,
    total_elapsed: float,
) -> None:
    """Record end-of-cycle metrics after all indices processed.

    Preserves original fallbacks: if mark_cycle fails, falls back to direct gauges.
    """
    if not metrics:
        return
    try:
        collection_time_elapsed = (datetime.datetime.now(datetime.UTC) - cycle_start_ts).total_seconds()
        metrics.collection_duration.observe(collection_time_elapsed)
        metrics.collection_cycles.inc()
        try:
            metrics.mark_cycle(
                success=True,
                cycle_seconds=total_elapsed,
                options_processed=getattr(metrics, '_last_cycle_options', 0) or 0,
                option_processing_seconds=getattr(metrics, '_last_cycle_option_seconds', 0.0) or 0.0,
            )
        except Exception:
            metrics.avg_cycle_time.set(total_elapsed)
            if total_elapsed > 0:
                try:
                    metrics.cycles_per_hour.set(3600.0 / total_elapsed)
                except Exception:
                    pass
        if hasattr(metrics, 'collection_cycle_in_progress'):
            try:
                metrics.collection_cycle_in_progress.set(0)
            except Exception:
                pass
    except Exception as e:  # pragma: no cover
        logger.error(f"Failed to update collection metrics: {e}")
