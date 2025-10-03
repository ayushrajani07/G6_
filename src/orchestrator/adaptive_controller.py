"""Adaptive Controller (Phase 5.3 Initial Implementation)

This module introduces a lightweight multi-signal adaptive controller that
evaluates runtime signals each cycle and decides whether to:

1. Adjust a scale factor (e.g., used by strike window scaling or future depth decisions)
2. Demote option detail mode (full -> band -> agg) under pressure
3. Promote detail mode when pressure subsides (with hysteresis)

Signals (initial):
 - Cycle SLA breach streak (derived from ctx.metrics.cycle_sla_breach counter delta)
 - Cardinality guard active (ctx.flag('cardinality_guard_active'))
 - Memory pressure tier (placeholder: env G6_MEMORY_TIER if exported by external watcher) 

Environment Flags / Thresholds:
 - G6_ADAPTIVE_CONTROLLER (enable)
 - G6_ADAPTIVE_SLA_BREACH_STREAK (default 3)  -> streak length that triggers demotion
 - G6_ADAPTIVE_RECOVERY_CYCLES (default 5)     -> consecutive healthy cycles to promote
 - G6_ADAPTIVE_MIN_DETAIL_MODE (default 2)     -> lowest allowed mode (2 = agg)
 - G6_ADAPTIVE_MAX_DETAIL_MODE (default 0)     -> highest mode (0 = full)

Detail Mode Encoding (mirrors roadmap proposal):
   0 = full
   1 = band (reduced strikes / narrower window)
   2 = agg (aggregated / minimal detail)

Metrics Emitted (if registry exposes matching attributes):
 - adaptive_controller_actions_total{reason,action}
 - option_detail_mode{index} (gauge updated if present)

State Persistence:
 The controller stores transient state on context under `_adaptive_state` to track:
  - last_cycle_sla_breach_counter
  - sla_breach_streak
  - healthy_streak
  - detail_mode

NOTE: This is intentionally conservative and side-effect light; future versions
may integrate memory profiler hooks, IV solver iteration stress, junk row volume, etc.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional, Dict, Any


@dataclass
class AdaptiveState:
    last_cycle_sla_breach_counter: int = 0
    sla_breach_streak: int = 0
    healthy_streak: int = 0
    detail_mode: int = 0  # start in full mode


def _get_metrics_counter_value(metrics, name: str) -> int:
    try:
        c = getattr(metrics, name, None)
        if c is None:
            return 0
        # Prometheus client counters have _value.get() in python-client
        if hasattr(c, '_value') and hasattr(c._value, 'get'):  # type: ignore[attr-defined]
            return int(c._value.get())  # type: ignore[no-any-return]
    except Exception:
        return 0
    return 0


def evaluate_adaptive_controller(ctx, elapsed: float, interval: float) -> None:  # noqa: C901 complexity acceptable for initial version
    if os.environ.get('G6_ADAPTIVE_CONTROLLER','').lower() not in ('1','true','yes','on'):
        return
    metrics = getattr(ctx, 'metrics', None)
    state: AdaptiveState
    existing = None
    try:
        existing = ctx.flag('__adaptive_state__')  # stored in flags due to slots
    except Exception:
        existing = None
    if existing is None or not isinstance(existing, AdaptiveState):
        state = AdaptiveState()
        try:
            ctx.set_flag('__adaptive_state__', state)
        except Exception:
            pass
    else:
        state = existing

    # Load thresholds
    try:
        breach_streak_target = int(os.environ.get('G6_ADAPTIVE_SLA_BREACH_STREAK','3'))
    except ValueError:
        breach_streak_target = 3
    try:
        recovery_cycles = int(os.environ.get('G6_ADAPTIVE_RECOVERY_CYCLES','5'))
    except ValueError:
        recovery_cycles = 5
    try:
        max_detail_mode = int(os.environ.get('G6_ADAPTIVE_MAX_DETAIL_MODE','0'))
    except ValueError:
        max_detail_mode = 0
    try:
        min_detail_mode = int(os.environ.get('G6_ADAPTIVE_MIN_DETAIL_MODE','2'))
    except ValueError:
        min_detail_mode = 2

    # Memory tier (0 good, 1 warning, 2 critical). Prefer dynamic ctx flag populated by memory_pressure evaluator; fallback to env.
    memory_tier = 0
    try:
        memory_tier = int(ctx.flag('memory_tier'))  # type: ignore[attr-defined]
    except Exception:
        try:
            memory_tier = int(os.environ.get('G6_MEMORY_TIER','0'))
        except ValueError:
            memory_tier = 0

    # Signal: SLA breach (derive delta)
    breach_counter_now = _get_metrics_counter_value(metrics, 'cycle_sla_breach') if metrics else 0
    if breach_counter_now > state.last_cycle_sla_breach_counter:
        state.sla_breach_streak += 1
        state.healthy_streak = 0
    else:
        state.healthy_streak += 1
        # decay breach streak slowly if healthy
        if state.sla_breach_streak > 0 and state.healthy_streak >= 2:
            state.sla_breach_streak -= 1
    state.last_cycle_sla_breach_counter = breach_counter_now

    # Signal: cardinality guard active flag (set by guard when engaged)
    cardinality_active = False
    try:
        cardinality_active = bool(ctx.flag('cardinality_guard_active'))  # type: ignore[attr-defined]
    except Exception:
        cardinality_active = False

    # Decision logic
    action: Optional[str] = None
    reason: Optional[str] = None
    # Demotion triggers
    if state.detail_mode < min_detail_mode:
        if state.sla_breach_streak >= breach_streak_target:
            state.detail_mode += 1
            action = 'demote'
            reason = 'sla_breach_streak'
            state.sla_breach_streak = 0  # reset after action
            state.healthy_streak = 0
        elif cardinality_active and state.detail_mode < min_detail_mode:
            state.detail_mode += 1
            action = 'demote'
            reason = 'cardinality_guard'
            state.healthy_streak = 0
        elif memory_tier >= 2 and state.detail_mode < min_detail_mode:
            state.detail_mode += 1
            action = 'demote'
            reason = 'memory_pressure'
            state.healthy_streak = 0
    # Promotion triggers (only if not at max detail and healthy for recovery_cycles)
    if action is None and state.detail_mode > max_detail_mode and state.healthy_streak >= recovery_cycles and not cardinality_active and memory_tier == 0:
        # Allow chained promotions if recovery_cycles * (modes_above_max) healthy cycles have accumulated.
        modes_to_recover = state.detail_mode - max_detail_mode
        # Determine how many promotions permitted by healthy streak budget
        possible_promotions = state.healthy_streak // recovery_cycles
        promotions = min(modes_to_recover, possible_promotions)
        if promotions > 0:
            state.detail_mode -= promotions
            action = 'promote'
            reason = f'healthy_recovery_{promotions}'
            # Consume equivalent healthy cycles
            state.healthy_streak = state.healthy_streak - promotions * recovery_cycles
            state.sla_breach_streak = 0

    # Clamp detail_mode boundaries
    if state.detail_mode < max_detail_mode:
        state.detail_mode = max_detail_mode
    if state.detail_mode > min_detail_mode:
        state.detail_mode = min_detail_mode

    # Persist selected detail mode onto context for downstream components (e.g., strike builder, collectors)
    try:
        ctx.set_flag('option_detail_mode', state.detail_mode)  # type: ignore[attr-defined]
    except Exception:
        pass

    # Emit metrics if possible
    if metrics:
        if action and hasattr(metrics, 'adaptive_controller_actions'):  # counter with labels
            try:
                metrics.adaptive_controller_actions.labels(reason=reason or 'unknown', action=action).inc()  # type: ignore[attr-defined]
            except Exception:
                pass
        # Per-index gauge updates (if collector loop later wants per-index granularity, replicate for each)
        if hasattr(metrics, 'option_detail_mode'):
            try:
                # If multiple indices, apply same mode uniformly (future: index-specific decisions)
                for idx in (list(ctx.index_params.keys()) if getattr(ctx, 'index_params', None) else []):  # type: ignore[assignment]
                    metrics.option_detail_mode.labels(index=idx).set(state.detail_mode)  # type: ignore[attr-defined]
            except Exception:
                pass

__all__ = ["evaluate_adaptive_controller", "AdaptiveState"]
