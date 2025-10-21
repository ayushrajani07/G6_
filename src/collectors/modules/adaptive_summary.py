"""Adaptive summary emission extraction.

Provides a best-effort structured adaptive summary event consolidating key
adaptive strike tuning state per index after processing all expiries.

Public API:
    emit_adaptive_summary(ctx, index_symbol)

Payload (fields optional when unavailable):
    index: str
    scale_factor: float | None (if passthrough scaling active)
    strikes_itm: int | None (current configured ITM depth)
    strikes_otm: int | None (current configured OTM depth)
    baseline_itm/otm: int | None (from contraction state)
    healthy_streak: int | None
    had_low_cov: bool | None (flag recorded this cycle)
    had_expansion: bool | None (flag recorded this cycle)

Honors G6_DISABLE_STRUCT_EVENTS via struct_events_bridge; never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:  # reuse existing bridge for uniform formatting + gating
    from src.collectors.modules.struct_events_bridge import emit_struct
except Exception:  # pragma: no cover
    def emit_struct(event: str, fields: dict[str, Any]) -> None:
        try:
            import json
            import logging as _l
            _l.getLogger(__name__).info("STRUCT %s | %s", event, json.dumps(fields, default=str, ensure_ascii=False))
        except Exception:
            pass

class AdaptiveCtxLike(Protocol):  # re-uses shape from adaptive_adjust (duplicated locally to avoid import cycle)
    index_params: dict[str, dict[str, Any]]
    _adaptive_contraction_state: dict[str, dict[str, Any]]
    flags: dict[str, Any]

__all__ = ["emit_adaptive_summary", "AdaptiveCtxLike"]

def emit_adaptive_summary(ctx: AdaptiveCtxLike | Any, index_symbol: str) -> None:  # pragma: no cover (side-effect wrapper)
    try:
        flags = getattr(ctx, 'flags', {}) or {}
        scale_factor = flags.get('adaptive_scale_factor')
        idx_cfg = (getattr(ctx, 'index_params', {}) or {}).get(index_symbol, {})
        strikes_itm = idx_cfg.get('strikes_itm')
        strikes_otm = idx_cfg.get('strikes_otm')
        contraction_state = getattr(ctx, '_adaptive_contraction_state', {}) or {}
        cst = contraction_state.get(index_symbol, {})
        payload = {
            'index': index_symbol,
            'scale_factor': scale_factor,
            'strikes_itm': strikes_itm,
            'strikes_otm': strikes_otm,
            'baseline_itm': cst.get('baseline_itm'),
            'baseline_otm': cst.get('baseline_otm'),
            'healthy_streak': cst.get('healthy_streak'),
            'had_low_cov': cst.get('had_low_cov'),
            'had_expansion': cst.get('had_expansion_this_cycle'),
        }
        # Trim None-only entries (keep index always)
        payload = {k:v for k,v in payload.items() if v is not None or k == 'index'}
        emit_struct('adaptive_summary', payload)
        # Best-effort aggregation hook (optional)
        try:
            from importlib import import_module
            _mod = import_module('src.collectors.helpers.cycle_tables')
            record_adaptive = getattr(_mod, 'record_adaptive', None)
            if callable(record_adaptive):
                record_adaptive(payload)
        except Exception:
            pass
    except Exception:
        logger.debug('adaptive_summary_emit_failed', exc_info=True)
