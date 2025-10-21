"""Structured event emission helpers for collector pipeline (R1 Observability Block #9).

Each emit_* function assembles a normalized payload and logs a line of the form:
    STRUCT <event_name> | {json}

Design goals:
- Stable field ordering (best-effort) and consistent key naming (snake_case).
- Avoid raising on any failure (best-effort logging only).
- Lightweight: no external deps; reuses stdlib json + logging.
- Gated by environment G6_DISABLE_STRUCT_EVENTS=1 to allow ops to silence volume quickly.

Event Types Implemented:
- instrument_prefilter_summary: prefilter coverage & rejection stats before deep filtering.
- option_match_stats: post-match summary (strike & leg distribution) per expiry.
- zero_data: already emitted inline today; kept helper for future consolidation.
- cycle_status_summary: final per-index aggregated status (OK/PARTIAL/EMPTY) + expiry statuses.
- strike_depth_adjustment: adaptive expansion of strikes_itm/otm after low coverage detection.
 - prefilter_clamp: safety valve triggered when instrument list exceeds configured ceiling.

NOTE: zero_data kept minimal to preserve legacy parsing downstream; other events purposely richer.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

try:
    # Aggregation hooks (best-effort; ignore if module missing for any reason)
    from .cycle_tables import (
        emit_cycle_tables,
        record_adaptive,
        record_option_stats,
        record_prefilter,
        record_strike_adjust,
    )  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    # Explicit light-weight no-op fallbacks ensure safe removal of cycle_tables module.
    record_prefilter = lambda *a, **k: None  # type: ignore
    record_option_stats = lambda *a, **k: None  # type: ignore
    record_strike_adjust = lambda *a, **k: None  # type: ignore
    record_adaptive = lambda *a, **k: None  # type: ignore
    emit_cycle_tables = lambda *a, **k: None  # type: ignore

logger = logging.getLogger(__name__)

_STRUCT_DISABLED = str.__call__( # trick to avoid global mutation if env read fails
    __import__('os').environ.get('G6_DISABLE_STRUCT_EVENTS','0').lower()
) in ('1','true','yes','on')

# Fine-grained suppression (comma/space separated list of event names)
_STRUCT_SUPPRESS: set[str] = set()
try:
    _raw_sup = os.environ.get('G6_STRUCT_EVENTS_SUPPRESS','')
    if _raw_sup:
        for _tok in _raw_sup.replace(',', ' ').split():
            if _tok:
                _STRUCT_SUPPRESS.add(_tok.strip())
except Exception:  # pragma: no cover
    pass

# Formatting mode: json (default existing behaviour), human (concise human readable), both
_STRUCT_FMT_MODE = os.environ.get('G6_STRUCT_EVENTS_FORMAT', 'json').strip().lower()
if _STRUCT_FMT_MODE not in {'json','human','both'}:
    _STRUCT_FMT_MODE = 'json'

_STRUCT_COMPACT = os.environ.get('G6_STRUCT_COMPACT','').lower() in {'1','true','yes','on'}

def _compact_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not _STRUCT_COMPACT:
        return payload
    try:
        p = dict(payload)
        # Truncate common list fields
        for key in ('sample','strike_list','contam_samples'):
            if key in p and isinstance(p[key], list):
                if len(p[key]) > 5:
                    p[key] = p[key][:5] + ['+%d' % (len(payload[key])-5,)]
        # Remove verbose keys rarely needed in compact mode
        drop_keys = {'rejects','contamination_samples','raw_instruments','raw_quotes'}
        for dk in drop_keys:
            if dk in p:
                del p[dk]
        return p
    except Exception:
        return payload

# Common safe json dumps
_def_dumps = lambda obj: json.dumps(obj, default=str, ensure_ascii=False, separators=(',', ':'))


def _human_line(event: str, payload: dict[str, Any]) -> str:
    try:
        if event == 'cycle_status_summary':
            totals = payload.get('expiry_status_totals') or {}
            ok = totals.get('ok',0); partial = totals.get('partial',0); empty = totals.get('empty',0); synth = totals.get('synth',0)
            dur = payload.get('duration_s')
            idx_cnt = payload.get('index_count')
            return f"STRUCT_H {event} idx={idx_cnt} ok={ok} partial={partial} empty={empty} synth={synth} dur={dur}s"
        if event == 'option_match_stats':
            rule = payload.get('rule'); idx = payload.get('index'); exp = payload.get('expiry')
            sc = payload.get('strike_count'); cov = payload.get('strike_cov'); fcv = payload.get('field_cov'); opts = payload.get('legs')
            return f"STRUCT_H {event} {idx} {rule} exp={exp} strikes={sc} legs={opts} strike_cov={cov} field_cov={fcv}"
        if event == 'instrument_prefilter_summary':
            idx = payload.get('index'); raw = payload.get('total_raw'); kept = payload.get('prefiltered'); cand = payload.get('option_candidates'); rej = (payload.get('rejects') or {}).get('prefilter_rejected',0)
            return f"STRUCT_H {event} {idx} raw={raw} kept={kept} cand={cand} rej={rej}"
    except Exception:
        pass
    # Fallback generic summarizer
    try:
        keys = list(payload.keys())[:6]
        summary = ' '.join(f"{k}={payload.get(k)}" for k in keys)
        return f"STRUCT_H {event} {summary}"
    except Exception:
        return f"STRUCT_H {event}"

def _emit(event: str, payload: dict[str, Any]) -> None:  # pragma: no cover (thin wrapper)
    if _STRUCT_DISABLED:
        return
    if event in _STRUCT_SUPPRESS:
        return
    try:
        if _STRUCT_FMT_MODE in {'json','both'}:
            logger.info("STRUCT %s | %s", event, _def_dumps(_compact_payload(event, payload)))
        if _STRUCT_FMT_MODE in {'human','both'}:
            try:
                logger.info(_human_line(event, payload))
            except Exception:
                logger.debug("human_struct_emit_failed %s", event, exc_info=True)
    except Exception:
        try:
            logger.debug("Failed STRUCT %s", event, exc_info=True)
        except Exception:
            pass

# ---------------------- Event Specific Emitters ----------------------

def emit_instrument_prefilter_summary(
    *,
    index: str,
    expiry: str,
    rule: str,
    total_raw: int,
    prefiltered: int,
    option_candidates: int,
    ce: int,
    pe: int,
    rejects: dict[str, int],
    latency_ms: float | None = None,
    contamination: bool | None = None,
    contamination_samples: list[str] | None = None,
) -> None:
    payload = {
        'index': index,
        'expiry': expiry,
        'rule': rule,
        'ts': int(time.time()),
        'total_raw': total_raw,
        'prefiltered': prefiltered,
        'option_candidates': option_candidates,
        'ce': ce,
        'pe': pe,
        'rejects': rejects or {},
    }
    if latency_ms is not None:
        payload['latency_ms'] = round(latency_ms,2)
    if contamination is not None:
        payload['contamination'] = bool(contamination)
    if contamination_samples:
        payload['contam_samples'] = contamination_samples[:8]
    _emit('instrument_prefilter_summary', payload)
    try:
        record_prefilter(payload)
    except Exception:
        pass


def emit_option_match_stats(
    *,
    index: str,
    expiry: str,
    rule: str,
    strike_count: int,
    legs: int,
    ce_legs: int,
    pe_legs: int,
    strike_min: float | None,
    strike_max: float | None,
    step: float | None,
    sample: list[float] | list[str],
    ce_per_strike: float | None,
    pe_per_strike: float | None,
    synthetic: bool,
    strike_coverage: float | None = None,
    field_coverage: float | None = None,
    partial_reason: str | None = None,
) -> None:
    payload = {
        'index': index,
        'expiry': expiry,
        'rule': rule,
        'strike_count': strike_count,
        'legs': legs,
        'ce': ce_legs,
        'pe': pe_legs,
        'strike_min': strike_min,
        'strike_max': strike_max,
        'step': step,
        'sample': sample[:8] if isinstance(sample, list) else sample,
        'ce_per_strike': round(ce_per_strike, 3) if isinstance(ce_per_strike,(int,float)) else None,
        'pe_per_strike': round(pe_per_strike, 3) if isinstance(pe_per_strike,(int,float)) else None,
        'synthetic': bool(synthetic),
    }
    if strike_coverage is not None:
        payload['strike_cov'] = round(strike_coverage,3)
    if field_coverage is not None:
        payload['field_cov'] = round(field_coverage,3)
    if partial_reason:
        payload['partial_reason'] = partial_reason
    # FINNIFTY strike sample normalization (log-time only): keep multiples of 100 for readability
    try:
        if (payload.get('index') or '').upper() == 'FINNIFTY':
            sample = payload.get('sample') or []
            if isinstance(sample, list):
                filt = [s for s in sample if isinstance(s,(int,float)) and (int(round(float(s))) % 100 == 0)]
                if filt:
                    payload['sample'] = filt[:8]
    except Exception:
        pass
    _emit('option_match_stats', payload)
    try:
        record_option_stats(payload)
    except Exception:
        pass


def emit_zero_data(
    *,
    index: str,
    expiry: str,
    rule: str,
    atm: float | int | None,
    strike_count: int,
) -> None:
    payload = {
        'index': index,
        'expiry': expiry,
        'rule': rule,
        'atm': atm,
        'strike_count': strike_count,
        'ts': int(time.time()),
        'event': 'zero_data_expiry',
    }
    _emit('zero_data', payload)


def _compute_reason_totals(indices: list[dict[str, Any]]) -> dict[str,int]:
    counts = {'low_strike':0,'low_field':0,'low_both':0,'unknown':0}
    for idx in indices:
        for exp in idx.get('expiries', []) or []:
            if (exp.get('status') or '').upper() == 'PARTIAL':
                reason = exp.get('partial_reason') or 'unknown'
                if reason not in counts:
                    reason = 'unknown'
                counts[reason] += 1
    return counts


def emit_cycle_status_summary(
    *,
    cycle_ts: int,
    duration_s: float,
    indices: list[dict[str, Any]],
    index_count: int,
    include_reason_totals: bool = True,
) -> None:
    # Produce aggregated counts
    ok = partial = empty = synth = 0
    for idx in indices:
        for exp in idx.get('expiries', []) or []:
            st = (exp.get('status') or '').upper()
            if st == 'OK':
                ok += 1
            elif st == 'PARTIAL':
                partial += 1
            elif st == 'EMPTY':
                empty += 1
            # SYNTH status removed (synthetic fallback feature deprecated)
    reason_totals = _compute_reason_totals(indices) if include_reason_totals else None
    payload: dict[str, Any] = {
        'cycle_ts': cycle_ts,
        'duration_s': round(duration_s,2),
        'index_count': index_count,
    'expiry_status_totals': {'ok': ok,'partial': partial,'empty': empty},
        'indices': [
            {
                'index': i.get('index'),
                'status': i.get('status'),
                'expiries': [
                    {
                        'rule': e.get('rule'),
                        'status': e.get('status'),
                        'strike_cov': e.get('strike_coverage'),
                        'field_cov': e.get('field_coverage'),
                        'options': e.get('options'),
                        # synthetic flag removed
                        'partial_reason': e.get('partial_reason'),
                    }
                    for e in i.get('expiries', []) or []
                ],
            }
            for i in indices
        ],
    }
    if reason_totals:
        payload['partial_reason_totals'] = reason_totals
    _emit('cycle_status_summary', payload)
    try:  # best-effort table emission at cycle end
        emit_cycle_tables(payload)
    except Exception:
        pass


def emit_strike_depth_adjustment(
    *,
    index: str,
    reason: str,
    prev_itm: int,
    prev_otm: int,
    new_itm: int,
    new_otm: int,
    strike_coverage: float | None = None,
    field_coverage: float | None = None,
    expiry_rule: str | None = None,
    min_threshold: float | None = None,
    ts: int | None = None,
) -> None:
    """Emit event describing adaptive strike depth expansion.

    reason: short token (e.g., 'low_strike_cov', 'low_field_cov').
    Thresholds included for observability of policy decisions.
    """
    payload = {
        'index': index,
        'reason': reason,
        'prev_itm': prev_itm,
        'prev_otm': prev_otm,
        'new_itm': new_itm,
        'new_otm': new_otm,
        'ts': ts or int(time.time()),
    }
    if strike_coverage is not None:
        payload['strike_cov'] = round(strike_coverage,3)
    if field_coverage is not None:
        payload['field_cov'] = round(field_coverage,3)
    if expiry_rule:
        payload['rule'] = expiry_rule
    if min_threshold is not None:
        payload['threshold'] = min_threshold
    _emit('strike_depth_adjustment', payload)
    try:
        record_strike_adjust(payload)
    except Exception:
        pass

def emit_prefilter_clamp(
    *,
    index: str,
    expiry: str,
    rule: str,
    original_count: int,
    kept_count: int,
    dropped_count: int,
    max_allowed: int,
    strategy: str = 'head',
    disabled: bool | None = None,
    strict: bool | None = None,
    ts: int | None = None,
) -> None:
    """Emit event when prefilter safety clamp trims excessive instrument list.

    strategy: sampling approach used (e.g., 'head', 'head_tail').
    disabled: indicates clamp logic globally disabled (emitted only if still somehow triggered).
    strict: whether strict mode (downgrade status) was active.
    """
    payload = {
        'index': index,
        'expiry': expiry,
        'rule': rule,
        'original': original_count,
        'kept': kept_count,
        'dropped': dropped_count,
        'max_allowed': max_allowed,
        'strategy': strategy,
        'ts': ts or int(time.time()),
    }
    if disabled is not None:
        payload['disabled'] = bool(disabled)
    if strict is not None:
        payload['strict'] = bool(strict)
    _emit('prefilter_clamp', payload)

__all__ = [
    'emit_instrument_prefilter_summary',
    'emit_option_match_stats',
    'emit_zero_data',
    'emit_cycle_status_summary',
    'emit_strike_depth_adjustment',
    'emit_prefilter_clamp',
    '_compute_reason_totals',  # exported for tests
]
