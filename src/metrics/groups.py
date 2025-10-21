from __future__ import annotations

"""Metric group taxonomy + group filtering helpers.

Consolidates group enumeration (MetricGroup), always-on set, and the
GroupFilters loader previously scattered across modules.
"""

from enum import Enum


class MetricGroup(str, Enum):
    ANALYTICS_VOL_SURFACE = "analytics_vol_surface"
    ANALYTICS_RISK_AGG = "analytics_risk_agg"
    PANEL_DIFF = "panel_diff"
    PARALLEL = "parallel"
    SLA_HEALTH = "sla_health"
    OVERLAY_QUALITY = "overlay_quality"
    STORAGE = "storage"
    CACHE = "cache"
    EXPIRY_POLICY = "expiry_policy"
    PANELS_INTEGRITY = "panels_integrity"
    IV_ESTIMATION = "iv_estimation"
    GREEKS = "greeks"
    ADAPTIVE_CONTROLLER = "adaptive_controller"
    PROVIDER_FAILOVER = "provider_failover"
    EXPIRY_REMEDIATION = "expiry_remediation"
    LIFECYCLE = "lifecycle"
    SSE_INGEST = "sse_ingest"


ALWAYS_ON = {
    MetricGroup.EXPIRY_REMEDIATION,
    MetricGroup.PROVIDER_FAILOVER,
    # MetricGroup.ADAPTIVE_CONTROLLER removed from ALWAYS_ON to allow explicit disable in tests
    MetricGroup.IV_ESTIMATION,
    MetricGroup.SLA_HEALTH,
}

import os
from dataclasses import dataclass
from typing import Callable

_env_str: Callable[[str, str], str]
try:
    from src.collectors.env_adapter import get_str as _env_str  # type: ignore
except Exception:  # pragma: no cover - fallback
    def _fallback_env_str(name: str, default: str = "") -> str:
        v = os.getenv(name, default)
        return v or ""
    _env_str = _fallback_env_str

@dataclass
class GroupFilters:
    enabled_raw: str
    disabled_raw: str
    enabled: set[str] | None
    disabled: set[str]

    def allowed(self, name: str) -> bool:
        if self.disabled and name in self.disabled:
            return False
        if self.enabled is not None:
            return name in self.enabled
        return True


def load_group_filters() -> GroupFilters:
    """Load group filters from environment."""
    enabled_raw = _env_str("G6_ENABLE_METRIC_GROUPS", "")
    disabled_raw = _env_str("G6_DISABLE_METRIC_GROUPS", "")
    enabled = {g.strip() for g in enabled_raw.split(',') if g.strip()} if enabled_raw else None
    disabled = {g.strip() for g in disabled_raw.split(',') if g.strip()}
    return GroupFilters(enabled_raw, disabled_raw, enabled, disabled)

__all__ = [
    "MetricGroup",
    "ALWAYS_ON",
    "GroupFilters",
    "load_group_filters",
]
