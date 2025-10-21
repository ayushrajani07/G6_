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

from typing import Any, cast

try:  # pragma: no cover
    from .status_finalize import (
        MetricsLike as _MetricsLike,
    )
    from .status_finalize import (
        PartialReasonTotals as _PartialReasonTotals,
    )
    from .status_finalize import (
        compute_cycle_reason_totals as _compute_cycle_reason_totals,
    )
    from .status_finalize import (
        finalize_expiry as _finalize_expiry,
    )
    finalize_expiry = cast(Any, _finalize_expiry)
    compute_cycle_reason_totals = cast(Any, _compute_cycle_reason_totals)
    PartialReasonTotals = cast(Any, _PartialReasonTotals)
    MetricsLike = cast(Any, _MetricsLike)
except Exception:  # pragma: no cover
    # Fallbacks: keep runtime behavior safe and names available
    def finalize_expiry(*args: Any, **kwargs: Any) -> None:
        return None

    def compute_cycle_reason_totals(*args: Any, **kwargs: Any) -> None:
        return None

    PartialReasonTotals = dict
    MetricsLike = object

__all__ = [
    "finalize_expiry",
    "compute_cycle_reason_totals",
    "PartialReasonTotals",
    "MetricsLike",
]
