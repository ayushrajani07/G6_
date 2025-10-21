"""Centralized metric registration helpers.

Provides two functions used by `MetricsRegistry`:

1. core_register(...)   -> idempotent creation of non‑grouped core metrics
2. maybe_register(...)  -> guarded creation of grouped metrics respecting enable/disable filters

Both functions are resilient to duplicate name ValueErrors (common when the
Prometheus default registry still holds a previous collector due to prior
initialization in the same process). Unexpected exceptions are logged and
optionally re-raised if G6_METRICS_STRICT_EXCEPTIONS is set (fail‑fast mode).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY  # type: ignore

logger = logging.getLogger(__name__)


def core_register(registry: Any, attr: str, ctor: Callable, name: str, doc: str,
                  labels: list[str] | None = None, group: str | None = None, **ctor_kwargs) -> Any:  # type: ignore
    if hasattr(registry, attr):  # idempotent fast path
        return getattr(registry, attr)
    collector = None
    try:
        if labels:
            collector = ctor(name, doc, labels, **ctor_kwargs)
        else:
            collector = ctor(name, doc, **ctor_kwargs)
    except ValueError:
        # Duplicate: recover existing collector from global registry
        try:
            names_map = getattr(REGISTRY, '_names_to_collectors', {})
            collector = names_map.get(name)
        except Exception:
            collector = None
    except Exception as e:  # unexpected
        strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
        logger.error("core_register unexpected error creating %s (%s): %s", attr, name, e, exc_info=True)
        if strict:
            raise
        collector = None
    if collector is not None:
        try:
            setattr(registry, attr, collector)
            if group:
                registry._metric_groups[attr] = group  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - bookkeeping
            pass
    return collector


def maybe_register(registry: Any, group: str, attr: str, metric_cls: Callable,
                   name: str, documentation: str, labels: list[str] | None = None, **ctor_kwargs) -> Any:  # type: ignore
    strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}

    # Resolve alias map if present (some refactors add _group_alias on registry)
    try:
        if hasattr(registry, '_group_alias'):
            group = registry._group_alias.get(group, group)  # type: ignore[attr-defined]
    except Exception:
        pass

    # Respect gating predicate if available
    try:
        if hasattr(registry, '_group_allowed') and not registry._group_allowed(group):  # type: ignore[attr-defined]
            return None
    except Exception:
        pass

    if hasattr(registry, attr):  # idempotent
        return getattr(registry, attr)

    collector = None
    try:
        if labels:
            collector = metric_cls(name, documentation, labels, **ctor_kwargs)
        else:
            collector = metric_cls(name, documentation, **ctor_kwargs)
    except ValueError:
        # Duplicate registration: attempt to reuse existing by name, else fall back to any existing attr
        try:
            names_map = getattr(REGISTRY, '_names_to_collectors', {})
            existing = names_map.get(name)
            if existing is not None:
                collector = existing
            elif hasattr(registry, attr):  # attribute already present; reuse
                collector = getattr(registry, attr)
            else:
                collector = None
        except Exception as e:  # pragma: no cover
            logger.debug("maybe_register registry lookup failed for duplicate %s: %s", name, e)
            collector = getattr(registry, attr, None)
    except Exception as e:  # unexpected
        logger.error("maybe_register unexpected error creating %s (%s): %s", attr, name, e, exc_info=True)
        if strict:
            raise
        return None

    if collector is not None:
        try:
            setattr(registry, attr, collector)
            registry._metric_groups[attr] = group  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
    return collector


__all__ = ["core_register", "maybe_register"]
