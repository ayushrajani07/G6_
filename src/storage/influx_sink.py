#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InfluxDB sink for G6 Options Trading Platform.

Refactored to use:
- InfluxBufferManager for batching and periodic flush
- InfluxCircuitBreaker to avoid hammering a failing backend
- InfluxConnectionPool to share clients (optional lightweight)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

from .influx_buffer_manager import InfluxBufferManager
from .influx_circuit_breaker import InfluxCircuitBreaker
from .influx_connection_pool import InfluxConnectionPool
from ..health import runtime as health_runtime
from ..health.models import HealthLevel, HealthState
from ..utils.circuit_registry import circuit_protected  # optional adaptive CB for write paths
from src.error_handling import get_error_handler, ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)


class _TinyPoint:
    """Minimal Point stand-in for tests when influxdb_client isn't installed.

    Supports chained .tag(), .field(), and .time(ts) methods and stores timestamp
    on attribute `_time` so tests can assert propagation.
    """
    def __init__(self, measurement: str):
        self._measurement = measurement
        self._tags: Dict[str, Any] = {}
        self._fields: Dict[str, Any] = {}
        self._time: Optional[datetime] = None

    def tag(self, k: str, v: Any):
        self._tags[k] = v
        return self

    def field(self, k: str, v: Any):
        self._fields[k] = v
        return self

    def time(self, ts: datetime):
        self._time = ts
        return self


