"""Centralized tracing helpers for Kite provider (Phase 9).

Goals:
  * Single place to decide if a trace should emit (env + quiet gating + runtime toggle).
  * Uniform prefix 'TRACE <event>' to match existing downstream log scrapers.
  * Optional structured context (dict) pretty-trimmed & length limited.
  * Lightweight rate limiting to avoid floods in tight loops.

Environment flags (mirrors legacy behavior):
  G6_TRACE_COLLECTOR=1      -> enable tracing globally
  G6_QUIET_MODE=1           -> suppress non-essential logs (still allow trace if G6_QUIET_ALLOW_TRACE=1)
  G6_QUIET_ALLOW_TRACE=1    -> override quiet suppression for trace

Runtime override:
  call set_enabled(True/False) to toggle irrespective of env (unless force_disable=True)

Public API:
  trace(event: str, **ctx)
  trace_kv(event: str, data: dict)
  is_enabled() -> bool
  rate_limited_trace(event, interval=2.0, **ctx)

The implementation intentionally has ZERO imports from heavy modules to keep
hot-path overhead minimal; provider/state objects are not required.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_BOOL_TRUE = {"1","true","yes","on"}

def _b(val: str | None) -> bool:
    return val is not None and val.strip().lower() in _BOOL_TRUE

_env_trace = _b(os.environ.get("G6_TRACE_COLLECTOR"))
_env_quiet = os.environ.get("G6_QUIET_MODE") == "1"
_env_quiet_allow = _b(os.environ.get("G6_QUIET_ALLOW_TRACE"))

_runtime_enabled: bool | None = None  # explicit override
_force_disable: bool = False

_last_emit: dict[str, float] = {}

MAX_CTX_LEN = 4000  # safeguard

def is_enabled() -> bool:
    if _force_disable:
        return False
    if _runtime_enabled is not None:
        return _runtime_enabled
    if _env_quiet and not _env_quiet_allow:
        return False
    return _env_trace

def set_enabled(flag: bool, *, force: bool=False) -> None:
    global _runtime_enabled, _force_disable  # noqa: PLW0603
    if force:
        _force_disable = not flag
        _runtime_enabled = flag
    else:
        _runtime_enabled = flag

def trace(event: str, **ctx: Any) -> None:
    if not is_enabled():
        return
    try:
        if ctx:
            # Keep deterministic key ordering for testability
            data = json.dumps({k: ctx[k] for k in sorted(ctx)}, default=str)[:MAX_CTX_LEN]
            logger.warning("TRACE %s | %s", event, data)
        else:
            logger.warning("TRACE %s", event)
    except Exception:  # pragma: no cover
        logger.debug("trace_emit_failed", exc_info=True)

def trace_kv(event: str, data: dict[str, Any]) -> None:
    try:
        trace(event, **data)
    except Exception:
        pass

def rate_limited_trace(event: str, interval: float = 2.0, **ctx: Any) -> None:
    now = time.time()
    last = _last_emit.get(event, 0.0)
    if now - last >= interval:
        _last_emit[event] = now
        trace(event, **ctx)

__all__ = [
    "trace",
    "trace_kv",
    "rate_limited_trace",
    "is_enabled",
    "set_enabled",
]
