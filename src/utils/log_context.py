"""Lightweight structured logging context helper.

Provides process-wide contextual fields (via contextvars) that are injected
into log records by setup_logging. This lets existing logging calls gain
consistent dimensions without changing call sites.

Context fields (stable keys):
- run_id: unique short id per process run
- component: module/area name (e.g., 'unified_main', 'collector')
- cycle: current collection cycle number
- index: current index symbol being processed
- provider: active provider name when relevant

Usage:
  from src.utils import log_context as lc
  lc.set_context(run_id='abc123', component='unified_main')
  with lc.push_context(cycle=5, index='NIFTY'):
      logging.info('Collecting...')

The JSON console logger (G6_JSON_LOGS=1) will include these fields if present.
"""
from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_CTX: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("g6_log_ctx", default={})


def get_context() -> dict[str, Any]:
    """Return a shallow copy of the current context dict."""
    ctx = _CTX.get()
    # Return a copy to prevent accidental external mutation
    return dict(ctx) if ctx else {}


def set_context(**fields: Any) -> None:
    """Replace or add context fields (overwrites existing keys)."""
    cur = dict(_CTX.get())
    cur.update({k: v for k, v in fields.items() if v is not None})
    _CTX.set(cur)


def clear_context(*keys: str) -> None:
    """Clear specific keys or all if no keys provided."""
    if not keys:
        _CTX.set({})
        return
    cur = dict(_CTX.get())
    for k in keys:
        cur.pop(k, None)
    _CTX.set(cur)


@contextmanager
def push_context(**fields: Any) -> Iterator[None]:
    """Temporarily add/override context fields within a block."""
    prev = _CTX.get()
    merged = dict(prev)
    merged.update({k: v for k, v in fields.items() if v is not None})
    token = _CTX.set(merged)
    try:
        yield
    finally:
        # Restore previous context
        _CTX.reset(token)


__all__ = [
    "get_context",
    "set_context",
    "clear_context",
    "push_context",
]
