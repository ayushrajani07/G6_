#!/usr/bin/env python3
"""Basic sanity tests for the MetricsAdapter fallbacks.

These tests intentionally do not require a running Prometheus server; they only
check that the adapter loads and methods fail safely (return None / empty) in
typical environments where metrics server may not be up.
"""
from __future__ import annotations

import os
import pytest


def test_metrics_adapter_safe_import():
    try:
        from src.utils.metrics_adapter import get_metrics_adapter
    except Exception as e:
        pytest.fail(f"metrics_adapter import failed unexpectedly: {e}")


def test_metrics_adapter_safe_getters():
    from src.utils.metrics_adapter import get_metrics_adapter

    # Use default configuration (no prometheus URL override)
    ma = get_metrics_adapter()

    # All getters should be safe to call; they can return None/empty without raising
    ma.get_platform_metrics()
    ma.get_performance_metrics()
    ma.get_index_metrics()

    # Scalar getters should return None or numbers, but must not raise
    vals = [
        ma.get_cpu_percent(),
        ma.get_memory_usage_mb(),
        ma.get_api_success_rate_percent(),
        ma.get_api_latency_ms(),
        ma.get_collection_success_rate_percent(),
        ma.get_options_processed_total(),
        ma.get_options_per_minute(),
        ma.get_last_cycle_options_sum(),
    ]
    # No assertion on values; just ensure the call path is resilient
    assert len(vals) == 8
