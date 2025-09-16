#!/usr/bin/env python3
"""
health/health_checker.py

Runs health checks for system components and records results in Prometheus metrics.
Supports per-index checks automatically from index_registry.
"""
import time
import logging
from typing import Callable, Optional
try:  # optional registry import
    from src.utils.index_registry import list_indices  # type: ignore
except Exception:  # pragma: no cover
    def list_indices():  # fallback minimal stub
        return {}

# Add this before launching the subprocess
import sys
import os
from src.metrics.metrics import setup_metrics_server, MetricsRegistry

_METRICS_SINGLETON: Optional[MetricsRegistry] = None

def metrics_init() -> MetricsRegistry:
    global _METRICS_SINGLETON
    if _METRICS_SINGLETON is None:
        metrics, _ = setup_metrics_server(port=9108)
        _METRICS_SINGLETON = metrics
    return _METRICS_SINGLETON

logger = logging.getLogger(__name__)

def check_component(name: str, check_fn: Callable[[], bool], index: Optional[str] = None) -> None:
    """
    Run a health check for a given component and record metrics.

    Args:
        name: Component name (e.g., "broker_api", "redis", "influxdb").
        check_fn: Callable that returns True if healthy, False otherwise.
        index: Optional index symbol to tag the metric (e.g., "NIFTY").
    """
    metrics = metrics_init()
    start = time.time()
    # Use existing generic gauges or add lazily if needed
    status_metric = getattr(metrics, 'health_check_status', None)
    if status_metric is None:
        try:
            from prometheus_client import Gauge  # local import to avoid hard dep at module load
            status_metric = Gauge('g6_health_check_status', 'Health check status', ['component', 'index'])
            setattr(metrics, 'health_check_status', status_metric)
        except Exception:
            status_metric = None
    duration_metric = getattr(metrics, 'health_check_duration', None)
    if duration_metric is None:
        try:
            from prometheus_client import Gauge
            duration_metric = Gauge('g6_health_check_duration_seconds', 'Health check duration', ['component', 'index'])
            setattr(metrics, 'health_check_duration', duration_metric)
        except Exception:
            duration_metric = None

    try:
        healthy = bool(check_fn())
        if status_metric:
            status_metric.labels(component=name, index=index or "").set(1 if healthy else 0)
        logger.info(f"[HealthCheck] {name} {f'[{index}]' if index else ''} → {'healthy' if healthy else 'unhealthy'}")
    except Exception as e:
        if status_metric:
            status_metric.labels(component=name, index=index or "").set(0)
        logger.exception(f"[HealthCheck] {name} {f'[{index}]' if index else ''} → exception during check: {e}")
    finally:
        if duration_metric:
            duration_metric.labels(component=name, index=index or "").set(time.time() - start)

def check_all_indices(component_name: str, check_fn_factory: Callable[[str], Callable[[], bool]]) -> None:
    """
    Run a health check for every index in the registry.

    Args:
        component_name: Name of the component being checked.
        check_fn_factory: Function that takes an index symbol and returns a check_fn for that index.
    """
    for index in list_indices().keys():
        check_fn = check_fn_factory(index)
        check_component(component_name, check_fn, index=index)