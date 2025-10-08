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
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from src.collectors.helpers.status_reducer import derive_partial_reason  # type: ignore
except Exception:  # pragma: no cover
    def derive_partial_reason(expiry_rec):  # type: ignore
        return None

try:  # pragma: no cover
    from src.collectors.helpers.struct_events import _compute_reason_totals as _crt  # type: ignore
except Exception:  # pragma: no cover
    def _crt(indices_struct):  # type: ignore
        return {}

try:  # pragma: no cover
    from src.collectors.helpers.struct_events import emit_option_match_stats as _emit_option_match_stats  # type: ignore
except Exception:  # pragma: no cover
    def _emit_option_match_stats(**k):  # type: ignore
        return None

__all__ = ["finalize_expiry", "compute_cycle_reason_totals"]


def finalize_expiry(expiry_rec: Dict[str, Any], enriched_data: Dict[str, Any], strikes: List[int], index_symbol: str,
                    expiry_date: Any, expiry_rule: str, metrics) -> None:
    # Build strike footprint sample
    precomputed_strikes = strikes or []
    if precomputed_strikes:
        try:
            strike_min = float(min(precomputed_strikes))
            strike_max = float(max(precomputed_strikes))
            diffs_tmp = [b - a for a,b in zip(precomputed_strikes, precomputed_strikes[1:]) if b>a]
            step_val = min(diffs_tmp) if diffs_tmp else None
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
    ce_legs = pe_legs = 0
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
    _partial_reason = None
    try:
        if expiry_rec.get('status') == 'PARTIAL':
            _partial_reason = derive_partial_reason(expiry_rec)
            if _partial_reason:
                expiry_rec['partial_reason'] = _partial_reason
                if metrics is not None:
                    try:
                        if not hasattr(metrics, 'partial_expiries_total'):
                            from prometheus_client import Counter as _C  # type: ignore
                            try:
                                metrics.partial_expiries_total = _C('g6_partial_expiries_total','Partial expiries total',['reason'])  # type: ignore[attr-defined]
                            except Exception:
                                pass
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


def compute_cycle_reason_totals(indices_struct: List[Dict[str, Any]], metrics) -> Dict[str, int] | None:
    try:
        partial_reason_totals = _crt(indices_struct)
        if partial_reason_totals and metrics is not None:
            try:
                if not hasattr(metrics, 'partial_cycle_reasons_total'):
                    from prometheus_client import Counter as _C  # type: ignore
                    try:
                        metrics.partial_cycle_reasons_total = _C('g6_partial_cycle_reasons_total','Partial expiry reasons per cycle',['reason'])  # type: ignore[attr-defined]
                    except Exception:
                        pass
                c_counter = getattr(metrics, 'partial_cycle_reasons_total', None)
                if c_counter:
                    for r, cnt in partial_reason_totals.items():
                        if cnt > 0:
                            c_counter.labels(reason=r).inc(cnt)
            except Exception:
                logger.debug('partial_cycle_reasons_total_metric_failed', exc_info=True)
        return partial_reason_totals
    except Exception:
        return None
