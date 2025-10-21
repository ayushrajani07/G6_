"""Metric descriptor system (Phase 3 initial).

Provides a data-driven description for a subset of metrics to enable future
lean registration and documentation generation. Initially migrating the
"resource utilization" metrics group as a proof of concept.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram, Summary

__all__ = [
    "MetricDescriptor",
    "MetricType",
    "RESOURCE_DESCRIPTORS",
    "PROVIDER_DESCRIPTORS",
    "LOOP_DESCRIPTORS",
    "register_descriptors",
]

MetricType = str  # Could be Literal["counter","gauge","histogram","summary"] later

@dataclass(frozen=True)
class MetricDescriptor:
    name: str
    documentation: str
    mtype: MetricType
    labels: Sequence[str] = ()
    buckets: Sequence[float] | None = None  # for histograms
    group: str = "resource_utilization"

RESOURCE_DESCRIPTORS: list[MetricDescriptor] = [
    MetricDescriptor("g6_memory_usage_mb", "Resident memory usage in MB", "gauge"),
    MetricDescriptor("g6_cpu_usage_percent", "Process CPU utilization percent", "gauge"),
    MetricDescriptor("g6_disk_io_operations_total", "Disk I/O operation count (increment)", "counter"),
    MetricDescriptor("g6_network_bytes_transferred_total", "Bytes transferred over network (cumulative)", "counter"),
]

# Provider latency / success descriptors (Phase 3 migration subset)
PROVIDER_DESCRIPTORS: list[MetricDescriptor] = [
    MetricDescriptor("g6_api_response_latency_ms", "Upstream API response latency distribution (ms)", "histogram", buckets=[5,10,20,50,100,200,400,800,1600,3200], group="provider"),
    MetricDescriptor("g6_api_success_rate_percent", "Successful API call percentage (rolling window)", "gauge", group="provider"),
    MetricDescriptor("g6_api_response_time_ms", "Average upstream API response time (ms, rolling)", "gauge", group="provider"),
]

# Loop / cycle timing core descriptors (non per-index; stick to gauges for snapshot values)
LOOP_DESCRIPTORS: list[MetricDescriptor] = [
    MetricDescriptor("g6_collection_cycle_time_seconds", "Average end-to-end collection cycle time (sliding)", "gauge", group="loop"),
    MetricDescriptor("g6_cycles_per_hour", "Observed cycles per hour (rolling)", "gauge", group="loop"),
    MetricDescriptor("g6_collection_cycle_in_progress", "Current collection cycle execution flag (1=in-progress,0=idle)", "gauge", group="loop"),
]

_TYPE_MAP = {
    "counter": Counter,
    "gauge": Gauge,
    "histogram": Histogram,
    "summary": Summary,
}

def register_descriptors(target, descriptors: Sequence[MetricDescriptor], maybe_register) -> None:
    """Register descriptor-defined metrics onto target using maybe_register hook."""
    for d in descriptors:
        if hasattr(target, _attr_name(d.name)):
            continue
        ctor = _TYPE_MAP.get(d.mtype)
        if ctor is None:
            continue
        try:
            if d.mtype == "histogram" and d.buckets:
                metric = maybe_register(d.group, _attr_name(d.name), ctor, d.name, d.documentation, d.labels, buckets=list(d.buckets))
            elif d.labels:
                metric = maybe_register(d.group, _attr_name(d.name), ctor, d.name, d.documentation, list(d.labels))
            else:
                metric = maybe_register(d.group, _attr_name(d.name), ctor, d.name, d.documentation)
            if metric is not None and not hasattr(target, _attr_name(d.name)):
                setattr(target, _attr_name(d.name), metric)
        except Exception:
            # Non-fatal: skip descriptor
            pass

def _attr_name(metric_name: str) -> str:
    # Convert prometheus metric name to attribute style (strip g6_ prefix)
    if metric_name.startswith("g6_"):
        metric_name = metric_name[3:]
    return metric_name
