"""Adaptive controller logic implementation.

Evaluates multiple signals to determine option detail mode (0 full, 1 band, 2 agg)
and records actions via metrics introduced previously.

Environment Flags:
  G6_ADAPTIVE_CONTROLLER=1   Enable controller
  G6_ADAPTIVE_MIN_HEALTH_CYCLES=3  Cycles without pressure to consider promotion
    G6_ADAPTIVE_MAX_SLA_BREACH_STREAK=2  Demote after this many consecutive SLA breaches
    G6_ADAPTIVE_DEMOTE_COOLDOWN=1   Minimum cycles between successive demotions
    G6_ADAPTIVE_PROMOTE_COOLDOWN=2  Minimum cycles between successive promotions

Signals (best-effort reads from metrics object):
  - SLA breach streak (derived by tracking delta in g6_cycle_sla_breach_total)
  - Memory pressure (g6_memory_pressure_level gauge)
  - Cardinality guard (last trip delta of g6_cardinality_guard_trips_total)

State is maintained on the metrics singleton (attributes with _adaptive_ prefix) to avoid
additional global singletons.
"""
from __future__ import annotations

import os
import time
from typing import cast

from src.metrics import get_metrics  # facade import

from . import followups as _followups
from . import severity as _severity
from .controller import DetailMode, record_controller_action, set_detail_mode


def _enabled() -> bool:
    return os.getenv('G6_ADAPTIVE_CONTROLLER','').lower() in ('1','true','yes','on')


def _get_val(metric, labels=None) -> float | None:  # best-effort gauge value fetch
    try:
        if metric is None:
            return None
        # prometheus_client internal sample extraction
        for sample in metric.collect():  # type: ignore
            for s in sample.samples:
                if labels:
                    if all(s.labels.get(k) == v for k,v in labels.items()):
                        return float(s.value)
                else:
                    return float(s.value)
    except Exception:
        return None
    return None


