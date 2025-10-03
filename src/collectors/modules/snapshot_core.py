"""Snapshot core extraction (Phase 7).

Provides a reduced, stable snapshot summary structure used by both legacy
unified collectors path and the staged pipeline. Centralizes:
- Counting indices / options
- Aggregating alerts total (best-effort)
- Computing partial_reason_totals (via status_finalize)

Public API:
    build_snapshot(indices_struct, index_param_count, metrics, *, build_reason_totals=True) -> SnapshotSummary

Design Notes:
- Does not mutate index expiry records except where status_finalize already attached
  partial_reason earlier in the flow. This function is read-only.
- Leaves anomaly / benchmark attachment to benchmark_bridge.
- Provides dict export for backward compatibility (`to_dict`).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import time
import logging

logger = logging.getLogger(__name__)

try:  # optional import (legacy path may run before module available during rollout)
    from src.collectors.modules.status_finalize import compute_cycle_reason_totals  # type: ignore
except Exception:  # pragma: no cover
    def compute_cycle_reason_totals(indices_struct, metrics):  # type: ignore
        return None

@dataclass
class SnapshotSummary:
    status: str
    indices_processed: int
    indices: List[Dict[str, Any]]
    indices_count: int
    options_total: int
    expiries_total: int
    indices_ok: int
    indices_empty: int
    alerts_total: Optional[int]
    partial_reason_totals: Optional[Dict[str,int]]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Preserve legacy return keys naming subset
        return {
            'status': d['status'],
            'indices_processed': d['indices_processed'],
            'indices': d['indices'],
            'partial_reason_totals': d['partial_reason_totals'],
            # Additional fields (indices_count, options_total, alerts_total, timestamp)
            'indices_count': d['indices_count'],
            'options_total': d['options_total'],
            'expiries_total': d['expiries_total'],
            'alerts_total': d['alerts_total'],
            'indices_ok': d['indices_ok'],
            'indices_empty': d['indices_empty'],
            'snapshot_ts': d['timestamp'],
        }


def _compute_basic_counts(indices_struct: List[Dict[str, Any]]) -> tuple[int,int,int,int,int]:
    idx_count = len(indices_struct)
    opt_total = 0
    expiries_total = 0
    indices_ok = 0
    indices_empty = 0
    for ix in indices_struct:
        try:
            opt_total += int(ix.get('option_count') or 0)
            exps = ix.get('expiries') or []
            expiries_total += len(exps)
            status = ix.get('status')
            if status == 'OK':
                indices_ok += 1
            elif status == 'EMPTY':
                indices_empty += 1
        except Exception:  # pragma: no cover
            pass
    return idx_count, opt_total, expiries_total, indices_ok, indices_empty


def _derive_alerts_total(indices_struct: List[Dict[str, Any]]) -> Optional[int]:
    # Alerts not directly embedded in indices_struct; placeholder for future aggregation.
    return None


def build_snapshot(indices_struct: List[Dict[str, Any]], index_param_count: int, metrics, *, build_reason_totals: bool = True) -> SnapshotSummary:
    idx_count, opt_total, expiries_total, indices_ok, indices_empty = _compute_basic_counts(indices_struct)
    alerts_total = _derive_alerts_total(indices_struct)
    reason_totals = None
    if build_reason_totals:
        try:
            reason_totals = compute_cycle_reason_totals(indices_struct, metrics)
        except Exception:
            logger.debug('compute_cycle_reason_totals_failed', exc_info=True)
            reason_totals = None
    snap = SnapshotSummary(
        status='ok',
        indices_processed=index_param_count,
        indices=indices_struct,
        indices_count=idx_count,
    options_total=opt_total,
    expiries_total=expiries_total,
    indices_ok=indices_ok,
    indices_empty=indices_empty,
        alerts_total=alerts_total,
        partial_reason_totals=reason_totals,
        timestamp=time.time(),
    )
    return snap

__all__ = ['SnapshotSummary','build_snapshot']
