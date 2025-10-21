#!/usr/bin/env python3
"""
InfluxDB sink for G6 Options Trading Platform.

Refactored to use:
- InfluxBufferManager for batching and periodic flush
- InfluxCircuitBreaker to avoid hammering a failing backend
- InfluxConnectionPool to share clients (optional lightweight)
"""

import logging
import os  # noqa: F401

# Add this before launching the subprocess
import sys  # noqa: F401
from datetime import UTC, datetime
from typing import Any, cast

from src.collectors.env_adapter import get_bool as _env_bool
from src.collectors.env_adapter import get_float as _env_float
from src.collectors.env_adapter import get_int as _env_int
from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler

from ..health import runtime as health_runtime
from ..health.models import HealthLevel, HealthState
from ..utils.circuit_registry import circuit_protected  # optional adaptive CB for write paths
from .influx_buffer_manager import InfluxBufferManager
from .influx_circuit_breaker import InfluxCircuitBreaker
from .influx_connection_pool import InfluxConnectionPool

logger = logging.getLogger(__name__)


class _TinyPoint:
    """Minimal Point stand-in for tests when influxdb_client isn't installed.

    Supports chained .tag(), .field(), and .time(ts) methods and stores timestamp
    on attribute `_time` so tests can assert propagation.
    """
    def __init__(self, measurement: str):
        self._measurement = measurement
        self._tags: dict[str, Any] = {}
        self._fields: dict[str, Any] = {}
        self._time: datetime | None = None

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
        self.write_api = None  # type: Optional[Any]
        self.enable_symbol_tag = enable_symbol_tag
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.metrics = None  # attach externally like CsvSink
        self._buffer = None  # type: Optional[InfluxBufferManager]
        self._breaker = InfluxCircuitBreaker(failure_threshold=breaker_fail_threshold, reset_timeout=breaker_reset_timeout)
        self._pool = None  # type: Optional[InfluxConnectionPool]
        try:
            self._health_enabled = _env_bool('G6_HEALTH_COMPONENTS', False)
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
                    min_size=_env_int('G6_INFLUX_POOL_MIN_SIZE', pool_min_size),
                    max_size=_env_int('G6_INFLUX_POOL_MAX_SIZE', pool_max_size),
                )
            except Exception:
                self._pool = None
            # Buffer manager configured from env overrides when not provided
            eff_batch = _env_int('G6_INFLUX_BATCH_SIZE', batch_size or 500)
            eff_flush = _env_float('G6_INFLUX_FLUSH_INTERVAL', float(flush_interval) if flush_interval is not None else 1.0)
            eff_queue = _env_int('G6_INFLUX_MAX_QUEUE_SIZE', max_queue_size or 10000)

            def _write_points(points: list[Any]) -> None:
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
            if _env_bool('G6_ADAPTIVE_CB_INFLUX', False):
                if hasattr(self, 'write_options_data'):
                    self.write_options_data = cast(Any, circuit_protected('influx.write_options_data')(self.write_options_data))
                if hasattr(self, 'write_overview_snapshot'):
                    self.write_overview_snapshot = cast(Any, circuit_protected('influx.write_overview_snapshot')(self.write_overview_snapshot))
                if hasattr(self, 'write_cycle_stats'):
                    self.write_cycle_stats = cast(Any, circuit_protected('influx.write_cycle_stats')(self.write_cycle_stats))
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

    def close(self) -> None:
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

    def flush(self) -> None:
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

    def attach_metrics(self, metrics_registry: Any) -> None:
        self.metrics = metrics_registry

    def write_options_data(self, index_symbol: str, expiry_date: Any, options_data: dict[str, dict[str, Any]], timestamp: datetime | None = None) -> None:
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
                timestamp = datetime.now(UTC)

        # Convert expiry_date to string if it's a date object
        if hasattr(expiry_date, 'strftime'):
            expiry_str = expiry_date.strftime('%Y-%m-%d')
        else:
            expiry_str = str(expiry_date)

        try:
            # Validation integration: mirror csv_sink behavior (drop invalid rows, clamp negatives, etc.)
            # local import to avoid hard dependency if validation package absent
            try:
                from src import validation as _validation
                run_validators = getattr(_validation, 'run_validators', None)
            except Exception:
                run_validators = None
            if options_data and callable(run_validators):
                raw_rows = []
                for sym, data in list(options_data.items()):
                    if isinstance(data, dict):
                        r = dict(data)
                        r['__symbol'] = sym
                        raw_rows.append(r)
                ctx = {'index': index_symbol, 'expiry': expiry_date, 'stage': 'influx-pre-write'}
                try:
                    rv: Any = run_validators(ctx, raw_rows)
                    cleaned: Any
                    reports: Any
                    if isinstance(rv, tuple) and len(rv) >= 2:
                        cleaned, reports = rv[0], rv[1]
                    else:
                        cleaned, reports = rv, []
                    rebuilt = {}
                    for r in cleaned:
                        sym = r.pop('__symbol', None)
                        if sym:
                            rebuilt[sym] = r
                    options_data = rebuilt
                    if reports:
                        logger.debug('influx_validation_reports', extra={'count': len(reports), 'index': index_symbol})
                except Exception:  # pragma: no cover
                    logger.debug('influx_validation_failed', exc_info=True)

            # Check if we still have data after validation
            if not options_data:
                logger.warning(f"No options data to write for {index_symbol} {expiry_date}")
                return

            # Import Point from canonical path; fall back to tiny stand-in in test contexts
            try:
                from influxdb_client.client.write.point import Point as _Point
            except Exception:  # pragma: no cover - env without influxdb_client
                _Point = _TinyPoint

            points: list[Any] = []
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

                point = _Point("option_data") \
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
                buf = self._buffer
                if buf is not None:
                    buf.add_many(points)
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

    def write_overview_snapshot(self, index_symbol: str, pcr_snapshot: dict[str, float], timestamp: datetime, day_width: float = 0, expected_expiries: list[str] | None = None) -> None:
        """Write aggregated PCR overview for multiple expiries as a single point.

        Measurement: options_overview
        Tags: index
        Fields: pcr_this_week, pcr_next_week, pcr_this_month, pcr_next_month, day_width
        """
        if not self.client or not self.write_api:
            return
        try:
            try:
                from influxdb_client.client.write.point import Point as _Point
            except Exception:
                _Point = _TinyPoint
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

            point = _Point("options_overview") \
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
                buf = getattr(self, '_buffer', None)
                if buf is not None:
                    buf.add(point)
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

    def write_cycle_stats(self, cycle: int, elapsed: float, success_rate: float | None, options_last: int | None, per_index: dict[str, int] | None, timestamp: datetime | None = None) -> None:
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
                from influxdb_client.client.write.point import Point as _Point
            except Exception:
                _Point = _TinyPoint
            if timestamp is None:
                try:
                    from src.utils.timeutils import ensure_utc_helpers
                    utc_now, _iso = ensure_utc_helpers()
                except Exception:
                    def utc_now() -> datetime:
                        return datetime.now(UTC)
                timestamp = utc_now()
            point = _Point("g6_cycle") \
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
                # Be tolerant of instances created via __new__ in tests where _buffer may not exist
                buf = getattr(self, "_buffer", None)
                if buf is not None:
                    buf.add(point)
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

    def __init__(self) -> None:
        """Initialize null sink."""
        pass

    def close(self) -> None:
        """Close sink (no-op)."""
        pass

    def write_options_data(self, index_symbol: str, expiry_date: Any, options_data: dict[str, dict[str, Any]], timestamp: datetime | None = None) -> None:
        """Write options data (no-op)."""
        pass

    def write_overview_snapshot(self, index_symbol: str, pcr_snapshot: dict[str, float], timestamp: datetime, day_width: float = 0, expected_expiries: list[str] | None = None) -> None:
        """Write aggregated overview snapshot (no-op).

        Accepts expected_expiries for API compatibility with InfluxSink.
        """
        pass

    def write_cycle_stats(self, cycle: int, elapsed: float, success_rate: float | None, options_last: int | None, per_index: dict[str, int] | None, timestamp: datetime | None = None) -> None:
        """Write cycle stats (no-op)."""
        pass
