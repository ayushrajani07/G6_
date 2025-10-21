"""Volatility surface analytics metric registrations.

Extracted from `group_registry.py` to provide a single authoritative
constructor path for the `analytics_vol_surface` metric family, mirroring
recent extractions (risk_agg, greeks, adaptive, scheduler, provider_failover, sla).

Behavior: Pure refactor. Metric names, labels, grouping, and gating logic
remain unchanged. Environment flags `G6_VOL_SURFACE`, `G6_VOL_SURFACE_PER_EXPIRY`
continue to gate certain metrics exactly as before.

Metrics covered (group = analytics_vol_surface):
  - vol_surface_rows (g6_vol_surface_rows) Gauge labels: index, source
  - vol_surface_rows_expiry (g6_vol_surface_rows_expiry) Gauge labels: index, expiry, source (per-expiry variant, gated by G6_VOL_SURFACE_PER_EXPIRY=1)
  - vol_surface_interpolated_fraction (g6_vol_surface_interpolated_fraction) Gauge labels: index (requires G6_VOL_SURFACE=1)
  - vol_surface_quality_score (g6_vol_surface_quality_score) Gauge labels: index (requires G6_VOL_SURFACE=1)
  - vol_surface_interp_seconds (g6_vol_surface_interp_seconds) Histogram (always registered with group if group enabled; buckets preserved)

Deprecated legacy duplicate (left untouched elsewhere):
  - vol_surface_quality (g6_vol_surface_quality_score_legacy) Gauge (group adaptive). Not handled here; remains in adaptive group for backward compatibility.

Ordering: Called from group registry during grouped metric registration
phase; relative ordering vs other analytic groups unchanged.
"""
from __future__ import annotations

from typing import Any


def init_vol_surface_metrics(reg: Any) -> None:  # pragma: no cover - deprecated shim
      """Deprecated no-op.

      Vol surface metrics are now registered via declarative spec (GROUPED_METRIC_SPECS).
      This shim remains temporarily to avoid import errors; will be removed in a future
      release after downstream references migrate.
      """
      return

__all__ = ['init_vol_surface_metrics']
