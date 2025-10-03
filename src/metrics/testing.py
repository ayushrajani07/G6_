"""Testing helpers for metrics isolation.

Provides force_new_metrics_registry() which:
  - Clears the Prometheus default registry
  - Resets the internal metrics server singleton
  - Rebuilds a MetricsRegistry WITHOUT starting a new HTTP server (avoids port churn)
  - Re-applies group registrations / gating
Use in pytest fixtures to ensure deterministic state across tests that mutate groups or rely on clean counters.
"""
from __future__ import annotations

import os
import logging
from prometheus_client import REGISTRY  # type: ignore

from .metrics import get_metrics, setup_metrics_server, MetricsRegistry

logger = logging.getLogger(__name__)


def _purge_default_registry() -> None:
    try:  # pragma: no cover - defensive
        names_map = getattr(REGISTRY, '_names_to_collectors', {})
        for c in list(getattr(names_map, 'values', lambda: [])()):  # type: ignore
            try:
                REGISTRY.unregister(c)  # type: ignore[arg-type]
            except Exception:
                pass
    except Exception:
        logger.debug("_purge_default_registry failed", exc_info=True)


def force_new_metrics_registry(enable_resource_sampler: bool = False) -> MetricsRegistry:
    """Return a brand new MetricsRegistry, clearing any existing singleton.

    We avoid binding a new HTTP server listener by passing reset=True and then
    skipping sampler threads unless explicitly requested.
    """
    # Set env flag so downstream logic sees explicit intent (mirrors runtime pattern)
    os.environ['G6_FORCE_NEW_REGISTRY'] = '1'
    _purge_default_registry()
    # Use reset path on server setup; disable resource sampler for test speed by default
    metrics, _ = setup_metrics_server(reset=True, enable_resource_sampler=enable_resource_sampler)
    # Trigger group re-registration explicitly (idempotent) in case tests rely on dynamic gating updates
    try:
        from .group_registry import register_group_metrics as _rgm  # type: ignore
        _rgm(metrics)
    except Exception:
        pass
    return metrics

__all__ = ["force_new_metrics_registry"]
