"""
Standardized label names for Prometheus metrics in the G6 platform.

This module centralizes common label keys to avoid typos and drift.
"""
from __future__ import annotations

from enum import Enum


class MetricLabel(str, Enum):
    index = "index"
    expiry = "expiry"
    strike = "strike"
    type = "type"
    provider = "provider"
    component = "component"
    error_type = "error_type"
    state = "state"


# Convenience bundles (advisory; not enforced)
ERROR_BASE = (MetricLabel.component.value, MetricLabel.error_type.value)
ERROR_BY_PROVIDER = (
    MetricLabel.provider.value,
    MetricLabel.component.value,
    MetricLabel.error_type.value,
)
ERROR_BY_INDEX = (
    MetricLabel.index.value,
    MetricLabel.component.value,
    MetricLabel.error_type.value,
)


__all__ = [
    "MetricLabel",
    "ERROR_BASE",
    "ERROR_BY_PROVIDER",
    "ERROR_BY_INDEX",
]
