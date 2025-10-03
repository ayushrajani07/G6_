"""Phase 4: Adaptive strike expansion & contraction extraction.

This module encapsulates the adaptive logic previously inlined inside
`unified_collectors.py`. Behavior must remain identical (parity focus). The
original logic is moved with only minimal structural changes (function
wrapping + explicit parameters).
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "adaptive_strike_retry",
    "adaptive_contraction",
    "adaptive_post_expiry",
]

def adaptive_strike_retry(ctx: Any, index_symbol: str, expiry_rec: dict, expiry_rule: str) -> None:
    """Apply adaptive strike expansion (retry) logic based on strike coverage.

    Mutates `ctx.index_params` in-place to expand strikes_itm / strikes_otm when
    coverage is below threshold. Mirrors original inlined logic.
    """
    # Mark per-index cycle flags used by contraction logic
    if not hasattr(ctx, '_adaptive_contraction_state'):
        ctx._adaptive_contraction_state = {}  # type: ignore[attr-defined]
    _acs = ctx._adaptive_contraction_state  # type: ignore[attr-defined]
    if index_symbol not in _acs:
        base_cfg = (getattr(ctx, 'index_params', {}) or {}).get(index_symbol, {})  # type: ignore[index]
        _acs[index_symbol] = {
            'baseline_itm': int(base_cfg.get('strikes_itm', 2) or 2),
            'baseline_otm': int(base_cfg.get('strikes_otm', 2) or 2),
            'healthy_streak': 0,
            'cycle_last_action': -1,
            'had_expansion_this_cycle': False,
            'had_low_cov': False,
        }
    # One-time caching of adaptive retry env controls on context
    if not hasattr(ctx, '_adaptive_retry_cache'):
        ctx._adaptive_retry_cache = {  # type: ignore[attr-defined]
            'disable': os.environ.get('G6_DISABLE_ADAPTIVE_STRIKE_RETRY','').lower() in ('1','true','yes','on'),
            'strike_ok_raw': os.environ.get('G6_STRIKE_COVERAGE_OK'),
            'max_itm_raw': os.environ.get('G6_ADAPTIVE_STRIKE_MAX_ITM'),
            'max_otm_raw': os.environ.get('G6_ADAPTIVE_STRIKE_MAX_OTM'),
            'step_raw': os.environ.get('G6_ADAPTIVE_STRIKE_STEP'),
        }
    _arc = ctx._adaptive_retry_cache  # type: ignore[attr-defined]
    if _arc['disable']:
        return
    strike_cov_local = expiry_rec.get('strike_coverage')
    base_thresh_env = _arc['strike_ok_raw']
    try:
        base_thresh = float(base_thresh_env) if base_thresh_env is not None else 0.75
    except ValueError:
        base_thresh = 0.75
    trigger = max(0.05, min(0.99, base_thresh * 0.9))
    if strike_cov_local is not None and strike_cov_local < trigger and expiry_rec.get('options',0) > 0:
        idx_cfg = (getattr(ctx, 'index_params', {}) or {}).get(index_symbol, {})  # type: ignore[index]
        cur_itm = int(idx_cfg.get('strikes_itm', 10))
        cur_otm = int(idx_cfg.get('strikes_otm', 10))
        max_itm_env = _arc['max_itm_raw']
        max_otm_env = _arc['max_otm_raw']
        try:
            max_itm = int(max_itm_env) if max_itm_env else max(10, cur_itm + 10)
        except ValueError:
            max_itm = max(10, cur_itm + 10)
        try:
            max_otm = int(max_otm_env) if max_otm_env else max(10, cur_otm + 10)
        except ValueError:
            max_otm = max(10, cur_otm + 10)
        step_env = _arc['step_raw']
        try:
            step_inc = int(step_env) if step_env else 2
        except ValueError:
            step_inc = 2
        new_itm = min(max_itm, cur_itm + step_inc)
        new_otm = min(max_otm, cur_otm + step_inc)
        if new_itm > cur_itm or new_otm > cur_otm:
            try:
                if getattr(ctx, 'index_params', None) and index_symbol in ctx.index_params:  # type: ignore[attr-defined]
                    ctx.index_params[index_symbol]['strikes_itm'] = new_itm  # type: ignore[index]
                    ctx.index_params[index_symbol]['strikes_otm'] = new_otm  # type: ignore[index]
                    _acs[index_symbol]['had_expansion_this_cycle'] = True  # type: ignore[index]
            except Exception:
                logger.debug("adaptive_strike_param_update_failed", exc_info=True)
            # Structured event emit left inline (import deferred to avoid cycles)
            try:
                from src.collectors.helpers.struct_events import emit_strike_depth_adjustment  # type: ignore
                emit_strike_depth_adjustment(
                    index=index_symbol,
                    reason='low_strike_cov',
                    prev_itm=cur_itm,
                    prev_otm=cur_otm,
                    new_itm=new_itm,
                    new_otm=new_otm,
                    strike_coverage=strike_cov_local,
                    field_coverage=expiry_rec.get('field_coverage'),
                    expiry_rule=expiry_rule,
                    min_threshold=trigger,
                )
            except Exception:
                logger.debug("emit_strike_depth_adjustment_failed", exc_info=True)
    else:
        if strike_cov_local is not None and strike_cov_local < trigger:
            _acs[index_symbol]['had_low_cov'] = True  # type: ignore[index]


def adaptive_contraction(ctx: Any, index_symbol: str, expiry_rec: dict, expiry_rule: str) -> None:
    """Apply contraction logic after expansion decisions.

    Contracts strike depth after a healthy streak, respecting cooldowns and
    baselines. Mirrors original logic ordering.
    """
    _acs = getattr(ctx, '_adaptive_contraction_state', {})  # type: ignore[attr-defined]
    if index_symbol not in _acs:
        return
    st = _acs[index_symbol]
    if not st['had_expansion_this_cycle'] and not st['had_low_cov']:
        st['healthy_streak'] += 1
    else:
        st['healthy_streak'] = 0
    st['had_expansion_this_cycle'] = False
    st['had_low_cov'] = False
    ok_cycles_env = os.environ.get('G6_CONTRACT_OK_CYCLES')
    cooldown_env = os.environ.get('G6_CONTRACT_COOLDOWN')
    step_env = os.environ.get('G6_CONTRACT_STEP')
    try:
        ok_cycles = int(ok_cycles_env) if ok_cycles_env else 5
    except ValueError:
        ok_cycles = 5
    try:
        cooldown = int(cooldown_env) if cooldown_env else 3
    except ValueError:
        cooldown = 3
    try:
        step_dec = int(step_env) if step_env else 2
    except ValueError:
        step_dec = 2
    idx_cfg = (getattr(ctx, 'index_params', {}) or {}).get(index_symbol, {})  # type: ignore[index]
    cur_itm = int(idx_cfg.get('strikes_itm', 0) or 0)
    cur_otm = int(idx_cfg.get('strikes_otm', 0) or 0)
    baseline_itm = st['baseline_itm']
    baseline_otm = st['baseline_otm']
    if st['healthy_streak'] < ok_cycles or (cur_itm <= baseline_itm and cur_otm <= baseline_otm):
        return
    cycle_count = getattr(getattr(ctx, 'metrics', None), 'collection_cycles_total', None)
    cur_cycle_num = None
    try:
        if cycle_count and hasattr(cycle_count, 'count'):
            cur_cycle_num = int(getattr(cycle_count, 'count'))  # type: ignore
    except Exception:
        cur_cycle_num = None
    if cur_cycle_num is None:
        try:
            interval_s = int(os.environ.get('G6_CYCLE_INTERVAL','60') or '60')
        except ValueError:
            interval_s = 60
        cur_cycle_num = int(time.time() // max(1, interval_s))
    if st['cycle_last_action'] >= 0 and (cur_cycle_num - st['cycle_last_action']) < cooldown:
        return
    new_itm = max(baseline_itm, cur_itm - step_dec)
    new_otm = max(baseline_otm, cur_otm - step_dec)
    if new_itm >= cur_itm and new_otm >= cur_otm:
        return
    try:
        if getattr(ctx, 'index_params', None) and index_symbol in ctx.index_params:  # type: ignore[attr-defined]
            ctx.index_params[index_symbol]['strikes_itm'] = new_itm  # type: ignore[index]
            ctx.index_params[index_symbol]['strikes_otm'] = new_otm  # type: ignore[index]
            st['cycle_last_action'] = cur_cycle_num
            st['healthy_streak'] = 0
    except Exception:
        logger.debug("adaptive_contraction_param_update_failed", exc_info=True)
    try:
        from src.collectors.helpers.struct_events import emit_strike_depth_adjustment  # type: ignore
        # Signature parity: keep only parameters supported by existing struct event helper
        emit_strike_depth_adjustment(
            index=index_symbol,
            reason='contraction',
            prev_itm=cur_itm,
            prev_otm=cur_otm,
            new_itm=new_itm,
            new_otm=new_otm,
            expiry_rule=expiry_rule,
            strike_coverage=expiry_rec.get('strike_coverage'),
            field_coverage=expiry_rec.get('field_coverage'),
        )
    except Exception:
        logger.debug("emit_contraction_event_failed", exc_info=True)


def adaptive_post_expiry(ctx: Any, index_symbol: str, expiry_rec: dict, expiry_rule: str) -> None:
    """Convenience wrapper executing retry then contraction phases."""
    try:
        adaptive_strike_retry(ctx, index_symbol, expiry_rec, expiry_rule)
    except Exception:
        logger.debug("adaptive_strike_retry_logic_failed", exc_info=True)
    try:
        adaptive_contraction(ctx, index_symbol, expiry_rec, expiry_rule)
    except Exception:
        logger.debug("adaptive_strike_contraction_logic_failed", exc_info=True)
