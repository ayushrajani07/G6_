"""Backward compatibility shim for cache metrics.

Historically this module owned cache metric registration. Canonical
registration now lives in `cache_metrics.init_cache_metrics`. This shim
retains the previous public symbol (`register_cache_metrics`) so any
third-party or legacy internal import continues to function.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["register_cache_metrics"]

def register_cache_metrics(reg: Any, maybe_register: Callable | None = None) -> None:  # pragma: no cover - thin adapter
    try:
        from .cache_metrics import init_cache_metrics as _init  # type: ignore
    except Exception:
        return
    # The new initializer expects the registry object only (it resolves _maybe_register itself)
    _init(reg)