class InfluxSink:
    """InfluxDB storage sink for G6 data."""
    
    def __init__(
        self,
        url: str = 'http://localhost:8086',
        token: str = '',
        org: str = '',
        bucket: str = 'g6_data',
        enable_symbol_tag: bool = True,
        # buffering
        batch_size: int | None = None,
        flush_interval: float | None = None,
        max_queue_size: int | None = None,
        # retries (for buffer manager)
        max_retries: int = 3,
        backoff_base: float = 0.25,
        # breaker
        breaker_fail_threshold: int = 5,
        breaker_reset_timeout: float = 30.0,
        # pool
        pool_min_size: int = 1,
        pool_max_size: int = 2,
    ):
        """
        Initialize InfluxDB sink.
        
        Args:
            url: InfluxDB server URL
            token: InfluxDB API token
            org: InfluxDB organization
            bucket: InfluxDB bucket name
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client = None
        self.enable_symbol_tag = enable_symbol_tag
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.metrics = None  # attach externally like CsvSink
        self._buffer: Optional[InfluxBufferManager] = None
        self._breaker = InfluxCircuitBreaker(failure_threshold=breaker_fail_threshold, reset_timeout=breaker_reset_timeout)
        self._pool: Optional[InfluxConnectionPool] = None
        try:
            self._health_enabled = os.environ.get('G6_HEALTH_COMPONENTS', '').lower() in ('1','true','yes','on')
        except Exception:
            self._health_enabled = False
        
        try:
            from influxdb_client.client.influxdb_client import InfluxDBClient
            # Initialize base client (will also seed pool)
            self.client = InfluxDBClient(url=url, token=token, org=org)
            self.write_api = self.client.write_api()
            # Connection pool uses factory to create additional clients if needed
            try:
                self._pool = InfluxConnectionPool(
                    factory=lambda: InfluxDBClient(url=url, token=token, org=org),
                    min_size=int(os.environ.get('G6_INFLUX_POOL_MIN_SIZE', pool_min_size)),
                    max_size=int(os.environ.get('G6_INFLUX_POOL_MAX_SIZE', pool_max_size)),
                )
            except Exception:
                self._pool = None
            # Buffer manager configured from env overrides when not provided
            eff_batch = int(os.environ.get('G6_INFLUX_BATCH_SIZE', batch_size or 500))
            eff_flush = float(os.environ.get('G6_INFLUX_FLUSH_INTERVAL', flush_interval or 1.0))
            eff_queue = int(os.environ.get('G6_INFLUX_MAX_QUEUE_SIZE', max_queue_size or 10000))

            def _write_points(points: List[Any]) -> None:
                # write using main write_api (single client). Could round-robin via pool if desired.
                if not self.write_api:
                    raise RuntimeError("write_api not initialized")
                # points may be Point or str; delegate directly
                self.write_api.write(bucket=self.bucket, record=points)

            def _on_success(n: int) -> None:
                try:
                    self._breaker.record_success()
                    if self.metrics:
                        self.metrics.influxdb_points_written.inc(n)
                        self.metrics.influxdb_write_success_rate.set(100.0)
                        self.metrics.influxdb_connection_status.set(1)
                    if self._health_enabled:
                        health_runtime.set_component('influx_sink', HealthLevel.HEALTHY, HealthState.HEALTHY)
                except Exception:
                    pass

            def _on_failure(e: Exception) -> None:
                try:
                    self._breaker.record_failure()
                    if self.metrics:
                        self.metrics.influxdb_write_success_rate.set(0.0)
                        self.metrics.influxdb_connection_status.set(0)
                    if self._health_enabled:
                        state = HealthState.CRITICAL if self._breaker.state == "OPEN" else HealthState.WARNING
                        level = HealthLevel.CRITICAL if self._breaker.state == "OPEN" else HealthLevel.WARNING
                        health_runtime.set_component('influx_sink', level, state)
                except Exception:
                    pass

            self._buffer = InfluxBufferManager(
                write_fn=_write_points,
                batch_size=eff_batch,
                flush_interval=eff_flush,
                max_queue_size=eff_queue,
                max_retries=self.max_retries,
                backoff_base=self.backoff_base,
                on_success=_on_success,
                on_failure=_on_failure,
            )
            logger.info(f"InfluxDB sink initialized with bucket: {bucket}")
        except ImportError as e:
            logger.warning("influxdb_client package not installed, using dummy implementation")
            # Soft-route missing dependency
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.CONFIGURATION,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="__init__",
                message="influxdb_client not installed; using dummy",
                should_log=False,
            )
        except Exception as e:
            logger.error(f"Error initializing InfluxDB client: {e}")
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH,
                component="storage.influx_sink",
                function_name="__init__",
                message="Failed to initialize InfluxDB client",
                should_log=False,
            )
        # Optionally protect write paths with adaptive circuit breakers (env opt-in)
        try:
            if os.environ.get('G6_ADAPTIVE_CB_INFLUX', '').lower() in ('1','true','yes','on'):
                if hasattr(self, 'write_options_data'):
                    self.write_options_data = circuit_protected('influx.write_options_data')(self.write_options_data)  # type: ignore[assignment]
                if hasattr(self, 'write_overview_snapshot'):
                    self.write_overview_snapshot = circuit_protected('influx.write_overview_snapshot')(self.write_overview_snapshot)  # type: ignore[assignment]
                if hasattr(self, 'write_cycle_stats'):
                    self.write_cycle_stats = circuit_protected('influx.write_cycle_stats')(self.write_cycle_stats)  # type: ignore[assignment]
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="__init__",
                message="Failed to enable adaptive circuit breakers",
                should_log=False,
            )
    
    def close(self):
        """Close InfluxDB client."""
        try:
            if self._buffer:
                self._buffer.stop()
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="close",
                message="Buffer stop failed",
                should_log=False,
            )
        if self.client:
            try:
                self.client.close()
                logger.info("InfluxDB client closed")
            except Exception as e:
                logger.error(f"Error closing InfluxDB client: {e}")
                get_error_handler().handle_error(
                    e,
                    category=ErrorCategory.DATABASE,
                    severity=ErrorSeverity.MEDIUM,
                    component="storage.influx_sink",
                    function_name="close",
                    message="Error closing InfluxDB client",
                    should_log=False,
                )
        try:
            if self._pool:
                self._pool.close_all()
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="close",
                message="Failed closing pool",
                should_log=False,
            )

    def flush(self):
        try:
            if self._buffer:
                self._buffer.flush()
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="flush",
                message="Buffer flush failed",
                should_log=False,
            )
    
    def attach_metrics(self, metrics_registry):
        self.metrics = metrics_registry

    def write_options_data(self, index_symbol, expiry_date, options_data: Dict[str, Dict[str, Any]], timestamp=None):
        """
        Write options data to InfluxDB.
        
        Args:
            index_symbol: Index symbol
            expiry_date: Expiry date string or date object
            options_data: Dictionary of options data
            timestamp: Timestamp for the data (default: current time)
        """
        if not self.client or not self.write_api:
            return
        
        # Use current time if timestamp not provided
        if timestamp is None:
            try:
                from src.utils.timeutils import utc_now
                timestamp = utc_now()
            except Exception:
                timestamp = datetime.now(timezone.utc)
        
        # Convert expiry_date to string if it's a date object
        if hasattr(expiry_date, 'strftime'):
            expiry_str = expiry_date.strftime('%Y-%m-%d')
        else:
            expiry_str = str(expiry_date)
        
        try:
            # Check if we have data
            if not options_data:
                logger.warning(f"No options data to write for {index_symbol} {expiry_date}")
                return

            # Import Point from canonical path; fall back to tiny stand-in in test contexts
            try:
                from influxdb_client.client.write.point import Point
            except Exception:  # pragma: no cover - env without influxdb_client
                Point = _TinyPoint  # type: ignore

            points: List[Any] = []
            for symbol, data in options_data.items():
                strike = data.get('strike', 0)
                opt_type = data.get('type', data.get('instrument_type', ''))  # 'CE' or 'PE'
                ltp = data.get('last_price', 0)
                oi = data.get('oi', 0)
                volume = data.get('volume', 0)
                iv = data.get('iv', 0)
                delta = data.get('delta')
                gamma = data.get('gamma')
                theta = data.get('theta')
                vega = data.get('vega')
                rho = data.get('rho')

                point = Point("option_data") \
                    .tag("index", index_symbol) \
                    .tag("expiry", expiry_str) \
                    .tag("type", opt_type) \
                    .tag("strike", str(strike)) \
                    .field("price", float(ltp)) \
                    .field("oi", float(oi)) \
                    .field("volume", float(volume)) \
                    .field("iv", float(iv))
                if self.enable_symbol_tag:
                    point = point.tag("symbol", symbol)
                # Add greek fields conditionally if present to avoid writing zeros when not computed
                if delta is not None:
                    point = point.field("delta", float(delta))
                if gamma is not None:
                    point = point.field("gamma", float(gamma))
                if theta is not None:
                    point = point.field("theta", float(theta))
                if vega is not None:
                    point = point.field("vega", float(vega))
                if rho is not None:
                    point = point.field("rho", float(rho))
                point = point.time(timestamp)
                points.append(point)

            # Use circuit breaker to guard enqueue when backend failing hard
            if getattr(self, "_breaker", None) is None or self._breaker.allow():
                if getattr(self, "_buffer", None):
                    self._buffer.add_many(points)  # type: ignore[union-attr]
                else:
                    # Back-compat path for tests that stub write_api only
                    try:
                        self.write_api.write(bucket=self.bucket, record=points)
                        if self.metrics:
                            try:
                                self.metrics.influxdb_points_written.inc(len(points))
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"Fallback direct write failed: {e}")
                        get_error_handler().handle_error(
                            e,
                            category=ErrorCategory.DATABASE,
                            severity=ErrorSeverity.MEDIUM,
                            component="storage.influx_sink",
                            function_name="write_options_data",
                            message="Fallback direct write failed",
                            should_log=False,
                        )
            else:
                logger.debug("Influx breaker OPEN/HALF_OPEN: drop enqueue")
        except Exception as e:
            logger.error(f"Error writing options data to InfluxDB: {e}")
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH,
                component="storage.influx_sink",
                function_name="write_options_data",
                message="Error writing options data to InfluxDB",
                should_log=False,
            )
            try:
                if self.metrics:
                    self.metrics.influxdb_connection_status.set(0)
            except Exception:
                pass

    def write_overview_snapshot(self, index_symbol, pcr_snapshot, timestamp, day_width=0, expected_expiries=None):
        """Write aggregated PCR overview for multiple expiries as a single point.

        Measurement: options_overview
        Tags: index
        Fields: pcr_this_week, pcr_next_week, pcr_this_month, pcr_next_month, day_width
        """
        if not self.client or not self.write_api:
            return
        try:
            try:
                from influxdb_client.client.write.point import Point
            except Exception:
                Point = _TinyPoint  # type: ignore
            expiry_bit_map = {'this_week':1,'next_week':2,'this_month':4,'next_month':8}
            collected_mask = 0
            for k in pcr_snapshot.keys():
                collected_mask |= expiry_bit_map.get(k,0)
            expected_mask = 0
            if expected_expiries:
                for k in expected_expiries:
                    expected_mask |= expiry_bit_map.get(k,0)
            else:
                expected_mask = collected_mask
            missing_mask = expected_mask & (~collected_mask)
            expiries_collected = len(pcr_snapshot)
            expiries_expected = len(expected_expiries) if expected_expiries else expiries_collected

            point = Point("options_overview") \
                .tag("index", index_symbol) \
                .field("pcr_this_week", float(pcr_snapshot.get('this_week', 0))) \
                .field("pcr_next_week", float(pcr_snapshot.get('next_week', 0))) \
                .field("pcr_this_month", float(pcr_snapshot.get('this_month', 0))) \
                .field("pcr_next_month", float(pcr_snapshot.get('next_month', 0))) \
                .field("day_width", float(day_width)) \
                .field("expiries_expected", expiries_expected) \
                .field("expiries_collected", expiries_collected) \
                .field("expected_mask", expected_mask) \
                .field("collected_mask", collected_mask) \
                .field("missing_mask", missing_mask) \
                .time(timestamp)
            if getattr(self, "_breaker", None) is None or self._breaker.allow():
                if getattr(self, "_buffer", None):
                    self._buffer.add(point)  # type: ignore[union-attr]
                else:
                    try:
                        self.write_api.write(bucket=self.bucket, record=point)
                        if self.metrics:
                            try:
                                self.metrics.influxdb_points_written.inc()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"Fallback direct write (overview) failed: {e}")
                        get_error_handler().handle_error(
                            e,
                            category=ErrorCategory.DATABASE,
                            severity=ErrorSeverity.MEDIUM,
                            component="storage.influx_sink",
                            function_name="write_overview_snapshot",
                            message="Fallback direct write overview failed",
                            should_log=False,
                        )
        except Exception as e:
            logger.error(f"Error writing overview snapshot to InfluxDB: {e}")
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH,
                component="storage.influx_sink",
                function_name="write_overview_snapshot",
                message="Error writing overview snapshot",
                should_log=False,
            )

    def write_cycle_stats(self, cycle:int, elapsed: float, success_rate: float | None, options_last:int | None, per_index: dict[str,int] | None, timestamp=None):
        """Write a single cycle summary point.

        Measurement: g6_cycle
        Tags: none (could add host later)
        Fields:
          cycle (int), elapsed_seconds (float), success_rate_pct (float), options_last_cycle (int), per-index option counts as fields: options_<INDEX>
        """
        if not self.client or not self.write_api:
            return
        try:
            try:
                from influxdb_client.client.write.point import Point
            except Exception:
                Point = _TinyPoint  # type: ignore
            if timestamp is None:
                try:
                    from src.utils.timeutils import ensure_utc_helpers  # type: ignore
                    utc_now, _iso = ensure_utc_helpers()
                except Exception:
                    def utc_now():  # type: ignore
                        return datetime.now(timezone.utc)
                timestamp = utc_now()
            point = Point("g6_cycle") \
                .field("cycle", int(cycle)) \
                .field("elapsed_seconds", float(elapsed))
            if success_rate is not None:
                point = point.field("success_rate_pct", float(success_rate))
            if options_last is not None:
                point = point.field("options_last_cycle", int(options_last))
            if per_index:
                for k,v in per_index.items():
                    try:
                        point = point.field(f"options_{k}", int(v))
                    except Exception:
                        pass
            point = point.time(timestamp)
            if getattr(self, "_breaker", None) is None or self._breaker.allow():
                if getattr(self, "_buffer", None):
                    self._buffer.add(point)  # type: ignore[union-attr]
                else:
                    try:
                        self.write_api.write(bucket=self.bucket, record=point)
                        if self.metrics:
                            try:
                                self.metrics.influxdb_points_written.inc()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"Fallback direct write (cycle) failed: {e}")
                        get_error_handler().handle_error(
                            e,
                            category=ErrorCategory.DATABASE,
                            severity=ErrorSeverity.MEDIUM,
                            component="storage.influx_sink",
                            function_name="write_cycle_stats",
                            message="Fallback direct write cycle failed",
                            should_log=False,
                        )
        except Exception as e:
            logger.debug(f"Failed to write cycle stats: {e}")
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.LOW,
                component="storage.influx_sink",
                function_name="write_cycle_stats",
                message="Failed to write cycle stats",
                should_log=False,
            )

class NullInfluxSink:
    """Null implementation of InfluxDB sink that does nothing."""
    
    def __init__(self):
        """Initialize null sink."""
        pass
    
    def close(self):
        """Close sink (no-op)."""
        pass
    
    def write_options_data(self, index_symbol, expiry_date, options_data, timestamp=None):
        """Write options data (no-op)."""
        pass

    def write_overview_snapshot(self, index_symbol, pcr_snapshot, timestamp, day_width=0, expected_expiries=None):
        """Write aggregated overview snapshot (no-op).

        Accepts expected_expiries for API compatibility with InfluxSink.
        """
        pass

    def write_cycle_stats(self, cycle:int, elapsed: float, success_rate: float | None, options_last:int | None, per_index: dict[str,int] | None, timestamp=None):
        """Write cycle stats (no-op)."""
        pass