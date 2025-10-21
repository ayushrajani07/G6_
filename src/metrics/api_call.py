"""API call related metrics and helper logic (extracted from metrics.py).

Refactor only: metric names and semantics unchanged.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from .metrics import MetricsRegistry

def init_api_call_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    # Gauges / histograms already initialized in performance module except success rate & latency metrics.
    # Success rate gauge & latency histogram delegated to performance module; this function ensures presence
    # if performance metrics initialization was skipped for any reason (defensive).
    try:
        if not hasattr(registry, 'api_success_rate'):
            core('api_success_rate', __import__('prometheus_client').Gauge, 'g6_api_success_rate_percent', 'Successful API call percentage (rolling window)')
    except Exception:
        pass
    try:
        if not hasattr(registry, 'api_response_time'):
            core('api_response_time', __import__('prometheus_client').Gauge, 'g6_api_response_time_ms', 'Average upstream API response time (ms, rolling)')
    except Exception:
        pass
    try:
        if not hasattr(registry, 'api_response_latency'):
            core('api_response_latency', __import__('prometheus_client').Histogram, 'g6_api_response_latency_ms', 'Upstream API response latency distribution (ms)', buckets=[5,10,20,50,100,200,400,800,1600,3200])
    except Exception:
        pass


def mark_api_call(registry: MetricsRegistry, success: bool, latency_ms: float | None = None) -> None:
    """Track API call statistics for success rate and latency EMA.

    Mirrors previous MetricsRegistry.mark_api_call behavior.
    """
    registry._api_calls += 1  # type: ignore[attr-defined]
    if not success:
        registry._api_failures += 1  # type: ignore[attr-defined]
    try:
        if registry._api_calls > 0:  # type: ignore[attr-defined]
            success_rate = (1 - (registry._api_failures / registry._api_calls)) * 100.0  # type: ignore[attr-defined]
            try:
                registry.api_success_rate.set(success_rate)  # type: ignore[attr-defined]
            except Exception:
                pass
        if latency_ms is not None and latency_ms >= 0:
            current = getattr(registry, '_api_latency_ema', None)
            alpha = 0.3
            if current is None:
                current = latency_ms
            else:
                current = alpha * latency_ms + (1 - alpha) * current
            registry._api_latency_ema = current  # type: ignore[attr-defined]
            try:
                registry.api_response_time.set(current)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                registry.api_response_latency.observe(latency_ms)  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
