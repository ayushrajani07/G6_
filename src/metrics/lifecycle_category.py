"""Lifecycle hygiene metric registrations.

Extracted from temporary placement in storage_category. Covers:
 - g6_compressed_files_total (Counter, label: type)
 - g6_retention_files_deleted_total (Counter)
 - g6_quarantine_scan_seconds (Histogram)

Registration happens only if lifecycle group is allowed.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:  # pragma: no cover - type hint only
    from .registry import MetricsRegistry  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = ["init_lifecycle_metrics"]

def init_lifecycle_metrics(registry: MetricsRegistry) -> None:
    try:
        core = registry._core_reg  # type: ignore[attr-defined]
        core('compressed_files_total', Counter, 'g6_compressed_files_total', 'Lifecycle compression operations performed (files compressed)', ['type'])
        core('retention_files_deleted', Counter, 'g6_retention_files_deleted_total', 'Retention pruning deletions performed')
        core('quarantine_scan_seconds', Histogram, 'g6_quarantine_scan_seconds', 'Latency scanning quarantine/retention directories.')
        core('retention_candidates', Gauge, 'g6_retention_candidates', 'Current cycle count of aged compressed artifacts eligible for deletion (pre-limit).')
        core('retention_scan_seconds', Histogram, 'g6_retention_scan_seconds', 'Latency of retention pruning candidate enumeration & deletion phase.')
        core('retention_delete_limit', Gauge, 'g6_retention_delete_limit', 'Configured maximum deletions allowed per retention cycle.')
        core('retention_candidate_age_seconds', Histogram, 'g6_retention_candidate_age_seconds', 'Age (seconds) distribution for eligible retention candidates.')
    except Exception:
        logger.debug("init_lifecycle_metrics failed", exc_info=True)
