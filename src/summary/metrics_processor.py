#!/usr/bin/env python3
"""
G6 Platform Metrics Processor - High Level Metrics Hub

This module serves as the central metrics processing and distribution hub for the G6 platform.
It collects all metrics from the Prometheus server, processes them with intuitive naming,
and supplies clean, organized metrics to all processes in need.

Architecture:
- Single source of truth for all platform metrics
- Prometheus-based data pipeline 
- Intuitive metric naming and organization
- Real-time metric processing and distribution
- Eliminates metric duplication across the platform

Usage:
    from src.summary.metrics_processor import MetricsProcessor
    
    processor = MetricsProcessor()
    metrics = processor.get_all_metrics()
    performance = processor.get_performance_metrics()
    indices = processor.get_index_metrics()
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from src.utils.timeutils import utc_now

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Platform performance metrics with intuitive names."""
    # Timing Metrics
    uptime_seconds: float = 0.0
    collection_cycle_time: float = 0.0
    processing_time_per_option: float = 0.0
    api_response_time: float = 0.0

    # Throughput Metrics
    options_processed_total: int = 0
    options_per_minute: float = 0.0
    cycles_completed: int = 0
    cycles_per_hour: float = 0.0

    # Success Rates
    api_success_rate: float = 0.0
    collection_success_rate: float = 0.0
    data_quality_score: float = 0.0

    # Resource Utilization
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    disk_io_operations: int = 0
    network_bytes_transferred: int = 0


@dataclass
class CollectionMetrics:
    """Data collection metrics with intuitive names."""
    # Cache Performance
    cache_hit_rate: float = 0.0
    cache_size_items: int = 0
    cache_memory_mb: float = 0.0
    cache_evictions: int = 0

    # Batch Processing
    batch_efficiency: float = 0.0
    avg_batch_size: float = 0.0
    batch_processing_time: float = 0.0

    # Error Tracking
    total_errors: int = 0
    api_errors: int = 0
    network_errors: int = 0
    data_errors: int = 0
    error_rate_per_hour: float = 0.0


@dataclass
class IndexMetrics:
    """Index-specific metrics with intuitive names."""
    options_processed: int = 0
    avg_processing_time: float = 0.0
    success_rate: float = 0.0
    last_collection_time: str | None = None
    atm_strike_current: float | None = None
    volatility_current: float | None = None
    current_cycle_legs: int = 0
    cumulative_legs: int = 0
    data_quality_score: float = 0.0
    data_quality_issues: int = 0


@dataclass
class StorageMetrics:
    """Storage and persistence metrics with intuitive names."""
    # CSV Storage
    csv_files_created: int = 0
    csv_records_written: int = 0
    csv_write_errors: int = 0
    csv_disk_usage_mb: float = 0.0
    csv_last_write_time: str | None = None

    # InfluxDB Storage
    influxdb_points_written: int = 0
    influxdb_write_success_rate: float = 0.0
    influxdb_connection_status: str = "unknown"
    influxdb_query_performance: float = 0.0
    influxdb_last_write_time: str | None = None

    # Backup Status
    backup_files_created: int = 0
    last_backup_time: str | None = None
    backup_size_mb: float = 0.0


@dataclass
class PlatformMetrics:
    """Complete platform metrics structure."""
    performance: PerformanceMetrics
    collection: CollectionMetrics
    indices: dict[str, IndexMetrics]
    storage: StorageMetrics
    last_updated: str
    collection_cycle: int = 0


