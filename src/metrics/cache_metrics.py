"""Cache metrics registration module.

Extracted from `group_registry.py` to centralize the `cache` group
metrics (root symbol cache performance indicators).

Pure refactor: names, labels, group tagging, ordering unchanged.
"""
from __future__ import annotations

from typing import Any

__all__ = ["init_cache_metrics"]


def init_cache_metrics(reg: Any) -> None:  # pragma: no cover - deprecated shim
    """Deprecated no-op (cache metrics now spec-driven; legacy perf_cache alias removed)."""
    return
