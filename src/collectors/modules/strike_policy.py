"""Adaptive Strike Policy (Phase 10, v2)

Provides pluggable strike depth policy selection used by pipeline (and later
legacy path) to compute `strikes_itm` / `strikes_otm` dynamically prior to
calling `compute_strike_universe`.

Policy Resolution Order:
  1. Environment override G6_STRIKE_POLICY (adaptive_v2 | fixed)
  2. Fallback: 'fixed'

adaptive_v2 Logic (lightweight heuristic v1):
  - Inputs: last N (default 5) strike_coverage_avg values (per index) captured in
    context plus current expiry's strike_coverage (if available).
  - Target coverage: env `G6_STRIKE_POLICY_TARGET` (default 0.85).
  - If median recent coverage < target_low (target * 0.92) => widen by +step_inc (env `G6_STRIKE_POLICY_STEP`, default 2).
  - If median recent coverage > target_high (min(0.99, target + 0.05)) AND current configured depth > baseline => narrow by step_dec (same step).
  - Guard rails: min baseline (original config), max caps via `G6_STRIKE_POLICY_MAX_ITM` / `_MAX_OTM` (defaults baseline+20).
  - Cooldown: require at least `G6_STRIKE_POLICY_COOLDOWN` (default 2) cycles between successive adjustments per index.

State is stored on collector context under `_strike_policy_state` keyed by index.

This early version intentionally avoids volatility modeling; future iterations
may incorporate realized IV buckets or historical quote density.
"""
from __future__ import annotations

import logging
import os
import statistics
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["resolve_strike_depth"]

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default

def _policy_name() -> str:
    return os.environ.get('G6_STRIKE_POLICY','fixed').lower()

def resolve_strike_depth(ctx: Any, index_symbol: str, base_cfg: dict[str, Any]) -> tuple[int,int]:
    """Return (strikes_itm, strikes_otm) per active policy.

    base_cfg: index_params[index_symbol] mapping from caller (immutable expectation).
    """
    name = _policy_name()
    if name != 'adaptive_v2':
        return int(base_cfg.get('strikes_itm', 2) or 2), int(base_cfg.get('strikes_otm', 2) or 2)
    return _adaptive_v2(ctx, index_symbol, base_cfg)

def _adaptive_v2(ctx: Any, index_symbol: str, base_cfg: dict[str, Any]) -> tuple[int,int]:
    # Initialize state container on ctx
    if not hasattr(ctx, '_strike_policy_state'):
        ctx._strike_policy_state = {}
    st = ctx._strike_policy_state
    if index_symbol not in st:
        st[index_symbol] = {
            'baseline_itm': int(base_cfg.get('strikes_itm', 2) or 2),
            'baseline_otm': int(base_cfg.get('strikes_otm', 2) or 2),
            'history': [],  # recent strike_coverage_avg values
            'last_adjust_cycle': -1,
            'last_depth': (
                int(base_cfg.get('strikes_itm', 2) or 2),
                int(base_cfg.get('strikes_otm', 2) or 2),
            ),
        }
    rec = st[index_symbol]
    # Attempt to pull last coverage average from ctx indices_struct snapshot if present
    # Caller may optionally append coverage averages after each index processing.
    coverage_val = None
    try:
        if hasattr(ctx, 'last_index_coverage'):
            coverage_val = ctx.last_index_coverage.get(index_symbol)
    except Exception:
        coverage_val = None
    if coverage_val is not None:
        rec['history'].append(float(coverage_val))
        # Trim history length
        win = _env_int('G6_STRIKE_POLICY_WINDOW', 5)
        if len(rec['history']) > max(1, win):
            rec['history'] = rec['history'][-win:]
    # Compute median recent coverage
    median_cov = None
    if rec['history']:
        try:
            median_cov = statistics.median(rec['history'])
        except Exception:
            median_cov = None
    target = _env_float('G6_STRIKE_POLICY_TARGET', 0.85)
    step = _env_int('G6_STRIKE_POLICY_STEP', 2)
    cooldown = _env_int('G6_STRIKE_POLICY_COOLDOWN', 2)
    max_itm = _env_int('G6_STRIKE_POLICY_MAX_ITM', rec['baseline_itm'] + 20)
    max_otm = _env_int('G6_STRIKE_POLICY_MAX_OTM', rec['baseline_otm'] + 20)
    target_low = max(0.05, target * 0.92)
    target_high = min(0.99, target + 0.05)
    cycle_num = int(time.time() // max(1, _env_int('G6_CYCLE_INTERVAL', 60)))

    cur_itm, cur_otm = rec['last_depth']
    new_itm, new_otm = cur_itm, cur_otm
    adjusted = False
    if median_cov is not None and len(rec['history']) >= 2:
        if median_cov < target_low and (cycle_num - rec['last_adjust_cycle']) >= cooldown:
            new_itm = min(max_itm, cur_itm + step)
            new_otm = min(max_otm, cur_otm + step)
            adjusted = (new_itm, new_otm) != (cur_itm, cur_otm)
        elif median_cov > target_high and (cur_itm > rec['baseline_itm'] or cur_otm > rec['baseline_otm']) and (cycle_num - rec['last_adjust_cycle']) >= cooldown:
            new_itm = max(rec['baseline_itm'], cur_itm - step)
            new_otm = max(rec['baseline_otm'], cur_otm - step)
            adjusted = (new_itm, new_otm) != (cur_itm, cur_otm)
    if adjusted:
        rec['last_adjust_cycle'] = cycle_num
        rec['last_depth'] = (new_itm, new_otm)
        try:
            from importlib import import_module
            _mod = import_module('src.collectors.helpers.struct_events')
            emit_strike_depth_adjustment = getattr(_mod, 'emit_strike_depth_adjustment', None)
            if callable(emit_strike_depth_adjustment):
                emit_strike_depth_adjustment(
                index=index_symbol,
                reason='policy_adaptive_v2_widen' if (new_itm>cur_itm or new_otm>cur_otm) else 'policy_adaptive_v2_narrow',
                prev_itm=cur_itm,
                prev_otm=cur_otm,
                new_itm=new_itm,
                new_otm=new_otm,
                strike_coverage=coverage_val,
                field_coverage=None,
                expiry_rule='policy',
                )
        except Exception:
            logger.debug('emit_strike_policy_adjustment_failed', exc_info=True)
    depth = rec.get('last_depth')
    return (int(depth[0]), int(depth[1])) if isinstance(depth, tuple) and len(depth) == 2 else (
        int(base_cfg.get('strikes_itm', 2) or 2), int(base_cfg.get('strikes_otm', 2) or 2)
    )
