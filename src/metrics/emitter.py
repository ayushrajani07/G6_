"""Structured batched emission for Prometheus counters.

Purpose: Reduce lock contention from high-frequency counter increments by
accumulating deltas and flushing periodically.

Design Principles:
- Opt-in via env var G6_METRICS_BATCH (default off)
- Thread-safe accumulation using a single global RLock
- Background flush thread with configurable interval (default 2s)
- Safe degradation: if any error occurs during flush, it logs (once per error signature) and continues
- Histograms & gauges are NOT batched (only counters via label accessors) because observations often carry timing
- Accessor expectation: *_labels accessor returning a label-bound counter object supporting .inc()

Usage:
    from src.metrics.emitter import metric_batcher
    metric_batcher.inc(m_api_calls_total_labels, 1, 'get_quote', 'success')

If batching disabled, it falls back to immediate increment.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol


class _GaugeLike(Protocol):  # minimal protocol for .set
    def set(self, value: float): ...  # noqa: D401

def m_metrics_batch_queue_depth():  # default stub, replaced on success import
    return None  # type: ignore

if not TYPE_CHECKING:
    try:  # lazy import to avoid circulars during early startup
        from src.metrics.generated import m_metrics_batch_queue_depth as _real_mq  # type: ignore
        m_metrics_batch_queue_depth = _real_mq  # type: ignore
    except Exception:  # pragma: no cover
        pass

logger = logging.getLogger(__name__)

CounterAccessor = Callable[..., Any]  # expects labels args and returns object with .inc(amount)

class _ErrorOnce:
    def __init__(self):
        self._seen = set()
        self._lock = threading.Lock()
    def log(self, key: str, msg: str):
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)
        logger.warning(msg)

_error_once = _ErrorOnce()

class MetricBatcher:
    def __init__(self, enabled: bool, flush_interval: float = 2.0, flush_threshold: int | None = None):
        self.enabled = enabled
        self.flush_interval = flush_interval
        # If set (>0), triggers an immediate flush when queue cardinality reaches this size
        self.flush_threshold = flush_threshold if (flush_threshold and flush_threshold > 0) else None
        self._lock = threading.RLock()
        # Map: (accessor id, callable, label tuple) -> count
        self._counters: dict[tuple[int, CounterAccessor, tuple[Any, ...]], float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._start_thread()

    def _start_thread(self):
        t = threading.Thread(target=self._loop, name="MetricBatcherFlush", daemon=True)
        self._thread = t
        t.start()

    def _loop(self):  # pragma: no cover (timing / background)
        while not self._stop.is_set():
            time.sleep(self.flush_interval)
            try:
                self.flush()
            except Exception as e:  # defensive; never crash
                _error_once.log(f"loop:{type(e).__name__}", f"MetricBatcher flush loop error: {e}")

    def inc(self, accessor: CounterAccessor, amount: float, *label_values: Any):
        if not self.enabled:
            # Immediate fallback
            try:
                lbl = accessor(*label_values)
                if lbl:
                    lbl.inc(amount)  # type: ignore[attr-defined]
            except Exception as e:
                _error_once.log(f"direct:{type(e).__name__}", f"Direct metric increment failed: {e}")
            return
        key = (id(accessor), accessor, tuple(label_values))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount
            try:
                g = m_metrics_batch_queue_depth()
                if g:
                    g.set(len(self._counters))  # type: ignore[attr-defined]
            except Exception:
                pass
            # Adaptive threshold-based flush (best-effort, non-blocking outside lock duration)
            if self.flush_threshold and len(self._counters) >= self.flush_threshold:
                # Copy and clear inside lock; perform increments outside
                items = list(self._counters.items())
                self._counters.clear()
                try:
                    g = m_metrics_batch_queue_depth()
                    if g:
                        g.set(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                items = None
        if items is not None:
            for (_, accessor2, label_tuple), amt in items:
                try:
                    lbl = accessor2(*label_tuple)
                    if lbl and amt:
                        lbl.inc(amt)  # type: ignore[attr-defined]
                except Exception as e:
                    _error_once.log(f"flush:{type(e).__name__}", f"MetricBatcher threshold flush error: {e}")

    def flush(self):
        if not self.enabled:
            return
        with self._lock:
            items = list(self._counters.items())
            self._counters.clear()
        for ( _, accessor, label_tuple), amount in items:
            try:
                lbl = accessor(*label_tuple)
                if lbl and amount:
                    lbl.inc(amount)  # type: ignore[attr-defined]
            except Exception as e:
                _error_once.log(f"flush:{type(e).__name__}", f"MetricBatcher flush error: {e}")
        # After flush reset gauge
        try:
            g = m_metrics_batch_queue_depth()
            if g:
                g.set(0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def stop(self):  # pragma: no cover
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self.flush()
        except Exception:
            pass

_enabled = os.getenv("G6_METRICS_BATCH", "0").lower() in ("1", "true", "on", "yes")
_flush_interval = float(os.getenv("G6_METRICS_BATCH_INTERVAL", "2.0") or 2.0)
_flush_threshold = int(os.getenv("G6_METRICS_BATCH_FLUSH_THRESHOLD", "0") or 0)
metric_batcher = MetricBatcher(enabled=_enabled, flush_interval=_flush_interval, flush_threshold=_flush_threshold)

@atexit.register
def _final_flush():  # pragma: no cover
    try:
        metric_batcher.stop()
    except Exception:
        pass

def batch_inc(accessor: CounterAccessor, *label_values: Any, amount: float = 1.0) -> None:
    """Convenience helper to batch increment a counter accessor.

    Usage:
        from src.metrics.emitter import batch_inc
        batch_inc(m_api_calls_total_labels, 'get_quote', 'success')

    Falls back to direct .inc() if batching disabled or any error occurs.
    """
    try:
        metric_batcher.inc(accessor, amount, *label_values)
    except Exception:
        try:
            lbl = accessor(*label_values)
            if lbl:
                lbl.inc(amount)  # type: ignore[attr-defined]
        except Exception:
            pass

def flush_now() -> None:
    """Force an immediate flush (used in tests)."""
    try:
        metric_batcher.flush()
    except Exception:
        pass

def pending_queue_size() -> int:
    """Return number of pending batched counter keys (best-effort)."""
    try:
        if not metric_batcher.enabled:
            return 0
        return len(metric_batcher._counters)  # type: ignore[attr-defined]
    except Exception:
        return 0

__all__ = ["metric_batcher", "MetricBatcher", "batch_inc", "flush_now", "pending_queue_size"]
