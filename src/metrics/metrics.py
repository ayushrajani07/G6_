#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Metrics for G6 Options Trading Platform.
Sets up a Prometheus metrics server.
"""

import logging
import os
import threading
from prometheus_client import start_http_server, Summary, Counter, Gauge, Histogram, CollectorRegistry, REGISTRY
import time

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Singleton / Idempotency Guards
# ----------------------------------------------------------------------------
# The Prometheus Python client uses a global default CollectorRegistry. Creating
# metric objects (Counter/Gauge/Histogram/Summary) with the same name twice in
# the same process raises a ValueError (Duplicated timeseries). We observed
# duplicate initialization when bootstrap/setup was invoked multiple times
# (e.g., via different entrypoints or inadvertent re-calls). To make platform
# startup resilient and idempotent we guard setup_metrics_server with a simple
# module-level singleton. Subsequent calls will return the existing registry
# instead of attempting to recreate metrics / re-bind the HTTP port.

_METRICS_SINGLETON = None  # type: ignore[var-annotated]
_METRICS_PORT = None       # type: ignore[var-annotated]
_METRICS_HOST = None       # type: ignore[var-annotated]
# Fancy console metadata snapshot (populated on setup)
_METRICS_META: dict | None = None

class MetricsRegistry:
    """Metrics registry for G6 Platform."""
    
    def __init__(self):
        """Initialize metrics."""
        # -------------------------------------------------------------
        # Core Collection Metrics
        # -------------------------------------------------------------
        try:
            self.collection_duration = Summary('g6_collection_duration_seconds', 'Time spent collecting data')
        except ValueError:
            logger.debug("Metric already exists: g6_collection_duration_seconds")
        
        try:
            self.collection_cycles = Counter('g6_collection_cycles_total', 'Number of collection cycles run')
        except ValueError:
            logger.debug("Metric already exists: g6_collection_cycles_total")
        
        # NOTE: labels = index, error_type (NOT expiry). If you need expiry dimension,
        # introduce a separate counter to avoid overloading semantic meaning.
        self.collection_errors = Counter('g6_collection_errors_total',
                                       'Number of collection errors',
                                       ['index', 'error_type'])
        
        # Index metrics
        self.index_price = Gauge('g6_index_price',
                              'Current index price',
                              ['index'])
        
        self.index_atm = Gauge('g6_index_atm_strike',
                            'ATM strike price',
                            ['index'])
        
        # Collection stats
        self.options_collected = Gauge('g6_options_collected',
                                    'Number of options collected',
                                    ['index', 'expiry'])
        
        # Market metrics
        self.pcr = Gauge('g6_put_call_ratio',
                      'Put-Call Ratio',
                      ['index', 'expiry'])
        
        # Option metrics
        self.option_price = Gauge('g6_option_price',
                              'Option price',
                              ['index', 'expiry', 'strike', 'type'])
        
        self.option_volume = Gauge('g6_option_volume',
                               'Option volume',
                               ['index', 'expiry', 'strike', 'type'])

        self.option_oi = Gauge('g6_option_oi',
                           'Option open interest',
                           ['index', 'expiry', 'strike', 'type'])

        self.option_iv = Gauge('g6_option_iv',
                           'Option implied volatility',
                           ['index', 'expiry', 'strike', 'type'])

        # IV estimation metrics
        self.iv_success = Counter('g6_iv_estimation_success_total', 'Successful IV estimations', ['index','expiry'])
        self.iv_fail = Counter('g6_iv_estimation_failure_total', 'Failed IV estimations', ['index','expiry'])
        self.iv_iterations = Gauge('g6_iv_estimation_avg_iterations', 'Average IV solver iterations (rolling per cycle)', ['index','expiry'])
        
        # -------------------------------------------------------------
        # Expanded Performance & Throughput Metrics
        # -------------------------------------------------------------
        self.uptime_seconds = Gauge('g6_uptime_seconds', 'Process uptime in seconds')
        self.avg_cycle_time = Gauge('g6_collection_cycle_time_seconds', 'Average end-to-end collection cycle time (sliding)')
        self.processing_time_per_option = Gauge('g6_processing_time_per_option_seconds', 'Average processing time per option in last cycle')
        self.api_response_time = Gauge('g6_api_response_time_ms', 'Average upstream API response time (ms, rolling)')
        self.api_response_latency = Histogram('g6_api_response_latency_ms', 'Upstream API response latency distribution (ms)', buckets=[5,10,20,50,100,200,400,800,1600,3200])
        self.options_processed_total = Counter('g6_options_processed_total', 'Total option records processed')
        self.options_per_minute = Gauge('g6_options_processed_per_minute', 'Throughput of options processed per minute (rolling)')
        self.cycles_per_hour = Gauge('g6_cycles_per_hour', 'Observed cycles per hour (rolling)')
        self.api_success_rate = Gauge('g6_api_success_rate_percent', 'Successful API call percentage (rolling window)')
        self.collection_success_rate = Gauge('g6_collection_success_rate_percent', 'Successful collection cycle percentage (rolling window)')
        self.data_quality_score = Gauge('g6_data_quality_score_percent', 'Composite data quality score (validation completeness)')
        # Cycle state flag (1=in progress collecting, 0=idle between cycles)
        self.collection_cycle_in_progress = Gauge('g6_collection_cycle_in_progress', 'Current collection cycle execution flag (1=in-progress,0=idle)')
        # Timestamp of last fully successful collection cycle (unix seconds)
        self.last_success_cycle_unixtime = Gauge('g6_last_success_cycle_unixtime', 'Unix timestamp of last fully successful collection cycle')

        # -------------------------------------------------------------
        # Resource Utilization Metrics (set externally by resource sampler)
        # -------------------------------------------------------------
        self.memory_usage_mb = Gauge('g6_memory_usage_mb', 'Resident memory usage in MB')
        self.cpu_usage_percent = Gauge('g6_cpu_usage_percent', 'Process CPU utilization percent')
        self.disk_io_operations = Counter('g6_disk_io_operations_total', 'Disk I/O operation count (increment)')
        self.network_bytes_transferred = Counter('g6_network_bytes_transferred_total', 'Bytes transferred over network (cumulative)')

        # -------------------------------------------------------------
        # Cache / Batch / Error Breakdown Metrics
        # -------------------------------------------------------------
        self.cache_hit_rate = Gauge('g6_cache_hit_rate_percent', 'Cache hit rate percent (rolling)')
        self.cache_size_items = Gauge('g6_cache_items', 'Number of objects in cache')
        self.cache_memory_mb = Gauge('g6_cache_memory_mb', 'Approximate cache memory footprint (MB)')
        self.cache_evictions = Counter('g6_cache_evictions_total', 'Total cache evictions')
        self.batch_efficiency = Gauge('g6_batch_efficiency_percent', 'Batch efficiency percent vs target size')
        self.avg_batch_size = Gauge('g6_avg_batch_size', 'Average batch size (rolling)')
        self.batch_processing_time = Gauge('g6_batch_processing_time_seconds', 'Average batch processing time (rolling)')
        self.total_errors = Counter('g6_total_errors_total', 'Total errors (all categories)')
        self.api_errors = Counter('g6_api_errors_total', 'API related errors')
        self.network_errors = Counter('g6_network_errors_total', 'Network related errors')
        self.data_errors = Counter('g6_data_errors_total', 'Data validation errors')
        self.error_rate_per_hour = Gauge('g6_error_rate_per_hour', 'Error rate per hour (derived)')
        # Watchdog / liveness counters & gauges
        # DEBUG_CLEANUP_BEGIN: These diagnostic metrics are provisional and can be
        # removed or consolidated once stall detection is production-grade.
        self.metric_stall_events = Counter('g6_metric_stall_events_total', 'Metric stall detection events', ['metric'])
        # Removed legacy dashboard parser metrics (dashboard_snapshot_age, dashboard_last_parse_unixtime, parser_unknown_lines)
        # DEBUG_CLEANUP_END

        # -------------------------------------------------------------
        # Storage Metrics
        # -------------------------------------------------------------
        self.csv_files_created = Counter('g6_csv_files_created_total', 'CSV files created')
        self.csv_records_written = Counter('g6_csv_records_written_total', 'CSV records written')
        self.csv_write_errors = Counter('g6_csv_write_errors_total', 'CSV write errors')
        self.csv_disk_usage_mb = Gauge('g6_csv_disk_usage_mb', 'Disk usage attributed to CSV outputs (MB)')
        self.csv_cardinality_unique_strikes = Gauge('g6_csv_cardinality_unique_strikes', 'Unique strikes encountered in last write cycle', ['index','expiry'])
        self.csv_cardinality_suppressed = Gauge('g6_csv_cardinality_suppressed', 'Flag: 1 if cardinality suppression active for index/expiry, else 0', ['index','expiry'])
        self.csv_cardinality_events = Counter('g6_csv_cardinality_events_total', 'Cardinality suppression events', ['index','expiry','event'])
        self.csv_overview_writes = Counter('g6_csv_overview_writes_total', 'Overview snapshot rows written', ['index'])
        self.csv_overview_aggregate_writes = Counter('g6_csv_overview_aggregate_writes_total', 'Aggregated overview snapshot writes', ['index'])
        self.influxdb_points_written = Counter('g6_influxdb_points_written_total', 'InfluxDB points written')
        self.influxdb_write_success_rate = Gauge('g6_influxdb_write_success_rate_percent', 'InfluxDB write success rate percent')
        self.influxdb_connection_status = Gauge('g6_influxdb_connection_status', 'InfluxDB connection status (1=healthy,0=down)')
        self.influxdb_query_performance = Gauge('g6_influxdb_query_time_ms', 'InfluxDB representative query latency (ms)')
        self.backup_files_created = Counter('g6_backup_files_created_total', 'Backup files created')
        self.last_backup_unixtime = Gauge('g6_last_backup_unixtime', 'Timestamp of last backup (unix seconds)')
        self.backup_size_mb = Gauge('g6_backup_size_mb', 'Total size of last backup (MB)')

        # -------------------------------------------------------------
        # Memory Pressure / Adaptive Degradation
        # -------------------------------------------------------------
        # 0=normal,1=elevated,2=high,3=critical
        self.memory_pressure_level = Gauge('g6_memory_pressure_level', 'Memory pressure ordinal level (0=normal,1=elevated,2=high,3=critical)')
        self.memory_pressure_actions = Counter('g6_memory_pressure_actions_total', 'Count of mitigation actions taken due to memory pressure', ['action','tier'])
        self.memory_pressure_seconds_in_level = Gauge('g6_memory_pressure_seconds_in_level', 'Seconds spent in current memory pressure level')
        self.memory_pressure_downgrade_pending = Gauge('g6_memory_pressure_downgrade_pending', 'Downgrade pending flag (1=yes,0=no)')
        self.memory_depth_scale = Gauge('g6_memory_depth_scale', 'Current strike depth scaling factor (0-1)')
        self.memory_per_option_metrics_enabled = Gauge('g6_memory_per_option_metrics_enabled', 'Per-option metrics enabled flag (1=yes,0=no)')
        self.memory_greeks_enabled = Gauge('g6_memory_greeks_enabled', 'Greek & IV computation enabled flag (1=yes,0=no)')

        # -------------------------------------------------------------
        # Index Specific Aggregates (on-demand; labels reused)
        # -------------------------------------------------------------
        try:
            self.index_options_processed = Gauge('g6_index_options_processed', 'Options processed for index last cycle', ['index'])
        except ValueError:
            logger.debug("Metric already exists: g6_index_options_processed")
        # New cumulative counter (monotonic) to help detect actual progress and drive error/stall detection
        try:
            self.index_options_processed_total = Counter('g6_index_options_processed_total', 'Cumulative options processed per index (monotonic)', ['index'])
        except ValueError:
            logger.debug("Metric already exists: g6_index_options_processed_total")
        self.index_avg_processing_time = Gauge('g6_index_avg_processing_time_seconds', 'Average per-option processing time last cycle', ['index'])
        self.index_success_rate = Gauge('g6_index_success_rate_percent', 'Per-index success rate percent', ['index'])
        self.index_last_collection_unixtime = Gauge('g6_index_last_collection_unixtime', 'Last successful collection timestamp (unix)', ['index'])
        self.index_current_atm = Gauge('g6_index_current_atm_strike', 'Current ATM strike (redundant but stable label set)', ['index'])
        self.index_current_volatility = Gauge('g6_index_current_volatility', 'Current representative IV (e.g., ATM option)', ['index'])
        # New explicit attempt/failure metrics (principled success calculations)
        self.index_attempts_total = Counter('g6_index_attempts_total', 'Total index collection attempts (per index, resets never)', ['index'])
        self.index_failures_total = Counter('g6_index_failures_total', 'Total index collection failures (per index, labeled by error_type)', ['index','error_type'])
        self.index_cycle_attempts = Gauge('g6_index_cycle_attempts', 'Attempts in the most recent completed cycle (per index)', ['index'])
        self.index_cycle_success_percent = Gauge('g6_index_cycle_success_percent', 'Success percent for the most recent completed cycle (per index)', ['index'])

        # -------------------------------------------------------------
        # ATM Collection Metrics
        # -------------------------------------------------------------
        self.atm_batch_time = Gauge('g6_atm_batch_time_seconds', 'Elapsed wall time to collect ATM option batch', ['index'])
        self.atm_avg_option_time = Gauge('g6_atm_avg_option_time_seconds', 'Average per-option processing time within ATM batch', ['index'])

        # -------------------------------------------------------------
        # Internal rolling state (not exported) for derived gauges
        # -------------------------------------------------------------
        self._process_start_time = time.time()
        self._cycle_total = 0
        self._cycle_success = 0
        self._api_calls = 0
        self._api_failures = 0
        self._ema_cycle_time = None  # exponential moving average
        self._ema_alpha = 0.2
        self._last_cycle_options = 0
        self._last_cycle_option_seconds = 0.0
        # Previous samples for resource deltas (initialized with ints; not strict literal types)
        self._prev_net_bytes = (0, 0)  # (sent, recv)
        self._prev_disk_ops = 0  # total read+write ops

        # Generate Greek metrics at end
        self._init_greek_metrics()
        logger.info(f"Initialized {len(self.__dict__)} metrics for g6_platform")
    
    def _init_greek_metrics(self):
        """Initialize metrics for option Greeks."""
        greek_names = ['delta', 'theta', 'gamma', 'vega', 'rho']
        
        for greek in greek_names:
            metric_name = f"option_{greek}"
            setattr(self, metric_name, Gauge(
                f'g6_option_{greek}',
                f'Option {greek}',
                ['index', 'expiry', 'strike', 'type']
            ))

    # ---------------- Helper Methods For Derived Metrics -----------------
    def mark_cycle(self, success: bool, cycle_seconds: float, options_processed: int, option_processing_seconds: float):
        """Update rolling cycle statistics and derived gauges.

        Parameters
        ----------
        success : bool
            Whether the cycle completed without fatal errors.
        cycle_seconds : float
            Total wall time for the cycle.
        options_processed : int
            Number of option rows processed in the cycle.
        option_processing_seconds : float
            Time spent specifically in per-option processing (subset of cycle_seconds).
        """
        self._cycle_total += 1
        if success:
            self._cycle_success += 1
            # Record last successful cycle timestamp
            try:
                self.last_success_cycle_unixtime.set(time.time())
            except Exception:
                pass
        # Exponential moving average for cycle time
        if self._ema_cycle_time is None:
            self._ema_cycle_time = cycle_seconds
        else:
            self._ema_cycle_time = (self._ema_alpha * cycle_seconds) + (1 - self._ema_alpha) * self._ema_cycle_time
        # Derived gauges
        if self._ema_cycle_time:
            try:
                self.avg_cycle_time.set(self._ema_cycle_time)
                if self._ema_cycle_time > 0:
                    self.cycles_per_hour.set(3600.0 / self._ema_cycle_time)
            except Exception:
                pass
        # Success rate
        try:
            if self._cycle_total > 0:
                rate = (self._cycle_success / self._cycle_total) * 100.0
                self.collection_success_rate.set(rate)
        except Exception:
            pass
        # Options throughput
        self._last_cycle_options = options_processed
        self._last_cycle_option_seconds = option_processing_seconds
        try:
            if cycle_seconds > 0:
                per_min = (options_processed / cycle_seconds) * 60.0
                self.options_per_minute.set(per_min)
            if options_processed > 0 and option_processing_seconds > 0:
                self.processing_time_per_option.set(option_processing_seconds / options_processed)
        except Exception:
            pass
        # Uptime refresh
        try:
            self.uptime_seconds.set(time.time() - self._process_start_time)
        except Exception:
            pass

    def mark_api_call(self, success: bool, latency_ms: float | None = None):
        """Track API call statistics for success rate and latency EMA."""
        self._api_calls += 1
        if not success:
            self._api_failures += 1
        try:
            if self._api_calls > 0:
                success_rate = (1 - (self._api_failures / self._api_calls)) * 100.0
                self.api_success_rate.set(success_rate)
            if latency_ms is not None and latency_ms >= 0:
                # Simple moving update (EMA based gauge) plus histogram observation
                current = getattr(self, '_api_latency_ema', None)
                alpha = 0.3
                if current is None:
                    current = latency_ms
                else:
                    current = alpha * latency_ms + (1 - alpha) * current
                self._api_latency_ema = current
                try:
                    self.api_response_time.set(current)
                except Exception:
                    pass
                try:
                    self.api_response_latency.observe(latency_ms)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------------- Per-Index Cycle Attempts / Success -----------------
    def mark_index_cycle(self, index: str, attempts: int, failures: int):
        """Record per-index cycle attempts/failures and update success metrics.

        Parameters
        ----------
        index : str
            Index symbol.
        attempts : int
            Number of collection attempts for this index in the cycle.
        failures : int
            Number of failed attempts within those attempts.
        """
        if attempts < 0 or failures < 0:
            return
        # Update cumulative counters
        try:
            if attempts > 0:
                self.index_attempts_total.labels(index=index).inc(attempts)
            if failures > 0:
                # Use generic error_type 'cycle' for aggregate failures (more granular increments should also be emitted where they occur)
                self.index_failures_total.labels(index=index, error_type='cycle').inc(failures)
        except Exception:
            pass
        # Set per-cycle gauges
        try:
            self.index_cycle_attempts.labels(index=index).set(attempts)
            success_pct = None
            if attempts > 0:
                success_pct = (attempts - failures) / attempts * 100.0
                self.index_cycle_success_percent.labels(index=index).set(success_pct)
            else:
                # Represent unknown by clearing gauge (cannot unset; set to NaN) if Prometheus client supports
                try:
                    self.index_cycle_success_percent.labels(index=index).set(float('nan'))
                except Exception:
                    pass
        except Exception:
            pass

def setup_metrics_server(port=9108, host="0.0.0.0", enable_resource_sampler: bool = True, sampler_interval: int = 10,
                         use_custom_registry: bool | None = None, reset: bool = False):
    """Set up metrics server and return metrics registry.

    Parameters
    ----------
    port : int
        HTTP port for Prometheus exposition.
    host : str
        Bind address.
    enable_resource_sampler : bool
        Whether to launch a background sampler for resource gauges.
    sampler_interval : int
        Seconds between resource samples.
    """
    global _METRICS_SINGLETON, _METRICS_PORT, _METRICS_HOST  # noqa: PLW0603
    # Fast path: if already initialized, return existing without side effects
    if _METRICS_SINGLETON is not None and not reset:
        # If caller requested a different port/host than the first initialization,
        # log a warning for visibility (cannot rebind without restart)
        if (port != _METRICS_PORT) or (host != _METRICS_HOST):
            logger.warning(
                "setup_metrics_server called again with different host/port (%s:%s) != (%s:%s); reusing existing server",
                host, port, _METRICS_HOST, _METRICS_PORT,
            )
        else:
            logger.debug("setup_metrics_server called again; returning existing singleton")
        return _METRICS_SINGLETON, (lambda: None)

    # If reset requested, attempt to clear default registry (best effort). This is
    # primarily for interactive/dev sessions; production code should rely on idempotency.
    if reset:
        try:  # pragma: no cover - defensive path
            collectors = list(REGISTRY._names_to_collectors.values())  # type: ignore[attr-defined]
            for c in collectors:
                try:
                    REGISTRY.unregister(c)  # type: ignore[arg-type]
                except Exception:
                    pass
            logger.info("Prometheus default registry cleared via reset flag")
        except Exception:
            logger.warning("Registry reset attempt failed; proceeding")
        # Reset singleton markers
        globals()['_METRICS_SINGLETON'] = None
        globals()['_METRICS_PORT'] = None
        globals()['_METRICS_HOST'] = None

    # Determine whether to use a custom (non-global) registry. If unspecified, default False.
    if use_custom_registry is None:
        use_custom_registry = False

    if use_custom_registry:
        # Use an isolated CollectorRegistry and start_http_server bound to it.
        registry = CollectorRegistry()
        start_http_server(port, addr=host, registry=registry)
    else:
        start_http_server(port, addr=host)
    _METRICS_PORT = port
    _METRICS_HOST = host
    fancy = os.environ.get('G6_FANCY_CONSOLE','').lower() in ('1','true','yes','on')
    if fancy:
        logger.debug(f"Metrics server started on {host}:{port}")
        logger.debug(f"Metrics available at http://{host}:{port}/metrics")
    else:
        logger.info(f"Metrics server started on {host}:{port}")
        logger.info(f"Metrics available at http://{host}:{port}/metrics")

    metrics = MetricsRegistry()
    _METRICS_SINGLETON = metrics

    if enable_resource_sampler:
        try:
            import psutil  # type: ignore
        except ImportError:
            logger.warning("psutil not installed; resource sampler disabled")
        else:
            def _sample():
                while True:
                    try:
                        p = psutil.Process()
                        with p.oneshot():
                            mem_mb = p.memory_info().rss / (1024 * 1024)
                            cpu_percent = p.cpu_percent(interval=None)  # non-blocking (last interval)
                        metrics.memory_usage_mb.set(mem_mb)
                        metrics.cpu_usage_percent.set(cpu_percent)
                        # System-wide network I/O (cumulative); we expose as counters via .inc delta if desired.
                        net = psutil.net_io_counters()
                        prev_net = getattr(metrics, '_prev_net_bytes', (0, 0))
                        try:
                            d_sent = max(0, net.bytes_sent - prev_net[0])
                            d_recv = max(0, net.bytes_recv - prev_net[1])
                            metrics.network_bytes_transferred.inc(d_sent + d_recv)
                        except Exception:
                            pass
                        setattr(metrics, '_prev_net_bytes', (net.bytes_sent, net.bytes_recv))
                        # Disk IO ops delta
                        dio = psutil.disk_io_counters()
                        if dio is not None and hasattr(dio, 'read_count') and hasattr(dio, 'write_count'):
                            if hasattr(metrics, '_prev_disk_ops'):
                                d_ops = max(0, (dio.read_count + dio.write_count) - metrics._prev_disk_ops)
                                metrics.disk_io_operations.inc(d_ops)
                            metrics._prev_disk_ops = dio.read_count + dio.write_count
                    except Exception:
                        logger.debug("Resource sampling iteration failed", exc_info=True)
                    time.sleep(sampler_interval)
            t = threading.Thread(target=_sample, name="g6-resource-sampler", daemon=True)
            t.start()
            if fancy:
                logger.debug("Resource sampler thread started (interval=%ss)" % sampler_interval)
            else:
                logger.info("Resource sampler thread started (interval=%ss)" % sampler_interval)

    # DEBUG_CLEANUP_BEGIN: watchdog thread (temporary diagnostic liveness monitor)
    def _watchdog():
        last_cycle = 0.0
        last_options = 0.0
        stale_intervals = 0
        check_interval = max(5, sampler_interval)
        while True:
            try:
                # Safely read underlying counters via exposed gauges/counters
                # We infer cycle progress from collection_cycles_total and options_processed_total
                # Prometheus client does not expose get(), so we keep local shadow via internal attributes where possible.
                current_cycles = getattr(metrics, '_cycle_total', None)
                current_options = getattr(metrics, '_last_cycle_options', None)
                in_progress = 0
                try:
                    if hasattr(metrics, 'collection_cycle_in_progress'):
                        # Best effort: if set recently to 1, skip stall accrual
                        in_progress = 1 if getattr(metrics.collection_cycle_in_progress, '_value', None) else 0
                except Exception:
                    pass
                progressed = False
                if current_cycles is not None and current_cycles > last_cycle:
                    progressed = True
                if current_options is not None and current_options > last_options:
                    progressed = True
                if progressed or in_progress:
                    stale_intervals = 0
                    last_cycle = current_cycles if current_cycles is not None else last_cycle
                    last_options = current_options if current_options is not None else last_options
                else:
                    stale_intervals += 1
                    if stale_intervals >= 6:  # ~30-60s depending on interval
                        try:
                            metrics.metric_stall_events.labels(metric='collection').inc()
                        except Exception:
                            pass
                        # backoff to avoid spamming
                        stale_intervals = 0
            except Exception:
                logger.debug("Watchdog iteration failed", exc_info=True)
            time.sleep(check_interval)
    wt = threading.Thread(target=_watchdog, name="g6-watchdog", daemon=True)
    wt.start()
    if fancy:
        logger.debug("Watchdog thread started")
    else:
        logger.info("Watchdog thread started")

    # Record metadata for fancy panel consumption
    try:
        globals()['_METRICS_META'] = {
            'host': host,
            'port': port,
            'resource_sampler': bool(enable_resource_sampler),
            'watchdog': True,
            'custom_registry': bool(use_custom_registry),
            'reset': bool(reset),
        }
    except Exception:
        pass
    # DEBUG_CLEANUP_END

    return metrics, lambda: None  # No direct way to stop the server (Prometheus client lacks shutdown)

def get_metrics_metadata() -> dict | None:
    """Return metrics server metadata collected at setup (for fancy console panel)."""
    return _METRICS_META