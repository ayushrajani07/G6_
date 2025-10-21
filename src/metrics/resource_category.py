"""Resource utilization metric registrations (extracted).

Refactor only.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge


def init_resource_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('memory_usage_mb', Gauge, 'g6_memory_usage_mb', 'Resident memory usage in MB')
    core('cpu_usage_percent', Gauge, 'g6_cpu_usage_percent', 'Process CPU utilization percent')
    core('disk_io_operations', Counter, 'g6_disk_io_operations_total', 'Disk I/O operation count (increment)')
    core('network_bytes_transferred', Counter, 'g6_network_bytes_transferred_total', 'Bytes transferred over network (cumulative)')
