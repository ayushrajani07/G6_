"""Adaptive strike depth scaling logic.

Environment Flags
-----------------
G6_ADAPTIVE_STRIKE_SCALING=1 enables logic.
G6_ADAPTIVE_STRIKE_MIN=2 minimum strikes_itm/otm (default 2)
G6_ADAPTIVE_STRIKE_REDUCTION=0.8 scale factor applied on breach (default 0.8)
G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD=3 consecutive breaches required to scale (default 3)
G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY=10 healthy cycles to restore toward baseline (default 10)

Algorithm
---------
1. Track consecutive breach count (cycle_time > interval * 0.85) and healthy count.
2. When breaches reach threshold, multiply active scale factor by reduction (not below min ratio of (min_depth/base_depth)).
3. Apply new scaled depths to each enabled index (mutate ctx.index_params in-place) and emit metric.
4. Healthy cycles increment healthy counter and reset breach counter. When healthy counter reaches restore threshold and scale<1.0, restore toward 1.0 by dividing by reduction (or set to 1.0 if close). Reapply depths.

State Persistence
-----------------
State stored in ctx.flags under keys:
  adaptive_scale_factor (float)
  adaptive_breach_streak (int)
  adaptive_healthy_streak (int)

This keeps implementation side-effect free beyond context mutation and metrics.
"""
from __future__ import annotations

import math
import os
from typing import Any

from src.utils.env_flags import is_truthy_env  # type: ignore

try:  # optional event dispatch (graceful if events module absent)
    from src.events.event_log import dispatch as emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(*_, **__):  # type: ignore
        return None

BREACH_RATIO = 0.85  # SLA ratio threshold


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def update_strike_scaling(ctx: Any, elapsed: float, interval: float) -> None:
    if not ctx or ctx.index_params is None:
        return
    if not is_truthy_env('G6_ADAPTIVE_STRIKE_SCALING'):
        return
    try:
        metrics = getattr(ctx, 'metrics', None)
        breach_threshold = int(os.environ.get('G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD','3'))
        restore_threshold = int(os.environ.get('G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY','10'))
        reduction = _get_env_float('G6_ADAPTIVE_STRIKE_REDUCTION', 0.8)
        min_depth = int(os.environ.get('G6_ADAPTIVE_STRIKE_MIN','2'))
        passthrough = is_truthy_env('G6_ADAPTIVE_SCALE_PASSTHROUGH')

        scale = ctx.flag('adaptive_scale_factor', 1.0)
        breach_streak = ctx.flag('adaptive_breach_streak', 0)
        healthy_streak = ctx.flag('adaptive_healthy_streak', 0)

        sla = interval * BREACH_RATIO if interval > 0 else float('inf')
        breached = elapsed > sla
        if breached:
            breach_streak += 1
            healthy_streak = 0
        else:
            healthy_streak += 1
            breach_streak = 0

        old_scale = scale
        changed = False
        # Scale down
        if breached and breach_streak >= breach_threshold and scale > 0.05:
            new_scale = scale * reduction
            # Do not reduce below ratio implied by min_depth & typical baseline (assume baseline config values)
            # Determine smallest baseline strikes from current params to infer min_ratio
            min_baseline = math.inf
            for p in ctx.index_params.values():
                if not p.get('enable', True):
                    continue
                baseline = min(p.get('strikes_itm', 2), p.get('strikes_otm', 2))
                if baseline < min_baseline:
                    min_baseline = baseline
            if min_baseline == math.inf:
                min_baseline = 2
            min_ratio = min_depth / max(min_baseline, 1)
            if new_scale < min_ratio:
                new_scale = min_ratio
            if new_scale < scale:
                scale = new_scale
                changed = True
            breach_streak = 0  # reset after scaling to require new streak

        # Restore upward (toward 1.0)
        elif (not breached) and healthy_streak >= restore_threshold and scale < 0.999:
            # inverse of reduction step
            inv = 1.0 / reduction if reduction > 0 else 1.25
            new_scale = scale * inv
            if new_scale > 0.999:
                new_scale = 1.0
            if new_scale > scale:
                scale = new_scale
                changed = True
            healthy_streak = 0

        # Ensure we capture baseline (original) depths once for restoration
        if ctx.flag('adaptive_baseline_captured', False) is False and ctx.index_params:
            baseline_map = {}
            for idx, params in ctx.index_params.items():
                if not params.get('enable', True):
                    continue
                baseline_map[idx] = {
                    'strikes_itm': params.get('strikes_itm', 2),
                    'strikes_otm': params.get('strikes_otm', 2),
                }
            ctx.set_flag('adaptive_baseline', baseline_map)
            ctx.set_flag('adaptive_baseline_captured', True)

        # Apply scaled depths if changed
        if changed:
            baseline_map: dict[str, dict[str,int]] = ctx.flag('adaptive_baseline', {}) or {}
            for idx, params in ctx.index_params.items():  # type: ignore[union-attr]
                if not params.get('enable', True):
                    continue
                if metrics and hasattr(metrics, 'strike_depth_scale_factor'):
                    try:
                        metrics.strike_depth_scale_factor.labels(index=idx).set(scale)
                    except Exception:
                        pass
                if passthrough:
                    # Do NOT mutate depths; strike builders will read scale factor separately
                    continue
                # Legacy mutating path (default behaviour)
                base_vals = baseline_map.get(idx, {})
                base_itm = int(base_vals.get('strikes_itm', params.get('strikes_itm', 2)) or 2)
                base_otm = int(base_vals.get('strikes_otm', params.get('strikes_otm', 2)) or 2)
                safe_scale = float(scale or 1.0)
                params['strikes_itm'] = max(min_depth, int(round(base_itm * safe_scale)))
                params['strikes_otm'] = max(min_depth, int(round(base_otm * safe_scale)))

            # Emit event on scale transitions
            try:
                emit_event(
                    "adaptive_scale_change",
                    context={
                        "old_scale": round(old_scale, 6),
                        "new_scale": round(scale, 6),
                        "breach_streak": breach_streak,
                        "healthy_streak": healthy_streak,
                        "mode": "passthrough" if passthrough else "mutating",
                    },
                )
            except Exception:  # pragma: no cover
                pass
        # Persist state
        ctx.set_flag('adaptive_scale_factor', scale)
        ctx.set_flag('adaptive_breach_streak', breach_streak)
        ctx.set_flag('adaptive_healthy_streak', healthy_streak)
    except Exception:  # pragma: no cover
        # Fail silent; adaptation is best-effort
        pass

__all__ = ["update_strike_scaling"]
