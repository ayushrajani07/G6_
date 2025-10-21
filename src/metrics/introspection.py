"""Metrics introspection utilities (extracted from metrics.py).

Provides lightweight reflection helpers for enumerating metric objects
registered on the central MetricsRegistry instance without scraping the
Prometheus exposition format. Only metrics whose underlying collector name
begins with the g6_ namespace prefix are included (internal helper metrics
may be in other namespaces and are intentionally excluded to keep the
surface stable and reduce noise).

Functions:
  build_introspection_inventory(registry) -> list[dict]
  get_metrics_introspection(registry) -> list[dict]

Both helpers are defensive: any unexpected errors result in an empty list
so callers (tests / operators) don't experience hard failures when new
collector types are introduced.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # Prometheus client is required by the surrounding package
    from prometheus_client import REGISTRY  # type: ignore
except Exception:  # pragma: no cover - extremely unlikely import failure
    REGISTRY = None  # type: ignore

__all__ = [
    "build_introspection_inventory",
    "get_metrics_introspection",
]


def build_introspection_inventory(registry: Any) -> list[dict[str, Any]]:  # pragma: no cover - pure data assembly
    """Assemble a list of metric metadata dictionaries.

    Each entry contains: name, attr, type, group, labels, documentation.
    Only attributes whose underlying collector exposes a _name beginning
    with the 'g6_' prefix are included to avoid leaking internal state.
    The result is deterministically sorted by metric name then attribute.
    """
    inventory: list[dict[str, Any]] = []
    try:
        # The registry mapping can be useful for future enrichment; retained for parity
        _ = getattr(REGISTRY, "_names_to_collectors", {}) if REGISTRY else {}
    except Exception:
        pass
    metric_groups = getattr(registry, "_metric_groups", {})
    for attr, value in registry.__dict__.items():
        try:
            metric_name = getattr(value, "_name", None)
        except Exception:
            metric_name = None
        if not metric_name or not isinstance(metric_name, str) or not metric_name.startswith("g6_"):
            continue
        mtype = value.__class__.__name__
        labels = []
        for cand in ("_labelnames", "_labelnames_set"):
            try:
                ln = getattr(value, cand, None)
                if ln:
                    if isinstance(ln, (list, tuple, set)):
                        labels = list(ln)
                        break
            except Exception:
                pass
        doc = getattr(value, "_documentation", "")
        group = metric_groups.get(attr)
        inventory.append(
            {
                "name": metric_name,
                "attr": attr,
                "type": mtype,
                "group": group,
                "labels": labels,
                "documentation": doc,
            }
        )
    inventory.sort(key=lambda x: (x["name"], x["attr"]))
    return inventory


def get_metrics_introspection(registry: Any) -> list[dict[str, Any]]:  # pragma: no cover - thin accessor
    """Return cached introspection inventory, rebuilding if absent."""
    inv = getattr(registry, "_metrics_introspection", None)
    if inv is None:
        try:
            registry._metrics_introspection = build_introspection_inventory(registry)  # type: ignore[attr-defined]
        except Exception:
            registry._metrics_introspection = []  # type: ignore[attr-defined]
        inv = registry._metrics_introspection
        # Structured log indicating lazy construction
        try:  # pragma: no cover
            logger.info(
                "metrics.introspection.lazy_built",
                extra={
                    "event": "metrics.introspection.lazy_built",
                    "metric_count": len(inv) if inv else 0,
                },
            )
        except Exception:
            pass
    # Return a shallow copy so callers don't mutate internal cache
    return list(inv)
