"""Per-expiry processing module.

Extracted from `unified_collectors._process_expiry` to reduce monolith size while
preserving behavior. The original function in `unified_collectors` now acts as a
thin delegator. This module purposely performs imports *inside* the function
body for helpers that still live in the legacy file to avoid hard circular
imports during module initialization.

Parity Philosophy: Logic is copied verbatim with only structural adjustments:
- Helper functions (`_resolve_expiry`, `_fetch_option_instruments`, `_enrich_quotes`,
  `_synthetic_metric_pop`) are imported lazily from `src.collectors.unified_collectors`.
- External helper modules imported as previously (try/except guarded) to keep
  failure semantics identical.

Return contract identical to legacy: dict with keys: success(bool), option_count(int on success),
expiry_rec(dict), human_row(optional tuple), plus any intermediate flags.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import os, datetime, logging

# Phase 0 settings integration (safe import; tolerates absence if path changes later)
try:  # pragma: no cover - import guard
    # Correct module path: collectors.settings (was mistakenly collector.settings)
    from src.collectors.settings import CollectorSettings  # type: ignore
except Exception:  # pragma: no cover
    class CollectorSettings:  # type: ignore
        pass

def get_collector_settings(force_reload: bool = False):  # pragma: no cover - lightweight cache helper
    """Lazy singleton loader for CollectorSettings.

    Maintains backward compatibility with earlier refactor draft that imported
    get_collector_settings from a settings module. If CollectorSettings lacks
    a load() (fallback stub), returns None. Swallows all exceptions.
    """
    try:
        cache_name = '_CACHED_COLLECTOR_SETTINGS'
        if force_reload or cache_name not in globals():
            settings_obj = None
            try:
                if hasattr(CollectorSettings, 'load'):
                    settings_obj = CollectorSettings.load()  # type: ignore[attr-defined]
            except Exception:
                settings_obj = None
            globals()[cache_name] = settings_obj
        return globals().get(cache_name)
    except Exception:
        return None

from src.utils.exceptions import (
    ResolveExpiryError,
    NoInstrumentsError,
    NoQuotesError,
)
from src.error_handling import handle_collector_error

logger = logging.getLogger(__name__)

def _coerce_mapping(obj):  # pragma: no cover
    try:
        if not isinstance(obj, dict):
            obj = dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}
    out = {}
    for k,v in list(obj.items()):
        try:
            sk = str(k)
        except Exception:
            continue
        out[sk] = v
    return out

def apply_basic_filters(
    enriched_data: Dict[str, Dict[str, Any]] | Dict[str, Any] | None,
    settings: Any,
    index_symbol: str,
    expiry_rule: str,
    logger: logging.Logger,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Apply basic volume / OI / percentile filters using CollectorSettings.

    Behavior preserved relative to legacy inline logic. Returns (filtered_data, meta).
    Meta keys: before, after, min_volume, min_oi, volume_percentile, applied(bool), pct_cutoff(optional).
    Swallows all exceptions and returns original data on failure.
    """
    meta: Dict[str, Any] = {
        'before': len(enriched_data or {}) if enriched_data else 0,
        'after': len(enriched_data or {}) if enriched_data else 0,
        'min_volume': 0,
        'min_oi': 0,
        'volume_percentile': 0.0,
        'applied': False,
    }
    if not isinstance(enriched_data, dict) or not settings:
        return (enriched_data or {}), meta
    try:
        min_vol = int(getattr(settings, 'min_volume', 0) or 0)
    except Exception:
        min_vol = 0
    try:
        min_oi = int(getattr(settings, 'min_oi', 0) or 0)
    except Exception:
        min_oi = 0
    try:
        vol_pct = float(getattr(settings, 'volume_percentile', 0.0) or 0.0)
    except Exception:
        vol_pct = 0.0
    meta.update({'min_volume': min_vol, 'min_oi': min_oi, 'volume_percentile': vol_pct})
    # Safe local mutable reference; guarantee dict after guard above
    data: Dict[str, Dict[str, Any]] = {k: v for k, v in enriched_data.items()}  # shallow copy
    try:
        if (min_vol > 0 or min_oi > 0) and data:
            pre_cnt = len(data)
            data = {k: v for k, v in data.items() if isinstance(v, dict) and int(v.get('volume', 0) or 0) >= min_vol and int(v.get('oi', 0) or 0) >= min_oi}
            logger.debug('enhanced_filters_basic_applied index=%s rule=%s before=%d after=%d min_vol=%d min_oi=%d', index_symbol, expiry_rule, pre_cnt, len(data), min_vol, min_oi)
            meta['applied'] = True
        if vol_pct > 0 and data and len(data) > 10:
            vols = []
            for v in data.values():
                if isinstance(v, dict):
                    try:
                        vols.append(int(v.get('volume', 0) or 0))
                    except Exception:
                        continue
            vols.sort()
            if vols:
                try:
                    cutoff = vols[int(len(vols) * vol_pct)]
                except Exception:
                    cutoff = vols[-1]
                pre_cnt2 = len(data)
                data = {k: v for k, v in data.items() if isinstance(v, dict) and int(v.get('volume', 0) or 0) >= cutoff}
                logger.debug('enhanced_filters_percentile index=%s rule=%s before=%d after=%d pct=%.3f cutoff=%d', index_symbol, expiry_rule, pre_cnt2, len(data), vol_pct, cutoff)
                meta['applied'] = True
                meta['pct_cutoff'] = cutoff
    except Exception:
        logger.debug('apply_basic_filters_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)
        return (enriched_data, meta)
    meta['after'] = len(data)
    return data, meta


def process_expiry(
    *,
    ctx,
    index_symbol: str,
    expiry_rule: str,
    atm_strike: float,
    concise_mode: bool,
    precomputed_strikes: List[float],
    expiry_universe_map: Optional[Dict[Any, Any]],
    allow_per_option_metrics: bool,
    local_compute_greeks: bool,
    local_estimate_iv: bool,
    greeks_calculator: Any,
    risk_free_rate: float,
    per_index_ts: datetime.datetime,
    index_price: float,
    index_ohlc: Dict[str, Any],
    metrics: Any,
    mem_flags: Dict[str, Any],
    dq_checker: Any,
    dq_enabled: bool,
    snapshots_accum: List[Any],
    build_snapshots: bool,
    allowed_expiry_dates: set,
    pcr_snapshot: Dict[str, Any],
    aggregation_state: Any,
    collector_settings=None,  # new optional settings object (CollectorSettings); falls back to env parsing if None
    # Accept and ignore additional legacy or refactor-era keyword arguments to preserve
    # backward compatibility with older test invocations (e.g. refactor_debug, parity flags).
    **legacy_kwargs: Any,
) -> Dict[str, Any]:
    # Lazy & resilient imports to avoid circular dependency and tolerate removed optional modules.
    try:
        from src.collectors.unified_collectors import _trace  # retain trace wrapper for consistency
    except Exception:  # pragma: no cover
        def _trace(*args, **ctx):  # type: ignore
            try:
                logging.getLogger(__name__).debug("trace_fallback args=%s ctx=%s", args, ctx)
            except Exception:
                pass
    # Core helpers (must succeed) – if these fail, we allow exception to bubble to caller fallback.
    from src.collectors.modules.expiry_helpers import (
        resolve_expiry as _resolve_expiry,
        fetch_option_instruments as _fetch_option_instruments,
        enrich_quotes as _enrich_quotes,
    )
    try:
        from src.collectors.modules.coverage_eval import (  # type: ignore
            coverage_metrics as _cov_metrics_raw,  # type: ignore
            field_coverage_metrics as _field_cov_metrics_raw,  # type: ignore
        )
        def _coverage_metrics(ctx,*a,**k):  # type: ignore
            val = _cov_metrics_raw(ctx,*a,**k)
            try:
                return float(val) if val is not None else 0.0
            except Exception:
                return 0.0
        def _field_coverage_metrics(ctx,*a,**k):  # type: ignore
            val = _field_cov_metrics_raw(ctx,*a,**k)
            try:
                return float(val) if val is not None else 0.0
            except Exception:
                return 0.0
    except Exception:  # pragma: no cover
        def _coverage_metrics(*_a, **_k):  # type: ignore
            return 0.0  # strike coverage ratio fallback
        def _field_coverage_metrics(*_a, **_k):  # type: ignore
            return 0.0  # field coverage ratio fallback
        logger.debug('coverage_eval_import_failed (tolerated)')
    # Synthetic fallback & classification removed (2025-10-08 aggressive cleanup)
    def _classify_expiry_result(*_a, **_k):  # type: ignore  # legacy stub
        return 'OK'
    try:
        from src.collectors.helpers.status_reducer import compute_expiry_status as _compute_expiry_status  # type: ignore
    except Exception:  # pragma: no cover
        def _compute_expiry_status(_rec):  # type: ignore
            return 'empty'
        logger.debug('status_reducer_import_failed (using fallback compute_expiry_status)')
    # Data quality bridge (optional)
    try:
        from src.collectors.modules.data_quality_bridge import (  # type: ignore
            run_option_quality as _run_option_quality,
            run_expiry_consistency as _run_expiry_consistency,
        )
    except Exception:  # pragma: no cover
        def _run_option_quality(*_a, **_k):  # type: ignore
            return ({}, [])
        def _run_expiry_consistency(*_a, **_k):  # type: ignore
            return []
        logger.debug('data_quality_bridge_import_failed (DQ disabled)')
    # Start trace marker for observability
    try:
        _trace('expiry_process_start', index=index_symbol, rule=expiry_rule)
    except Exception:
        pass
    outcome: Dict[str, Any] = {'success': False}
    # Pre-create a minimal expiry_rec so exception paths before instrument fetch still return structure
    expiry_rec = {
        'rule': expiry_rule,
        'expiry_date': None,
        'strikes_requested': len(precomputed_strikes or []),
        'instruments': 0,
        'options': 0,
        'failed': True,
        'pcr': None,
    # synthetic_fallback flag removed
    }
    try:
        enriched_data = None  # type: ignore[assignment]
        prevent_report = None  # type: ignore[assignment]
        clamp_meta = None
        with ctx.time_phase('resolve_expiry'):
            expiry_date = _resolve_expiry(index_symbol, expiry_rule, ctx.providers, metrics, concise_mode)
            try:
                _trace('resolve_expiry', index=index_symbol, rule=expiry_rule, expiry=str(expiry_date))
            except Exception:
                pass
        strikes = precomputed_strikes
        if not strikes:
            raise NoInstrumentsError(f"Failed to build strike list for {index_symbol}; atm={atm_strike}")
        if not concise_mode:
            logger.info(f"Collecting {len(strikes)} strikes for {index_symbol} {expiry_rule}: {strikes}")
        else:
            logger.debug(f"Collecting {len(strikes)} strikes for {index_symbol} {expiry_rule}")
        with ctx.time_phase('fetch_instruments'):
            if expiry_universe_map is not None and expiry_date in expiry_universe_map:
                bucket = expiry_universe_map.get(expiry_date, [])
                strike_set = set(precomputed_strikes)
                instruments = [inst for inst in bucket if inst.get('strike') in strike_set]
                try:
                    _trace('fetch_instruments_expiry_map', index=index_symbol, rule=expiry_rule, count=len(instruments), bucket=len(bucket))
                except Exception:
                    pass
            else:
                instruments = _fetch_option_instruments(index_symbol, expiry_rule, expiry_date, strikes, ctx.providers, metrics)
                try:
                    _trace('fetch_instruments', index=index_symbol, rule=expiry_rule, count=len(instruments))
                except Exception:
                    pass
        try:
            logger.debug('expiry_stage_counts index=%s rule=%s stage=post_fetch instruments=%d strikes=%d', index_symbol, expiry_rule, len(instruments or []), len(strikes or []))
        except Exception:
            pass
        try:
            if instruments:
                from src.collectors.modules.prefilter_flow import run_prefilter_clamp  # type: ignore
                instruments, clamp_meta = run_prefilter_clamp(index_symbol, expiry_rule, expiry_date, instruments)
            else:
                clamp_meta = None
        except Exception:
            logger.debug('prefilter_clamp_logic_failed', exc_info=True); clamp_meta = None
        # Fill real values now that we have instruments
        expiry_rec.update({
            'expiry_date': str(expiry_date),
            'strikes_requested': len(strikes),
            'instruments': len(instruments),
            'failed': False,
        })
        if not instruments:
            # Phase 10 reliability: deduplicate noisy no-instruments warnings per cycle
            suppress = False  # define early for static analysis
            try:
                dedup_key = f"{index_symbol}|{expiry_rule}|{expiry_date}"
                if hasattr(ctx, 'no_instruments_dedup'):
                    if dedup_key in ctx.no_instruments_dedup:  # type: ignore[attr-defined]
                        suppress = True
                    else:
                        try:
                            ctx.no_instruments_dedup.add(dedup_key)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                if not suppress:
                    logger.warning(f"No option instruments found for {index_symbol} expiry {expiry_date}")
                else:
                    logger.debug(f"suppressed_no_instruments_warning key={dedup_key}")
            except Exception:
                logger.warning(f"No option instruments found for {index_symbol} expiry {expiry_date}")
            try:
                from math import isnan
                atm_val = atm_strike if isinstance(atm_strike,(int,float)) and not (isinstance(atm_strike,float) and isnan(atm_strike)) else None
                from src.collectors.unified_collectors import _emit_zero_data_struct
                _emit_zero_data_struct(index=index_symbol, expiry=str(expiry_date), rule=expiry_rule, atm=atm_val, strike_count=len(strikes))
            except Exception:
                logger.debug('zero_data_struct_emit_failed', exc_info=True)
            if not suppress:  # only escalate to error bridge the first time per cycle
                try:
                    from src.collectors.modules.error_bridge import report_no_instruments  # type: ignore
                    report_no_instruments(index_symbol, expiry_rule, expiry_date, strikes, NoInstrumentsError)
                except Exception:
                    handle_collector_error(NoInstrumentsError(f"No instruments for {index_symbol} expiry {expiry_date} (rule: {expiry_rule}) with strikes={strikes}"), component='collectors.expiry_processor', index_name=index_symbol, context={'stage':'get_option_instruments','rule':expiry_rule,'expiry':str(expiry_date),'strikes':strikes},)
            outcome['expiry_rec']=expiry_rec
            try:
                # Augment expiry_rec with provider error classification for downstream outage analytics
                expiry_rec.setdefault('provider_error', True)
                expiry_rec.setdefault('provider_reason', 'no_instruments')
            except Exception:
                pass
            return outcome
        with ctx.time_phase('enrich_quotes'):
            enriched_data = _enrich_quotes(index_symbol, expiry_rule, expiry_date, instruments, ctx.providers, metrics)
            try:
                _trace('enrich_quotes', index=index_symbol, rule=expiry_rule, enriched=len(enriched_data))
            except Exception:
                pass
        try:
            logger.debug('expiry_stage_counts index=%s rule=%s stage=post_enrich enriched=%d instruments=%d', index_symbol, expiry_rule, len(enriched_data or {}), len(instruments or []))
        except Exception:
            pass

        # Enforced mapping type for downstream logic
        if not isinstance(enriched_data, dict):  # fallback normalization already attempted above for list
            try:
                enriched_data = dict(enriched_data)  # type: ignore[arg-type]
            except Exception:
                enriched_data = {}
        # Defensive: ensure string keys
        # No further normalization; static type checker inconsistencies tolerated via ignores where needed.

        # ------------------------------------------------------------------
        # Phase 0: Basic filters now centralized via CollectorSettings.
        # Backward compatibility: if caller didn't supply settings, lazily hydrate singleton.
        # ------------------------------------------------------------------
        if collector_settings is None:
            try:
                collector_settings = get_collector_settings()
            except Exception:
                collector_settings = None
        # Apply centralized basic filters (volume / OI / percentile) – behavior parity with legacy inline logic.
        # NOTE: Intentionally AFTER normalization and before DQ so DQ runs on filtered universe (unchanged from legacy order).
        enriched_data, _filter_meta = apply_basic_filters(enriched_data or {}, collector_settings, index_symbol, expiry_rule, logger)
        if dq_checker and dq_enabled and enriched_data:
            try:
                from src.collectors.modules.data_quality_flow import apply_data_quality  # type: ignore
                apply_data_quality(
                    dq_checker,
                    dq_enabled,
                    enriched_data,
                    index_symbol=index_symbol,
                    expiry_rule=expiry_rule,
                    index_price=index_price,
                    expiry_rec=expiry_rec,
                    run_option_quality=_run_option_quality,
                    run_expiry_consistency=_run_expiry_consistency,
                )
            except Exception:
                logger.debug('dq_flow_apply_failed', exc_info=True)
        # Synthetic metric pop removed
        try:
            if 'clamp_meta' in locals() and clamp_meta:
                orig_cnt, dropped_cnt, max_allowed, strict_mode = clamp_meta
                expiry_rec['prefilter_clamped'] = True
                expiry_rec['prefilter_original_instruments'] = orig_cnt
                expiry_rec['prefilter_dropped'] = dropped_cnt
                expiry_rec['prefilter_max_allowed'] = max_allowed
                if strict_mode:
                    expiry_rec.setdefault('partial_reason','prefilter_clamp')
        except Exception:
            logger.debug('prefilter_clamp_expiry_rec_augment_failed', exc_info=True)
        # Normalize enriched_data to dict; some provider enrich paths might return list
        if isinstance(enriched_data, list):  # rare path
            try:
                enriched_data = {str(i.get('symbol') or i.get('tradingsymbol') or idx): i for idx,i in enumerate(enriched_data) if isinstance(i, dict)}  # type: ignore
            except Exception:
                enriched_data = {}
        # Final type normalization for static typing & downstream helpers: ensure mapping[str]->dict
        try:
            if isinstance(enriched_data, dict):
                enriched_data = {str(k): v for k, v in enriched_data.items() if isinstance(v, dict)}  # type: ignore[assignment]
            else:
                enriched_data = {}
        except Exception:
            enriched_data = {}
        # Synthetic fallback branch removed – if no enriched_data remains empty.
        # Preserve original enriched snapshot for potential salvage of foreign_expiry-only drops
        _orig_enriched_snapshot = dict(enriched_data) if enriched_data else {}
        with ctx.time_phase('preventive_validate'):
            try:
                from src.collectors.modules.preventive_validate import run_preventive_validation  # type: ignore
                cleaned_data, prevent_report = run_preventive_validation(index_symbol, expiry_rule, expiry_date, instruments, enriched_data, index_price)
            except Exception:
                logger.debug('preventive_validation_module_failed', exc_info=True); prevent_report={'error':True}; cleaned_data=enriched_data
            if not prevent_report.get('ok', True):
                logger.warning(f"Preventive validation flagged issues for {index_symbol} {expiry_rule}: issues={prevent_report.get('issues')} dropped={prevent_report.get('dropped_count')} kept={prevent_report.get('post_enriched_count')}")
            else:
                logger.debug(f"Preventive validation ok {index_symbol} {expiry_rule} kept={prevent_report.get('post_enriched_count')} dropped={prevent_report.get('dropped_count')}")
            enriched_data = cleaned_data
        # Phase 1 shadow pipeline (resolve, fetch, prefilter, enrich) parity check
        try:
            if collector_settings is not None and getattr(collector_settings, 'pipeline_v2_flag', False):
                legacy_snapshot = {
                    'expiry_date': expiry_date,
                    'strike_count': len(strikes or []),
                    'strikes': list(strikes or []),
                    'instrument_count': len(instruments or []),
                    'enriched_keys': len(enriched_data or {}),
                }
                from src.collectors.pipeline.shadow import run_shadow_pipeline  # type: ignore
                run_shadow_pipeline(
                    ctx,
                    collector_settings,
                    index=index_symbol,
                    rule=expiry_rule,
                    precomputed_strikes=strikes or [],
                    legacy_snapshot=legacy_snapshot,
                )
        except Exception:
            logger.debug('expiry.shadow.invoke_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)
        try:
            logger.debug('expiry_stage_counts index=%s rule=%s stage=post_validate remaining=%d', index_symbol, expiry_rule, len(enriched_data or {}))
        except Exception:
            pass
        # ------------------------------------------------------------------
        # Foreign expiry salvage (optional): If all rows were dropped solely due to
        # foreign_expiry / insufficient_strike_coverage, we can attempt a salvage by
        # rewriting the detected single distinct expiry present in original data to
        # the resolved_expiry and proceed. Controlled by G6_FOREIGN_EXPIRY_SALVAGE=1.
        # ------------------------------------------------------------------
        salvage_flag = False
        try:
            if collector_settings is not None:
                salvage_flag = bool(getattr(collector_settings, 'foreign_expiry_salvage', False) or getattr(collector_settings, 'salvage_enabled', False))
            else:
                from src.utils.env_flags import is_truthy_env  # type: ignore
                salvage_flag = is_truthy_env('G6_FOREIGN_EXPIRY_SALVAGE')
        except Exception:
            salvage_flag = False
        # Salvage / rehydrate logic (Option A): always attempt parity-preserving rehydrate on pure foreign expiry drop.
        # A20: RecoveryStrategy integration (flag gated)
        try:
            if collector_settings is not None and hasattr(collector_settings, 'recovery_strategy_legacy'):
                use_recovery_strategy = bool(getattr(collector_settings, 'recovery_strategy_legacy'))
            else:
                from src.utils.env_flags import is_truthy_env  # type: ignore
                use_recovery_strategy = is_truthy_env('G6_RECOVERY_STRATEGY_LEGACY')
        except Exception:
            from src.utils.env_flags import is_truthy_env  # type: ignore
            use_recovery_strategy = is_truthy_env('G6_RECOVERY_STRATEGY_LEGACY')
        recovery_invoked = False
        if (not enriched_data and _orig_enriched_snapshot):
            issues = []
            try:
                if isinstance(prevent_report, dict):
                    cand = prevent_report.get('issues', [])
                    if isinstance(cand, (list, tuple, set)):
                        issues = list(cand)
            except Exception:
                issues = []
            salvage_only = False
            if issues:
                try:
                    salvage_only = all(i in ('foreign_expiry','insufficient_strike_coverage') for i in issues) and any(i=='foreign_expiry' for i in issues)
                except Exception:
                    salvage_only = False
            if salvage_only:
                if use_recovery_strategy:
                    try:
                        from src.collectors.pipeline.recovery import DefaultRecoveryStrategy  # type: ignore
                        strat = DefaultRecoveryStrategy()
                        # Build a minimal shim state-like object exposing meta/issues if needed in future
                        class _StateShim:
                            def __init__(self, issues_list):
                                self.meta = {'issues': issues_list}
                        _shim = _StateShim(issues)
                        # Currently attempt_salvage just checks meta; we call it for parity of side-effects
                        strat.attempt_salvage(ctx=None, settings=collector_settings, state=_shim)
                        recovery_invoked = True
                    except Exception:
                        logger.debug('recovery_strategy_invoke_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)
                distinct_foreign: set = set()
                for _sym, _row in _orig_enriched_snapshot.items():
                    raw_exp = _row.get('expiry') or _row.get('expiry_date') or _row.get('instrument_expiry')
                    if raw_exp:
                        import datetime as _dt
                        if isinstance(raw_exp, _dt.datetime):
                            distinct_foreign.add(raw_exp.date())
                        elif isinstance(raw_exp, _dt.date):
                            distinct_foreign.add(raw_exp)
                        else:
                            try:
                                distinct_foreign.add(_dt.date.fromisoformat(str(raw_exp)))
                            except Exception:
                                continue
                if len(distinct_foreign) <= 3:  # accept small distinct set
                    if salvage_flag:
                        for _sym, _row in _orig_enriched_snapshot.items():
                            _row['expiry'] = expiry_date
                        enriched_data = _orig_enriched_snapshot
                        logger.warning('foreign_expiry_salvage_applied index=%s rule=%s salvage_count=%d distinct_foreign=%s', index_symbol, expiry_rule, len(enriched_data), list(distinct_foreign)[:3])
                    else:
                        logger.debug('foreign_expiry_salvage_disabled index=%s rule=%s distinct_count=%d recovery_invoked=%s', index_symbol, expiry_rule, len(distinct_foreign), recovery_invoked)
                else:
                    logger.debug('foreign_expiry_salvage_skipped index=%s rule=%s distinct_count=%d recovery_invoked=%s', index_symbol, expiry_rule, len(distinct_foreign), recovery_invoked)
        with ctx.time_phase('coverage_metrics'):
            strike_cov = _coverage_metrics(ctx, instruments, strikes, index_symbol, expiry_rule, expiry_date)  # type: ignore[misc]
        with ctx.time_phase('field_coverage_metrics'):
            field_cov = _field_coverage_metrics(ctx, enriched_data, index_symbol, expiry_rule, expiry_date)  # type: ignore[misc]
        # Empty quotes diagnostics: if field coverage is 0 or None and options >0 instruments present
        try:
            if (field_cov is None or field_cov == 0) and enriched_data:
                # Determine if every enriched quote lacks core fields (volume, oi, avg_price)
                missing_all = True
                for _sym,_row in enriched_data.items():
                    if any(k in _row for k in ('volume','oi','avg_price')):
                        missing_all = False
                        break
                if missing_all:
                    logger.warning(
                        'empty_quote_fields index=%s rule=%s expiry=%s instruments=%d',
                        index_symbol, expiry_rule, expiry_date, len(enriched_data or {}),
                    )
                    if metrics:
                        try:
                            from src.metrics.adapter import MetricsAdapter  # type: ignore
                            MetricsAdapter(metrics).record_empty_quote_fields(index_symbol, expiry_rule)
                        except Exception:
                            logger.debug('empty_quote_metric_adapter_failed', exc_info=True)
        except Exception:
            logger.debug('empty_quote_diagnostics_failed', exc_info=True)
        with ctx.time_phase('iv_estimation'):
            try:
                from src.collectors.modules.iv_estimation import run_iv_estimation  # type: ignore
                run_iv_estimation(ctx, enriched_data, index_symbol, expiry_rule, expiry_date, index_price, greeks_calculator, local_estimate_iv, risk_free_rate, None, None, None, None)
            except Exception:
                logger.debug('iv_estimation_module_failed', exc_info=True)
        with ctx.time_phase('greeks_compute'):
            try:
                from src.collectors.modules.greeks_compute import run_greeks_compute  # type: ignore
                run_greeks_compute(ctx, enriched_data, index_symbol, expiry_rule, expiry_date, per_index_ts, greeks_calculator, risk_free_rate, local_compute_greeks, allow_per_option_metrics, None, mem_flags)
            except Exception:
                logger.debug('greeks_compute_module_failed', exc_info=True)
        collection_time = per_index_ts
        from src.collectors.cycle_context import ExpiryContext
        expiry_ctx = ExpiryContext(index_symbol=index_symbol, expiry_rule=expiry_rule, expiry_date=expiry_date, collection_time=collection_time, index_price=index_price, risk_free_rate=risk_free_rate, allow_per_option_metrics=allow_per_option_metrics, compute_greeks=local_compute_greeks)
        with ctx.time_phase('persist_and_metrics'):
            try:
                from src.collectors.modules.persist_flow import run_persist_flow  # type: ignore
                persist_result = run_persist_flow(
                    ctx,
                    enriched_data,
                    expiry_ctx,
                    index_ohlc,
                    allowed_expiry_dates,
                    _trace,
                    concise_mode,
                )
            except Exception:
                logger.debug('persist_flow_module_failed', exc_info=True)
                try:
                    from src.collectors.helpers.persist import persist_with_context  # fallback
                    persist_result = persist_with_context(ctx, enriched_data, expiry_ctx, index_ohlc)
                    _trace('persist_done', index=index_symbol, rule=expiry_rule, options=persist_result.option_count, failed=persist_result.failed)
                except Exception:
                    from dataclasses import dataclass
                    @dataclass
                    class _PersistFailSurrogate:  # local minimal substitute
                        option_count: int = 0
                        pcr: any = None  # type: ignore
                        metrics_payload: any = None  # type: ignore
                        failed: bool = True
                    persist_result = _PersistFailSurrogate()
        if persist_result.failed:
            outcome['expiry_rec']=expiry_rec
            return outcome
        pcr_val = persist_result.pcr; metrics_payload = persist_result.metrics_payload
        try:
            expiry_rec['options'] = len(enriched_data); expiry_rec['pcr']=pcr_val
        except Exception:
            pass
        _classify_expiry_result(expiry_rec, enriched_data)
        if strike_cov is not None: expiry_rec['strike_coverage']=strike_cov
        if field_cov is not None: expiry_rec['field_coverage']=field_cov
        expiry_rec['status'] = _compute_expiry_status(expiry_rec)
        # refactor_debug parity accumulation removed
        try:
            if metrics_payload:
                pcr_snapshot[metrics_payload['expiry_code']] = metrics_payload['pcr']
                aggregation_state.capture(metrics_payload)
        except Exception as agg_e:
            logger.debug(f'Aggregation capture failed for {index_symbol} {expiry_rule}: {agg_e}')
        if not concise_mode:
            logger.info(f"Successfully collected {len(enriched_data)} options for {index_symbol} {expiry_rule}")
        else:
            logger.debug(f"Collected {len(enriched_data)} options for {index_symbol} {expiry_rule}")
        try:
            if precomputed_strikes:
                diffs_tmp = [b-a for a,b in zip(precomputed_strikes, precomputed_strikes[1:]) if b>a]
                step_val = min(diffs_tmp) if diffs_tmp else None
            else:
                step_val = None
            try:
                from src.collectors.modules.status_finalize_core import finalize_expiry  # type: ignore
                int_strikes: List[int] = []
                for s in (precomputed_strikes or []):
                    try:
                        int_strikes.append(int(s))
                    except Exception:
                        continue
                finalize_expiry(expiry_rec, enriched_data, int_strikes, index_symbol, expiry_date, expiry_rule, metrics)
            except Exception:
                logger.debug('status_finalize_expiry_failed', exc_info=True)
        except Exception:
            logger.debug('option_match_stats_emit_failed', exc_info=True)
        try:
            from src.collectors.modules.adaptive_adjust import adaptive_post_expiry as _adaptive_post_expiry
            _adaptive_post_expiry(ctx, index_symbol, expiry_rec, expiry_rule)
        except Exception:
            logger.debug('adaptive_adjust_module_failed', exc_info=True)
        # Enhanced collector parity: optional domain model mapping before snapshot build.
        if collector_settings is not None:
            _domain_models_enabled = bool(getattr(collector_settings, 'domain_models', False))
        else:
            from src.utils.env_flags import is_truthy_env  # type: ignore
            _domain_models_enabled = is_truthy_env('G6_DOMAIN_MODELS')
        if _domain_models_enabled and enriched_data and build_snapshots:
            try:
                from src.domain.models import OptionQuote  # type: ignore
                mapped_cnt = 0
                for k, q in list(enriched_data.items()):  # iteration copy; mapping side-effects not persisted
                    try:
                        OptionQuote.from_raw(k, q)
                        mapped_cnt += 1
                    except Exception:
                        continue
                logger.debug('domain_models_mapped index=%s rule=%s count=%d', index_symbol, expiry_rule, mapped_cnt)
            except Exception:
                logger.debug('domain_models_mapping_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)

        if build_snapshots:
            try:
                from src.collectors.modules.snapshots import build_expiry_snapshot  # type: ignore
                snap_obj = build_expiry_snapshot(index_symbol, expiry_rule, expiry_date, atm_strike, enriched_data, per_index_ts)
                if snap_obj is not None:
                    snapshots_accum.append(snap_obj)
            except Exception:
                logger.debug('snapshot_build_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)
        if concise_mode:
            try:
                from src.collectors.modules.formatters import format_concise_expiry_row  # type: ignore
                outcome['human_row'] = format_concise_expiry_row(
                    per_index_ts=per_index_ts,
                    index_price=index_price,
                    atm_strike=atm_strike,
                    expiry_date=expiry_date,
                    expiry_rule=expiry_rule,
                    enriched_data=enriched_data,
                    strikes=strikes,
                )
            except Exception:
                logger.debug('concise_row_format_failed index=%s rule=%s', index_symbol, expiry_rule, exc_info=True)
        outcome['success']=True
        outcome['option_count']=len(enriched_data)
        outcome['expiry_rec']=expiry_rec
    except Exception as e:
        logger.error(f"Error collecting data for {index_symbol} {expiry_rule}: {e}")
        _trace('expiry_error', index=index_symbol, rule=expiry_rule, error=str(e))
        try:
            expiry_rec['failed']=True
            outcome['expiry_rec']=expiry_rec
        except Exception:
            pass
        if metrics:
            try:
                metrics.collection_errors.labels(index=index_symbol, error_type='expiry_collection').inc(); metrics.total_errors.inc(); metrics.data_errors.inc()
            except Exception:
                logger.debug('Failed to increment collection errors metric')
    return outcome

__all__ = ["process_expiry"]
