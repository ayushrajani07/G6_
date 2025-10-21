"""Memory & Adaptive Scaling Utilities.

Encapsulates logic that adjusts strike depth counts and related feature flags
based on memory pressure evaluation (`mem_flags`) and adaptive scaling
passthrough environment variables.

Behavior preserved exactly from inline implementation in `index_processor`:
- Applies `depth_scale` multiplicatively to requested ITM/OTM counts with a
  minimum of 2 on each side.
- Disables greeks/IV when `skip_greeks` flag set.
- Disables per-option metrics when `drop_per_option_metrics` flag set.
- Supports adaptive passthrough via env `G6_ADAPTIVE_SCALE_PASSTHROUGH`; when
  enabled, reads `ctx.flags['adaptive_scale_factor']` (defaults to 1.0) and
  passes through the scale to strike universe builder.

Public API:
    apply_memory_and_adaptive_scaling(effective_itm, effective_otm, mem_flags, ctx, *,
                                      compute_greeks, estimate_iv) -> tuple
        Returns (itm, otm, allow_per_option_metrics, local_compute_greeks,
                 local_estimate_iv, passthrough_scale_factor or None)
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["apply_memory_and_adaptive_scaling"]


def apply_memory_and_adaptive_scaling(
    effective_itm: int,
    effective_otm: int,
    mem_flags: dict[str, Any],
    ctx: Any,
    *,
    compute_greeks: bool,
    estimate_iv: bool,
) -> tuple[int, int, bool, bool, bool, float | None]:
    allow_per_option_metrics = True
    local_compute_greeks = compute_greeks
    local_estimate_iv = estimate_iv
    # Memory pressure scaling
    try:
        scale = float(mem_flags.get('depth_scale', 1.0))
        effective_otm = max(2, int(effective_otm * scale))
        effective_itm = max(2, int(effective_itm * scale))
        if mem_flags.get('skip_greeks'):
            local_compute_greeks = False
            local_estimate_iv = False
        if mem_flags.get('drop_per_option_metrics'):
            allow_per_option_metrics = False
    except Exception:
        logger.debug('memory_adjust_scale_failed', exc_info=True)

    # Adaptive passthrough
    passthrough_scale_factor = None
    try:
        passthrough = os.environ.get('G6_ADAPTIVE_SCALE_PASSTHROUGH','').lower() in ('1','true','yes','on')
    except Exception:
        passthrough = False
    if passthrough:
        try:
            flags = getattr(ctx, 'flags', {})
            if isinstance(flags, dict):
                raw = flags.get('adaptive_scale_factor', 1.0)
            else:
                raw = getattr(flags, 'adaptive_scale_factor', 1.0)
            passthrough_scale_factor = float(raw)
        except Exception:
            passthrough_scale_factor = 1.0

    return (
        effective_itm,
        effective_otm,
        allow_per_option_metrics,
        local_compute_greeks,
        local_estimate_iv,
        passthrough_scale_factor if passthrough else None,
    )
