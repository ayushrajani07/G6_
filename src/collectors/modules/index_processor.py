"""Index Processing Module (extracted from unified_collectors).

Provides `process_index` which encapsulates the legacy per-index workflow.
To avoid circular imports it receives a `deps` mapping supplying required
helper callables / flags originating from `unified_collectors`:

Expected deps keys:
  TRACE_ENABLED: bool
  trace: callable(msg:str, **ctx)
  AggregationState: class
  build_strikes: callable(atm, itm, otm, index, scale=None) -> List[float]
  synth_index_price: callable(index, index_price, atm) -> (index_price, atm, used_synth)
  aggregate_cycle_status: callable(expiry_details) -> str
  process_expiry: callable(... same signature as original _process_expiry ...)
  run_index_quality: callable(dq_checker, index_price, index_ohlc)

All original semantics retained. Any failure inside this module is logged and
an empty result structure (all None / zeros) is returned; this allows callers
to fallback / continue the wider cycle without hard stopping.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from typing import (
    Any,
    Protocol,
    TypedDict,
    TypeVar,
    cast,
    runtime_checkable,
)

from src.collectors.env_adapter import get_bool as _env_bool
from src.collectors.env_adapter import get_str as _env_str
from src.error_handling import handle_collector_error  # parity with legacy path
from src.utils.timeutils import utc_now

logger = logging.getLogger(__name__)


T = TypeVar("T")

class StrikeUniverseResult(TypedDict, total=False):
    strikes: list[float]
    meta: dict[str, Any]

class IndexProcessResult(TypedDict, total=False):
    human_block: str | None
    indices_struct_entry: dict[str, Any] | None
    summary_rows_entry: dict[str, Any] | None
    overall_legs: int
    overall_fails: int

ExpiryDetail = dict[str, Any]  # current dynamic; could be narrowed in later wave
DepsMap = dict[str, Any]

@runtime_checkable
class ProviderFacade(Protocol):  # minimal surface actually used
    def get_index_data(self, index: str) -> Any: ...  # (price, ohlc) pair expected
    def get_ltp(self, index: str) -> Any: ...
    def get_atm_strike(self, index: str) -> Any: ...
    def get_expiry_dates(self, index: str) -> Iterable[Any]: ...
    def get_option_instruments_universe(self, index: str) -> Iterable[dict[str, Any]]: ...

class TimePhaseCtx(Protocol):  # context manager factory
    def __call__(self, name: str) -> Any: ...

@runtime_checkable
class ContextLike(Protocol):
    providers: ProviderFacade
    def time_phase(self, name: str) -> Any: ...
    csv_sink: Any
    influx_sink: Any

class MetricsLike(Protocol):  # intentionally permissive
    def mark_api_call(self, *, success: bool, latency_ms: float) -> Any: ...
    # dynamic attributes (gauges/counters) added at runtime; kept as Any
    def __getattr__(self, name: str) -> Any: ...  # allow arbitrary metric attributes for typing
    # Allow setting arbitrary attributes (Prometheus metric objects) without mypy complaints
    def __setattr__(self, name: str, value: Any) -> None: ...  # noqa: D401

def _p(obj: Any, name: str, default: T) -> T:
    """Best-effort attribute/dict key accessor with fallback default.

    Anchors return type to the type of `default`. Returns `default` when attribute/key
    missing, value is None, or any exception occurs.
    """
    try:
        if isinstance(obj, dict):
            val: Any = obj.get(name, default)
        else:
            val = getattr(obj, name, default)
        if val is None:
            return default
        return cast(T, val)
    except Exception:
        return default

def process_index(
    ctx: ContextLike | Any,
    index_symbol: str,
    params: dict[str, Any] | Any,
    *,
    compute_greeks: bool,
    estimate_iv: bool,
    greeks_calculator: Any,
    mem_flags: dict[str, Any],
    concise_mode: bool,
    build_snapshots: bool,
    risk_free_rate: float,
    metrics: MetricsLike | Any,
    snapshots_accum: list[Any],
    dq_enabled: bool,
    dq_checker: Any,
    deps: DepsMap,
) -> IndexProcessResult:
    """Process a single index collection cycle.

    Parameters
    ----------
    ctx : ContextLike | Any
        Orchestrator context exposing providers & sinks.
    index_symbol : str
        Index name (e.g., NIFTY, BANKNIFTY).
    params : mapping/obj
        Per-index configuration (strikes, expiries, enable flag).
    compute_greeks / estimate_iv : bool
        Feature gates passed downstream.
    greeks_calculator : Any
        Calculator instance (protocol not yet stabilized).
    mem_flags : dict
        Memory/adaptive tuning flags.
    concise_mode : bool
        Reduces verbose logging when True.
    build_snapshots : bool
        Whether to build snapshot artifacts.
    risk_free_rate : float
        Risk free rate for greeks/IV.
    metrics : MetricsLike | Any
        Metrics registry; dynamic attributes created lazily.
    snapshots_accum : list
        Accumulator mutated with per-expiry or index snapshots downstream.
    dq_enabled / dq_checker : bool | Any
        Data quality gate control & checker facade.
    deps : DepsMap
        Dependency injection mapping for helper callables & flags.

    Returns
    -------
    IndexProcessResult
        Structure containing human-rendered block (optional), indices_struct_entry,
        summary row entry, and counters for legs/fails. Fields may be None when
        early exits occur.

    Notes
    -----
    - Never raises; on failure returns partially populated result.
    - Mutates provided metrics object and snapshots_accum list.
    - Strike universe selection prefers new strike_universe module with layered fallbacks.
    """
    result: IndexProcessResult = {
        'human_block': None,
        'indices_struct_entry': None,
        'summary_rows_entry': None,
        'overall_legs': 0,
        'overall_fails': 0,
    }
    # Test-only debug helper (env-guarded)
    def _truthy_env(name: str) -> bool:
        try:
            return _env_bool(name, False)
        except Exception:
            return False
    _test_debug = _truthy_env('G6_TEST_DEBUG')
    # Weekend mode short-circuit removed; rely solely on market_hours gating at higher level.
    TRACE_ENABLED = bool(deps.get('TRACE_ENABLED'))
    trace = deps.get('trace', lambda *_a, **_k: None)
    # AggregationState fallback: provide a lightweight stub so downstream code relying
    # on attributes (snapshot_base_time, representative_day_width) does not explode.
    AggregationState = deps.get('AggregationState')
    if AggregationState is None:  # create a minimal stub class
        class _AggregationStateStub:  # pragma: no cover - exercised only when dependency missing
            def __init__(self) -> None:
                self.snapshot_base_time: datetime.datetime | None = None
                self.representative_day_width: int | None = None
        AggregationState = _AggregationStateStub
    # Dependency injected helpers with safe fallbacks (no runtime semantic changes)
    build_strikes_fallback_any: Any = deps.get('build_strikes')
    if not callable(build_strikes_fallback_any):  # pragma: no cover
        def _build_strikes_fallback_default(*_a: Any, **_k: Any) -> list[float]:
            return []
        build_strikes_fallback_any = _build_strikes_fallback_default
    build_strikes_fallback = cast(Callable[..., list[float]], build_strikes_fallback_any)

    synth_index_price_any: Any = deps.get('synth_index_price')
    if not callable(synth_index_price_any):  # pragma: no cover
        def _synth_index_price_default(_i: str, p: int | float, a: int | float) -> tuple[int | float, int | float, bool]:
            return p, a, False
        synth_index_price_any = _synth_index_price_default
    synth_index_price = cast(Callable[[str, int | float, int | float], tuple[int | float, int | float, bool]], synth_index_price_any)

    aggregate_cycle_status_any: Any = deps.get('aggregate_cycle_status')
    if not callable(aggregate_cycle_status_any):  # pragma: no cover
        def _aggregate_cycle_status_default(_details: list[ExpiryDetail]) -> str:
            return 'bad'
        aggregate_cycle_status_any = _aggregate_cycle_status_default
    aggregate_cycle_status = cast(Callable[[list[ExpiryDetail]], str], aggregate_cycle_status_any)

    process_expiry_any: Any = deps.get('process_expiry')
    if not callable(process_expiry_any):  # pragma: no cover
        def _process_expiry_default(**_kw: Any) -> dict[str, Any]:
            return {}
        process_expiry_any = _process_expiry_default
    process_expiry = cast(Callable[..., dict[str, Any]], process_expiry_any)

    run_index_quality_any: Any = deps.get('run_index_quality')
    if not callable(run_index_quality_any):  # pragma: no cover
        def _run_index_quality_default(*_a: Any, **_k: Any) -> tuple[bool, list[str]]:
            return (True, [])
        run_index_quality_any = _run_index_quality_default
    run_index_quality = cast(Callable[[Any, Any, Any], tuple[bool, list[str]]], run_index_quality_any)

    # Skip disabled indices early
    if not _p(params, 'enable', True):
        return result

    if TRACE_ENABLED:
        try:
            extra = {}
            try:
                if isinstance(params, dict):
                    extra = {k: v for k, v in params.items() if k not in ('strikes_itm','strikes_otm','expiries','enable')}
            except Exception:
                extra = {}
            trace(
                "index_config",
                index=index_symbol,
                strikes_itm=_p(params,'strikes_itm', None),
                strikes_otm=_p(params,'strikes_otm', None),
                expiries=_p(params,'expiries', None),
                extra=extra,
            )
        except Exception:
            pass
    if not concise_mode:
        logger.info(f"Collecting data for {index_symbol}")
    else:
        logger.debug(f"Collecting data for {index_symbol}")
    per_index_start = time.time(); per_index_ts = utc_now()
    per_index_option_count = 0
    per_index_option_processing_seconds = 0.0
    per_index_success = True
    per_index_attempts = 0
    per_index_failures = 0
    index_price: int | float = 0
    index_ohlc: dict[str, Any] = {}
    _t0 = time.time()
    # Predefine variables to ensure they are always bound even if later phases fail early
    atm_strike: int | float = 0
    precomputed_strikes: list[float] = []
    allow_per_option_metrics: bool = False
    local_compute_greeks: bool = compute_greeks
    local_estimate_iv: bool = estimate_iv
    scale_factor: float | None = 1.0
    allowed_expiry_dates: set[Any] = set()
    pcr_snapshot: dict[str, Any] = {}
    aggregation_state = AggregationState()
    aggregation_state.snapshot_base_time = per_index_ts
    expected_expiries = _p(params,'expiries',['this_week'])
    # Human rows accumulate per-expiry display tuples: (t, price_disp, atm_disp, exp_str, tag, legs, ce_c, pe_c, pcr_v, rng_disp, step_v)
    human_rows: list[tuple[Any, ...]] = []
    try:
        providers = ctx.providers
        if hasattr(providers, 'get_index_data'):
            with ctx.time_phase('index_get_data'):
                index_price, index_ohlc = providers.get_index_data(index_symbol)  # runtime attr; providers facade protocol allows
            if metrics and hasattr(metrics, 'mark_api_call'):
                metrics.mark_api_call(success=True, latency_ms=(time.time()-_t0)*1000.0)
            trace("index_get_data", index=index_symbol, price=index_price, ohlc=index_ohlc)
        else:
            with ctx.time_phase('index_get_data_fallback'):
                if hasattr(providers, 'get_ltp'):
                    try:
                        index_price = providers.get_ltp(index_symbol)
                    except Exception:
                        index_price = 0
                index_ohlc = {}
            if metrics and hasattr(metrics, 'mark_api_call'):
                metrics.mark_api_call(success=bool(index_price), latency_ms=(time.time()-_t0)*1000.0)
            logger.debug(f"Providers facade missing get_index_data; used fallback path for {index_symbol} price={index_price}")
            trace("index_get_data_fallback", index=index_symbol, price=index_price)
    except Exception:
        if metrics and hasattr(metrics, 'mark_api_call'):
            metrics.mark_api_call(success=False, latency_ms=(time.time()-_t0)*1000.0)
        # continue with downstream logic using default index_price/ohlc (fail-soft)
    if dq_checker and dq_enabled and callable(run_index_quality):
        try:
            _ok_idx, _idx_issues = run_index_quality(dq_checker, index_price, index_ohlc)
            if _idx_issues:
                logger.debug(f"DQ index issues index={index_symbol} issues={_idx_issues}")
        except Exception:
            logger.debug('dq_index_evaluation_failed', exc_info=True)

    # Always fetch/derive ATM strike regardless of DQ settings
    _t0 = time.time()
    providers = ctx.providers
    try:
        atm_strike = providers.get_atm_strike(index_symbol)
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"get_atm_strike failed for {index_symbol}: {e}; falling back to get_ltp")
        try:
            atm_strike = providers.get_ltp(index_symbol)
        except (KeyError, ValueError, TypeError) as e2:  # pragma: no cover
            try:
                from src.collectors.modules.error_bridge import report_atm_fallback_error
                report_atm_fallback_error(e2, index_symbol)
            except Exception:
                handle_collector_error(e2, component="collectors.index_processor", index_name=index_symbol, context={"stage":"atm_strike","fallback":True})
            atm_strike = 0
    except Exception as e:  # final safety net
        logger.error(f"Unexpected ATM strike error {index_symbol}: {e}")
        atm_strike = 0
    if (not isinstance(atm_strike,(int,float))) or atm_strike <= 0:
        try:
            if isinstance(index_price,(int,float)) and index_price>0:
                try:
                    from src.utils.index_registry import get_index_meta  # local
                    _meta_step = float(get_index_meta(index_symbol).step)
                    if _meta_step <=0: _meta_step = 50.0 if index_symbol not in ("BANKNIFTY","SENSEX") else 100.0
                except Exception:
                    _meta_step = 50.0 if index_symbol not in ("BANKNIFTY","SENSEX") else 100.0
                atm_strike = round(float(index_price)/_meta_step)*_meta_step
                logger.debug(f"Derived ATM from index_price for {index_symbol} using step {_meta_step}: {atm_strike}")
        except Exception:
            pass
    if metrics and hasattr(metrics,'mark_api_call'):
        success_flag = isinstance(atm_strike,(int,float)) and atm_strike>0
        metrics.mark_api_call(success=success_flag, latency_ms=(time.time()-_t0)*1000.0)
    trace("atm_strike", index=index_symbol, atm=atm_strike)
    if not concise_mode: logger.info(f"{index_symbol} ATM strike: {atm_strike}")
    else: logger.debug(f"{index_symbol} ATM strike: {atm_strike}")
    # Normalize return typing from injected synthetic price function
    ip_val, atm_val, used_synth = synth_index_price(index_symbol, index_price, atm_strike)
    index_price = ip_val  # already numeric tuple contract
    atm_strike = atm_val
    if used_synth:
        trace("synthetic_index_price", index=index_symbol, price=index_price, atm=atm_strike, strategy=True)
    if not isinstance(atm_strike,(int,float)) or atm_strike <=0:
        per_index_success = False
        per_index_failures = len(_p(params,'expiries',['this_week']))
        per_index_attempts = per_index_failures
        reason = 'atm_zero'
        logger.warning(f"Skipping {index_symbol}: ATM strike invalid ({atm_strike}); marking expiries failed")
        if metrics and hasattr(metrics,'index_errors_total'):
            try: metrics.index_errors_total.labels(index=index_symbol, reason=reason).inc()
            except Exception: logger.debug('Failed to inc index_errors_total for atm_zero', exc_info=True)
        result['summary_rows_entry'] = {
            'index': index_symbol,
            'timestamp': per_index_ts,
            'price': index_price,
            'atm': atm_strike,
            'attempts': per_index_attempts,
            'failures': per_index_failures,
            'legs': 0,
            'status': 'bad',
            'error': reason,
            'age_s': 0,
        }
        return result

    # Provider diagnostics
    try:
        mode = 'unknown'; prov = getattr(ctx.providers, 'primary_provider', None)
        if prov is None: mode = 'fallback-providers'
        else:
            if getattr(prov,'_last_quotes_synthetic',False): mode='synthetic-quotes'
            elif getattr(prov,'_auth_failed',False): mode='auth-failed-synthetic'
            else: mode='real'
        logger.debug(f"INDEX_DIAG index={index_symbol} mode={mode} price={index_price} atm={atm_strike}")
    except Exception:
        logger.debug('Index diagnostics emission failed', exc_info=True)

    if metrics:
        try:
            metrics.index_price.labels(index=index_symbol).set(index_price)
            metrics.index_atm.labels(index=index_symbol).set(atm_strike)
        except Exception:
            logger.debug(f"Failed to update metrics for {index_symbol}")

    pcr_snapshot = {}
    aggregation_state = AggregationState()
    aggregation_state.snapshot_base_time = per_index_ts
    expected_expiries = _p(params,'expiries',['this_week'])
    effective_strikes_otm = _p(params,'strikes_otm',10); effective_strikes_itm = _p(params,'strikes_itm',10)
    from src.collectors.modules.memory_adjust import apply_memory_and_adaptive_scaling
    (
        effective_strikes_itm,
        effective_strikes_otm,
        allow_per_option_metrics,
        local_compute_greeks,
        local_estimate_iv,
        scale_factor,
    ) = apply_memory_and_adaptive_scaling(
        effective_strikes_itm,
        effective_strikes_otm,
        mem_flags,
        ctx,
        compute_greeks=compute_greeks,
        estimate_iv=estimate_iv,
    )

    # Reset per-expiry human rows after adaptive scaling stage
    human_rows = []  # reuse existing list (already typed)
    if scale_factor is None:
        scale_factor = 1.0
    # Phase 9: Prefer new strike_universe abstraction (policy + caching) with graceful fallback
    try:
        from src.collectors.modules.strike_universe import build_strike_universe
        su_result = build_strike_universe(
            atm_strike,
            effective_strikes_itm,
            effective_strikes_otm,
            index_symbol,
            scale=scale_factor,
        )
        precomputed_strikes = su_result.strikes
        _strike_meta = su_result.meta
    except Exception:
        try:
            # Fallback to earlier thin wrapper (Phase 3) if available
            from src.collectors.modules.strike_depth import compute_strike_universe as _compute_strike_universe
            precomputed_strikes, _strike_meta = _compute_strike_universe(
                atm_strike, effective_strikes_itm, effective_strikes_otm, index_symbol, scale=scale_factor,
            )
        except Exception:
            # Last resort legacy inline builder passed in via deps
            precomputed_strikes = build_strikes_fallback(
                atm_strike, effective_strikes_itm, effective_strikes_otm, index_symbol, scale=scale_factor,
            )
        trace('build_strikes', index=index_symbol, strikes=precomputed_strikes[:40], total=len(precomputed_strikes))
        if not precomputed_strikes: logger.warning(f"Precomputed strike list empty for {index_symbol}; atm={atm_strike}")
        else: logger.debug(f"Precomputed {len(precomputed_strikes)} strikes for {index_symbol}: {precomputed_strikes}")
    # Strike clustering diagnostics (best-effort)
    try:
        if precomputed_strikes and len(precomputed_strikes) >=3:
            enable_cluster = _env_bool('G6_STRIKE_CLUSTER', False) or TRACE_ENABLED
            if enable_cluster:
                diffs: list[float] = []; last: float | None = None
                for s in precomputed_strikes:
                    if last is not None: diffs.append(round(s-last,6))
                    last = s
                if diffs:
                    from statistics import mean, median
                    step_counts: dict[float,int] = {}
                    for d in diffs: step_counts[d]=step_counts.get(d,0)+1
                    unique_steps=sorted(step_counts.keys())
                    dominant_step=None
                    if step_counts: dominant_step = max(step_counts.items(), key=lambda kv: kv[1])[0]
                    anomalies=[step for step,cnt in step_counts.items() if cnt==1 and step!=dominant_step]
                    cluster_struct={
                        'index': index_symbol,
                        'atm': atm_strike,
                        'strikes': len(precomputed_strikes),
                        'unique_steps': len(unique_steps),
                        'steps': {str(k): v for k,v in step_counts.items()},
                        'min_step': min(unique_steps) if unique_steps else None,
                        'max_step': max(unique_steps) if unique_steps else None,
                        'mean_step': mean(diffs) if diffs else None,
                        'median_step': median(diffs) if diffs else None,
                        'dominant_step': dominant_step,
                        'anomaly_steps': anomalies,
                        'sample': precomputed_strikes[:10],
                    }
                    try:
                        from src.collectors.modules.struct_events_bridge import emit_strike_cluster
                        emit_strike_cluster(cluster_struct)
                    except Exception:
                        try:
                            import json as _json
                            logger.info('STRUCT strike_cluster | %s', _json.dumps(cluster_struct, default=str))
                        except Exception:
                            logger.debug('Failed to emit strike_cluster struct', exc_info=True)
    except Exception:
        logger.debug('Strike clustering diagnostics failed', exc_info=True)

    # Allowed expiries and adaptive summary should run regardless of strike_universe import outcome
    try:
        allowed_expiry_dates = set(ctx.providers.get_expiry_dates(index_symbol))
    except Exception:
        allowed_expiry_dates = set()
    try:
        from src.collectors.modules.adaptive_summary import emit_adaptive_summary
        emit_adaptive_summary(ctx, index_symbol)
    except Exception:
        logger.debug('adaptive_summary_module_failed', exc_info=True)
    expiry_details: list[ExpiryDetail] = []
    expiry_universe_map: dict[Any, Any] | None = None  # keys may be date objects
    # Initialize stale flags early to avoid unbound branches
    index_stale: bool = False
    stale_mode: str = 'mark'
    stale_field_thr: float = 0.0
    try:
        if not _env_bool('G6_DISABLE_EXPIRY_MAP', False):
            raw_universe_fetch = getattr(ctx.providers,'get_option_instruments_universe',None)
            if callable(raw_universe_fetch):
                _t_um = time.time(); universe = raw_universe_fetch(index_symbol)
                try:
                    # Ensure universe is iterable of dicts; if not, skip building.
                    if not isinstance(universe, Iterable):
                        raise TypeError('universe_not_iterable')
                except Exception:
                    universe = []
                from src.collectors.unified_collectors import _build_expiry_map  # local import (kept stable)
                try:
                    from typing import cast as _cast
                    expiry_universe_map_raw, map_stats = _build_expiry_map(universe)
                    expiry_universe_map = _cast(dict[Any, Any], expiry_universe_map_raw)
                    if TRACE_ENABLED:
                        trace('expiry_map_build', index=index_symbol, unique=len(expiry_universe_map) if expiry_universe_map else 0, stats=map_stats)
                    if metrics and hasattr(metrics,'expiry_map_build_seconds'):
                        try: metrics.expiry_map_build_seconds.labels(index=index_symbol).observe(time.time()-_t_um)
                        except Exception: pass
                except Exception:
                    logger.debug('Expiry map build inner failed', exc_info=True)
    except Exception:
        logger.debug('Expiry map build failed (non-fatal)', exc_info=True)

    # ------------------------------------------------------------------
    # Expiry Rules Resolution (with optional expansion)
    # ------------------------------------------------------------------
    raw_expiries_obj = _p(params,'expiries',['this_week']) or ['this_week']
    if isinstance(raw_expiries_obj, (list, tuple)):
        final_expiries: list[str] = [str(x) for x in raw_expiries_obj]
    else:
        final_expiries = [str(raw_expiries_obj)]
    try:
        expand_flag = _env_bool('G6_EXPIRY_EXPAND_CONFIG', False)
        if expand_flag and len(final_expiries) == 1:
            # Load config
            proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
            cfg_path = os.path.join(proj_root, 'config', 'g6_config.json')
            with open(cfg_path, encoding='utf-8') as _cf:
                _cfg = json.load(_cf)
            cfg_exp = (_cfg.get('indices', {}).get(index_symbol, {}) or {}).get('expiries')
            if isinstance(cfg_exp, list) and len(cfg_exp) > 1:
                # Only expand if config list actually contains more tags
                final_expiries = list(dict.fromkeys(cfg_exp))  # preserve order / dedupe
                try:
                    log_msg = f"expiry_expansion index={index_symbol} original={raw_expiries_obj} expanded={final_expiries}"
                    if concise_mode:
                        logger.debug(log_msg)
                    else:
                        logger.info(log_msg)
                except Exception:
                    pass
    except Exception:
        # Non-fatal; keep original list
        pass

    for expiry_rule in final_expiries:
        per_index_attempts += 1
        if _test_debug:
            try:
                print(f"[G6_TEST_DEBUG] stage=pre_expiry_call index={index_symbol} rule={expiry_rule} strikes={len(precomputed_strikes or [])}")
            except Exception:
                pass
        expiry_outcome = process_expiry(
            ctx=ctx,
            index_symbol=index_symbol,
            expiry_rule=expiry_rule,
            atm_strike=atm_strike,
            concise_mode=concise_mode,
            precomputed_strikes=precomputed_strikes,
            expiry_universe_map=expiry_universe_map,
            allow_per_option_metrics=allow_per_option_metrics,
            local_compute_greeks=local_compute_greeks,
            local_estimate_iv=local_estimate_iv,
            greeks_calculator=greeks_calculator,
            risk_free_rate=risk_free_rate,
            per_index_ts=per_index_ts,
            index_price=index_price,
            index_ohlc=index_ohlc,
            metrics=metrics,
            mem_flags=mem_flags,
            dq_checker=dq_checker,
            dq_enabled=dq_enabled,
            snapshots_accum=snapshots_accum,
            build_snapshots=build_snapshots,
            allowed_expiry_dates=allowed_expiry_dates,
            pcr_snapshot=pcr_snapshot,
            aggregation_state=aggregation_state,
        )
        if _test_debug:
            try:
                succ = bool(expiry_outcome.get('success'))
                oc = int(expiry_outcome.get('option_count') or 0)
                rec = expiry_outcome.get('expiry_rec') or {}
                inst = int(rec.get('instruments') or 0) if isinstance(rec, dict) else None
                print(f"[G6_TEST_DEBUG] stage=post_expiry_call index={index_symbol} rule={expiry_rule} success={succ} option_count={oc} instruments={inst}")
            except Exception:
                pass
        if expiry_outcome.get('success'):
            per_index_option_count += expiry_outcome.get('option_count',0)
        else:
            per_index_failures += 1
        if 'expiry_rec' in expiry_outcome:
            try:
                expiry_details.append(expiry_outcome['expiry_rec'])
            except Exception:
                pass
        hr = expiry_outcome.get('human_row')
        if hr and isinstance(hr, (list, tuple)):
            human_rows.append(tuple(hr))

    # ---------------- Stale Detection (pre snapshot writes) ----------------
    # A future system-wide stale decision is made in unified_collectors; here we tag per-index condition.
    # Index considered stale when every processed expiry has field_coverage present and <= threshold (or missing/0) while options >0 attempted.
    try:
        stale_mode = _env_str('G6_STALE_WRITE_MODE', 'mark').strip().lower()  # allow|mark|skip|abort (abort handled system-wide)
        field_thr_raw = _env_str('G6_STALE_FIELD_COV_THRESHOLD', '').strip()
        stale_field_thr = 0.0
        if field_thr_raw:
            try:
                stale_field_thr = max(0.0, min(1.0, float(field_thr_raw)))
            except Exception:
                stale_field_thr = 0.0
        # Build a simple view of field coverage across expiries.
        _expiry_field_cov = []
        for _exp in expiry_details:
            fc = _exp.get('field_coverage')
            try:
                fc_f = float(fc) if fc is not None else -1.0
            except Exception:
                fc_f = -1.0
            _expiry_field_cov.append(fc_f)
        index_stale = False
        if expiry_details:
            # Stale if all expiries have fc_f < 0 (missing) or <= threshold.
            if all(fc < 0 or fc <= stale_field_thr for fc in _expiry_field_cov):
                index_stale = True
        # Attach early flag (consumed later when building indices_struct_entry & human block)
        # Also precompute cycle_status for structured result: mark as STALE when stale regardless of write mode.
        # This ensures visibility even when we still perform writes in 'mark'/'abort' modes.
        cycle_status = 'STALE' if index_stale else None
    except Exception:
        index_stale = False
        stale_mode = 'mark'
        stale_field_thr = 0.0
        cycle_status = None

    # Emit stale metrics (per-index) before any potential snapshot gating
    if metrics:
        try:  # pragma: no cover - metrics side-effects
            from prometheus_client import Counter as _C
            from prometheus_client import Gauge as _G
            # Lazy metric creation (attributes cached on metrics registry object)
            if not hasattr(metrics, 'stale_cycles_total'):
                try:
                    metrics.stale_cycles_total = _C(
                        'g6_stale_cycles_total',
                        'Count of cycles where index or system classified stale',
                        ['index','mode'],
                    )
                except Exception:
                    pass
            if not hasattr(metrics, 'stale_active'):
                try:
                    metrics.stale_active = _G(
                        'g6_stale_active',
                        'Whether index stale in current cycle (1 stale, 0 ok)',
                        ['index'],
                    )
                except Exception:
                    pass
            # Update gauges & counters (best-effort)
            try:
                metrics.stale_active.labels(index=index_symbol).set(1 if index_stale else 0)
            except Exception:
                pass
            if index_stale:
                try:
                    metrics.stale_cycles_total.labels(index=index_symbol, mode=stale_mode).inc()
                except Exception:
                    pass
        except Exception:
            logger.debug('stale_metrics_update_failed', exc_info=True)

    # overview snapshot write (skip when stale_mode=skip and index_stale)
    if not (stale_mode == 'skip' and index_stale):
        try:
            from src.collectors.modules.aggregation_overview import emit_overview_aggregation
            representative_day_width, snapshot_base_time = emit_overview_aggregation(
                ctx,
                index_symbol,
                pcr_snapshot,
                aggregation_state,
                per_index_ts,
                expected_expiries,
            )
        except Exception:
            # aggregation_state.representative_day_width may be None; treat as Optional[int]
            representative_day_width = aggregation_state.representative_day_width  # type: ignore[assignment]
            snapshot_base_time = aggregation_state.snapshot_base_time or per_index_ts
            try:
                if pcr_snapshot:
                    ctx.csv_sink.write_overview_snapshot(index_symbol, pcr_snapshot, snapshot_base_time, representative_day_width, expected_expiries=expected_expiries)
                    if ctx.influx_sink:
                        try:
                            ctx.influx_sink.write_overview_snapshot(index_symbol, pcr_snapshot, snapshot_base_time, representative_day_width, expected_expiries=expected_expiries)
                        except Exception as ie:  # pragma: no cover
                            logger.debug(f"Influx overview snapshot failed for {index_symbol}: {ie}")
            except Exception as snap_e:  # pragma: no cover
                logger.error(f"Failed to write aggregated overview snapshot for {index_symbol}: {snap_e}")
    else:
        logger.warning(f"stale_write_skip index={index_symbol} mode=skip field_cov_thr={stale_field_thr}")
        if metrics:
            try:
                from src.collectors.modules.metrics_updater import update_per_index_metrics
                update_per_index_metrics(
                    metrics,
                    index_symbol=index_symbol,
                    per_index_start=per_index_start,
                    per_index_option_count=per_index_option_count,
                    per_index_option_processing_seconds=per_index_option_processing_seconds,
                    per_index_attempts=per_index_attempts,
                    per_index_failures=per_index_failures,
                    per_index_success=per_index_success,
                    atm_strike=atm_strike,
                )
            except Exception:
                try:
                    elapsed_index = time.time() - per_index_start
                    _ = elapsed_index
                    if per_index_option_count > 0:
                        metrics.index_options_processed.labels(index=index_symbol).set(per_index_option_count)
                        metrics.index_avg_processing_time.labels(index=index_symbol).set(per_index_option_processing_seconds / max(per_index_option_count,1))
                    else:
                        try: metrics.collection_errors.labels(index=index_symbol, error_type='no_options').inc()
                        except Exception: pass
                    metrics.index_last_collection_unixtime.labels(index=index_symbol).set(int(time.time()))
                    metrics.index_current_atm.labels(index=index_symbol).set(float(atm_strike))
                    try: metrics.mark_index_cycle(index=index_symbol, attempts=per_index_attempts, failures=per_index_failures)
                    except Exception:
                        rate = 100.0 if per_index_success else 0.0
                        metrics.index_success_rate.labels(index=index_symbol).set(rate)
                except Exception: logger.debug(f"Failed index aggregate metrics for {index_symbol}")
        # Initialize to a sane default; override below
        cycle_status = 'unknown'
        try:
            # Derive index status from aggregated expiry statuses (coverage aware) instead of simple fail count heuristic.
            from src.collectors.helpers.status_reducer import aggregate_cycle_status as _agg_status
            from src.collectors.helpers.status_reducer import compute_expiry_status as _comp_status
            last_age = 0.0; pcr_val = None
            try:
                if pcr_snapshot:
                    first_key = sorted(pcr_snapshot.keys())[0]; pcr_val = pcr_snapshot[first_key]
            except Exception:
                pass
            # Ensure each expiry_detail has a definitive status reflecting coverage metrics.
            for _exp in expiry_details:
                try:
                    # Recompute status if missing or legacy placeholder
                    _exp_status = _exp.get('status')
                    if not _exp_status or _exp_status.lower() in ('bad','unknown'):
                        _exp['status'] = _comp_status(_exp)
                except Exception:
                    continue
            cycle_status = _agg_status(expiry_details)
            if index_stale:
                # Preserve original classification but mark explicitly as STALE for visibility.
                cycle_status = 'STALE'
            # Format index summary line (non-concise mode) using cycle_status (ok/partial/empty)
            from src.logstream.formatter import format_index as _format_index
            line = _format_index(
                index=index_symbol,
                legs=per_index_option_count,
                legs_avg=None,
                legs_cum=None,
                succ_pct=None,
                succ_avg_pct=None,
                attempts=per_index_attempts,
                failures=per_index_failures,
                last_age_s=last_age,
                pcr=pcr_val,
                atm=atm_strike if isinstance(atm_strike,(int,float)) else None,
                err=None if per_index_failures==0 else 'fail',
                status=cycle_status.lower(),
            )
            if concise_mode:
                logger.debug(line)
            else:
                logger.info(line)
            if concise_mode:
                block_lines = [
                    "-------------------------",
                    f"INDEX: {index_symbol}",
                    "-------------------------",
                    "Time   Price     ATM   Expiry      Tag         Legs  CE   PE   PCR   Range          Step",
                    "-------------------------------------------------------------------------------",
                ]
                for (t, price_disp, atm_disp, exp_str, tag, legs, ce_c, pe_c, pcr_v, rng_disp, step_v) in human_rows:
                    block_lines.append(f"{t:<6} {price_disp:>8} {atm_disp:>6} {exp_str:<11} {tag:<11} {legs:>4} {ce_c:>3} {pe_c:>3} {pcr_v:>5} {rng_disp:<14} {step_v:>4}")
                block_lines.append("-------------------------------------------------------------------------------")
                block_lines.append(f"{index_symbol} TOTAL LEGS: {per_index_option_count} | FAILS: {per_index_failures} | STATUS: {cycle_status.upper()}{' (SKIPPED)' if (stale_mode=='skip' and index_stale) else ''}")
                result['human_block'] = "\n".join(block_lines)
                result['overall_legs'] += per_index_option_count
                result['overall_fails'] += per_index_failures
        except Exception as e:  # ensure we always return a result structure
            logger.error(f"Error processing index {index_symbol}: {e}")
            try: trace('index_error', index=index_symbol, error=str(e))
            except Exception: pass
    # Always set overall legs/fails on the result (used by callers for rollups)
    try:
        result['overall_legs'] = int(per_index_option_count)
        result['overall_fails'] = int(per_index_failures)
    except Exception:
        # Leave defaults from initialization
        pass

    # Populate the structured per-index entry so callers can aggregate indices
    try:
        # Ensure expiry details is a list for downstream consumers
        _expiries = expiry_details if isinstance(expiry_details, list) else []
        # Minimalist environments may skip expiry processing; synthesize a tiny placeholder
        # so that structured return contains one expiry with the requested rule when we had attempts.
        if not _expiries and per_index_attempts > 0:
            try:
                _rule = (_p(params,'expiries',['this_week']) or ['this_week'])[0]
            except Exception:
                _rule = 'this_week'
            _expiries = [{'rule': _rule, 'status': 'empty', 'options': 0, 'failed': True}]
        # Prefer the computed cycle_status if available; default to 'unknown'
        _status = locals().get('cycle_status', None)
        if not _status or not isinstance(_status, str):
            _status = 'unknown'
        entry = {
            'index': index_symbol,
            'price': index_price,
            'atm': atm_strike,
            'attempts': int(per_index_attempts),
            'failures': int(per_index_failures),
            'option_count': int(per_index_option_count),
            'status': _status,
            'expiries': _expiries,
        }
        # Attach stale flag if evaluated
        try:
            if 'index_stale' in locals():
                entry['stale'] = bool(index_stale)
        except Exception:
            pass
        result['indices_struct_entry'] = entry
    except Exception:
        # Keep result without indices_struct_entry on unexpected failure
        logger.debug('build_indices_struct_entry_failed', exc_info=True)
    return result

__all__ = ["process_index"]
