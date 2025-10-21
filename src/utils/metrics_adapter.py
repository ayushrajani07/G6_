#!/usr/bin/env python3
"""
Metrics Adapter

Thin compatibility layer over src.summary.metrics_processor that exposes a
small, stable set of getters used by runtime status and live panel code.

Goals:
- Centralize metrics reads via MetricsProcessor (single source of truth)
- Avoid re-computing the same metrics in multiple places
- Provide safe fallbacks (return None) when metrics are unavailable

This module is intentionally lightweight: it delegates to MetricsProcessor,
which already handles caching, parsing, and fault tolerance.
"""
from __future__ import annotations

from typing import Any, Protocol

try:
    from src.summary.metrics_processor import get_metrics_processor  # real factory
except Exception:  # pragma: no cover
    get_metrics_processor = None  # type: ignore[assignment]

# Lightweight placeholders used only when returning empty/fallback objects
class _IndexMetricsPlaceholder:
    pass


class _ProcessorProto(Protocol):  # minimal protocol for typing convenience
    def get_all_metrics(self) -> Any: ...
    def get_performance_metrics(self) -> Any: ...
    def get_index_metrics(self, index: str | None = None) -> Any: ...


class MetricsAdapter:
    """Facade around the global MetricsProcessor with simple getters.

    All accessor methods return simple scalars or dicts, and they are
    defensive: on error they return None (or empty structures) instead of
    raising. This keeps call sites robust.
    """

    def __init__(self, prometheus_url: str | None = None, processor: Any | None = None):
        """Create an adapter.

        Parameters:
        - prometheus_url: Optional override for the metrics processor's Prometheus base URL
        - processor: Optional injected metrics processor instance (for tests/DI). If provided,
          the adapter will use this directly and ignore prometheus_url.
        """
        if processor is not None:
            self._processor = processor
        else:
            if get_metrics_processor is None:
                # Allow construction even if imports failed; methods will no-op
                self._processor = None
            else:
                # Let processor use its default URL unless explicitly provided
                # The real get_metrics_processor accepts optional url override; narrow via runtime check
                if get_metrics_processor is not None:
                    if prometheus_url:
                        self._processor = get_metrics_processor(prometheus_url)
                    else:
                        self._processor = get_metrics_processor()

    # ---- Raw accessors ----
    def get_platform_metrics(self) -> Any | None:
        try:
            if not self._processor:
                return None
            return self._processor.get_all_metrics()
        except Exception:
            return None

    def get_performance_metrics(self) -> Any | None:
        try:
            if not self._processor:
                return None
            return self._processor.get_performance_metrics()
        except Exception:
            return None

    def get_index_metrics(self, index: str | None = None) -> Any:
        try:
            if not self._processor:
                return {} if index is None else _IndexMetricsPlaceholder()
            return self._processor.get_index_metrics(index)
        except Exception:
            return {} if index is None else _IndexMetricsPlaceholder()

    # ---- Scalar helpers ----
    def get_memory_usage_mb(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'memory_usage_mb', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_cpu_percent(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'cpu_usage_percent', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_api_success_rate_percent(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'api_success_rate', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_api_latency_ms(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'api_response_time', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_collection_success_rate_percent(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'collection_success_rate', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_options_processed_total(self) -> int | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'options_processed_total', None)
            if isinstance(val, (int, float)):
                return int(val)
            return None
        except Exception:
            return None

    def get_options_per_minute(self) -> float | None:
        pm = self.get_performance_metrics()
        try:
            if pm is None:
                return None
            val = getattr(pm, 'options_per_minute', None)
            if isinstance(val, (int, float)):
                return float(val)
            return None
        except Exception:
            return None

    def get_last_cycle_options_sum(self) -> int | None:
        """Approximate last-cycle options by summing per-index current_cycle_legs.

        This mirrors what the UI previously reported via local counters, but
        now uses the processor’s per-index metric g6_index_options_processed.
        """
        try:
            idx = self.get_index_metrics() or {}
            if not isinstance(idx, dict):
                return None
            total = 0
            for _name, im in idx.items():
                try:
                    total += int(getattr(im, 'current_cycle_legs', 0))
                except Exception:
                    continue
            return total
        except Exception:
            return None


_adapter_singleton: MetricsAdapter | None = None


def get_metrics_adapter(prometheus_url: str | None = None, *, processor: Any | None = None) -> MetricsAdapter:
    """Return a process-wide MetricsAdapter singleton.

    The adapter internally uses a cached MetricsProcessor instance which also
    caches recent Prometheus reads, so repeated calls are cheap.
    """
    global _adapter_singleton
    if _adapter_singleton is None:
        _adapter_singleton = MetricsAdapter(prometheus_url, processor=processor)
    return _adapter_singleton
