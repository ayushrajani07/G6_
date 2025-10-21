"""Finalize/persist helper for pipeline direct finalize path.

Goal: Allow future pipeline path to bypass re-running enrichment/validation in legacy
`process_expiry` when we already have validated enriched quotes produced by
pipeline phases.

This helper performs a trimmed subset of the tail logic from `expiry_processor.process_expiry`:
- Classification & status computation
- Coverage metrics already assumed pre-computed upstream (optional recompute hooks skipped)
- Persistence via `run_persist_flow`
- Optional domain model mapping & snapshot build to preserve side effects
- Metrics adapter synthetic fallback counter (if synthetic flag present)

Contract:
    finalize_from_enriched(
        ctx,
        *,
        index_symbol: str,
        expiry_rule: str,
        expiry_date: Any,
        atm_strike: float,
        enriched_data: Dict[str, Dict[str, Any]],
        strikes: List[float],
        per_index_ts: Any,
        index_price: float,
        index_ohlc: Dict[str, Any],
        allowed_expiry_dates: set,
        concise_mode: bool,
        metrics: Any,
        collector_settings: Any,
        legacy_classifiers: Dict[str, Any],
    ) -> Dict[str, Any]

Returns outcome dict mirroring legacy shape (success, option_count, expiry_rec, optional human_row).
Adds marker: expiry_rec['pipeline_direct_finalize']=True

Assumptions / Omissions for minimal risk:
- Does NOT recompute greeks or IV estimation (expected already handled or intentionally skipped).
- Does NOT perform preventive validation (input is expected post-validation).
- Does NOT run coverage metrics (assumed earlier or not required for parity in this path initially).
- Preserves concise human_row formatting if concise_mode.

If any step fails, falls back to a failed legacy-shaped outcome with marker.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Reuse existing persist flow & context helpers
class _ExpiryContextFallback:  # baseline fallback; may be replaced by import below
    def __init__(self, **k: Any) -> None:
        for a,b in k.items():
            setattr(self, a, b)
try:  # pragma: no cover
    from src.collectors.cycle_context import ExpiryContext as _ExpiryContextReal
    ExpiryContext = _ExpiryContextReal  # simple alias (safe)
except Exception:  # pragma: no cover
    ExpiryContext = _ExpiryContextFallback  # fallback alias

try:  # pragma: no cover
    from src.collectors.modules.persist_flow import run_persist_flow
except Exception:  # pragma: no cover
    def run_persist_flow(ctx: Any, enriched_data: dict[str, dict[str, Any]], expiry_ctx: Any, index_ohlc: Any, allowed_expiry_dates: set, trace: Callable[..., None], concise_mode: bool) -> Any:
        raise RuntimeError("persist_flow_unavailable")

# Fallback classifier/status if imports fail
def _classify_expiry_result(_expiry_rec: dict[str, Any], _enriched: dict[str, Any]) -> str:
    status: str = 'OK'
    try:  # pragma: no cover
        from src.collectors.helpers.synthetic import classify_expiry_result as _real
        _res = _real(_expiry_rec, _enriched)
        if isinstance(_res, str):
            status = _res
    except Exception:
        status = 'OK'
    return status
def _compute_expiry_status(_rec: dict[str, Any]) -> str:
    try:  # pragma: no cover
        from src.collectors.helpers.status_reducer import compute_expiry_status as _real_status
        _res: object = _real_status(_rec)
        if isinstance(_res, str):
            return _res
    except Exception:
        return 'empty'
    return 'empty'

# Optional concise formatter
def format_concise_expiry_row(**_k: Any) -> Any:
    try:  # pragma: no cover
        from src.collectors.modules.formatters import format_concise_expiry_row as _real_fmt
        return _real_fmt(**_k)
    except Exception:
        return None


def finalize_from_enriched(
    ctx: Any,
    *,
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
    atm_strike: float,
    enriched_data: dict[str, dict[str, Any]],
    strikes: list[float],
    per_index_ts: Any,
    index_price: float,
    index_ohlc: dict[str, Any],
    allowed_expiry_dates: set,
    concise_mode: bool,
    metrics: Any,
    collector_settings: Any,
    legacy_classifiers: dict[str, Any] | None = None,
    instruments_count: int | None = None,
    clamp_sentinal: dict[str, Any] | None = None,
) -> dict[str, Any]:  # runtime contract stays a plain dict
    outcome: dict[str, Any] = { 'success': False }
    expiry_rec = {
        'rule': expiry_rule,
        'expiry_date': str(expiry_date) if expiry_date is not None else None,
        'strikes_requested': len(strikes or []),
        'instruments': instruments_count or 0,
        'options': len(enriched_data or {}),
        'failed': False,  # will flip if persist fails
        'pcr': None,
        'pipeline_direct_finalize': True,
    }
    try:
        if not enriched_data:
            expiry_rec['failed'] = True
            outcome['expiry_rec'] = expiry_rec
            return outcome
        # Extract pipeline clamp sentinel if present (injected by PrefilterClampPhase)
        try:
            clamp_meta = clamp_sentinal or enriched_data.get('_pipeline_clamp')
            if isinstance(clamp_meta, dict):
                expiry_rec['prefilter_clamped'] = True
                expiry_rec['prefilter_original_instruments'] = clamp_meta.get('prefilter_original_instruments')
                expiry_rec['prefilter_dropped'] = clamp_meta.get('prefilter_dropped')
                expiry_rec['prefilter_max_allowed'] = clamp_meta.get('prefilter_max_allowed')
                if clamp_meta.get('prefilter_strict_mode'):
                    expiry_rec.setdefault('partial_reason','prefilter_clamp')
        except Exception:
            logger.debug('pipeline_finalize_clamp_meta_failed', exc_info=True)
        # Remove sentinel to avoid polluting persisted data
        if '_pipeline_clamp' in enriched_data:
            try: enriched_data.pop('_pipeline_clamp', None)
            except Exception: pass
        collection_time = per_index_ts
        expiry_ctx = ExpiryContext(index_symbol=index_symbol, expiry_rule=expiry_rule, expiry_date=expiry_date, collection_time=collection_time, index_price=index_price, risk_free_rate=getattr(legacy_classifiers,'risk_free_rate',0.05), allow_per_option_metrics=getattr(legacy_classifiers,'allow_per_option_metrics',True), compute_greeks=getattr(legacy_classifiers,'compute_greeks',False))
        # Persist
        persist_result = run_persist_flow(
            ctx,
            enriched_data,
            expiry_ctx,
            index_ohlc,
            allowed_expiry_dates,
            getattr(legacy_classifiers,'trace', lambda *a,**k: None),
            concise_mode,
        )
        if persist_result.failed:
            expiry_rec['failed'] = True
            outcome['expiry_rec'] = expiry_rec
            return outcome
        # Classification & status
        try:
            expiry_rec['options'] = len(enriched_data)
        except Exception:
            pass
        # Coverage metrics propagated from pipeline coverage phase (if present via preventive_report path is not passed here; rely on enriched_data sentinel? For now skipped.)
        try:
            _classify_expiry_result(expiry_rec, enriched_data)
        except Exception:
            logger.debug('pipeline_finalize_classify_failed', exc_info=True)
        try:
            expiry_rec['status'] = _compute_expiry_status(expiry_rec)
        except Exception:
            logger.debug('pipeline_finalize_status_failed', exc_info=True)
        # Optional domain models mapping (parity w/ legacy)
        _domain_models_enabled = False
        try:
            if collector_settings is not None:
                _domain_models_enabled = bool(getattr(collector_settings, 'domain_models_enabled', False))
            else:
                _domain_models_enabled = os.environ.get('G6_DOMAIN_MODELS','').lower() in ('1','true','yes','on')
        except Exception:
            _domain_models_enabled = False
        if _domain_models_enabled and enriched_data:
            try:
                from src.domain.models import OptionQuote
                for k,q in list(enriched_data.items()):
                    try:
                        OptionQuote.from_raw(k,q)
                    except Exception:
                        continue
            except Exception:
                logger.debug('pipeline_finalize_domain_models_failed', exc_info=True)
        # Snapshot build if requested
        if getattr(ctx, 'build_snapshots', False):
            try:
                from src.collectors.modules.snapshots import build_expiry_snapshot
                snap_obj = build_expiry_snapshot(index_symbol, expiry_rule, expiry_date, atm_strike, enriched_data, per_index_ts)
                if snap_obj is not None:
                    getattr(ctx, 'snapshots_accum', []).append(snap_obj)
            except Exception:
                logger.debug('pipeline_finalize_snapshot_failed', exc_info=True)
        # Concise row
        if concise_mode:
            try:
                outcome['human_row'] = format_concise_expiry_row(
                    per_index_ts=per_index_ts,
                    index_price=index_price,
                    atm_strike=atm_strike,
                    expiry_date=expiry_date,
                    expiry_rule=expiry_rule,
                    enriched_data=enriched_data,
                    strikes=strikes,
                )
            except Exception:
                logger.debug('pipeline_finalize_concise_row_failed', exc_info=True)
        expiry_rec['failed'] = False
        outcome['success'] = True
        outcome['option_count'] = len(enriched_data)
        outcome['expiry_rec'] = expiry_rec
        return outcome
    except Exception as e:
        logger.error('pipeline_finalize_unexpected_error index=%s rule=%s err=%s', index_symbol, expiry_rule, e)
        try:
            expiry_rec['failed'] = True
            outcome['expiry_rec'] = expiry_rec
        except Exception:
            pass
        return outcome

__all__ = ['finalize_from_enriched']
