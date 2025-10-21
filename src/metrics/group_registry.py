"""Grouped metric registration dispatcher (spec-driven).

All grouped metrics (panel_diff, risk_agg, adaptive_controller,
panels_integrity, analytics_vol_surface, greeks, cache) are now declared in
``GROUPED_METRIC_SPECS`` within ``spec.py``.  This module becomes a very thin
adapter that invokes ``MetricDef.register`` for each spec.  Any failure is
suppressed so that metrics issues never block process startup (mirrors legacy
behavior) while still logging a warning for operator visibility.

Legacy delegated module bodies have been replaced with no-op shims elsewhere;
keep this module minimal to avoid drift.
"""
from __future__ import annotations

import logging
import os
from typing import Any

try:  # pragma: no cover - defensive import guard
    from .spec import GROUPED_METRIC_SPECS  # type: ignore
except Exception:  # pragma: no cover - extremely defensive: treat as empty
    GROUPED_METRIC_SPECS = []  # type: ignore

__all__ = ["register_group_metrics"]

_log = logging.getLogger(__name__)


def register_group_metrics(reg: Any) -> None:  # pragma: no cover - exercised via higher level tests
    maybe = getattr(reg, "_maybe_register", None)
    if not callable(maybe):
        _log.debug("Registry lacks _maybe_register; skipping grouped metrics")
        return

    registered = 0
    for spec in GROUPED_METRIC_SPECS:  # type: ignore
        try:
            spec.register(reg)
            registered += 1
        except Exception:  # pragma: no cover - robustness
            _log.warning("Failed registering grouped metric spec %s", getattr(spec, 'attr', '?'), exc_info=True)

    # Optional hard suppression (beyond generic noise filter first-occurrence behavior)
    suppress = os.getenv('G6_SUPPRESS_GROUPED_METRICS_BANNER','').strip().lower() in {'1','true','yes','on'}
    if not suppress:
        _log.info("Grouped metrics registration complete (specs=%s attrs=%s)", len(GROUPED_METRIC_SPECS), registered)
