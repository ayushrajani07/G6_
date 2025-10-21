"""Cache, batching & error breakdown metric registrations (extracted)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge


def init_cache_error_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('cache_hit_rate', Gauge, 'g6_cache_hit_rate_percent', 'Cache hit rate percent (rolling)')
    core('cache_size_items', Gauge, 'g6_cache_items', 'Number of objects in cache')
    core('cache_memory_mb', Gauge, 'g6_cache_memory_mb', 'Approximate cache memory footprint (MB)')
    core('cache_evictions', Counter, 'g6_cache_evictions_total', 'Total cache evictions')
    core('batch_efficiency', Gauge, 'g6_batch_efficiency_percent', 'Batch efficiency percent vs target size')
    core('avg_batch_size', Gauge, 'g6_avg_batch_size', 'Average batch size (rolling)')
    core('batch_processing_time', Gauge, 'g6_batch_processing_time_seconds', 'Average batch processing time (rolling)')
    core('total_errors', Counter, 'g6_total_errors_total', 'Total errors (all categories)')
    core('api_errors', Counter, 'g6_api_errors_total', 'API related errors')
    core('network_errors', Counter, 'g6_network_errors_total', 'Network related errors')
    core('data_errors', Counter, 'g6_data_errors_total', 'Data validation errors')
    core('error_rate_per_hour', Gauge, 'g6_error_rate_per_hour', 'Error rate per hour (derived)')
    from prometheus_client import Counter as _C
    registry.metric_stall_events = _C('g6_metric_stall_events_total', 'Metric stall detection events', ['metric'])
