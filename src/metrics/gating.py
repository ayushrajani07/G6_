"""Metric group gating utilities.

Encapsulates environment-based group enable/disable logic previously
embedded directly in `metrics.py` so the registry constructor can stay
focused on metric creation while this module handles policy.

Key Functions:
  parse_filters() -> (enabled_set|None, disabled_set)
  configure_registry_groups(reg) -> (controlled_groups, enabled_set, disabled_set)
  apply_pruning(reg, controlled_groups, enabled_set, disabled_set)

Constants:
  CONTROLLED_GROUPS: set[str] - all metric groups subject to gating

Behavior:
  - Always-on groups (attached on registry as _always_on_groups) are never pruned.
    - Legacy 'perf_cache' alias removed (use 'cache').
"""
from __future__ import annotations

from typing import Any

try:
    from src.orchestrator.gating_types import MetricsRegistryLike  # type: ignore
except Exception:  # pragma: no cover
    class MetricsRegistryLike:  # type: ignore
        pass
import logging
import os

from .groups import ALWAYS_ON, MetricGroup

logger = logging.getLogger(__name__)

# Canonical controlled group strings (aligned with MetricGroup values)
CONTROLLED_GROUPS: set[str] = {
    MetricGroup.ANALYTICS_VOL_SURFACE.value,
    MetricGroup.ANALYTICS_RISK_AGG.value,
    MetricGroup.PANEL_DIFF.value,
    MetricGroup.PARALLEL.value,
    MetricGroup.SLA_HEALTH.value,
    MetricGroup.OVERLAY_QUALITY.value,
    MetricGroup.STORAGE.value,
    MetricGroup.CACHE.value,
    MetricGroup.EXPIRY_POLICY.value,
    MetricGroup.PANELS_INTEGRITY.value,
    MetricGroup.IV_ESTIMATION.value,
    MetricGroup.GREEKS.value,
    MetricGroup.ADAPTIVE_CONTROLLER.value,
    MetricGroup.PROVIDER_FAILOVER.value,
    MetricGroup.EXPIRY_REMEDIATION.value,
    MetricGroup.LIFECYCLE.value,
}

# Fallback alias (exported) so callers needing a conservative default can use
# the same canonical set without duplicating literals. Maintained as a copy to
# avoid accidental mutation of CONTROLLED_GROUPS.
CONTROLLED_GROUPS_FALLBACK: set[str] = set(CONTROLLED_GROUPS)

_LEGACY_PERF_CACHE_KEY = "perf_cache"

def _warn_legacy_perf_cache(raw: str) -> None:
    if not raw:
        return
    if _LEGACY_PERF_CACHE_KEY in {p.strip() for p in raw.split(',')}:
        # Respect global suppression env
        if os.getenv("G6_SUPPRESS_DEPRECATIONS"):
            return
        try:
            logger.warning(
                "metrics.perf_cache_legacy_reference: 'perf_cache' alias removed; use 'cache' in G6_ENABLE_METRIC_GROUPS / G6_DISABLE_METRIC_GROUPS"
            )
        except Exception:
            pass


def parse_filters() -> tuple[set[str] | None, set[str]]:
    """Parse enable/disable environment variables.

    Returns a tuple: (enabled_set_or_None, disabled_set)
    - If enabled set is None: all groups implicitly enabled (subject to disables).
    """
    enable_env = os.environ.get("G6_ENABLE_METRIC_GROUPS", "")
    disable_env = os.environ.get("G6_DISABLE_METRIC_GROUPS", "")
    # Emit legacy alias warning if present
    _warn_legacy_perf_cache(enable_env)
    _warn_legacy_perf_cache(disable_env)
    enabled = {g.strip() for g in enable_env.split(',') if g.strip()} if enable_env else None
    disabled = {g.strip() for g in disable_env.split(',') if g.strip()}
    return enabled, disabled

