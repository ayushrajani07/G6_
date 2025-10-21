from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from . import (
    gating,  # Phase 4 gating controller (dry-run)
    phases,
)
from .executor import execute_phases
from .state import ExpiryState
from .struct_events import emit_struct_event

logger = logging.getLogger(__name__)

# Minimal diff surface intentionally: expand only after stability soak to avoid log cardinality surge.
DIFF_FIELDS = ('expiry_date','strike_count','instrument_count','enriched_keys')

def _compute_parity_hash(shadow_snap: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    """Compute stable parity hash v2.

    Only includes normalized structural + limited observational fields.
    Returns 16-hex digest or 'na' on failure.
    Separated for deterministic testing.
    """
    try:  # pragma: no cover - exercised via tests but guard for runtime safety
        cov = meta.get('coverage') or {}
        psim = meta.get('persist_sim') or {}
        strike_cov = cov.get('strike') if 'strike' in cov else 0
        field_cov = cov.get('field') if 'field' in cov else 0
        sim_opts = psim.get('option_count') if 'option_count' in psim else 0
        sim_pcr = psim.get('pcr') if 'pcr' in psim else 0
        # Canonicalize strikes head selection so hash is order-invariant for permutations
        # Previous behavior: first 5 in original order (order sensitive) -> caused nondeterminism in tests.
        # New behavior: sort full strike list ascending then take first 5 to provide stable structural signal.
        strikes_list = list(shadow_snap.get('strikes') or [])
        if strikes_list:
            try:
                # Sorting provides deterministic ordering; if heterogeneous types, fallback to original slice.
                strikes_head = sorted(strikes_list)[:5]
            except TypeError:
                strikes_head = strikes_list[:5]
        else:
            strikes_head = []
        payload = {
            'expiry_date': str(shadow_snap.get('expiry_date')),
            'strike_count': shadow_snap.get('strike_count'),
            'instrument_count': shadow_snap.get('instrument_count'),
            'enriched_keys': shadow_snap.get('enriched_keys'),
            'strike_cov': strike_cov,
            'field_cov': field_cov,
            'sim_opts': sim_opts,
            'sim_pcr': sim_pcr,
            'strikes_head': strikes_head,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(',',':')).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()[:16]
    except Exception:  # pragma: no cover
        return 'na'


def run_shadow_pipeline(
    ctx: Any,
    settings: Any,
    *,
    index: str,
    rule: str,
    precomputed_strikes: Iterable[float] | Any,
    legacy_snapshot: dict[str, Any],
) -> ExpiryState | None:
    state = ExpiryState(index=index, rule=rule, settings=settings)
    try:
        # Core taxonomy-managed phases (ordering preserved)
        state = execute_phases(
            ctx,
            state,
            [
                phases.phase_resolve,
                lambda c, s: phases.phase_fetch(c, s, precomputed_strikes),
                phases.phase_prefilter,
                phases.phase_enrich,
            ],
        )
        if state.enriched:
            state.meta['orig_enriched_snapshot'] = dict(state.enriched)
        # Secondary phases executed directly (they internally guard errors & do not influence taxonomy control flow yet)
        for fn in (
            phases.phase_preventive_validate,
            phases.phase_salvage,
            phases.phase_coverage,
            phases.phase_iv,
            phases.phase_greeks,
            phases.phase_persist_sim,
        ):
            try:
                fn(ctx, state)
            except Exception as inner:  # pragma: no cover - defensive containment
                state.errors.append(f"phase_secondary:{getattr(fn,'__name__','unknown')}:{inner}")
    except Exception as e:  # pragma: no cover
        logger.debug('expiry.shadow.pipeline_error index=%s rule=%s err=%s', index, rule, e, exc_info=True)
        return None
    shadow_snap = state.snapshot_core()
    # Compute stable parity hash (v2)
    parity_hash = _compute_parity_hash(shadow_snap, state.meta)
    # Record hash in meta with versioning so tests can assert presence
    state.meta['parity_hash_v2'] = parity_hash
    diffs = {}
    for field in DIFF_FIELDS:
        lval = legacy_snapshot.get(field)
        sval = shadow_snap.get(field)
        if lval != sval:
            diffs[field] = {'legacy': lval, 'shadow': sval}
    # Record diff meta for downstream gating / metrics (Phase 4)
    try:
        if diffs:
            state.meta['parity_diff_fields'] = tuple(sorted(diffs.keys()))  # stable ordering
            state.meta['parity_diff_count'] = len(diffs)
        else:
            state.meta['parity_diff_fields'] = ()
            state.meta['parity_diff_count'] = 0
    except Exception:  # pragma: no cover
        pass
    # Placeholder: future instrumentation hook (avoid prometheus import here to keep lightweight)
    # Example (planned): metrics.shadow_parity_diff_total.labels(field=...).inc() per field in diffs
    if diffs:
        # Compact single-line log for easier parsing
        try:
            parts = [f"{k}={v['legacy']}|{v['shadow']}" for k,v in diffs.items()]
            logger.debug('expiry.shadow.diff index=%s rule=%s hash=%s %s', index, rule, parity_hash, ' '.join(parts))
        except Exception:  # pragma: no cover
            logger.debug('expiry.shadow.diff_emit_failed index=%s rule=%s hash=%s diffs=%s', index, rule, parity_hash, diffs)
    else:
        logger.debug('expiry.shadow.ok index=%s rule=%s hash=%s', index, rule, parity_hash)
    # Phase 4: Gating (dry-run). Wrap in broad try to ensure no interference with shadow pipeline stability.
    try:  # pragma: no cover - decision logic unit tested separately
        decision = gating.decide(index, rule, state.meta)
        state.meta['gating_decision'] = decision
    except Exception:
        decision = None
        state.meta['gating_decision'] = {'mode':'error','promote':False,'reason':'exception'}
    # Structured decision log (single line JSON style for auditability)
    try:
        if decision:
            # Avoid large meta; log concise core keys
            log_payload = {
                'mode': decision.get('mode'),
                'promote': decision.get('promote'),
                'canary': decision.get('canary'),
                'ratio': decision.get('parity_ok_ratio'),
                'win': decision.get('window_size'),
                'ok_streak': decision.get('ok_streak'),
                'fail_streak': decision.get('fail_streak'),
                'diff_count': decision.get('diff_count'),
                'protected': decision.get('protected_diff'),
                'prot_win': decision.get('protected_in_window'),
                'churn': decision.get('hash_churn_ratio'),
                'reason': decision.get('reason'),
            }
            logger.debug('shadow.gate.decision index=%s rule=%s %s', index, rule, json.dumps(log_payload, separators=(',',':'), sort_keys=True))
    except Exception:  # pragma: no cover
        logger.debug('shadow.gate.decision_emit_failed index=%s rule=%s', index, rule, exc_info=True)
    # Emit structured snapshot/parity event
    try:
        emit_struct_event(
            'expiry.snapshot.event',
            {
                'index': index,
                'rule': rule,
                'parity_hash_v2': parity_hash,
                'diff_count': int(state.meta.get('parity_diff_count') or 0),
                'gating_mode': (decision or {}).get('mode') if isinstance(decision, dict) else None,
                'gating_promote': (decision or {}).get('promote') if isinstance(decision, dict) else None,
            },
            state=state,
        )
    except Exception:
        pass
    # Emit shadow parity metrics (best-effort) via MetricsAdapter if metrics registry present on ctx
    try:  # pragma: no cover - metrics side effects
        metrics_reg = getattr(ctx, 'metrics', None)
        if metrics_reg is not None:
            from src.metrics.adapter import MetricsAdapter  # optional metrics adapter
            adapter = MetricsAdapter(metrics_reg)
            diff_count = int(state.meta.get('parity_diff_count') or 0)
            adapter.record_shadow_parity(index, rule, diff_count=diff_count, decision=decision)
            # Emit gating decision metrics (mode/reason + promotions)
            adapter.record_shadow_gating(index, rule, decision)
            # Emit churn / rollback metrics
            adapter.record_shadow_churn(index, rule, decision)
            # Protected field diff counters (optional allowlist)
            try:
                protected_fields = tuple(getattr(decision, 'protected_fields', ()))  # not stored; fallback to env parse
            except Exception:
                protected_fields = ()
            # Reconstruct protected fields from gating config env (avoids importing config object)
            if not protected_fields:
                from . import gating as _g
                cfg = _g.load_config_from_env()
                protected_fields = cfg.protected_fields
            diff_fields = state.meta.get('parity_diff_fields') or ()
            adapter.record_shadow_protected_field_diffs(index, rule, diff_fields, protected_fields=protected_fields)
    except Exception:
        logger.debug('shadow_parity_metrics_emit_failed', exc_info=True)
    return state

__all__ = ["run_shadow_pipeline", "_compute_parity_hash"]
