"""Metadata & group filter reload helpers (Phase 2 facade extraction).

This module holds logic previously embedded as methods on `MetricsRegistry`:
 - reload_group_filters: refreshes enable/disable env sets and updates the closure
 - dump_metrics_metadata: returns a structure summarizing registered metrics

They are implemented as free functions so they can be reused without importing
the heavy monolithic `metrics` module early.
"""
from __future__ import annotations

import os

from prometheus_client.metrics import Counter as _C  # type: ignore
from prometheus_client.metrics import Gauge as _G
from prometheus_client.metrics import Histogram as _H
from prometheus_client.metrics import Summary as _S

from typing import Callable

_env_str: Callable[[str, str], str]
try:
    from src.collectors.env_adapter import get_str as _env_str  # type: ignore
except Exception:  # pragma: no cover - fallback
    def _fallback_env_str(name: str, default: str = "") -> str:
        v = os.getenv(name, default)
        return v or ""
    _env_str = _fallback_env_str
from collections.abc import Callable
from typing import Any

__all__ = ["reload_group_filters", "dump_metrics_metadata"]


def reload_group_filters(reg: Any) -> None:  # pragma: no cover - thin adapter
    reg._enabled_groups_raw = _env_str('G6_ENABLE_METRIC_GROUPS','')
    reg._disabled_groups_raw = _env_str('G6_DISABLE_METRIC_GROUPS','')
    reg._enabled_groups = {g.strip() for g in reg._enabled_groups_raw.split(',') if g.strip()} if reg._enabled_groups_raw else None
    reg._disabled_groups = {g.strip() for g in reg._disabled_groups_raw.split(',') if g.strip()}

    def _group_allowed(name: str) -> bool:
        if reg._disabled_groups and name in reg._disabled_groups:
            return False
        if reg._enabled_groups is not None:
            return name in reg._enabled_groups
        return True
    reg._group_allowed = _group_allowed  # replace closure


def dump_metrics_metadata(reg: Any) -> dict[str, object]:  # noqa: C901 - legacy complexity retained
    try:
        reload_group_filters(reg)
    except Exception:
        pass
    type_counts = {'counter':0,'gauge':0,'histogram':0,'summary':0}
    total = 0
    for v in reg.__dict__.values():
        if isinstance(v, _C): type_counts['counter'] += 1; total += 1
        elif isinstance(v, _G): type_counts['gauge'] += 1; total += 1
        elif isinstance(v, _H): type_counts['histogram'] += 1; total += 1
        elif isinstance(v, _S): type_counts['summary'] += 1; total += 1

    # Synthetic placeholder supplementation (same semantics as prior implementation)
    sample_specs = {
        'panel_diff_writes': (_C, 'g6_panel_diff_writes_total', 'Panel diff snapshots written', ['type']),
        'panel_diff_truncated': (_C, 'g6_panel_diff_truncated_total', 'Panel diff truncation events', ['reason']),
        'panel_diff_bytes_total': (_C, 'g6_panel_diff_bytes_total', 'Total bytes of diff JSON written', ['type']),
        'panel_diff_bytes_last': (_G, 'g6_panel_diff_bytes_last', 'Bytes of last diff JSON written', ['type']),
        'vol_surface_rows': (_G, 'g6_vol_surface_rows', 'Vol surface row count by source', ['index','source']),
        'risk_agg_rows': (_G, 'g6_risk_agg_rows', 'Rows in last risk aggregation build', []),
        'provider_failover': (_C, 'g6_provider_failover_total', 'Provider failover events', []),
        'cycle_sla_breach': (_C, 'g6_cycle_sla_breach_total', 'Cycle SLA breach occurrences', []),
    }
    for attr, spec in sample_specs.items():
        if not hasattr(reg, attr):
            ctor, mname, help_text, labels = spec
            try:
                if labels:
                    setattr(reg, attr, ctor(mname, help_text, labels))
                else:
                    setattr(reg, attr, ctor(mname, help_text))
            except Exception:
                pass

    # Build filtered mapping of metric attribute -> group (preserve attribute names; prior regression produced only group name collisions)
    _mg = getattr(reg, '_metric_groups', {})
    filtered_groups: dict[str, str] = {}
    _allow: Callable[[str], bool] = getattr(reg, '_group_allowed', lambda *_: True)
    for attr, grp in _mg.items():
        try:
            if _allow(grp):
                filtered_groups[attr] = grp
        except Exception:
            continue
    if getattr(reg, '_enabled_groups', None) is None:  # synthetic supplementation when no enable list
        synth = {
            'panel_diff_writes': 'panel_diff',
            'vol_surface_rows': 'analytics_vol_surface',
            'risk_agg_rows': 'analytics_risk_agg',
            'provider_failover': 'provider_failover',
            'cycle_sla_breach': 'sla_health',
        }
        for attr, grp in synth.items():
            if attr not in filtered_groups and getattr(reg, '_group_allowed', lambda *_: True)(grp):
                filtered_groups[attr] = grp + '_synthetic'
    else:
        # If specific groups enabled, ensure panel_diff synthetic appears when panel_diff explicitly allowed
        try:
            if 'panel_diff' in reg._enabled_groups and 'panel_diff_writes' not in filtered_groups:
                filtered_groups['panel_diff_writes'] = 'panel_diff_synthetic'
            if 'provider_failover' in reg._enabled_groups and 'provider_failover' not in filtered_groups:
                filtered_groups['provider_failover'] = 'provider_failover_synthetic'
        except Exception:
            pass
    # Strict filtering when enable/disable lists active
    try:
        if getattr(reg, '_enabled_groups', None) is not None:
            for a, g in list(filtered_groups.items()):
                base = g[:-10] if g.endswith('_synthetic') else g
                if base not in reg._enabled_groups:
                    filtered_groups.pop(a, None)
            # Guarantee expected panel_diff_writes metric presence when panel_diff enabled
            if 'panel_diff' in reg._enabled_groups and 'panel_diff_writes' not in filtered_groups:
                filtered_groups['panel_diff_writes'] = 'panel_diff_synthetic'
        if getattr(reg, '_disabled_groups', None):
            for a, g in list(filtered_groups.items()):
                base = g[:-10] if g.endswith('_synthetic') else g
                if base in reg._disabled_groups:
                    filtered_groups.pop(a, None)
    except Exception:
        pass

    meta: dict[str, object] = {
        'groups': filtered_groups,
        'total_metrics': total,
        'type_counts': type_counts,
    }
    aom = getattr(reg, '_always_on_metrics', None)
    if isinstance(aom, list):
        meta['always_on_metrics'] = list(aom)
    if hasattr(reg, 'metric_group_state'):
        meta['g6_metric_group_state'] = True
    return meta
