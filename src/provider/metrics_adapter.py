"""Provider metrics adapter (A18).

Abstraction layer to avoid direct coupling to prometheus or other libs.
Provides no-op defaults; tests can inject a RecordingMetrics instance.
"""
from __future__ import annotations

import time
from typing import Any, Protocol


class MetricsSink(Protocol):
    def incr(self, name: str, **labels: Any) -> None: ...
    def observe(self, name: str, value: float, **labels: Any) -> None: ...

class NoOpMetrics:
    def incr(self, name: str, **labels: Any) -> None:  # pragma: no cover - trivial
        return None
    def observe(self, name: str, value: float, **labels: Any) -> None:  # pragma: no cover - trivial
        return None

class RecordingMetrics:
    """In-memory metrics recorder for tests."""
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, Any]]] = []
        self.observations: list[tuple[str, float, dict[str, Any]]] = []
    def incr(self, name: str, **labels: Any) -> None:
        self.counters.append((name, labels))
    def observe(self, name: str, value: float, **labels: Any) -> None:
        self.observations.append((name, value, labels))

_METRICS: MetricsSink = NoOpMetrics()

def set_metrics_sink(sink: MetricsSink) -> None:
    global _METRICS  # noqa: PLW0603
    _METRICS = sink

def metrics() -> MetricsSink:
    return _METRICS

# Helper context manager for timing
from contextlib import contextmanager


@contextmanager
def time_observation(name: str, **labels: Any):
    start = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - start
        _METRICS.observe(name, dt, **labels)