def evaluate_and_apply(indexes: list[str]) -> None:
    if not _enabled():
        return
    m = get_metrics()
    # Always record a trend snapshot early in the cycle when severity feature is enabled,
    # so that HTTP theme endpoint has recent data even if later gates short-circuit.
    try:
        if _severity.enabled():
            _severity.record_trend_snapshot()
    except Exception:
        pass
    # Drain follow-up guard alerts (interpolation_high, risk_delta_drift, bucket_util_low)
    try:
        _new_followup_alerts = _followups.get_and_clear_alerts()
    except Exception:  # pragma: no cover - tolerant
        _new_followup_alerts = []
    followup_pressure = any(a.get('severity') == 'critical' and a.get('type') in {'interpolation_high','bucket_util_low'} for a in _new_followup_alerts)
    # Weight pressure (rolling window)
    weight_pressure = 0
    try:
        weight_pressure = _followups.get_weight_pressure()
    except Exception:
        weight_pressure = 0
    try:
        demote_threshold = int(os.getenv('G6_FOLLOWUPS_DEMOTE_THRESHOLD','3') or 3)
    except Exception:
        demote_threshold = 3
    # Initialize adaptive state storage
    streak = getattr(m, '_adaptive_sla_streak', 0)
    pressure_level = _get_val(getattr(m, 'memory_pressure_level', None)) or 0
    last_sla_total = getattr(m, '_adaptive_last_sla_total', 0)
    sla_total = 0
    try:
        sla_metric = getattr(m, 'cycle_sla_breach', None)
        # Use internal counter value if accessible
        if sla_metric:
            # Collect first sample value
            val = _get_val(sla_metric)
            sla_total = int(val) if val is not None else 0
    except Exception:
        pass
    if sla_total > last_sla_total:
        streak += 1
    else:
        streak = 0
    m._adaptive_last_sla_total = sla_total
    m._adaptive_sla_streak = streak

    # Cardinality guard trips delta
    card_total = 0
    last_card_total = getattr(m, '_adaptive_last_cardinality_trips', 0)
    try:
        card_metric = getattr(m, 'cardinality_guard_trips', None)
        val = _get_val(card_metric)
        card_total = int(val) if val is not None else 0
    except Exception:
        pass
    card_delta = card_total - last_card_total
    m._adaptive_last_cardinality_trips = card_total

    # Determine desired mode based on signals (simple heuristic)
    # Start from current (assume full=0 if unknown)
    current_mode = getattr(m, '_adaptive_current_mode', 0)
    last_mode_change_cycle = getattr(m, '_adaptive_last_mode_change_cycle', -1)
    last_mode_change_time = getattr(m, '_adaptive_last_mode_change_time', None)
    mode_change_count = getattr(m, '_adaptive_mode_change_count', 0)
    demote_reason = None
    promote_reason = None
    max_streak = int(os.getenv('G6_ADAPTIVE_MAX_SLA_BREACH_STREAK','2'))
    min_health = int(os.getenv('G6_ADAPTIVE_MIN_HEALTH_CYCLES','3'))
    healthy_cycles = getattr(m, '_adaptive_healthy_cycles', 0)

    pressure_demote = pressure_level >= 2  # high or critical
    sla_demote = streak >= max_streak
    guard_demote = card_delta > 0

    # Phase 3: severity-driven demotion signal
    # Env variables:
    #   G6_ADAPTIVE_CONTROLLER_SEVERITY=1 enables using severity for decisions
    #   G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES="t1,t2" subset (optional) else any critical triggers
    #   G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES="t1,t2" subset (optional) else any warn blocks promotion
    sev_enabled = os.getenv('G6_ADAPTIVE_CONTROLLER_SEVERITY','').lower() in ('1','true','yes','on')
    severity_demote = False
    severity_block_promote = False
    crit_filter = set()
    warn_block_filter = set()
    if sev_enabled and _severity.enabled():
        try:
            raw_crit = os.getenv('G6_ADAPTIVE_SEVERITY_CRITICAL_DEMOTE_TYPES','')
            raw_warn_block = os.getenv('G6_ADAPTIVE_SEVERITY_WARN_BLOCK_PROMOTE_TYPES','')
            if raw_crit:
                crit_filter = {s.strip() for s in raw_crit.split(',') if s.strip()}
            if raw_warn_block:
                warn_block_filter = {s.strip() for s in raw_warn_block.split(',') if s.strip()}
            # Record trend snapshot first (kept for historical ordering; already captured above)
            _severity.record_trend_snapshot()
            # Apply smoothing logic (falls back to immediate if smoothing disabled)
            severity_demote = _severity.should_trigger_critical_demote(crit_filter or None)
            severity_block_promote = _severity.should_block_promotion_for_warn(warn_block_filter or None)
        except Exception:
            pass
    if pressure_demote:
        demote_reason = 'memory_pressure'
    elif sla_demote:
        demote_reason = 'sla_breach_streak'
    elif guard_demote:
        demote_reason = 'cardinality_guard'
    elif severity_demote:
        demote_reason = 'severity_critical'
    elif followup_pressure:
        demote_reason = 'followups_critical'
    elif weight_pressure >= demote_threshold:
        demote_reason = 'followups_weight'

    # Cooldown state
    last_demote_cycle = getattr(m, '_adaptive_last_demote_cycle', -10)
    last_promote_cycle = getattr(m, '_adaptive_last_promote_cycle', -10)
    cycle_counter = getattr(m, '_adaptive_cycle_counter', 0)
    demote_cooldown = int(os.getenv('G6_ADAPTIVE_DEMOTE_COOLDOWN','1'))
    promote_cooldown = int(os.getenv('G6_ADAPTIVE_PROMOTE_COOLDOWN','2'))

    # Track streak id to ensure only one demotion per continuous streak segment
    streak_id = getattr(m, '_adaptive_last_streak_id', 0)
    current_streak_id = streak_id
    if streak == 0:
        current_streak_id += 1  # new segment (healthy reset)
    if demote_reason:
        if current_mode < 2 and (cycle_counter - last_demote_cycle) >= demote_cooldown:
            # Only demote if we haven't already demoted in this streak segment
            last_demote_segment = getattr(m, '_adaptive_last_demote_streak_id', -1)
            if last_demote_segment != current_streak_id:
                new_mode = current_mode + 1
                record_controller_action(demote_reason, 'demote')
                if new_mode != current_mode:
                    current_mode = new_mode
                    last_mode_change_cycle = cycle_counter
                    last_mode_change_time = time.time()
                    mode_change_count += 1
                healthy_cycles = 0
                last_demote_cycle = cycle_counter
                m._adaptive_last_demote_streak_id = current_streak_id
    else:
        # No pressure this cycle; increment healthy count
        healthy_cycles += 1
        required_healthy = max(min_health, promote_cooldown)
        # Block promotions if severity indicates elevated warn per config
        if severity_block_promote:
            healthy_cycles = 0  # reset healthy window to avoid immediate promote after clear
        if (
            not severity_block_promote
            and healthy_cycles >= required_healthy
            and current_mode > 0
            and (cycle_counter - last_promote_cycle) >= promote_cooldown
            and (cycle_counter - last_demote_cycle) >= promote_cooldown
        ):
            promote_reason = f'healthy_recovery_{healthy_cycles}'
            new_mode = current_mode - 1
            record_controller_action(promote_reason, 'promote')
            if new_mode != current_mode:
                current_mode = new_mode
                last_mode_change_cycle = cycle_counter
                last_mode_change_time = time.time()
                mode_change_count += 1
            healthy_cycles = 0
            last_promote_cycle = cycle_counter

    m._adaptive_current_mode = current_mode
    m._adaptive_healthy_cycles = healthy_cycles
    m._adaptive_last_demote_cycle = last_demote_cycle
    m._adaptive_last_promote_cycle = last_promote_cycle
    m._adaptive_cycle_counter = cycle_counter + 1
    m._adaptive_last_streak_id = current_streak_id
    m._adaptive_last_mode_change_cycle = last_mode_change_cycle
    m._adaptive_last_mode_change_time = last_mode_change_time
    m._adaptive_mode_change_count = mode_change_count

    # Emit per-index mode gauge
    for idx in indexes:
        # current_mode constrained to 0/1/2 via transitions; cast for type checker
        set_detail_mode(idx, cast(DetailMode, current_mode))
