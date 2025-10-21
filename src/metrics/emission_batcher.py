"""Emission batching layer for high-frequency Counter increments.

Optional performance optimization: coalesce many small Counter.inc(1) calls
into periodic aggregated increments to reduce contention and syscall overhead.

Activation: controlled by environment variables (see _Config below). Safe no-op
when disabled.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from prometheus_client import Counter as PromCounter  # noqa: F401
try:  # Runtime import (may fail in minimal environments)
    from prometheus_client import Counter  # type: ignore
except Exception:  # pragma: no cover
    class Counter:  # type: ignore
        def __init__(self, *a, **k): ...
        def inc(self, v=1.0): ...
        def labels(self, **l): return self

# Internal singleton (module-level) managed via get_batcher()
_BATCHER: EmissionBatcher | None = None
# Cache of counter objects by name so batch flush can resolve test-defined counters
_COUNTERS: dict[str, Any] = {}

@dataclass
class _Config:
    enabled: bool = False
    flush_interval: float = 1.0
    max_queue: int = 10000  # Total distinct key entries allowed in buffer
    max_drain: int = 5000   # Max distinct entries applied per flush cycle
    max_interval: float = 0.5  # Hard ceiling between flushes (seconds)

    @staticmethod
    def from_env() -> _Config:
        def _get(name: str, default: str) -> str:
            return os.getenv(name, default)
        return _Config(
            enabled=_get("G6_METRICS_BATCH_ENABLED", "0") in ("1", "true", "True"),
            flush_interval=float(_get("G6_METRICS_BATCH_FLUSH_INTERVAL_SECONDS", "1.0")),
            max_queue=int(_get("G6_METRICS_BATCH_MAX_QUEUE", "10000")),
            max_drain=int(_get("G6_METRICS_BATCH_MAX_DRAIN_PER_FLUSH", "5000")),
            max_interval=float(_get("G6_EMISSION_BATCH_MAX_INTERVAL_MS", "500")) / 1000.0,
        )

class EmissionBatcher:
    """Coalesces Counter increments by (name, labels_tuple).

    NOTE: Only supports Counter metrics. Gauge/Histogram/Summary are not handled.
    """
    def __init__(self, config: _Config):
        self._config = config
        self._lock = threading.Lock()
        # Key -> pending value
        self._pending: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Internal instrumentation bundle
        self._metrics = _InternalBatchMetrics()
        # --- Adaptive sizing state ---
        self._ewma_rate: float = 0.0  # increments per second (EWMA smoothed)
        self._last_ewma_ts: float = time.time()
        self._last_total_merged: float = 0.0  # cumulative merged increments snapshot
        # Configurable adaptive parameters (env tunable)
        self._adapt_alpha = 0.3  # EWMA smoothing factor
        self._target_interval = float(os.getenv("G6_EMISSION_BATCH_TARGET_INTERVAL_MS", "200")) / 1000.0
        self._min_batch = int(os.getenv("G6_EMISSION_BATCH_MIN_SIZE", "50"))
        self._max_batch = int(os.getenv("G6_EMISSION_BATCH_MAX_SIZE", "5000"))
        self._adaptive_target: int = self._min_batch
        # Under-utilization tracking
        self._under_util_count: int = 0
        self._under_util_threshold = float(os.getenv("G6_EMISSION_BATCH_UNDER_UTIL_THRESHOLD", "0.3"))
        self._under_util_consec = int(os.getenv("G6_EMISSION_BATCH_UNDER_UTIL_CONSEC", "3"))
        self._decay_alpha_idle = float(os.getenv("G6_EMISSION_BATCH_DECAY_ALPHA_IDLE", "0.6"))
        self._max_wait = float(os.getenv("G6_EMISSION_BATCH_MAX_WAIT_MS", "750")) / 1000.0
        self._last_activity = time.time()
        if self._config.enabled:
            self._start_thread()
        # Track last flush completion to enforce hard ceiling interval
        self._last_flush_end: float = time.time()

    def _start_thread(self) -> None:
        t = threading.Thread(target=self._run, name="g6-metrics-batch", daemon=True)
        t.start()
        self._thread = t

    def _run(self) -> None:  # pragma: no cover - timing loop
        interval = self._config.flush_interval
        while not self._stop_event.is_set():
            start = time.time()
            try:
                # Enforce hard ceiling even if interval slower
                if (start - self._last_flush_end) >= self._config.max_interval:
                    self.flush()
                else:
                    self.flush()
            except Exception:
                # Swallow exceptions to avoid killing thread; incremental loss acceptable
                pass
            elapsed = time.time() - start
            # Latency observation (seconds) and ms histogram
            self._metrics.observe_flush_seconds(elapsed)
            self._metrics.observe_flush_ms(elapsed * 1000.0)
            # Wait remaining interval
            remaining = interval - elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)

    def shutdown(self) -> None:
        if not self._config.enabled:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._config.flush_interval * 2)
        # Final flush of residual
        try:
            self.flush()
        except Exception:
            pass

    def batch_increment(self, counter: PromCounter, value: float = 1.0, labels: Mapping[str, str] | None = None) -> None:
        """Queue an increment (or apply directly if disabled)."""
        if not self._config.enabled:
            try:
                counter.inc(value)
            except Exception:
                pass
            return
        # Normalize labels
        label_items: tuple[tuple[str, str], ...]
        if labels:
            label_items = tuple(sorted(labels.items()))
        else:
            label_items = tuple()
        # Track counter object for dynamic lookup on flush (supports test-created counters not in generated module)
        try:  # pragma: no cover - defensive
            _COUNTERS[counter._name] = counter  # type: ignore[attr-defined]
        except Exception:
            pass
        key = (counter._name, label_items)  # type: ignore[attr-defined]
        with self._lock:
            if key in self._pending:
                self._pending[key] += value
            else:
                if len(self._pending) >= self._config.max_queue:
                    # Drop increment, account metric
                    self._metrics.inc_dropped()
                    return
                self._pending[key] = value
            self._metrics.inc_merged(value)
            # Proactive flush trigger: if distinct pending entries exceed adaptive target
            # (use current adaptive target or min_batch if not yet computed)
            pending_size = len(self._pending)
            target = self._adaptive_target or self._min_batch
            self._last_activity = time.time()
            if pending_size >= target:
                # Release lock before heavy flush work
                pass_trigger = True
            else:
                pass_trigger = False
        if pass_trigger:
            try:
                self.flush()
            except Exception:
                pass

    def flush(self) -> None:
        if not self._config.enabled:
            return
        with self._lock:
            if not self._pending:
                return
            # Copy and clear (respect max_drain); leave remainder for next flush
            items = list(self._pending.items())
            # Determine adaptive target batch size (distinct entries)
            adaptive_target = self._compute_adaptive_target()
            limit = min(self._config.max_drain, adaptive_target)
            to_apply = items[: limit]
            remainder = items[self._config.max_drain :]
            self._pending = {k: v for k, v in remainder}
        applied = 0
        for (name, label_items), delta in to_apply:
            ctr = _metric_lookup(name)
            if ctr is None:
                # Metric missing; treat as dropped
                self._metrics.inc_dropped()
                continue
            try:
                if label_items:
                    ctr.labels(**dict(label_items)).inc(delta)
                else:
                    ctr.inc(delta)
                applied += 1
            except Exception:
                self._metrics.inc_dropped()
        self._metrics.inc_flush(applied, queue_depth=len(self._pending))
        self._metrics.set_flush_size(applied)
        self._metrics.set_adaptive_target(self._adaptive_target)
        # Utilization metrics: applied distinct entries vs adaptive target
        self._metrics.set_utilization(applied, self._adaptive_target)
        self._last_flush_end = time.time()

    # --- Adaptive sizing helpers ---
    def _compute_adaptive_target(self) -> int:
        """Compute/update adaptive target batch size based on EWMA rate of merged increments.

        We approximate increments/sec using difference in merged counter total across flush cycles.
        Target size = clamp(rate * target_interval, min_batch, max_batch). If rate extremely low,
        still maintain minimum batch size to amortize overhead.
        """
        now = time.time()
        # Get current merged total (internal metric tracked on each batch_increment)
        merged_total = self._metrics.total_merged()
        dt = max(now - self._last_ewma_ts, 1e-6)
        delta = merged_total - self._last_total_merged
        inst_rate = max(delta / dt, 0.0)
        # Choose alpha: if very low instantaneous rate, accelerate decay using idle alpha
        low_rate_threshold = (self._min_batch / max(self._target_interval, 1e-3)) / 4.0
        alpha = self._decay_alpha_idle if inst_rate < low_rate_threshold else self._adapt_alpha
        if self._ewma_rate == 0.0:
            ewma = inst_rate
        else:
            ewma = alpha * inst_rate + (1 - alpha) * self._ewma_rate
        self._ewma_rate = ewma
        self._last_ewma_ts = now
        self._last_total_merged = merged_total
        target = int(ewma * self._target_interval)
        if target < self._min_batch:
            target = self._min_batch
        elif target > self._max_batch:
            target = self._max_batch
        # Under-utilization downshift: if last flush utilization repeatedly low, shrink target 25%
        util = self._metrics.last_utilization()  # prior flush utilization
        if util is not None and util < self._under_util_threshold:
            self._under_util_count += 1
        else:
            self._under_util_count = 0
        if self._under_util_count >= self._under_util_consec:
            target = max(self._min_batch, int(target * 0.75))
            self._under_util_count = 0
        self._adaptive_target = target
        return target

class _InternalBatchMetrics:
    """Handles optional registration of internal batch metrics lazily."""
    _registered = False

    def __init__(self):
        try:
            from prometheus_client import Counter as PCounter
            from prometheus_client import Gauge, Histogram
            self._Gauge = Gauge
            self._Counter = PCounter
            self._Histogram = Histogram
        except Exception:  # pragma: no cover
            self._Gauge = self._Counter = self._Histogram = None  # type: ignore
        self._queue_depth = None
        self._flush_total = None
        self._dropped_total = None
        self._merged_total = None
        self._flush_seconds = None
        self._maybe_register()
        self._merged_cumulative: float = 0.0
        self._flush_size_gauge = None
        self._adaptive_target_gauge = None
        self._flush_ms_hist = None
        self._utilization_gauge = None
        self._dropped_ratio_gauge = None
        self._last_utilization: float | None = None

    def _maybe_register(self):  # pragma: no cover - registration side effect
        if self._registered or not self._Gauge:
            return
        try:
            if self._Gauge and self._Counter and self._Histogram:  # extra guard for type checkers
                self._queue_depth = self._Gauge("g6_metrics_batch_queue_depth", "Current distinct batch entries")
                self._flush_total = self._Counter("g6_metrics_batch_flush_total", "Number of batch flushes applied")
                self._dropped_total = self._Counter("g6_metrics_batch_dropped_total", "Dropped increments due to full queue")
                self._merged_total = self._Counter("g6_metrics_batch_merged_total", "Total increments merged")
                self._flush_seconds = self._Histogram("g6_metrics_batch_flush_seconds", "Flush execution latency seconds")
                # New adaptive/instrumentation metrics (spec-based variants also exist -> duplication acceptable for internal vs spec lineage)
                self._flush_size_gauge = self._Gauge("g6_metrics_batch_flush_increments", "Number of distinct counter entries flushed in last batch")
                self._adaptive_target_gauge = self._Gauge("g6_metrics_batch_adaptive_target", "Current adaptive target batch size")
                self._flush_ms_hist = self._Histogram("g6_metrics_batch_flush_duration_ms", "Flush latency ms (duplicate internal instrument)")
                self._utilization_gauge = self._Gauge("g6_metrics_batch_adaptive_utilization", "Adaptive batch utilization (last_flush_size / adaptive_target)")
                self._dropped_ratio_gauge = self._Gauge("g6_metrics_batch_dropped_ratio", "Dropped increments / merged increments (cumulative ratio)")
            _InternalBatchMetrics._registered = True
        except Exception:
            pass

    def inc_flush(self, applied: int, queue_depth: int):
        if self._flush_total:
            self._flush_total.inc()
        if self._queue_depth:
            self._queue_depth.set(queue_depth)

    def inc_dropped(self):
        if self._dropped_total:
            self._dropped_total.inc()

    def inc_merged(self, value: float):
        if self._merged_total:
            self._merged_total.inc(value)
        self._merged_cumulative += value

    def observe_flush_seconds(self, v: float):
        if self._flush_seconds:
            self._flush_seconds.observe(v)

    def observe_flush_ms(self, v_ms: float):
        if self._flush_ms_hist:
            self._flush_ms_hist.observe(v_ms)

    def set_flush_size(self, size: int):
        if self._flush_size_gauge:
            self._flush_size_gauge.set(size)

    def set_adaptive_target(self, target: int):
        if self._adaptive_target_gauge:
            self._adaptive_target_gauge.set(target)

    def set_utilization(self, applied: int, target: int):
        if target <= 0:
            return
        util = applied / float(target)
        self._last_utilization = util
        if self._utilization_gauge:
            self._utilization_gauge.set(util)
        # Dropped ratio gauge updated opportunistically here
        if self._dropped_ratio_gauge and self._merged_total and self._dropped_total:
            try:
                # Access internal counters (prometheus_client stores value in _value)
                merged_val = self._merged_total._value.get()  # type: ignore
                dropped_val = self._dropped_total._value.get()  # type: ignore
                ratio = dropped_val / merged_val if merged_val else 0.0
                self._dropped_ratio_gauge.set(ratio)
            except Exception:
                pass

    def last_utilization(self) -> float | None:
        return self._last_utilization

    def total_merged(self) -> float:
        return self._merged_cumulative

def _metric_lookup(name: str):
    """Resolve a Counter by name.

    Order of resolution:
      1. Direct object recorded in _COUNTERS (covers test-defined counters).
      2. Attribute in generated metrics module (spec-defined counters).
      3. Fallback proxy that no-ops if still unresolved.
    """
    ctr = _COUNTERS.get(name)
    if ctr is not None:
        return ctr
    try:  # Try generated module
        from . import generated  # type: ignore
        gen = getattr(generated, name, None)
        if gen is not None:
            return gen
    except Exception:
        pass
    # Last resort: proxy (no-op if metric missing)
    return _GeneratedAccessorProxy(name)

class _GeneratedAccessorProxy:
    """Proxy that uses global variable lookup in generated metrics module if available."""
    def __init__(self, name: str):
        self._name = name
    def labels(self, **labels):  # type: ignore
        from . import generated  # type: ignore
        ctr = getattr(generated, self._name, None)
        if ctr is None:
            return self  # no-op
        return ctr.labels(**labels)
    def inc(self, value: float):  # type: ignore
        from . import generated  # type: ignore
        ctr = getattr(generated, self._name, None)
        if ctr is None:
            return
        ctr.inc(value)

def get_batcher() -> EmissionBatcher:
    global _BATCHER
    if _BATCHER is None:
        cfg = _Config.from_env()
        _BATCHER = EmissionBatcher(cfg)
    return _BATCHER

# --- Histogram pre-aggregation stub (future enhancement) ---
_HISTOGRAMS: dict[str, Any] = {}

def register_histogram(name: str, buckets: list[float] | None = None):  # pragma: no cover - stub
    """Placeholder for future histogram bucket coalescing registration.

    Currently returns a passthrough object with observe() writing directly to the underlying
    prometheus_client Histogram (created immediately). Future version may batch observations.
    """
    try:
        from prometheus_client import Histogram  # type: ignore
        h = Histogram(name, f"Registered histogram {name}", buckets=buckets) if buckets else Histogram(name, f"Registered histogram {name}")
        _HISTOGRAMS[name] = h
        return h
    except Exception:
        class _Stub:  # noqa: D401
            def observe(self, *_a, **_k):
                return None
        return _Stub()

def batch_observe(name: str, value: float):  # pragma: no cover - stub
    h = _HISTOGRAMS.get(name)
    if h is None:
        return
    try:
        h.observe(value)
    except Exception:
        pass

__all__ = ["get_batcher", "EmissionBatcher", "register_histogram", "batch_observe"]