def configure_registry_groups(reg: MetricsRegistryLike | Any) -> tuple[set[str], set[str] | None, set[str]]:  # pragma: no cover - simple wiring
    """Attach group filtering predicate and capture enable/disable sets.

    Semantics (verified by tests in test_metric_groups_enable_disable.py):
      1. If G6_ENABLE_METRIC_GROUPS is set (non-empty) treat it as an allow-list.
         Only groups appearing in that list (plus ALWAYS_ON) are allowed (unless disabled).
      2. ALWAYS_ON groups are always permitted regardless of enable list or disables.
      3. G6_DISABLE_METRIC_GROUPS always removes the group (even if enabled) UNLESS it is ALWAYS_ON.
      4. When enable list references no existing controlled groups, result should be empty (except ALWAYS_ON?).
         Historical tests expect truly empty (no controlled groups) so we DO NOT auto-add ALWAYS_ON when enable list
         has zero valid entries. (ALWAYS_ON only bypasses pruning when not explicitly excluded by enable semantics.)
    """
    enabled_set, disabled_set = parse_filters()
    reg._always_on_groups = {g.value for g in ALWAYS_ON}  # type: ignore[attr-defined]
    # Removed legacy perf_cache alias; callers should use 'cache'

    # Compute effective enabled universe respecting rule (4)
    if enabled_set is not None:
        # Intersect with controlled groups; if intersection empty keep it empty (don't inject ALWAYS_ON)
        intersection = {g for g in enabled_set if g in CONTROLLED_GROUPS}
        effective_enabled = intersection
    else:
        effective_enabled = CONTROLLED_GROUPS.copy()

    # Persist raw and effective filter state for dynamic prune API reuse
    try:  # pragma: no cover - defensive
        reg._enabled_groups_raw = os.environ.get("G6_ENABLE_METRIC_GROUPS", "")  # type: ignore[attr-defined]
        reg._disabled_groups_raw = os.environ.get("G6_DISABLE_METRIC_GROUPS", "")  # type: ignore[attr-defined]
        reg._enabled_groups = enabled_set  # type: ignore[attr-defined]
        reg._disabled_groups = disabled_set  # type: ignore[attr-defined]
        reg._effective_enabled_groups = effective_enabled  # type: ignore[attr-defined]
    except Exception:
        pass

    _trace = os.environ.get('G6_METRICS_GATING_TRACE','').lower() in {'1','true','yes','on'}
    def _group_allowed(name: str) -> bool:
        if enabled_set is not None:
            # Allow only those explicitly enabled (intersection already pruned) and not disabled
            allowed = (name in effective_enabled) and (name not in disabled_set)
            if _trace:
                try:
                    print(f"[metrics-gating] name={name} enabled_mode=1 in_enabled={name in effective_enabled} disabled={name in disabled_set} -> {allowed}", flush=True)
                except Exception:
                    pass
            return allowed
        # No enable list: all controlled groups allowed unless disabled
        if name in disabled_set:
            if _trace:
                try:
                    print(f"[metrics-gating] name={name} enabled_mode=0 disabled=1 -> False", flush=True)
                except Exception:
                    pass
            return False
        if _trace:
            try:
                print(f"[metrics-gating] name={name} enabled_mode=0 disabled=0 -> True", flush=True)
            except Exception:
                pass
        return True

    reg._group_allowed = _group_allowed  # type: ignore[attr-defined]
    # Structured log for observability (deduplicated). Allow override to force every call via env.
    try:  # pragma: no cover
        force_every = os.environ.get('G6_METRICS_GROUP_FILTERS_LOG_EVERY_CALL','').lower() in {'1','true','yes','on'}
        already = getattr(reg, '_group_filters_structured_emitted', False)
        if force_every or not already:
            logger.info(
                "metrics.group_filters.loaded",
                extra={
                    "event": "metrics.group_filters.loaded",
                    "enabled_raw": os.environ.get("G6_ENABLE_METRIC_GROUPS", ""),
                    "disabled_raw": os.environ.get("G6_DISABLE_METRIC_GROUPS", ""),
                    "effective_enabled_count": len(effective_enabled),
                    "enabled_spec_active": enabled_set is not None,
                    "disabled_count": len(disabled_set),
                    "dedup": (not force_every and already),
                },
            )
            try:
                reg._group_filters_structured_emitted = True
            except Exception:
                pass
    except Exception:
        pass
    return CONTROLLED_GROUPS, enabled_set, disabled_set

def apply_pruning(
    reg: MetricsRegistryLike | Any,
    controlled: set[str],
    enabled_set: set[str] | None,
    disabled_set: set[str],
) -> None:  # pragma: no cover - deterministic small loop
    try:
        always_on: set[str] = set(getattr(reg, '_always_on_groups', set()))
        predicate = getattr(reg, '_group_allowed', lambda n: True)
        metric_groups = getattr(reg, '_metric_groups', {})
        # Access Prometheus client registry for unregistration attempts
        try:
            from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
        except Exception:  # pragma: no cover
            _PROM_REG = None  # type: ignore
        for attr, group in list(metric_groups.items()):
            # Only consider controlled groups and skip ALWAYS_ON safety set
            if group in controlled and group not in always_on:
                remove = False
                try:
                    if not predicate(group):
                        remove = True
                except Exception:
                    remove = False
                if remove:
                    # Attempt to unregister underlying collector to free name
                    try:
                        coll = getattr(reg, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Remove attribute from registry instance
                    try:
                        if hasattr(reg, attr):
                            delattr(reg, attr)
                    except Exception:
                        pass
                    # Remove mapping entry
                    try:
                        del metric_groups[attr]
                    except Exception:
                        pass
    except Exception:
        pass

__all__ = [
    'CONTROLLED_GROUPS',
    'CONTROLLED_GROUPS_FALLBACK',
    'parse_filters',
    'configure_registry_groups',
    'apply_pruning',
]
