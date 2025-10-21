"""Error-tolerant emission wrapper.

Provides a decorator `safe_emit` that wraps emission functions (typically thin
wrappers around generated metric accessors) so that:
  * Exceptions are caught and do not propagate.
  * A per-emitter counter `g6_emission_failures_total{emitter=...}` is incremented.
  * A once-per-emitter counter `g6_emission_failure_once_total{emitter=...}` is
    incremented only the first time a given emitter fails (useful for quick
    inventory of failing sites).
  * A log warning is emitted only the first time for a given emitter signature
    (subsequent failures are silent apart from counters) to avoid log spam.

Emitter identity defaults to the qualified function name (module:function). A
custom `emitter` keyword arg can override for grouping (e.g., when many small
lambdas share semantics).
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from . import generated as m

_log = logging.getLogger("g6.metrics.safe_emit")
_seen_first_failure: set[str] = set()

def _emitter_name(func: Callable, override: str | None) -> str:
    if override:
        return override
    mod = getattr(func, "__module__", "unknown")
    name = getattr(func, "__qualname__", getattr(func, "__name__", "<lambda>"))
    return f"{mod}:{name}"

def safe_emit(_func: Callable | None = None, *, emitter: str | None = None) -> Callable:
    """Decorator making a metric emission site resilient.

    Usage:
        @safe_emit
        def emit_foo(x):
            m.m_some_counter_labels("foo").inc()

        or with grouping override:

        @safe_emit(emitter="panel_diff_builder")
        def emit_bar(y): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ident = _emitter_name(func, emitter)
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 broad to ensure containment
                # Increment per-failure counter
                try:
                    m.m_emission_failures_total_labels(ident).inc()  # type: ignore[attr-defined]
                except Exception:  # safeguard against metric registration issues
                    pass
                # First-failure path
                first = False
                if ident not in _seen_first_failure:
                    _seen_first_failure.add(ident)
                    first = True
                    try:
                        m.m_emission_failure_once_total_labels(ident).inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                if first:
                    _log.warning("[safe_emit] emitter=%s first failure: %s", ident, exc, exc_info=True)
                return None
        return wrapper
    if _func is not None:
        return decorator(_func)
    return decorator

__all__ = ["safe_emit"]
