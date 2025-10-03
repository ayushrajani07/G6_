"""Legacy registration compatibility shim.

Provides a minimal _register replacement used by older runtime code paths.
Extracted from metrics.py to reduce surface area there.
"""
from __future__ import annotations

from prometheus_client.registry import REGISTRY  # type: ignore
from prometheus_client import Counter  # type: ignore
import warnings
import os
import logging

logger = logging.getLogger(__name__)

__all__ = ["legacy_register"]

_legacy_counter = None  # lazy init to avoid import-time side effects
_warned_legacy_register = False

def _inc_legacy(name: str):  # pragma: no cover - simple helper
    global _legacy_counter  # noqa: PLW0603
    global _warned_legacy_register  # noqa: PLW0603
    try:
        if _legacy_counter is None:
            try:
                _legacy_counter = Counter(
                    "g6_legacy_register_calls_total",
                    "Count of legacy metrics._register compatibility shim invocations",
                    ["metric_name"],
                )
            except ValueError:  # already exists
                collectors = getattr(REGISTRY, "_names_to_collectors", {})
                _legacy_counter = collectors.get("g6_legacy_register_calls_total")
        if _legacy_counter is not None:
            try:
                _legacy_counter.labels(metric_name=name).inc()
            except Exception:
                pass
        # Deprecation warning (once) unless suppressed
        suppress = os.getenv("G6_SUPPRESS_LEGACY_WARNINGS", "").strip().lower() in {"1","true","yes","on"}
        if not suppress and not _warned_legacy_register:
            _warned_legacy_register = True
            try:
                warnings.warn(
                    "metrics._register legacy shim is deprecated and will be removed in a future release; use spec-driven registration or public helpers.",
                    DeprecationWarning,
                    stacklevel=3,
                )
            except Exception:
                pass
        logger.info(
            "metrics.legacy_register.used",
            extra={"event": "metrics.legacy_register.used", "metric_name": name},
        )
    except Exception:
        pass


def legacy_register(metric_cls, name: str, documentation: str, labelnames: list[str] | None = None, **_: object):  # pragma: no cover - defensive shim
    try:
        _inc_legacy(name)
        if labelnames:
            return metric_cls(name, documentation, labelnames)
        return metric_cls(name, documentation)
    except ValueError:
        # Return existing collector if already registered (mirrors previous resilience semantics)
        try:
            names_map = getattr(REGISTRY, "_names_to_collectors", {})
            return names_map.get(name)
        except Exception as e:  # pragma: no cover
            logger.debug("legacy_register fallback failed for %s: %s", name, e)
            return None