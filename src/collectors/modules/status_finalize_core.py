"""Status Finalization Facade (Phase 9 consolidation)

Provides a stable import surface for expiry status finalization & cycle partial
reason aggregation so that future internal reshuffles do not require touching
pipeline or legacy orchestrator code.

Facade over `status_finalize` for now.

Public API:
    finalize_expiry(...)
    compute_cycle_reason_totals(...)
"""
from __future__ import annotations
from typing import Any, Dict, List

try:  # re-export existing implementations
    from .status_finalize import finalize_expiry, compute_cycle_reason_totals  # type: ignore
except Exception:  # pragma: no cover
    def finalize_expiry(*a, **k):  # type: ignore
        return None
    def compute_cycle_reason_totals(*a, **k):  # type: ignore
        return None

__all__ = ["finalize_expiry", "compute_cycle_reason_totals"]
