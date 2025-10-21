#!/usr/bin/env python3
"""
Tiny adaptive circuit breaker registry and decorators (opt-in).
Safe-by-default: nothing changes unless explicitly used.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

from src.health import runtime as health_runtime
from src.health.models import HealthLevel, HealthState

from .adaptive_circuit_breaker import AdaptiveCircuitBreaker, BreakerConfig, CircuitOpenError, CircuitState

_REG_LOCK = threading.RLock()
_REGISTRY: dict[str, AdaptiveCircuitBreaker] = {}


def get_breaker(name: str) -> AdaptiveCircuitBreaker:
    with _REG_LOCK:
        b = _REGISTRY.get(name)
        if b is not None:
            return b
        # Build from env defaults
        cfg = BreakerConfig(
            name=name,
            failure_threshold=int(os.environ.get("G6_CB_FAILURES", "5")),
            min_reset_timeout=float(os.environ.get("G6_CB_MIN_RESET", "10")),
            max_reset_timeout=float(os.environ.get("G6_CB_MAX_RESET", "300")),
            backoff_factor=float(os.environ.get("G6_CB_BACKOFF", "2.0")),
            jitter=float(os.environ.get("G6_CB_JITTER", "0.2")),
            half_open_successes=int(os.environ.get("G6_CB_HALF_OPEN_SUCC", "1")),
            persistence_dir=os.environ.get("G6_CB_STATE_DIR") or None,
        )
        b = AdaptiveCircuitBreaker(cfg)
        _REGISTRY[name] = b
        return b


P = TypeVar("P")
F = TypeVar("F")


def circuit_protected(name: str | None = None, fallback: Callable[..., Any] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        cb_name = name or f"cb:{func.__module__}.{func.__name__}"
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            br = get_breaker(cb_name)
            try:
                result = br.execute(func, *args, **kwargs)
                # On success, update health based on current breaker state
                try:
                    from src.utils.env_flags import is_truthy_env  # type: ignore
                    if is_truthy_env('G6_HEALTH_COMPONENTS'):
                        st = br.state
                        if st == CircuitState.CLOSED:
                            health_runtime.set_component(cb_name, HealthLevel.HEALTHY, HealthState.HEALTHY)
                        elif st == CircuitState.HALF_OPEN:
                            health_runtime.set_component(cb_name, HealthLevel.WARNING, HealthState.WARNING)
                        # OPEN state on success is unlikely; ignore here
                except Exception:
                    pass
                return result
            except CircuitOpenError:
                try:
                    from src.utils.env_flags import is_truthy_env  # type: ignore
                    if is_truthy_env('G6_HEALTH_COMPONENTS'):
                        health_runtime.set_component(cb_name, HealthLevel.CRITICAL, HealthState.CRITICAL)
                except Exception:
                    pass
                if callable(fallback):
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return deco


__all__ = ["get_breaker", "circuit_protected"]
