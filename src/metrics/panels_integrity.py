"""Panels integrity metrics registration module.

Extracted from `group_registry.py` consolidating the `panels_integrity`
group metrics that track data freshness/consistency across panels.

Pure refactor: metric names and semantics unchanged.
"""
from __future__ import annotations

from typing import Any

__all__ = ["init_panels_integrity_metrics"]


def init_panels_integrity_metrics(reg: Any) -> None:  # pragma: no cover - deprecated shim
    """Deprecated no-op (panels_integrity metrics now spec-driven)."""
    return
