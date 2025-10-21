"""Panel diff metrics registration module.

Extracted from `group_registry.py` to centralize construction of the
`panel_diff` metric family (writes, truncations, bytes totals, last size).

Pure refactor: names, labels, group tagging, ordering unchanged.
"""
from __future__ import annotations

from typing import Any

__all__ = ["init_panel_diff_metrics"]


def init_panel_diff_metrics(reg: Any) -> None:  # pragma: no cover - deprecated shim
    """Deprecated no-op (panel_diff metrics now spec-driven)."""
    return
