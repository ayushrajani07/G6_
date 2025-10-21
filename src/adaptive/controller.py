"""Adaptive controller scaffolding (Potential Next Steps implementation).

This module provides lightweight helper functions that interact with newly
introduced metrics:
 - g6_adaptive_controller_actions_total
 - g6_option_detail_mode

The real controller (multi-signal) can replace these stubs later. For now
we provide a simple API so orchestrator code can begin integrating without
creating circular dependencies.
"""
from __future__ import annotations

import os
from importlib import import_module
from typing import Any, Literal

DetailMode = Literal[0,1,2]  # 0=full,1=band,2=agg

_METRICS_CACHE: Any | None = None
_METRICS_FAILED = False

def _get_metrics_safely() -> Any | None:
    global _METRICS_CACHE, _METRICS_FAILED
    if _METRICS_FAILED:
        return None
    if _METRICS_CACHE is not None:
        return _METRICS_CACHE
    try:
        # Prefer facade import; legacy module path retained in tests only
        mod = import_module('src.metrics')
        fn = getattr(mod, 'get_metrics', None)
        if callable(fn):
            _METRICS_CACHE = fn()
        else:
            _METRICS_FAILED = True
    except Exception:
        _METRICS_FAILED = True
    return _METRICS_CACHE

# Environment gate (future: more granular logic)
_ENABLE = os.getenv('G6_ADAPTIVE_CONTROLLER','').lower() in ('1','true','yes','on')


def record_controller_action(reason: str, action: str) -> None:
    """Increment adaptive controller actions counter.

    Parameters
    ----------
    reason : str
        Trigger for decision (e.g., 'sla_breach_streak','cardinality_guard').
    action : str
        Decision taken (e.g., 'demote','promote','hold').
    """
    if not _ENABLE:
        return
    try:
        m = _get_metrics_safely()
        if m is None:
            return
        counter = getattr(m, 'adaptive_controller_actions', None)
        if counter is not None:
            try:
                counter.labels(reason=reason, action=action).inc()
            except Exception:
                pass
    except Exception:
        pass


def set_detail_mode(index: str, mode: DetailMode) -> None:
    """Set the current detail mode gauge for an index.

    Safe to call even if metrics gated or disabled.
    """
    if not _ENABLE:
        return
    try:
        m = _get_metrics_safely()
        if m is None:
            return
        gauge = getattr(m, 'option_detail_mode', None)
        if gauge is not None:
            try:
                gauge.labels(index=index).set(int(mode))
            except Exception:
                pass
    except Exception:
        pass

__all__ = ["record_controller_action","set_detail_mode","DetailMode"]
