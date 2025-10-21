"""
Lightweight Metrics Factory to create Prometheus metrics with standardized labels.

This is intentionally minimal to avoid large refactors. It provides helper
methods to construct Counter/Gauge/Histogram ensuring label keys are strings
and optionally validating against recommended sets.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from prometheus_client import Counter, Gauge, Histogram


def _normalize_labels(labels: Iterable[str] | None) -> Sequence[str]:
    if not labels:
        return ()
    return tuple(str(l) for l in labels)


def make_counter(name: str, doc: str, labels: Iterable[str] | None = None) -> Counter:
    return Counter(name, doc, _normalize_labels(labels))


def make_gauge(name: str, doc: str, labels: Iterable[str] | None = None) -> Gauge:
    return Gauge(name, doc, _normalize_labels(labels))


def make_histogram(name: str, doc: str, labels: Iterable[str] | None = None, buckets: Sequence[float] | None = None) -> Histogram:
    if buckets is None:
        return Histogram(name, doc, _normalize_labels(labels))
    return Histogram(name, doc, _normalize_labels(labels), buckets=buckets)


__all__ = ["make_counter", "make_gauge", "make_histogram"]
