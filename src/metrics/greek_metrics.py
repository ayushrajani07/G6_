"""Greek metrics initialization (extracted Phase 2).

Provides a single function `init_greek_metrics(registry)` that attaches option
Greek gauges to the provided registry object. Mirrors legacy
`MetricsRegistry._init_greek_metrics` without changing metric names, labels or
semantics.
"""
from __future__ import annotations

from typing import Any

from prometheus_client import Gauge  # type: ignore

__all__ = ["init_greek_metrics"]


def init_greek_metrics(registry: Any) -> None:  # pragma: no cover - thin wrapper exercised via MetricsRegistry tests
    greek_names = ['delta', 'theta', 'gamma', 'vega', 'rho']
    for greek in greek_names:
        attr = f"option_{greek}"
        if hasattr(registry, attr):  # idempotent: skip if already present
            continue
        try:
            gauge = Gauge(f'g6_option_{greek}', f'Option {greek}', ['index', 'expiry', 'strike', 'type'])
            setattr(registry, attr, gauge)
        except Exception:  # pragma: no cover - defensive; errors ignored to avoid startup failure
            pass
