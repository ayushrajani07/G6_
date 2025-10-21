#!/usr/bin/env python3
"""
Lightweight Memory Manager for per-cycle hygiene and emergency cleanup.

Goals:
- Provide a central place to register caches/buffers with purge callbacks
- Offer pre/post cycle cleanup hooks (cheap before work; GC after work)
- Expose basic memory stats (rss, gc counts, last gc duration)
- Allow emergency cleanup on memory pressure

Non-invasive: safe no-ops if psutil unavailable or nothing registered.
"""
from __future__ import annotations

import gc
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

logger = logging.getLogger(__name__)
try:
    from src.error_handling import handle_data_collection_error, handle_data_error
except Exception:  # pragma: no cover
    handle_data_collection_error = None  # type: ignore[assignment]
    handle_data_error = None  # type: ignore[assignment]


@dataclass
class RegisteredCache:
    name: str
    purge_fn: Callable[[], Any] | None = None
    size_fn: Callable[[], int] | None = None
    # future: prune_fn with target size


class MemoryManager:
    """Singleton-style manager with minimal state and hooks."""

    def __init__(self) -> None:
        self._proc = psutil.Process() if psutil else None
        self._last_gc_ts: float | None = None
        self._last_gc_duration_ms: float | None = None
        self._gc_collections_total: int = 0
        self._peak_rss_mb: float | None = None
        self._registered: dict[str, RegisteredCache] = {}
        # cadence knobs
        import os
        try:
            from src.collectors.env_adapter import get_bool as _env_get_bool
            from src.collectors.env_adapter import get_float as _env_get_float  # type: ignore
        except Exception:  # pragma: no cover
            def _env_get_float(name: str, default: float) -> float:
                try:
                    v = os.getenv(name)
                    if v is None or str(v).strip() == "":
                        return default
                    return float(str(v).strip())
                except Exception:
                    return default
            def _env_get_bool(name: str, default: bool = False) -> bool:
                try:
                    v = os.getenv(name)
                    if v is None:
                        return default
                    return str(v).strip().lower() in {"1","true","yes","on","y"}
                except Exception:
                    return default
        self._gc_interval_sec = _env_get_float('G6_MEMORY_GC_INTERVAL_SEC', 30.0)
        # default True if env missing (legacy behavior)
        self._minor_gc_each_cycle = _env_get_bool('G6_MEMORY_MINOR_GC_EACH_CYCLE', True)

    # -------- Registration ---------
    def register_cache(self, name: str, purge_fn: Callable[[], Any] | None = None, size_fn: Callable[[], int] | None = None) -> None:
        """Register a cache/buffer with an optional purge callback and size getter."""
        self._registered[name] = RegisteredCache(name=name, purge_fn=purge_fn, size_fn=size_fn)

    # -------- Cycle hooks ----------
    def pre_cycle_cleanup(self) -> None:
        """Cheap per-cycle prep. Avoid heavy GC here; keep latency low."""
        # Placeholder for future: trim per-cycle scratch buffers if registered
        pass

    def post_cycle_cleanup(self, aggressive: bool = False, metrics: Any = None) -> None:
        """Run GC opportunistically and update metrics/stats.

        aggressive: if True, perform a full collection regardless of interval.
        metrics: optional metrics object with memory_usage_mb gauge.
        """
        now = time.time()
        do_minor = self._minor_gc_each_cycle
        do_full = aggressive
        if (self._last_gc_ts is None) or ((now - self._last_gc_ts) >= self._gc_interval_sec):
            do_full = True
        t0 = time.perf_counter()
        try:
            if do_minor:
                try:
                    gc.collect(0)
                except Exception:
                    try:
                        if handle_data_error is not None:
                            handle_data_error(Exception("minor_gc_failed"), component="utils.memory_manager", context={"phase": "minor_gc"})
                    except Exception:
                        pass
            if do_full:
                try:
                    # Collect all generations; track objects collected
                    collected = gc.collect()
                    self._gc_collections_total += int(collected)
                    self._last_gc_ts = now
                except Exception:
                    try:
                        if handle_data_error is not None:
                            handle_data_error(Exception("full_gc_failed"), component="utils.memory_manager", context={"phase": "full_gc"})
                    except Exception:
                        pass
        finally:
            self._last_gc_duration_ms = (time.perf_counter() - t0) * 1000.0
        # Update RSS and peaks
        rss_mb = None
        if self._proc is not None:
            try:
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                if self._peak_rss_mb is None or rss_mb > self._peak_rss_mb:
                    self._peak_rss_mb = rss_mb
            except Exception:
                rss_mb = None
                try:
                    if handle_data_error is not None:
                        handle_data_error(Exception("rss_query_failed"), component="utils.memory_manager", context={"phase": "post_cycle"})
                except Exception:
                    pass
        # Metrics (best-effort)
        try:
            if metrics and hasattr(metrics, 'memory_usage_mb'):
                if rss_mb is not None:
                    metrics.memory_usage_mb.set(rss_mb)
        except Exception:
            try:
                if handle_data_collection_error is not None:
                    handle_data_collection_error(Exception("metrics_update_failed"), component="utils.memory_manager", data_type="memory_usage", context={"phase": "post_cycle"})
            except Exception:
                pass

    # -------- Emergency path -------
    def emergency_cleanup(self, reason: str = '') -> int:
        """Invoke purge callbacks for all registered caches and run a full GC.

        Returns number of caches where purge was attempted.
        """
        attempted = 0
        for name, reg in list(self._registered.items()):
            try:
                if reg.purge_fn:
                    reg.purge_fn()
                    attempted += 1
                    logger.info("MemoryManager purge invoked for cache '%s' (reason=%s)", name, reason)
            except Exception as e:  # pragma: no cover
                logger.warning("Cache purge failed (%s): %s", name, e)
                try:
                    if handle_data_collection_error is not None:
                        handle_data_collection_error(e, component="utils.memory_manager", data_type="cache_purge", context={"cache": name, "reason": reason})
                except Exception:
                    pass
        try:
            gc.collect()
            self._gc_collections_total += 1
            self._last_gc_ts = time.time()
        except Exception:
            try:
                if handle_data_error is not None:
                    handle_data_error(Exception("emergency_gc_failed"), component="utils.memory_manager", context={"phase": "emergency"})
            except Exception:
                pass
        # update rss snapshot post-purge
        if self._proc is not None:
            try:
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                if self._peak_rss_mb is None or rss_mb > self._peak_rss_mb:
                    self._peak_rss_mb = rss_mb
            except Exception:
                try:
                    if handle_data_error is not None:
                        handle_data_error(Exception("rss_query_failed"), component="utils.memory_manager", context={"phase": "emergency"})
                except Exception:
                    pass
        return attempted

    # -------- Introspection --------
    def get_stats(self) -> dict[str, Any]:
        """Return a dict of lightweight memory stats suitable for dashboards."""
        rss_mb = None
        if self._proc is not None:
            try:
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
            except Exception:
                rss_mb = None
        gen_counts = None
        try:
            gen_counts = tuple(gc.get_count())  # (gen0, gen1, gen2)
        except Exception:
            gen_counts = None
        return {
            'rss_mb': rss_mb,
            'peak_rss_mb': self._peak_rss_mb,
            'gc_collections_total': self._gc_collections_total,
            'gc_last_ts': self._last_gc_ts,
            'gc_last_duration_ms': self._last_gc_duration_ms,
            'gc_gen_counts': gen_counts,
            'registered_caches': list(self._registered.keys()),
        }


_singleton: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    global _singleton
    if _singleton is None:
        _singleton = MemoryManager()
    return _singleton


# Optional decorator for wrapping cycles (not currently used)
def with_memory_cleanup(func: Callable[..., Any]) -> Callable[..., Any]:  # pragma: no cover (utility)
    def wrapper(*args: Any, **kwargs: Any):
        mm = get_memory_manager()
        mm.pre_cycle_cleanup()
        try:
            return func(*args, **kwargs)
        finally:
            # post cleanup without aggressive flag by default
            mm.post_cycle_cleanup(aggressive=False)
    return wrapper
