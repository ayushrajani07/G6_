"""Helpers for panel capability detection (Wave 4).

Centralizes detection of whether an OutputRouter-like object supports
transactional panel updates to reduce scattered hasattr chains.
"""
from __future__ import annotations

from typing import Any, TypedDict

REQUIRED_PANEL_METHODS = ("begin_panels_txn", "panel_update", "panel_append")

class PanelSupportDiagnostics(TypedDict):
    supported: bool
    missing: list[str]
    present: list[str]
    obj_type: str

def supports_panels(router: Any) -> bool:
    """Return True if the object exposes required panel transaction methods.

    Uses a simple hasattr check cluster; kept dynamic to avoid importing heavy
    protocol types at runtime.
    """
    if router is None:
        return False
    for name in REQUIRED_PANEL_METHODS:
        if not hasattr(router, name):  # pragma: no cover - trivial branch
            return False
    return True

def panels_support_diagnostics(router: Any) -> PanelSupportDiagnostics:
    """Return a diagnostic struct indicating capability status.

    Example:
        >>> panels_support_diagnostics(router)
        {'supported': False, 'missing': ['panel_append'], 'present': ['begin_panels_txn','panel_update'], 'obj_type': 'MyRouter'}
    """
    if router is None:
        return {
            'supported': False,
            'missing': list(REQUIRED_PANEL_METHODS),
            'present': [],
            'obj_type': 'None'
        }
    present: list[str] = []
    missing: list[str] = []
    for name in REQUIRED_PANEL_METHODS:
        if hasattr(router, name):
            present.append(name)
        else:
            missing.append(name)
    return {
        'supported': not missing,
        'missing': missing,
        'present': present,
        'obj_type': type(router).__name__,
    }

__all__ = ["supports_panels", "panels_support_diagnostics", "REQUIRED_PANEL_METHODS", "PanelSupportDiagnostics"]
