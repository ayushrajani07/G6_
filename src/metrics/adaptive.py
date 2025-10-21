"""Adaptive metrics extraction module.

Separates adaptive controller and band rejection metrics from placeholders/group_registry
without changing metric names, labels, or grouping semantics.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from prometheus_client import Counter, Gauge

__all__ = [
    "init_adaptive_placeholders",
    "register_adaptive_group_metrics",
]

logger = logging.getLogger(__name__)

def init_adaptive_placeholders(reg: Any, group_allowed: Callable[[str], bool]) -> None:
    """Register adaptive placeholder metrics (currently band rejections only).

    Leaves SLA health, provider failover, expiry remediation in existing placeholders module.
    Idempotent: will not recreate if attribute already present.
    """
    try:
        if not hasattr(reg, 'option_detail_band_rejections'):
            reg.option_detail_band_rejections = Counter(
                'g6_option_detail_band_rejections',
                'Option detail band window rejections',
                ['index']
            )
            # Not grouped historically (left untagged intentionally)
    except Exception:
        logger.debug("init_adaptive_placeholders failed", exc_info=True)


def register_adaptive_group_metrics(reg: Any) -> None:
    """Register adaptive controller grouped metrics via existing _maybe_register hook.

    Mirrors prior group_registry entries.
    """
    maybe = getattr(reg, '_maybe_register', None)
    if not callable(maybe):  # pragma: no cover - defensive
        return
    try:
      # adaptive_controller_actions counter now registered via declarative spec.
      # Avoid re-registering here to prevent duplicate attribute names pointing to same collector.
        maybe('adaptive_controller', 'option_detail_mode', Gauge,
              'g6_option_detail_mode', 'Current option detail mode (0=full,1=medium,2=low)', ['index'])
    except Exception:
        logger.debug("register_adaptive_group_metrics failure", exc_info=True)
