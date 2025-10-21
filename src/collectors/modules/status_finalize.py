"""Status & summary finalization extraction.

Provides helpers to:
- Derive partial_reason (if PARTIAL) and attach + metrics increment.
- Emit option match stats struct event.
- Aggregate cycle partial_reason_totals for return payload & metrics.

Public API:
    finalize_expiry(expiry_rec, enriched_data, strikes, index_symbol, expiry_date,
                    expiry_rule, metrics) -> None (mutates expiry_rec in-place)
    compute_cycle_reason_totals(indices_struct, metrics) -> dict | None

Behavior preserved from legacy unified_collectors implementation.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Protocol, TypedDict, cast

logger = logging.getLogger(__name__)

# Helper callable aliases (match concrete imported signatures to avoid spurious mismatches)
DerivePartialReason = Callable[[dict[str, Any]], str | None]
ComputeReasonTotals = Callable[[list[dict[str, Any]]], dict[str, int]]
class EmitMatchStats(Protocol):
    def __call__(self, **k: Any) -> None: ...  # pragma: no cover

try:  # pragma: no cover
    from src.collectors.helpers.status_reducer import derive_partial_reason as _derive_partial_reason_any
except Exception:  # pragma: no cover
    def _derive_partial_reason_any(expiry_rec: dict[str, Any]) -> str | None:
        return None
derive_partial_reason = cast(DerivePartialReason, _derive_partial_reason_any)

try:  # pragma: no cover
    from src.collectors.helpers.struct_events import (
        _compute_reason_totals as _crt,  # imported signature: (indices: List[Dict[str, Any]]) -> Dict[str,int]
    )
except Exception:  # pragma: no cover
    def _crt(indices: list[dict[str, Any]]) -> dict[str, int]:  # fallback keeps matching signature
        return {}

try:  # pragma: no cover
    from src.collectors.helpers.struct_events import (
        emit_option_match_stats as _emit_option_match_stats_impl,  # noqa: F401
    )
    _emit_option_match_stats_impl = cast(Any, _emit_option_match_stats_impl)
except Exception:  # pragma: no cover
    def _emit_option_match_stats_impl(**k: Any) -> None:  # fallback dynamic
        return None

_emit_option_match_stats_impl_t = cast(EmitMatchStats, _emit_option_match_stats_impl)

def _emit_option_match_stats(**k: Any) -> None:
    try:
        _emit_option_match_stats_impl_t(**k)
    except Exception:  # pragma: no cover
        logger.debug('emit_option_match_stats_wrapper_failed', exc_info=True)

class PartialReasonTotals(TypedDict, total=False):
    # dynamic keys are partial reasons, values are counts
    # We can't pre-enumerate reasons yet; keep as open mapping style
    # Example keys: 'low_option_count', 'missing_quotes', etc.
    # Using TypedDict (even open) gives us a nominal type anchor
    ...  # no fixed fields

class MetricsCounterLike(Protocol):  # minimal Protocol for counters
    def labels(self, **label_values: Any) -> MetricsCounterLike: ...  # pragma: no cover
    def inc(self, value: int = 1) -> None: ...  # pragma: no cover
    def set(self, value: float) -> None: ...  # pragma: no cover

class MetricsLike(Protocol):  # subset of attributes we touch dynamically
    # Attributes are optional; we test with hasattr before usage
    partial_expiries_total: Any  # prometheus Counter
    partial_cycle_reasons_total: Any

__all__ = [
    "finalize_expiry",
    "compute_cycle_reason_totals",
    "PartialReasonTotals",
    "MetricsLike",
]


def finalize_expiry(
    expiry_rec: dict[str, Any],
    enriched_data: Mapping[str, Mapping[str, Any] | MutableMapping[str, Any]],
    strikes: list[int],
    index_symbol: str,
    expiry_date: Any,
    expiry_rule: str,
    metrics: MetricsLike | Any | None,
) -> None:
    """Attach derived partial reason, emit option match stats, and update metrics.

    Parameters
    ----------
    expiry_rec : dict (mutated)
        Expiry record containing at least 'status' and optional coverage keys.
    enriched_data : mapping
        Per-option enriched data keyed by symbol.
    strikes : list[int]
        Canonical ordered strike list for the expiry.
    index_symbol : str
        Index identifier.
    expiry_date : Any
        Expiry date object or string (kept loose for now).
    expiry_rule : str
        Rule name for the expiry bucket.
    metrics : MetricsLike | Any | None
        Metrics collector (prometheus style) or None; accessed dynamically.
    """
    # Build strike footprint sample
    precomputed_strikes: list[int] = strikes or []
    strike_min: float | None
    strike_max: float | None
    step_val: float | None
    if precomputed_strikes:
        try:
            strike_min = float(min(precomputed_strikes))
            strike_max = float(max(precomputed_strikes))
            diffs_tmp = [b - a for a, b in zip(precomputed_strikes, precomputed_strikes[1:], strict=False) if b > a]
            step_val = float(min(diffs_tmp)) if diffs_tmp else None
        except Exception:
            strike_min = strike_max = step_val = None
    else:
        strike_min = strike_max = step_val = None
    sample_list: list[str] = []
    if precomputed_strikes:
        if len(precomputed_strikes) <= 6:
            sample_list = [f"{s:.0f}" for s in precomputed_strikes]
        else:
            head = [f"{s:.0f}" for s in precomputed_strikes[:2]]
            mid = [f"{precomputed_strikes[len(precomputed_strikes)//2]:.0f}"]
            tail = [f"{s:.0f}" for s in precomputed_strikes[-2:]]
            sample_list = head + mid + tail
    # Count legs by type
    ce_legs: int = 0
    pe_legs: int = 0
    try:
        for _q in enriched_data.values():
            _t = (_q.get('instrument_type') or _q.get('type') or '').upper()
            if _t == 'CE':
                ce_legs += 1
            elif _t == 'PE':
                pe_legs += 1
    except Exception:
        logger.debug('leg_count_failed', exc_info=True)
    ce_per_strike = (ce_legs / len(precomputed_strikes)) if precomputed_strikes else None
    pe_per_strike = (pe_legs / len(precomputed_strikes)) if precomputed_strikes else None

    # Derive partial reason if status PARTIAL
    _partial_reason: str | None = None
    try:
        if expiry_rec.get('status') == 'PARTIAL':
            _partial_reason = derive_partial_reason(expiry_rec)
            if _partial_reason:
                expiry_rec['partial_reason'] = _partial_reason
                if metrics is not None:
                    try:
                        if not hasattr(metrics, 'partial_expiries_total'):
                            try:
                                from prometheus_client import Counter as _C
                                metrics.partial_expiries_total = _C('g6_partial_expiries_total','Partial expiries total',['reason'])
                            except Exception:
                                metrics.partial_expiries_total = None
                        pe_counter = getattr(metrics, 'partial_expiries_total', None)
                        if pe_counter:
                            pe_counter.labels(reason=_partial_reason).inc()
                    except Exception:
                        logger.debug('partial_expiries_total_metric_failed', exc_info=True)
    except Exception:
        logger.debug('derive_partial_reason_failed', exc_info=True)

    try:
        _emit_option_match_stats(
            index=index_symbol,
            expiry=str(expiry_date),
            rule=expiry_rule,
            strike_count=len(precomputed_strikes),
            legs=len(enriched_data),
            ce_legs=ce_legs,
            pe_legs=pe_legs,
            strike_min=strike_min,
            strike_max=strike_max,
            step=step_val,
            sample=sample_list,
            ce_per_strike=ce_per_strike,
            pe_per_strike=pe_per_strike,
            strike_coverage=expiry_rec.get('strike_coverage'),
            field_coverage=expiry_rec.get('field_coverage'),
            partial_reason=_partial_reason,
        )
    except Exception:
        logger.debug('option_match_stats_emit_failed', exc_info=True)


def compute_cycle_reason_totals(
    indices_struct: list[dict[str, Any]],
    metrics: MetricsLike | Any | None,
) -> PartialReasonTotals | None:
    """Aggregate partial expiry reasons across indices in a cycle.

    Returns a mapping of partial reason -> count, or None on failure.
    Populates metrics counters if available.
    """
    try:
        # Accept list of dicts; _crt may expect a Sequence[Mapping]; list is fine at runtime.
        partial_reason_totals_raw = _crt(indices_struct)
        filtered: dict[str, int] = {
            str(k): int(v) for k, v in partial_reason_totals_raw.items() if isinstance(k, str) and isinstance(v, int)
        }
        partial_reason_totals = cast(PartialReasonTotals, filtered)
        if partial_reason_totals and metrics is not None:
            try:
                if not hasattr(metrics, 'partial_cycle_reasons_total'):
                    try:
                        from prometheus_client import Counter as _C
                        metrics.partial_cycle_reasons_total = _C('g6_partial_cycle_reasons_total','Partial expiry reasons per cycle',['reason'])
                    except Exception:
                        metrics.partial_cycle_reasons_total = None
                c_counter = getattr(metrics, 'partial_cycle_reasons_total', None)
                if c_counter:
                    for r, cnt in partial_reason_totals.items():
                        if isinstance(cnt, int) and cnt > 0:
                            c_counter.labels(reason=r).inc(cnt)
            except Exception:
                logger.debug('partial_cycle_reasons_total_metric_failed', exc_info=True)
        return partial_reason_totals
    except Exception:
        return None
