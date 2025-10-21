#!/usr/bin/env python3
"""Experimental expiry collection pipeline (Phase Skeleton).

Activated via env flag: G6_COLLECTOR_PIPELINE_V2=1

Current scope:
- Defines ExpiryState dataclass capturing minimal fields needed for parity diff.
- Provides Phase protocol and simple phase implementations delegating to existing process_expiry
  for now (acts as a wrapper) so we can measure and diff without changing behavior.
- Future phases will incrementally inline logic from legacy expiry_processor into separate
  functions registered in PHASES.

Shadow / Migration Strategy:
- When flag enabled, `process_expiry_v2` runs and returns a structure mimicking legacy output.
- Diff logic (optional TODO) can compare core counts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.observability.log_emitter import log_event

logger = logging.getLogger(__name__)  # retained for non-schema internal traces / exceptions

@dataclass
class ExpiryState:
    index_symbol: str
    expiry_rule: str
    atm_strike: float
    legacy_outcome: dict | None = None  # capture legacy outcome until phases ported
    # Placeholder for eventual granular fields
    instruments: int = 0
    options: int = 0  # pre-legacy enrichment option count (raw enriched size)
    errors: list[str] = field(default_factory=list)
    # Newly tracked early phase artifacts
    expiry_date: Any | None = None  # resolved by ResolvePhase
    strikes: list[float] = field(default_factory=list)
    fetched_instruments: list[dict] = field(default_factory=list)
    # Enrichment artifacts (pipeline-owned)
    enriched_data: dict[str, Any] = field(default_factory=dict)  # raw enriched quotes pre-validation
    validated_enriched: dict[str, Any] = field(default_factory=dict)  # post preventive validation cleaned quotes
    preventive_report: dict[str, Any] = field(default_factory=dict)
    validation_options: int = 0  # count after preventive validation
    # Clamp metadata persistence (added for parity in direct finalize)
    clamp_applied: bool = False
    clamp_original_instruments: int = 0
    clamp_dropped: int = 0
    clamp_max_allowed: int = 0
    clamp_strict_mode: bool = False

class Phase(Protocol):  # pragma: no cover - structural only
    name: str
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState: ...

class LegacyWrapperPhase:
    name = 'legacy_wrapper'
    def __init__(self, legacy_fn: Any):
        self._legacy: Any = legacy_fn
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Feature flag: allow direct finalize from validated_enriched to avoid re-processing legacy path
        use_direct = False
        try:
            use_direct = (
                os.environ.get('G6_COLLECTOR_PIPELINE_USE_ENRICHED','').lower() in {'1','true','yes','on'} and
                os.environ.get('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE','').lower() in {'1','true','yes','on'}
            )
        except Exception:
            use_direct = False
        # Defensive trace for decision (debug level to avoid noise in production by default)
        try:
            log_event(
                "expiry.finalize.decision",
                index=state.index_symbol,
                rule=state.expiry_rule,
                use_direct=use_direct,
                validated_present=bool(state.validated_enriched),
                expiry_date_present=state.expiry_date is not None,
                fetched=len(state.fetched_instruments or []),
                clamp_applied=state.clamp_applied,
            )
        except Exception:
            pass
        if use_direct and state.validated_enriched and state.expiry_date is not None:
            try:
                from src.collectors.modules.expiry_finalize import finalize_from_enriched
                out = finalize_from_enriched(
                    ctx,
                    index_symbol=state.index_symbol,
                    expiry_rule=state.expiry_rule,
                    expiry_date=state.expiry_date,
                    atm_strike=state.atm_strike,
                    enriched_data=state.validated_enriched,
                    strikes=state.strikes,
                    per_index_ts=ctx.per_index_ts,
                    index_price=getattr(ctx, 'index_price', 0.0),
                    index_ohlc=getattr(ctx, 'index_ohlc', {}),
                    allowed_expiry_dates=getattr(ctx, 'allowed_expiry_dates', set()),
                    concise_mode=getattr(ctx, 'concise_mode', False),
                    metrics=getattr(ctx, 'metrics', None),
                    collector_settings=getattr(ctx, 'collector_settings', None),
                    legacy_classifiers=None,
                    instruments_count=len(state.fetched_instruments or []),
                    clamp_sentinal={
                        'prefilter_clamped': state.clamp_applied,
                        'prefilter_original_instruments': state.clamp_original_instruments,
                        'prefilter_dropped': state.clamp_dropped,
                        'prefilter_max_allowed': state.clamp_max_allowed,
                        'prefilter_strict_mode': state.clamp_strict_mode,
                    } if state.clamp_applied else None,
                )
                state.legacy_outcome = out
                # Synthetic fallback propagation removed
                try:
                    rec = out.get('expiry_rec') if isinstance(out, dict) else None
                    if rec:
                        state.instruments = int(rec.get('instruments', 0) or 0)
                        state.options = int(rec.get('options', 0) or out.get('option_count', 0) or 0)
                except Exception:
                    pass
                return state
            except Exception:
                log_event(
                    "expiry.finalize.fail",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    reason="from_enriched_fallback",
                )
        else:
            # Log why direct path not taken (only if direct flags enabled partially or prerequisites missing)
            try:
                if os.environ.get('G6_COLLECTOR_PIPELINE_USE_ENRICHED','') or os.environ.get('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE',''):
                    log_event(
                        "expiry.finalize.skipped",
                        index=state.index_symbol,
                        rule=state.expiry_rule,
                        reason='flags_disabled' if not use_direct else 'missing_validated_or_expiry_date',
                    )
            except Exception:
                pass
        # Fallback to full legacy processing
        try:
            # Ensure per_index_ts present (legacy expects timestamp); fallback to start_ts or now
            if not hasattr(ctx, 'per_index_ts'):
                try:
                    import datetime
                    ts_fallback = getattr(ctx, 'start_ts', datetime.datetime.now(datetime.UTC))
                    ctx.per_index_ts = ts_fallback
                except Exception:
                    pass
            # Ensure aggregation_state present for legacy metrics aggregation
            if not hasattr(ctx, 'aggregation_state') or ctx.aggregation_state is None:
                try:
                    from src.collectors.unified_collectors import AggregationState
                    ctx.aggregation_state = AggregationState()
                except Exception:
                    class _AggStub:  # minimal stub
                        representative_day_width = 0
                        snapshot_base_time = None
                        def capture(self, *_a: object, **_k: object) -> None: return None
                    ctx.aggregation_state = _AggStub()
            out = self._legacy(
                ctx=ctx,
                index_symbol=state.index_symbol,
                expiry_rule=state.expiry_rule,
                atm_strike=state.atm_strike,
                concise_mode=getattr(ctx, 'concise_mode', False),
                precomputed_strikes=getattr(ctx, 'precomputed_strikes', []),
                expiry_universe_map=getattr(ctx, 'expiry_universe_map', None),
                allow_per_option_metrics=getattr(ctx, 'allow_per_option_metrics', True),
                local_compute_greeks=getattr(ctx, 'local_compute_greeks', False),
                local_estimate_iv=getattr(ctx, 'local_estimate_iv', False),
                greeks_calculator=getattr(ctx, 'greeks_calculator', None),
                risk_free_rate=getattr(ctx, 'risk_free_rate', 0.05),
                per_index_ts=ctx.per_index_ts,
                index_price=getattr(ctx, 'index_price', 0.0),
                index_ohlc=getattr(ctx, 'index_ohlc', {}),
                metrics=getattr(ctx, 'metrics', None),
                mem_flags=getattr(ctx, 'mem_flags', {}),
                dq_checker=getattr(ctx, 'dq_checker', None),
                dq_enabled=getattr(ctx, 'dq_enabled', False),
                snapshots_accum=getattr(ctx, 'snapshots_accum', []),
                build_snapshots=getattr(ctx, 'build_snapshots', False),
                allowed_expiry_dates=getattr(ctx, 'allowed_expiry_dates', set()),
                pcr_snapshot=getattr(ctx, 'pcr_snapshot', {}),
                aggregation_state=ctx.aggregation_state,
                collector_settings=getattr(ctx, 'collector_settings', None),
            )
            state.legacy_outcome = out
            try:
                rec = out.get('expiry_rec') if isinstance(out, dict) else None
                if rec:
                    state.instruments = int(rec.get('instruments', 0) or 0)
                    state.options = int(rec.get('options', 0) or out.get('option_count', 0) or 0)
                    # Synthetic fallback propagation removed
            except Exception:
                pass
        except Exception as e:
            state.errors.append(str(e))
        # Diagnostic: if legacy_outcome still None or lacks expiry_rec, emit debug with accumulated errors
        if state.legacy_outcome is None or not isinstance(state.legacy_outcome, dict) or 'expiry_rec' not in state.legacy_outcome:
            try:
                log_event(
                    "expiry.legacy_wrapper.fail",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    errors='|'.join(state.errors) if state.errors else None,
                    fetched=len(state.fetched_instruments or []),
                    enriched=len(state.enriched_data or {}),
                    validated=len(state.validated_enriched or {}),
                )
            except Exception:
                pass
        return state

PHASES: list[Phase] = []  # later phases appended dynamically for v2 work

class ResolvePhase:
    name = 'resolve'
    def __init__(self) -> None:
        pass
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        try:
            from src.collectors.modules.expiry_helpers import resolve_expiry as _resolve_expiry
            expiry_date = _resolve_expiry(state.index_symbol, state.expiry_rule, ctx.providers, getattr(ctx, 'metrics', None), getattr(ctx, 'concise_mode', False))
            state.expiry_date = expiry_date
            # Strikes are precomputed in existing flow; capture if available
            state.strikes = list(getattr(ctx, 'precomputed_strikes', []))
        except Exception as e:
            state.errors.append(f"resolve:{e}")
        return state

class FetchPhase:
    name = 'fetch'
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Skip if resolve failed
        if state.expiry_date is None or not state.strikes:
            try:
                log_event(
                    "expiry.fetch.skipped",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    expiry_date=state.expiry_date,
                    strikes=len(state.strikes or []),
                )
            except Exception:
                pass
            return state
        try:
            from src.collectors.modules.expiry_helpers import fetch_option_instruments as _fetch
            if getattr(ctx, 'expiry_universe_map', None) and state.expiry_date in ctx.expiry_universe_map:
                bucket = ctx.expiry_universe_map[state.expiry_date]
                strike_set = set(state.strikes)
                instruments = [inst for inst in bucket if inst.get('strike') in strike_set]
            else:
                instruments = _fetch(state.index_symbol, state.expiry_rule, state.expiry_date, state.strikes, ctx.providers, getattr(ctx, 'metrics', None))
            state.fetched_instruments = instruments or []
            try:
                log_event(
                    "expiry.fetch.ok",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    fetched=len(state.fetched_instruments or []),
                    strikes=len(state.strikes or []),
                )
            except Exception:
                pass
        except Exception as e:
            state.errors.append(f"fetch:{e}")
        return state

class EnrichPhase:
    name = 'enrich'
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Preconditions: need fetched instruments
        if not state.fetched_instruments or state.expiry_date is None or not state.strikes:
            return state
        try:
            from src.collectors.modules.expiry_helpers import enrich_quotes as _enrich
            enriched = _enrich(state.index_symbol, state.expiry_rule, state.expiry_date, state.fetched_instruments, ctx.providers, getattr(ctx, 'metrics', None))
            # Normalize & capture for downstream validation phase
            if isinstance(enriched, list):
                try:
                    tmp_map: dict[str, dict[str, Any]] = {}
                    for idx, i in enumerate(enriched):
                        if isinstance(i, dict):
                            key = str(i.get('symbol') or i.get('tradingsymbol') or idx)
                            tmp_map[key] = i  # value is a dict[str, Any]
                    enriched = tmp_map
                except Exception:
                    enriched = {}
            if isinstance(enriched, dict):
                state.enriched_data = enriched
                state.options = len(enriched)
        except Exception as e:
            state.errors.append(f"enrich:{e}")
        return state

class PrefilterClampPhase:
    name = 'prefilter_clamp'
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Preconditions: instruments fetched
        if not state.fetched_instruments:
            return state
        try:
            from src.collectors.modules.prefilter_flow import run_prefilter_clamp
            inst_before = len(state.fetched_instruments)
            instruments, clamp_meta = run_prefilter_clamp(state.index_symbol, state.expiry_rule, state.expiry_date, state.fetched_instruments)
            state.fetched_instruments = instruments or []
            if clamp_meta:
                try:
                    orig_cnt, dropped_cnt, max_allowed, strict_mode = clamp_meta
                    state.clamp_applied = True
                    state.clamp_original_instruments = orig_cnt
                    state.clamp_dropped = dropped_cnt
                    state.clamp_max_allowed = max_allowed
                    state.clamp_strict_mode = bool(strict_mode)
                except Exception:
                    logger.debug('prefilter_clamp_meta_capture_failed', exc_info=True)
            try:
                log_event(
                    "expiry.prefilter.applied",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    instruments_before=inst_before,
                    instruments_after=len(state.fetched_instruments or []),
                    clamped=state.clamp_applied,
                    dropped=state.clamp_dropped if state.clamp_applied else None,
                )
            except Exception:
                pass
        except Exception as e:
            state.errors.append(f"prefilter_clamp:{e}")
        return state

class ValidationPhase:
    name = 'validate'
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Preconditions: need enriched data & instruments
        if not state.enriched_data or not state.fetched_instruments or state.expiry_date is None:
            return state
        try:
            from src.collectors.modules.preventive_validate import run_preventive_validation
            cleaned, report = run_preventive_validation(
                state.index_symbol,
                state.expiry_rule,
                state.expiry_date,
                state.fetched_instruments,
                state.enriched_data,
                getattr(ctx, 'index_price', None),
            )
            if isinstance(cleaned, dict):
                state.validated_enriched = cleaned
                state.validation_options = len(cleaned)
            if isinstance(report, dict):
                state.preventive_report = report
        except Exception as e:
            state.errors.append(f"validate:{e}")
        return state


class CoverageMetricsPhase:
    name = 'coverage_metrics'
    def run(self, ctx: Any, settings: Any, state: ExpiryState) -> ExpiryState:
        # Preconditions: have instruments & possibly enriched (or validated) data
        if state.expiry_date is None or not state.fetched_instruments:
            return state
        try:
            from src.collectors.modules.coverage_eval import coverage_metrics as _cov
            from src.collectors.modules.coverage_eval import field_coverage_metrics as _field_cov
            strike_cov = None
            field_cov = None
            try:
                strike_cov = _cov(ctx, state.fetched_instruments, state.strikes, state.index_symbol, state.expiry_rule, state.expiry_date)  # expects numeric coverage
            except Exception:
                try:
                    log_event("expiry.coverage.fail", component="strike", index=state.index_symbol, rule=state.expiry_rule)
                except Exception:
                    pass
            try:
                # prefer validated_enriched else enriched_data
                data_map = state.validated_enriched or state.enriched_data
                field_cov = _field_cov(ctx, data_map, state.index_symbol, state.expiry_rule, state.expiry_date)
            except Exception:
                try:
                    log_event("expiry.coverage.fail", component="field", index=state.index_symbol, rule=state.expiry_rule)
                except Exception:
                    pass
            # Stash into preventive_report under a dedicated key to avoid expanding dataclass
            try:
                if 'coverage' not in state.preventive_report:
                    state.preventive_report['coverage'] = {}
                if strike_cov is not None:
                    state.preventive_report['coverage']['strike_coverage'] = strike_cov
                if field_cov is not None:
                    state.preventive_report['coverage']['field_coverage'] = field_cov
            except Exception:
                pass
        except Exception as e:
            state.errors.append(f'coverage_metrics:{e}')
        return state

def _build_phases(legacy_fn: Any) -> list[Phase]:
    if not PHASES:  # initialize once
        # Early phases first; legacy wrapper still executes full legacy path for parity.
        PHASES.extend([
            ResolvePhase(),
            FetchPhase(),
            PrefilterClampPhase(),
            EnrichPhase(),
            ValidationPhase(),
            CoverageMetricsPhase(),
            LegacyWrapperPhase(legacy_fn),
        ])
    return PHASES

def process_expiry_v2(legacy_fn: Any, *, ctx: Any, index_symbol: str, expiry_rule: str, atm_strike: float, settings: Any | None = None) -> dict[str, Any]:
    phases = _build_phases(legacy_fn)
    state = ExpiryState(index_symbol=index_symbol, expiry_rule=expiry_rule, atm_strike=atm_strike)
    for phase in phases:
        state = phase.run(ctx, settings, state)
    # For now just return legacy outcome; future will assemble from state
    legacy = state.legacy_outcome or {'success': False, 'option_count': 0, 'expiry_rec': {'rule': expiry_rule, 'failed': True}}
    # Optional diff logging
    try:
        if os.environ.get('G6_COLLECTOR_PIPELINE_DIFF','').lower() in {'1','true','yes','on'} and isinstance(legacy, dict):
            rec = legacy.get('expiry_rec') or {}
            diffs: list[str] = []
            # expiry_date
            legacy_exp = rec.get('expiry_date')
            if state.expiry_date is not None and str(state.expiry_date) != str(legacy_exp):
                diffs.append(f"expiry_date pipeline={state.expiry_date} legacy={legacy_exp}")
            # instruments count
            legacy_inst = rec.get('instruments')
            if state.fetched_instruments and isinstance(legacy_inst, (int,float)) and len(state.fetched_instruments) != int(legacy_inst):
                diffs.append(f"instruments pipeline={len(state.fetched_instruments)} legacy={legacy_inst}")
            # pre-validation option count snapshot (state.options set in EnrichPhase) vs legacy options
            legacy_opts = rec.get('options', legacy.get('option_count'))
            if state.options and isinstance(legacy_opts, (int,float)) and state.options != int(legacy_opts):
                diffs.append(f"options_enriched pipeline={state.options} legacy={legacy_opts}")
            # post-validation option count snapshot (validation_options)
            if state.validation_options and isinstance(legacy_opts, (int,float)) and state.validation_options != int(legacy_opts):
                diffs.append(f"options_validated pipeline={state.validation_options} legacy={legacy_opts}")
            # preventive validation report issues (compact)
            issues = state.preventive_report.get('issues') if isinstance(state.preventive_report, dict) else None
            if issues:
                try:
                    if isinstance(issues, (list, tuple, set)):
                        diffs.append("preventive_issues=" + ','.join(list(issues)[:5]))
                except Exception:
                    pass
            # synthetic fallback indicator removed
            # direct finalize marker
            try:
                if rec.get('pipeline_direct_finalize'):
                    diffs.append('pipeline_direct_finalize=1')
            except Exception:
                pass
            if diffs:
                log_event(
                    "expiry.pipeline.diff",
                    index=state.index_symbol,
                    rule=state.expiry_rule,
                    atm=state.atm_strike,
                    diffs=';'.join(diffs),
                    phases=','.join(p.name for p in phases),
                )
    except Exception:
            log_event("expiry.pipeline.diff_fail", index=state.index_symbol, rule=state.expiry_rule)
    # Emit accumulated errors for diagnostics when any exist
    try:
        if state.errors:
            log_event("expiry.pipeline.errors", index=state.index_symbol, rule=state.expiry_rule, errors='|'.join(state.errors))
    except Exception:
        pass
    return legacy


def pipeline_enabled() -> bool:
    return os.environ.get('G6_COLLECTOR_PIPELINE_V2','').lower() in {'1','true','yes','on'}

__all__ = [
    'ExpiryState',
    'Phase',
    'process_expiry_v2',
    'pipeline_enabled',
]
