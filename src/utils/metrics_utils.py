"""Metrics utilities centralizing Prometheus server setup for G6.

Abstraction layer so scripts do not import deep metrics implementation details.
"""
from __future__ import annotations
from typing import Any, Tuple, Callable

try:
    from src.metrics import setup_metrics_server as _setup_metrics_server  # facade import
except Exception:
    # Fallback if metrics module not present
    _setup_metrics_server = None  # type: ignore


def init_metrics(port: int = 9108) -> Tuple[Any, Callable[[], None]]:
    """Initialize metrics server returning (registry, stop_fn).

    If metrics backend unavailable, returns (None, noop_stop).
    """
    def _noop():
        pass

    if _setup_metrics_server is None:
        return None, _noop
    try:
        return _setup_metrics_server(port=port)
    except Exception:
        return None, _noop

__all__ = ["init_metrics"]
