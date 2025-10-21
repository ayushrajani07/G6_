"""Performance & throughput metric registrations (extracted from metrics.MetricsRegistry).

Refactor only: metric names, labels, ordering, and semantics unchanged.
"""
from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)


def init_performance_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('uptime_seconds', Gauge, 'g6_uptime_seconds', 'Process uptime in seconds')
    core('avg_cycle_time', Gauge, 'g6_collection_cycle_time_seconds', 'Average end-to-end collection cycle time (sliding)')
    core('processing_time_per_option', Gauge, 'g6_processing_time_per_option_seconds', 'Average processing time per option in last cycle')
    core('api_response_time', Gauge, 'g6_api_response_time_ms', 'Average upstream API response time (ms, rolling)')
    core('api_response_latency', Histogram, 'g6_api_response_latency_ms', 'Upstream API response latency distribution (ms)', buckets=[5,10,20,50,100,200,400,800,1600,3200])
    core('options_processed_total', Counter, 'g6_options_processed_total', 'Total option records processed')
    core('options_per_minute', Gauge, 'g6_options_processed_per_minute', 'Throughput of options processed per minute (rolling)')
    core('cycles_per_hour', Gauge, 'g6_cycles_per_hour', 'Observed cycles per hour (rolling)')
    core('api_success_rate', Gauge, 'g6_api_success_rate_percent', 'Successful API call percentage (rolling window)')
    core('collection_success_rate', Gauge, 'g6_collection_success_rate_percent', 'Successful collection cycle percentage (rolling window)')
    core('data_quality_score', Gauge, 'g6_data_quality_score_percent', 'Composite data quality score (validation completeness)')
    # Per-index data quality metrics (duplicate-safe direct instantiation preserves original semantics)
    from prometheus_client import Counter as _C  # local alias to avoid overshadow
    from prometheus_client import Gauge as _G
    try:
        registry.index_data_quality_score = _G('g6_index_data_quality_score_percent', 'Per-index data quality score percent', ['index'])
    except ValueError:
        logger.debug("Metric already exists: g6_index_data_quality_score_percent")
    try:
        registry.index_dq_issues_total = _C('g6_index_dq_issues_total', 'Total data quality issues observed', ['index'])
    except ValueError:
        logger.debug("Metric already exists: g6_index_dq_issues_total")
    registry.collection_cycle_in_progress = Gauge('g6_collection_cycle_in_progress', 'Current collection cycle execution flag (1=in-progress,0=idle)')
    registry.last_success_cycle_unixtime = Gauge('g6_last_success_cycle_unixtime', 'Unix timestamp of last fully successful collection cycle')
