"""Runtime gating and late-binding helpers extracted from monolithic metrics module.

Provides side-effect free functions operating on a MetricsRegistry-like object.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover
    # Minimal fallbacks for environments without prometheus_client
    class _Dummy:
        def __init__(self, *a, **k):
            pass
        def labels(self, *a, **k):
            return self
        def inc(self, *a, **k):
            return None
        def set(self, *a, **k):
            return None
    Counter = Gauge = Histogram = _Dummy  # type: ignore

__all__ = ["enforce_runtime_metric_gates", "late_bind_lazy_metrics"]


def enforce_runtime_metric_gates(reg: Any) -> None:  # pragma: no cover - thin logic
    """Apply environment-based runtime gates that may change between tests.

    Currently prunes per-expiry vol surface metrics when the enabling flag is now off.
    """
    try:
        if os.getenv('G6_VOL_SURFACE_PER_EXPIRY') != '1':
            for attr in ('vol_surface_rows_expiry', 'vol_surface_interpolated_fraction_expiry'):
                if hasattr(reg, attr):
                    try:
                        delattr(reg, attr)
                    except Exception:
                        pass
                    try:
                        getattr(reg, '_metric_groups', {}).pop(attr, None)
                    except Exception:
                        pass
    except Exception:
        pass


def late_bind_lazy_metrics(reg: Any) -> None:  # noqa: C901 - retained complexity from legacy path
    """Register metrics expected by tests if absent due to earlier init ordering.

    Mirrors prior _late_bind_lazy_metrics behavior from monolithic implementation.
    """
    try:
        def _force_panel_metric(attr: str, ctor, prom_name: str, doc: str, labels):  # noqa: ANN001
            if not getattr(reg, '_group_allowed', lambda *_: True)('panel_diff'):
                return
            existing = getattr(reg, attr, None)
            needs_replace = False
            if existing is not None:
                try:
                    existing.labels(**{l: 'x' for l in labels})
                    return
                except Exception:
                    needs_replace = True
            try:
                if needs_replace:
                    from prometheus_client import REGISTRY as _R
                    names_map = getattr(_R, '_names_to_collectors', {})
                    coll = names_map.get(prom_name)
                    if coll is not None:
                        try:
                            _R.unregister(coll)
                        except Exception:
                            pass
                metric = ctor(prom_name, doc, labels)
                setattr(reg, attr, metric)
                try:
                    getattr(reg, '_metric_groups', {})[attr] = 'panel_diff'
                except Exception:
                    pass
            except Exception:
                pass

        # Panel diff metrics are spec-driven; ensure presence if group allowed and spec registration skipped for any reason.
        _force_panel_metric('panel_diff_writes', Counter, 'g6_panel_diff_writes_total', 'Panel diff snapshots written', ['type'])
        _force_panel_metric('panel_diff_truncated', Counter, 'g6_panel_diff_truncated_total', 'Panel diff truncation events', ['reason'])
        _force_panel_metric('panel_diff_bytes_total', Counter, 'g6_panel_diff_bytes_total', 'Total bytes of diff JSON written', ['type'])
        _force_panel_metric('panel_diff_bytes_last', Gauge, 'g6_panel_diff_bytes_last', 'Bytes of last diff JSON written', ['type'])

        # Risk aggregation & vol surface metrics are spec-driven; legacy late-binding removed.

        mapping_candidates = {
            'expiry_rewritten_total': 'expiry_remediation',
            'expiry_rejected_total': 'expiry_remediation',
            'expiry_quarantine_pending': 'expiry_remediation',
            'expiry_quarantined_total': 'expiry_remediation',
        }
        for attr, grp in mapping_candidates.items():
            if hasattr(reg, attr) and attr not in getattr(reg, '_metric_groups', {}) and getattr(reg, '_group_allowed', lambda *_: True)(grp):
                try:
                    reg._metric_groups[attr] = grp
                except Exception:
                    pass
        for attr, grp in list(getattr(reg, '_metric_groups', {}).items()):
            if not getattr(reg, '_group_allowed', lambda *_: True)(grp):
                try:
                    reg._metric_groups.pop(attr, None)
                except Exception:
                    pass
    except Exception:
        pass