class MetricsProcessor:
    """High-level metrics processor for the G6 platform."""

    def __init__(self, prometheus_url: str = "http://127.0.0.1:9108/metrics"):
        self.prometheus_url = prometheus_url
        self.last_metrics: PlatformMetrics | None = None
        self.metrics_cache_ttl = 5.0  # Cache metrics for 5 seconds
        self.last_fetch_time = 0.0
        # Market-hours gating + rate limit state
        self._last_closed_notice_ts: float = 0.0
        self._closed_notice_interval = 300.0  # at most once every 5 minutes

        # Prometheus metric name mappings to intuitive names
        self.metric_mappings = {
            # Performance Metrics
            "g6_uptime_seconds": "uptime_seconds",
            "g6_avg_cycle_time_seconds": "collection_cycle_time",
            "g6_processing_time_per_option_seconds": "processing_time_per_option",
            "g6_api_latency_ema_ms": "api_response_time",
            "g6_options_processed_total": "options_processed_total",
            "g6_options_per_minute": "options_per_minute",
            "g6_collection_cycles_total": "cycles_completed",
            "g6_cycles_per_hour": "cycles_per_hour",
            "g6_api_success_rate_percent": "api_success_rate",
            "g6_collection_success_rate_percent": "collection_success_rate",
            "g6_data_quality_score_percent": "data_quality_score",
            "g6_memory_usage_mb": "memory_usage_mb",
            "g6_cpu_usage_percent": "cpu_usage_percent",
            "g6_disk_io_operations_total": "disk_io_operations",
            "g6_network_bytes_transferred_total": "network_bytes_transferred",

            # Per-Index Metrics
            "g6_index_options_processed": "current_cycle_legs",
            "g6_index_options_processed_total": "options_processed",
            "g6_index_avg_processing_time_seconds": "avg_processing_time",
            "g6_index_cycle_success_percent": "success_rate",
            "g6_index_last_collection_unixtime": "last_collection_time",
            "g6_index_current_atm": "atm_strike_current",
            "g6_index_data_quality_score_percent": "data_quality_score",
            "g6_index_dq_issues_total": "data_quality_issues",
        }

    def fetch_prometheus_metrics(self) -> dict[str, Any]:
        """Fetch raw metrics from Prometheus server."""
        try:
            response = requests.get(self.prometheus_url, timeout=5)
            if response.status_code != 200:
                logger.warning(f"Prometheus server returned {response.status_code}")
                return {}

            return self._parse_prometheus_text(response.text)

        except requests.exceptions.RequestException as e:
            logger.warning(f"Cannot connect to Prometheus metrics server: {e}")
            try:
                from src.error_handling import handle_api_error
                handle_api_error(e, component="summary.metrics_processor", context={"op": "fetch_prometheus"})
            except Exception:
                pass
            return {}
        except Exception as e:
            logger.error(f"Error fetching Prometheus metrics: {e}")
            try:
                from src.error_handling import handle_api_error
                handle_api_error(e, component="summary.metrics_processor", context={"op": "fetch_prometheus"})
            except Exception:
                pass
            return {}

    def _parse_prometheus_text(self, metrics_text: str) -> dict[str, Any]:
        """Parse Prometheus text format into structured metrics."""
        # metrics structure: name -> ( 'default' -> {value, labels} ) OR name -> { (label_tuple) -> {value, labels} }
        metrics: dict[str, dict[Any, dict[str, Any]]] = {}

        for line in metrics_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                # Parse metric line: metric_name{labels} value
                if '{' in line:
                    # Metric with labels
                    metric_part, value_part = line.rsplit(' ', 1)
                    metric_name, labels_part = metric_part.split('{', 1)
                    labels_part = labels_part.rstrip('}')

                    # Parse labels
                    labels = {}
                    if labels_part:
                        for label_pair in labels_part.split(','):
                            if '=' in label_pair:
                                key, val = label_pair.split('=', 1)
                                labels[key.strip()] = val.strip().strip('"')

                    # Store metric with labels
                    if metric_name not in metrics:
                        metrics[metric_name] = {}

                    label_key = tuple(sorted(labels.items())) if labels else 'default'
                    metrics[metric_name][label_key] = {
                        'value': float(value_part),
                        'labels': labels
                    }
                else:
                    # Simple metric without labels
                    metric_name, value_part = line.rsplit(' ', 1)
                    metrics[metric_name] = {'default': {'value': float(value_part), 'labels': {}}}

            except Exception as e:
                logger.debug(f"Failed to parse metric line '{line}': {e}")
                try:
                    from src.error_handling import handle_data_error
                    handle_data_error(e, component="summary.metrics_processor", context={"op": "parse_line", "line": line[:128]})
                except Exception:
                    pass
                continue

        return metrics

    def _get_metric_value(self, prometheus_metrics: dict[str, Any], metric_name: str,
                         labels: dict[str, str] | None = None) -> float | None:
        """Get metric value from parsed Prometheus data."""
        if metric_name not in prometheus_metrics:
            return None

        metric_data = prometheus_metrics[metric_name]

        if labels:
            # Find matching labels
            label_key = tuple(sorted(labels.items()))
            if label_key in metric_data:
                return metric_data[label_key]['value']
        else:
            # Get first available value or default
            if 'default' in metric_data:
                return metric_data['default']['value']
            elif len(metric_data) > 0:
                return next(iter(metric_data.values()))['value']

        return None

    def _get_index_metric_value(self, prometheus_metrics: dict[str, Any],
                               metric_name: str, index: str) -> float | None:
        """Get index-specific metric value."""
        return self._get_metric_value(prometheus_metrics, metric_name, {'index': index})

    def _sum_metric_all_labels(self, prometheus_metrics: dict[str, Any], metric_name: str) -> float:
        """Sum all values for a labeled metric.

        If the metric is not present, returns 0. If a 'default' (unlabeled) value is present,
        it will be included in the sum only if there are no other labeled series. This keeps
        behavior intuitive for counters that may exist in either form.
        """
        if metric_name not in prometheus_metrics:
            return 0.0

        series = prometheus_metrics[metric_name]
        # If only default exists, return it; otherwise sum all non-default entries
        if isinstance(series, dict):
            if set(series.keys()) == {"default"}:
                return float(series["default"].get("value", 0.0))
            total = 0.0
            for key, entry in series.items():
                if key == "default":
                    # Skip default when labeled time series are present
                    continue
                try:
                    total += float(entry.get("value", 0.0))
                except Exception:
                    continue
            return total
        return 0.0

    def process_performance_metrics(self, prometheus_metrics: dict[str, Any]) -> PerformanceMetrics:
        """Process performance metrics from Prometheus data."""
        return PerformanceMetrics(
            uptime_seconds=self._get_metric_value(prometheus_metrics, "g6_uptime_seconds") or 0.0,
            collection_cycle_time=self._get_metric_value(prometheus_metrics, "g6_avg_cycle_time_seconds") or 0.0,
            processing_time_per_option=self._get_metric_value(prometheus_metrics, "g6_processing_time_per_option_seconds") or 0.0,
            api_response_time=self._get_metric_value(prometheus_metrics, "g6_api_latency_ema_ms") or 0.0,
            options_processed_total=int(self._get_metric_value(prometheus_metrics, "g6_options_processed_total") or 0),
            options_per_minute=self._get_metric_value(prometheus_metrics, "g6_options_per_minute") or 0.0,
            cycles_completed=int(self._get_metric_value(prometheus_metrics, "g6_collection_cycles_total") or 0),
            cycles_per_hour=self._get_metric_value(prometheus_metrics, "g6_cycles_per_hour") or 0.0,
            api_success_rate=self._get_metric_value(prometheus_metrics, "g6_api_success_rate_percent") or 0.0,
            collection_success_rate=self._get_metric_value(prometheus_metrics, "g6_collection_success_rate_percent") or 0.0,
            data_quality_score=self._get_metric_value(prometheus_metrics, "g6_data_quality_score_percent") or 0.0,
            memory_usage_mb=self._get_metric_value(prometheus_metrics, "g6_memory_usage_mb") or 0.0,
            cpu_usage_percent=self._get_metric_value(prometheus_metrics, "g6_cpu_usage_percent") or 0.0,
            disk_io_operations=int(self._get_metric_value(prometheus_metrics, "g6_disk_io_operations_total") or 0),
            network_bytes_transferred=int(self._get_metric_value(prometheus_metrics, "g6_network_bytes_transferred_total") or 0),
        )

    def process_collection_metrics(self, prometheus_metrics: dict[str, Any]) -> CollectionMetrics:
        """Process collection metrics from Prometheus data."""
        # Effective totals: prefer legacy unlabelled totals if present (>0), else sum across labeled series
        api_total_legacy = int(self._get_metric_value(prometheus_metrics, "g6_api_errors_total") or 0)
        api_total_labeled = int(self._sum_metric_all_labels(prometheus_metrics, "g6_api_errors_by_provider_total"))
        api_errors_eff = api_total_legacy if api_total_legacy > 0 else api_total_labeled

        net_total_legacy = int(self._get_metric_value(prometheus_metrics, "g6_network_errors_total") or 0)
        net_total_labeled = int(self._sum_metric_all_labels(prometheus_metrics, "g6_network_errors_by_provider_total"))
        network_errors_eff = net_total_legacy if net_total_legacy > 0 else net_total_labeled

        data_total_legacy = int(self._get_metric_value(prometheus_metrics, "g6_data_errors_total") or 0)
        data_total_labeled = int(self._sum_metric_all_labels(prometheus_metrics, "g6_data_errors_by_index_total"))
        data_errors_eff = data_total_legacy if data_total_legacy > 0 else data_total_labeled

        # Calculate derived metrics
        total_errors = api_errors_eff + network_errors_eff + data_errors_eff

        uptime_hours = (self._get_metric_value(prometheus_metrics, "g6_uptime_seconds") or 0) / 3600
        error_rate_per_hour = total_errors / max(uptime_hours, 1.0)

        return CollectionMetrics(
            cache_hit_rate=self._get_metric_value(prometheus_metrics, "g6_cache_hit_rate_percent") or 0.0,
            cache_size_items=int(self._get_metric_value(prometheus_metrics, "g6_cache_size_items") or 0),
            cache_memory_mb=self._get_metric_value(prometheus_metrics, "g6_cache_memory_mb") or 0.0,
            cache_evictions=int(self._get_metric_value(prometheus_metrics, "g6_cache_evictions_total") or 0),
            batch_efficiency=self._get_metric_value(prometheus_metrics, "g6_batch_efficiency_percent") or 0.0,
            avg_batch_size=self._get_metric_value(prometheus_metrics, "g6_avg_batch_size") or 0.0,
            batch_processing_time=self._get_metric_value(prometheus_metrics, "g6_batch_processing_time_seconds") or 0.0,
            total_errors=total_errors,
            api_errors=api_errors_eff,
            network_errors=network_errors_eff,
            data_errors=data_errors_eff,
            error_rate_per_hour=error_rate_per_hour,
        )

    def process_index_metrics(self, prometheus_metrics: dict[str, Any]) -> dict[str, IndexMetrics]:
        """Process index-specific metrics from Prometheus data."""
        indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"]
        index_metrics = {}

        for index in indices:
            # Get last collection timestamp and format it
            last_collection_ts = self._get_index_metric_value(prometheus_metrics, "g6_index_last_collection_unixtime", index)
            last_collection_time = None
            if last_collection_ts:
                try:
                    dt = datetime.fromtimestamp(last_collection_ts, tz=UTC)
                    last_collection_time = dt.strftime("%H:%M:%S")
                except Exception:
                    last_collection_time = None

            index_metrics[index] = IndexMetrics(
                options_processed=int(self._get_index_metric_value(prometheus_metrics, "g6_index_options_processed_total", index) or 0),
                avg_processing_time=self._get_index_metric_value(prometheus_metrics, "g6_index_avg_processing_time_seconds", index) or 0.0,
                success_rate=self._get_index_metric_value(prometheus_metrics, "g6_index_cycle_success_percent", index) or 0.0,
                last_collection_time=last_collection_time,
                atm_strike_current=self._get_index_metric_value(prometheus_metrics, "g6_index_current_atm", index),
                volatility_current=self._get_index_metric_value(prometheus_metrics, "g6_index_implied_volatility", index),
                current_cycle_legs=int(self._get_index_metric_value(prometheus_metrics, "g6_index_options_processed", index) or 0),
                cumulative_legs=int(self._get_index_metric_value(prometheus_metrics, "g6_index_options_processed_total", index) or 0),
                data_quality_score=self._get_index_metric_value(prometheus_metrics, "g6_index_data_quality_score_percent", index) or 0.0,
                data_quality_issues=int(self._get_index_metric_value(prometheus_metrics, "g6_index_dq_issues_total", index) or 0),
            )

        return index_metrics

    def process_storage_metrics(self, prometheus_metrics: dict[str, Any]) -> StorageMetrics:
        """Process storage and persistence metrics from Prometheus data."""
        # Get timestamps and format them
        csv_last_write_ts = self._get_metric_value(prometheus_metrics, "g6_csv_last_write_unixtime")
        csv_last_write_time = None
        if csv_last_write_ts:
            try:
                dt = datetime.fromtimestamp(csv_last_write_ts, tz=UTC)
                csv_last_write_time = dt.isoformat()
            except Exception:
                pass

        influxdb_last_write_ts = self._get_metric_value(prometheus_metrics, "g6_influxdb_last_write_unixtime")
        influxdb_last_write_time = None
        if influxdb_last_write_ts:
            try:
                dt = datetime.fromtimestamp(influxdb_last_write_ts, tz=UTC)
                influxdb_last_write_time = dt.isoformat()
            except Exception:
                pass

        # Determine InfluxDB connection status
        influxdb_errors = self._get_metric_value(prometheus_metrics, "g6_influxdb_errors_total") or 0
        influxdb_status = "healthy" if influxdb_errors == 0 else ("degraded" if influxdb_errors < 10 else "unhealthy")

        return StorageMetrics(
            csv_files_created=int(self._get_metric_value(prometheus_metrics, "g6_csv_files_created_total") or 0),
            csv_records_written=int(self._get_metric_value(prometheus_metrics, "g6_csv_records_written_total") or 0),
            csv_write_errors=int(self._get_metric_value(prometheus_metrics, "g6_csv_write_errors_total") or 0),
            csv_disk_usage_mb=self._get_metric_value(prometheus_metrics, "g6_csv_disk_usage_mb") or 0.0,
            csv_last_write_time=csv_last_write_time,
            influxdb_points_written=int(self._get_metric_value(prometheus_metrics, "g6_influxdb_points_written_total") or 0),
            influxdb_write_success_rate=self._get_metric_value(prometheus_metrics, "g6_influxdb_write_success_rate_percent") or 0.0,
            influxdb_connection_status=influxdb_status,
            influxdb_query_performance=self._get_metric_value(prometheus_metrics, "g6_influxdb_query_time_ms") or 0.0,
            influxdb_last_write_time=influxdb_last_write_time,
            backup_files_created=int(self._get_metric_value(prometheus_metrics, "g6_backup_files_created_total") or 0),
            last_backup_time=None,  # Would need separate timestamp metric
            backup_size_mb=self._get_metric_value(prometheus_metrics, "g6_backup_size_mb") or 0.0,
        )

    def get_all_metrics(self, force_refresh: bool = False) -> PlatformMetrics:
        """Get complete platform metrics with caching."""
        current_time = time.time()

        # Return cached metrics if still valid
        if (not force_refresh and
            self.last_metrics is not None and
            (current_time - self.last_fetch_time) < self.metrics_cache_ttl):
            return self.last_metrics

        # Determine if we should suppress metrics fetch outside market hours
        suppress_off_hours = os.getenv("G6_SUPPRESS_CLOSED_METRICS", "1") not in ("0", "false", "False")

        def _is_market_open(now_utc: datetime) -> bool:
            """Return True if current time is within hard-coded IST market hours (09:15-15:30)."""
            # Convert UTC to IST (UTC+5:30)
            ist = now_utc + timedelta(hours=5, minutes=30)
            # Market hours Monday-Friday 09:15-15:30 local IST
            if ist.weekday() >= 5:  # 5=Saturday,6=Sunday
                return False
            open_dt = ist.replace(hour=9, minute=15, second=0, microsecond=0)
            close_dt = ist.replace(hour=15, minute=30, second=0, microsecond=0)
            return open_dt <= ist <= close_dt

        # Use timezone-aware current UTC (avoid deprecated utcnow())
        now_utc = utc_now()
        market_open = _is_market_open(now_utc)

        if suppress_off_hours and not market_open:
            # Off hours: optionally reuse last metrics silently (if any) else provide empty baseline
            if self.last_metrics is not None:
                # Light-touch update of timestamp so callers see freshness without spam
                self.last_metrics.last_updated = utc_now().isoformat()
                return self.last_metrics
            # First call off-hours: create empty metrics once
            if (current_time - self._last_closed_notice_ts) > self._closed_notice_interval:
                logger.debug("Metrics suppressed outside market hours (IST 09:15-15:30); returning empty snapshot")
                self._last_closed_notice_ts = current_time
            empty_metrics = PlatformMetrics(
                performance=PerformanceMetrics(),
                collection=CollectionMetrics(),
                indices={},
                storage=StorageMetrics(),
                last_updated=utc_now().isoformat(),
                collection_cycle=0
            )
            self.last_metrics = empty_metrics
            self.last_fetch_time = current_time
            return empty_metrics

        # Fetch fresh metrics from Prometheus (only during market hours, or suppression disabled)
        prometheus_metrics = self.fetch_prometheus_metrics()

        if not prometheus_metrics:
            # Return empty metrics if Prometheus unavailable. Downgraded to debug to avoid spam.
            if (current_time - self._last_closed_notice_ts) > self._closed_notice_interval:
                logger.debug("No metrics available from Prometheus (empty scrape); returning empty metrics snapshot")
                self._last_closed_notice_ts = current_time
            return PlatformMetrics(
                performance=PerformanceMetrics(),
                collection=CollectionMetrics(),
                indices={},
                storage=StorageMetrics(),
                last_updated=utc_now().isoformat(),
                collection_cycle=0
            )

        # Process all metric categories
        performance = self.process_performance_metrics(prometheus_metrics)
        collection = self.process_collection_metrics(prometheus_metrics)
        indices = self.process_index_metrics(prometheus_metrics)
        storage = self.process_storage_metrics(prometheus_metrics)

        # Get current cycle number
        current_cycle = int(self._get_metric_value(prometheus_metrics, "g6_collection_cycles_total") or 0)

        # Create complete metrics structure
        platform_metrics = PlatformMetrics(
            performance=performance,
            collection=collection,
            indices=indices,
            storage=storage,
            last_updated=utc_now().isoformat(),
            collection_cycle=current_cycle
        )

        # Cache the results
        self.last_metrics = platform_metrics
        self.last_fetch_time = current_time

        return platform_metrics

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Get only performance metrics."""
        return self.get_all_metrics().performance

    def get_collection_metrics(self) -> CollectionMetrics:
        """Get only collection metrics."""
        return self.get_all_metrics().collection

    def get_index_metrics(self, index: str | None = None) -> dict[str, IndexMetrics] | IndexMetrics:
        """Get index metrics - all indices or specific index."""
        indices = self.get_all_metrics().indices
        if index:
            return indices.get(index, IndexMetrics())
        return indices

    def get_storage_metrics(self) -> StorageMetrics:
        """Get only storage metrics."""
        return self.get_all_metrics().storage

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary view of key metrics."""
        metrics = self.get_all_metrics()

        return {
            "platform_health": {
                "uptime_hours": round(metrics.performance.uptime_seconds / 3600, 1),
                "success_rate": metrics.performance.collection_success_rate,
                "data_quality": metrics.performance.data_quality_score,
                "total_errors": metrics.collection.total_errors,
            },
            "performance": {
                "cycle_time": metrics.performance.collection_cycle_time,
                "throughput": metrics.performance.options_per_minute,
                "api_latency": metrics.performance.api_response_time,
                "memory_mb": metrics.performance.memory_usage_mb,
                "cpu_percent": metrics.performance.cpu_usage_percent,
            },
            "indices_status": {
                index: {
                    "current_legs": idx_metrics.current_cycle_legs,
                    "success_rate": idx_metrics.success_rate,
                    "quality_score": idx_metrics.data_quality_score,
                }
                for index, idx_metrics in metrics.indices.items()
            },
            "last_updated": metrics.last_updated,
            "collection_cycle": metrics.collection_cycle,
        }

    def export_metrics_dict(self) -> dict[str, Any]:
        """Export all metrics as a flat dictionary for compatibility."""
        metrics = self.get_all_metrics()
        return {
            # Flatten all metrics into a single dictionary
            **asdict(metrics.performance),
            **{f"collection_{k}": v for k, v in asdict(metrics.collection).items()},
            **{f"storage_{k}": v for k, v in asdict(metrics.storage).items()},
            **{f"indices_{index}_{k}": v for index, idx_metrics in metrics.indices.items()
               for k, v in asdict(idx_metrics).items()},
            "last_updated": metrics.last_updated,
            "collection_cycle": metrics.collection_cycle,
        }


# Global metrics processor instance
_metrics_processor: MetricsProcessor | None = None


def get_metrics_processor(prometheus_url: str = "http://127.0.0.1:9108/metrics") -> MetricsProcessor:
    """Get or create the global metrics processor instance."""
    global _metrics_processor
    if _metrics_processor is None:
        _metrics_processor = MetricsProcessor(prometheus_url)
    return _metrics_processor


# Convenience functions for easy access
def get_platform_metrics() -> PlatformMetrics:
    """Get complete platform metrics."""
    return get_metrics_processor().get_all_metrics()


def get_performance_metrics() -> PerformanceMetrics:
    """Get performance metrics."""
    return get_metrics_processor().get_performance_metrics()


def get_index_metrics(index: str | None = None) -> dict[str, IndexMetrics] | IndexMetrics:
    """Get index metrics."""
    return get_metrics_processor().get_index_metrics(index)


def get_metrics_summary() -> dict[str, Any]:
    """Get metrics summary."""
    return get_metrics_processor().get_metrics_summary()
