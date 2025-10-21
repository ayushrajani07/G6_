"""Lightweight summary diff & rendering metrics wrappers.

This module provides in-process metric collectors with *optional* Prometheus
export if `prometheus_client` is installed. Tests can assert against the
in-memory snapshot without requiring the external dependency.

Metrics Exposed (names chosen to align with broader platform naming):
  - g6_summary_panel_render_seconds  (Histogram[label=panel])
  - g6_summary_panel_updates_total   (Counter[label=panel])
  - g6_summary_diff_hit_ratio        (Gauge)
  - g6_summary_panel_updates_last    (Gauge)

The wrappers intentionally implement a tiny subset of the prometheus_client
interface (labels().inc(), labels().observe(), set()) so the rest of the code
does not need divergent paths.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

try:  # Optional dependency
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
except Exception:  # pragma: no cover - fallback when lib absent
    Histogram = Counter = Gauge = None  # type: ignore

_lock = threading.Lock()

# Internal stores for test inspection
_hist_store: dict[tuple[str, tuple[tuple[str,str], ...]], list] = {}
_counter_store: dict[tuple[str, tuple[tuple[str,str], ...]], float] = {}
_gauge_store: dict[str, float] = {}
_churn_streak: int = 0  # internal consecutive high-churn cycles tracker


def _norm_labels(labels: dict[str,str] | None) -> tuple[tuple[str,str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted(labels.items()))


@dataclass
class _HistWrap:
    name: str
    prom: Any | None
    labels_kv: dict[str,str] | None = None

    def labels(self, **lbls: str) -> _HistWrap:  # prometheus style
        return _HistWrap(self.name, self.prom, lbls)

    def observe(self, value: float) -> None:
        key = (self.name, _norm_labels(self.labels_kv))
        with _lock:
            _hist_store.setdefault(key, []).append(value)
        if self.prom is not None:  # delegate
            try:
                if self.labels_kv:
                    self.prom.labels(**self.labels_kv).observe(value)
                else:
                    self.prom.observe(value)
            except Exception:  # pragma: no cover - defensive
                pass


@dataclass
class _CounterWrap:
    name: str
    prom: Any | None
    labels_kv: dict[str,str] | None = None

    def labels(self, **lbls: str) -> _CounterWrap:
        return _CounterWrap(self.name, self.prom, lbls)

    def inc(self, value: float = 1.0) -> None:
        key = (self.name, _norm_labels(self.labels_kv))
        with _lock:
            _counter_store[key] = _counter_store.get(key, 0.0) + value
        if self.prom is not None:
            try:
                if self.labels_kv:
                    self.prom.labels(**self.labels_kv).inc(value)
                else:
                    self.prom.inc(value)
            except Exception:  # pragma: no cover
                pass


@dataclass
class _GaugeWrap:
    name: str
    prom: Any | None

    def set(self, value: float) -> None:
        with _lock:
            _gauge_store[self.name] = value
        if self.prom is not None:
            try:
                self.prom.set(value)
            except Exception:  # pragma: no cover
                pass


def _make_prom_hist(name: str, doc: str, labels: tuple[str, ...] = tuple()) -> Any | None:
    if Histogram is None:
        return None
    try:
        return Histogram(name, doc, labels)
    except Exception:  # pragma: no cover
        return None


def _make_prom_counter(name: str, doc: str, labels: tuple[str, ...] = tuple()) -> Any | None:
    if Counter is None:
        return None
    try:
        return Counter(name, doc, labels)
    except Exception:  # pragma: no cover
        return None


def _make_prom_gauge(name: str, doc: str) -> Any | None:
    if Gauge is None:
        return None
    try:
        return Gauge(name, doc)
    except Exception:  # pragma: no cover
        return None


# Public metric handles
panel_render_seconds_hist = _HistWrap(
    "g6_summary_panel_render_seconds",
    _make_prom_hist("g6_summary_panel_render_seconds", "Panel render duration seconds", ("panel",)),
)
panel_updates_total = _CounterWrap(
    "g6_summary_panel_updates_total",
    _make_prom_counter("g6_summary_panel_updates_total", "Total panel updates applied", ("panel",)),
)
diff_hit_ratio_gauge = _GaugeWrap(
    "g6_summary_diff_hit_ratio",
    _make_prom_gauge("g6_summary_diff_hit_ratio", "Panel diff hit ratio (unchanged cycles / total)"),
)
panel_updates_last_gauge = _GaugeWrap(
    "g6_summary_panel_updates_last",
    _make_prom_gauge("g6_summary_panel_updates_last", "Panel updates applied in last cycle"),
)

# Anomaly / churn metrics (Phase: anomaly instrumentation)
panel_churn_ratio_gauge = _GaugeWrap(
    "g6_summary_panel_churn_ratio",
    _make_prom_gauge("g6_summary_panel_churn_ratio", "Panel churn ratio last cycle (updates/total_panels)"),
)
panel_churn_anomalies_total = _CounterWrap(
    "g6_summary_panel_churn_anomalies_total",
    _make_prom_counter("g6_summary_panel_churn_anomalies_total", "Total high-churn anomaly cycles"),
)
panel_high_churn_streak_gauge = _GaugeWrap(
    "g6_summary_panel_high_churn_streak",
    _make_prom_gauge("g6_summary_panel_high_churn_streak", "Consecutive high-churn cycles streak"),
)

# PanelsWriter file update metrics (separate from terminal diff render metrics).
# These track when the JSON artifact content for a given panel file changes between
# successive PanelsWriter.process() cycles (hash comparison). The initial baseline
# emission does not increment counters to mirror terminal diff semantics.
panel_file_updates_total = _CounterWrap(
    "g6_summary_panel_file_updates_total",
    _make_prom_counter(
        "g6_summary_panel_file_updates_total",
        "Total panel file content updates detected by PanelsWriter",
        ("panel",),
    ),
)
panel_file_updates_last_gauge = _GaugeWrap(
    "g6_summary_panel_file_updates_last",
    _make_prom_gauge(
        "g6_summary_panel_file_updates_last",
        "Panel file updates applied in last PanelsWriter cycle",
    ),
)

# Test support: allow resetting in-memory stores between tests to avoid leakage
def _reset_in_memory() -> None:  # pragma: no cover - simple clearing
    global _hist_store, _counter_store, _gauge_store, _churn_streak
    with _lock:
        _hist_store = {}
        _counter_store = {}
        _gauge_store = {}
        _churn_streak = 0


def record_churn(changed: int, total_panels: int, warn_ratio: float | None = None) -> float:
    """Record churn metrics for the last cycle.

    Args:
        changed: number of panels updated this cycle
        total_panels: total panels considered (hash map size)
        warn_ratio: override threshold; default from env G6_SUMMARY_CHURN_WARN_RATIO (0.4)

    Returns:
        Calculated churn ratio (0 if total_panels==0)
    """
    global _churn_streak  # noqa: PLW0603
    if total_panels <= 0:
        ratio = 0.0
    else:
        ratio = changed / float(total_panels)
    try:
        panel_churn_ratio_gauge.set(ratio)
    except Exception:
        pass
    if warn_ratio is None:
        import os as _os
        try:
            warn_ratio = float(_os.getenv("G6_SUMMARY_CHURN_WARN_RATIO", "0.4") or 0.4)
        except Exception:
            warn_ratio = 0.4
    if ratio >= (warn_ratio or 0.4):
        panel_churn_anomalies_total.inc()
        _churn_streak += 1
    else:
        _churn_streak = 0
    try:
        panel_high_churn_streak_gauge.set(float(_churn_streak))
    except Exception:
        pass
    return ratio

def reset_for_tests() -> None:  # pragma: no cover - only used in tests
    global _hist_store, _counter_store, _gauge_store, _churn_streak
    with _lock:
        _hist_store = {}
        _counter_store = {}
        _gauge_store = {}
        _churn_streak = 0


def snapshot() -> dict[str, Any]:  # Used in tests
    with _lock:
        return {
            "hist": {k: list(v) for k,v in _hist_store.items()},
            "counter": dict(_counter_store),
            "gauge": dict(_gauge_store),
        }

__all__ = [
    "panel_render_seconds_hist",
    "panel_updates_total",
    "diff_hit_ratio_gauge",
    "panel_updates_last_gauge",
    "panel_churn_ratio_gauge",
    "panel_churn_anomalies_total",
    "panel_high_churn_streak_gauge",
    "record_churn",
    "reset_for_tests",
    "snapshot",
    "panel_file_updates_total",
    "panel_file_updates_last_gauge",
]
