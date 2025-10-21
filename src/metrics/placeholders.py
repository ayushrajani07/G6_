"""Always-on placeholder metrics extraction.

This module contains logic previously embedded in MetricsRegistry._init_always_on_placeholders.
It is imported by metrics.core components to register deterministic baseline metrics without
bloated monolithic code.
"""
from __future__ import annotations

import logging
import os  # required for strict mode flag evaluation
from collections.abc import Callable
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

__all__ = ["init_always_on_placeholders"]

def init_always_on_placeholders(reg: Any, group_allowed: Callable[[str], bool]) -> None:
    """Register always-on placeholder metrics onto an existing registry object.

    Parameters
    ----------
    reg : object
        Metrics registry instance (expects attributes set dynamically).
    group_allowed : Callable[[str], bool]
        Predicate used to respect current group gating for optional group tagging.
    """
    log = logging.getLogger(__name__)
    log.debug("init_always_on_placeholders: start for %s", reg.__class__.__name__)
    if not hasattr(reg, '_always_on_metrics'):
        reg._always_on_metrics = []  # type: ignore[attr-defined]

    from prometheus_client import REGISTRY as _R  # local import (defensive)

    def _ensure(attr: str, ctor, prom_name: str, doc: str, labels=None, *, group: str | None = None):  # noqa: ANN001
        labels = labels or []
        if hasattr(reg, attr):
            if attr not in reg._always_on_metrics:  # type: ignore[attr-defined]
                reg._always_on_metrics.append(attr)  # type: ignore[attr-defined]
            return
        metric = None
        strict = False
        try:
            strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
        except Exception:
            pass
        try:
            metric = ctor(prom_name, doc, labels) if labels else ctor(prom_name, doc)
        except ValueError:
            # Duplicate – attempt steal existing
            try:
                for coll, names in getattr(_R, '_collector_to_names', {}).items():  # type: ignore[attr-defined]
                    if prom_name in names:
                        metric = coll
                        break
            except Exception:
                pass
        except Exception as e:  # unexpected
            import logging
            logging.getLogger(__name__).error("placeholder metric create failed %s (%s): %s", attr, prom_name, e, exc_info=True)
            if strict:
                raise
            metric = None
        if metric is not None:
            setattr(reg, attr, metric)
            reg._always_on_metrics.append(attr)  # type: ignore[attr-defined]
            if group and group_allowed(group) and attr not in getattr(reg, '_metric_groups', {}):
                try:
                    reg._metric_groups[attr] = group  # type: ignore[attr-defined]
                    if hasattr(reg, 'metric_group_state'):
                        reg.metric_group_state.labels(group=group).set(1)  # type: ignore[attr-defined]
                except Exception:
                    pass

    # Expiry remediation
    _ensure('expiry_rewritten_total', Counter, 'g6_expiry_rewritten_total', 'Expiry misclassification rewritten events', ['index','from_code','to_code'], group='expiry_remediation')
    _ensure('expiry_rejected_total', Counter, 'g6_expiry_rejected_total', 'Expiry misclassification rejected rows', ['index','expiry_code'], group='expiry_remediation')
    _ensure('expiry_quarantine_pending', Gauge, 'g6_expiry_quarantine_pending', 'Pending quarantined expiry rows', ['date'], group='expiry_remediation')
    _ensure('expiry_quarantined_total', Counter, 'g6_expiry_quarantined_total', 'Quarantined expiry rows total', ['index','expiry_code'], group='expiry_remediation')
    # Additional gauges/counters referenced by CsvSink and error routing
    _ensure('expiry_misclassification_total', Counter, 'g6_expiry_misclassification_total', 'Expiry misclassification detections', ['index','expiry_code','expected_date','actual_date'], group='expiry_remediation')
    _ensure('expiry_canonical_date', Gauge, 'g6_expiry_canonical_date', 'Observed canonical expiry date by tag', ['index','expiry_code','expiry_date'], group='expiry_remediation')

    # IV estimation histogram (placeholder single source of truth post redundancy cleanup)
    # Buckets mirrored from historical group_registry registration
    try:
        if not hasattr(reg, 'iv_iterations_histogram'):
            hist = Histogram('g6_iv_iterations_histogram', 'Distribution of IV solver iterations', ['index','expiry'], buckets=[1,2,3,5,8,13,21])
            reg.iv_iterations_histogram = hist
            if group_allowed('iv_estimation'):
                try:
                    reg._metric_groups['iv_iterations_histogram'] = 'iv_estimation'  # type: ignore[attr-defined]
                except Exception:
                    pass
    except Exception:
        pass

    # SLA health moved to sla.init_sla_placeholders (extracted)

    # Provider failover moved to provider_failover.init_provider_failover_placeholders (extracted)

    # Scheduler metric moved to scheduler.init_scheduler_placeholders (extracted)

    # Panel diff metrics removed from placeholders to avoid duplication; group_registry authoritative.

    # Band rejections moved to adaptive.init_adaptive_placeholders
    log.debug("init_always_on_placeholders: registered attrs=%s", getattr(reg, '_always_on_metrics', None))
