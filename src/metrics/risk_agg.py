"""Risk aggregation metrics registration.

Extracted from group_registry to provide a focused module for analytics risk aggregation
metrics. Metrics (all Gauges):
  - risk_agg_rows
  - risk_agg_notional_delta
  - risk_agg_notional_vega
  - risk_agg_bucket_utilization

Registration contract:
  * Uses registry._maybe_register just like group_registry blocks.
  * Group name: analytics_risk_agg
  * Does not create metrics if group gating disallows the group.
  * Pure refactor: No changes to metric names, types, or documentation strings.
"""
from __future__ import annotations

from typing import Any

__all__ = ["init_risk_agg_metrics"]


def init_risk_agg_metrics(reg: Any) -> None:  # pragma: no cover - deprecated shim
      """Deprecated no-op (risk aggregation metrics now spec-driven)."""
      return
