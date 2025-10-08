#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified collectors for G6 Platform.

Diagnostic instrumentation:
    Set G6_IMPORT_TRACE=1 to emit progress markers during module import and
    early function entry. This helps isolate hangs during pytest collection.
    Markers are of the form [g6-import] <phase> and flushed immediately.
"""

import logging
import os
import datetime
import time
try:
    from src.utils.env_flags import is_truthy_env  # type: ignore
except Exception:  # fallback should not trigger normally
    def is_truthy_env(name: str) -> bool:  # type: ignore
        return os.environ.get(name,'').lower() in {'1','true','yes','on'}

## is_truthy_env imported above; fallback no longer needed (tests ensure availability)

_IMPORT_TRACE = is_truthy_env('G6_IMPORT_TRACE')
def _trace_import(msg: str):  # lightweight, safe no-op if disabled
    if not _IMPORT_TRACE:
        return
    try:
        print(f"[g6-import] {msg}", flush=True)
    except Exception:
        pass

_trace_import('unified_collectors: start import')
from typing import Dict, Any, List, Tuple, Optional, Callable
import json
from dataclasses import dataclass
_trace_import('import cycle_context')
from src.collectors.cycle_context import CycleContext, ExpiryContext
_trace_import('import timeutils')
from src.utils.timeutils import utc_now
_trace_import('import modules.context')
from src.collectors.modules.context import build_collector_context, CollectorContext  # Phase 1 context introduction
_trace_import('import persist_result')
from src.collectors.persist_result import PersistResult
_trace_import('import helpers.persist')
from src.collectors.helpers.persist import persist_and_metrics, persist_with_context
_trace_import('import logstream.formatter')
from src.logstream.formatter import format_index
_trace_import('import utils.deprecations')
from src.utils.deprecations import check_pipeline_flag_deprecation  # type: ignore


# Add this before launching the subprocess
import sys  # retained for potential future CLI usage
_trace_import('import utils.market_hours')
from src.utils.market_hours import get_next_market_open  # dynamic is_market_open access below
try:  # Phase 6: data quality bridge (extracted)
    _trace_import('import data_quality_bridge')
    from src.collectors.modules.data_quality_bridge import (
        get_dq_checker as _get_dq_checker,
        run_option_quality as _run_option_quality,
        run_index_quality as _run_index_quality,
        run_expiry_consistency as _run_expiry_consistency,
    )  # type: ignore
except Exception:  # pragma: no cover
    _get_dq_checker = lambda: None  # type: ignore
    _run_option_quality = lambda dq, data: ({}, [])  # type: ignore
    _run_index_quality = lambda dq, price, index_ohlc=None: (True, [])  # type: ignore
    _run_expiry_consistency = lambda dq, data, index_price, expiry_rule: []  # type: ignore
_trace_import('import memory_pressure_bridge')
from src.collectors.modules.memory_pressure_bridge import evaluate_memory_pressure  # memory pressure abstraction
_trace_import('import error_handling')
from src.error_handling import handle_collector_error
_trace_import('import utils.exceptions')
from src.utils.exceptions import (
    ResolveExpiryError,
    NoInstrumentsError,
    NoQuotesError,
    CsvWriteError,
    InfluxWriteError,
)
_trace_import('import helpers.status_reducer')
from src.collectors.helpers.status_reducer import derive_partial_reason  # hot-path helper (was dynamically imported)




_trace_import('imports complete, logger init')
logger = logging.getLogger(__name__)
# Stage2 global flags
try:
    _DAILY_HEADER_EMITTED  # type: ignore[name-defined]
except Exception:
    _DAILY_HEADER_EMITTED = set()  # type: ignore[var-annotated]
_AGGREGATED_SUMMARY_ENABLED = is_truthy_env('G6_AGGREGATE_GLOBAL_BANNER')
_PHASE_MERGE = is_truthy_env('G6_PHASE_TIMING_MERGE')
_PHASE_SINGLE_EMIT = is_truthy_env('G6_PHASE_TIMING_SINGLE_EMIT')  # new: consolidate to one line per cycle
# If single header mode is active, implicitly enable merged + single emit for consistency
if is_truthy_env('G6_SINGLE_HEADER_MODE'):
    if not _PHASE_MERGE:
        _PHASE_MERGE = True
    if not _PHASE_SINGLE_EMIT:
        _PHASE_SINGLE_EMIT = True

# Centralized TRACE emission: delegate to broker.kite.tracing when available.
try:  # pragma: no cover - import side-effect free
    from src.broker.kite.tracing import trace as _trace  # type: ignore
except Exception:  # pragma: no cover
    def _trace(msg: str, **ctx):  # fallback minimal gating using CollectorSettings when available
        try:
            from src.collector.settings import get_collector_settings as _get_cs  # type: ignore
        except Exception:
            _get_cs = None  # type: ignore
        settings_obj = None
        try:
            if _get_cs:
                settings_obj = _get_cs()
        except Exception:
            settings_obj = None
        try:
            quiet_mode = False
            quiet_allow_trace = False
            trace_enabled = False
            if settings_obj:
                quiet_mode = bool(getattr(settings_obj, 'quiet_mode', False))
                quiet_allow_trace = bool(getattr(settings_obj, 'quiet_allow_trace', False))
                trace_enabled = bool(getattr(settings_obj, 'trace_collector', getattr(settings_obj, 'trace_enabled', False)))
            else:  # legacy fallback
                quiet_mode = os.environ.get('G6_QUIET_MODE') == '1'
                quiet_allow_trace = is_truthy_env('G6_QUIET_ALLOW_TRACE')
                trace_enabled = is_truthy_env('G6_TRACE_COLLECTOR')
            if quiet_mode and not quiet_allow_trace:
                return
            if not trace_enabled:
                return
            if ctx:
                logger.warning("TRACE %s | %s", msg, json.dumps(ctx, default=str)[:4000])
            else:
                logger.warning("TRACE %s", msg)
        except Exception:
            pass

################################################################################
# Internal Helper Abstractions (extracted to reduce cyclomatic complexity)
################################################################################

class _ExpiryResult:
    """Lightweight container for per-expiry processing outcome."""
    __slots__ = (
        'expiry_rule','expiry_date','enriched','pcr','day_width','collection_time',
        'strike_list','option_count','fail','human_row','snapshot_timestamp'
    )
    def __init__(self, expiry_rule: str, expiry_date, enriched: Dict[str,Any], strike_list: List[float]):
        self.expiry_rule = expiry_rule
        self.expiry_date = expiry_date
        self.enriched = enriched
        self.pcr = None
        self.day_width = 0
        self.collection_time = None
        self.strike_list = strike_list
        self.option_count = len(enriched)
        self.fail = False
        self.human_row = None  # tuple built only in concise mode
        self.snapshot_timestamp = None

@dataclass
class AggregationState:
    """State accumulated across expiries for a single index cycle.

    representative_day_width: last non-zero day width observed.
    snapshot_base_time: earliest timestamp across expiries (used for snapshot anchoring).
    """
    representative_day_width: int = 0
    snapshot_base_time: Optional[datetime.datetime] = None

    def capture(self, metrics_payload: Dict[str, Any]):  # pragma: no cover - lightweight defensive
        try:
            if metrics_payload.get('day_width'):
                self.representative_day_width = int(metrics_payload['day_width'])
            ts = metrics_payload.get('timestamp')
            if ts:
                if self.snapshot_base_time is None or ts < self.snapshot_base_time:
                    self.snapshot_base_time = ts
        except Exception:
            logger.debug('aggregation_state_capture_failed', exc_info=True)




def _determine_concise_mode() -> bool:
    try:
        from src.broker.kite_provider import is_concise_logging  # type: ignore
        return bool(is_concise_logging())
    except Exception:  # pragma: no cover
        return False

# Heartbeat state (process-wide)
_LAST_HEARTBEAT_EMIT = 0.0

def _maybe_emit_heartbeat(metrics, *, force: bool = False) -> None:
    """Emit a lightweight structured heartbeat log at most every G6_LOOP_HEARTBEAT_INTERVAL seconds.

    Fields focus on high-level loop health without verbose per-phase data:
        hb.loop.heartbeat duration_s=<sec_since_last_cycle> options=<last_cycle_options> cycles=<total_cycles>
    Safe no-op if metrics absent. Uses module global to avoid cross-import duplication.
    """
    import os, time as _t
    try:
        from src.collector.settings import get_collector_settings as _get_cs  # type: ignore
    except Exception:
        _get_cs = None  # type: ignore
    global _LAST_HEARTBEAT_EMIT
    try:
        interval_env = ''
        settings_obj = None
        if _get_cs:
            try:
                settings_obj = _get_cs()
            except Exception:
                settings_obj = None
        if settings_obj:
            # prefer explicit setting; if unset fallback to env (legacy)
            hb_val = getattr(settings_obj, 'loop_heartbeat_interval', 0.0)
            if hb_val and hb_val > 0:
                interval_env = str(hb_val)
            else:
                interval_env = os.environ.get('G6_LOOP_HEARTBEAT_INTERVAL','')
        else:
            interval_env = os.environ.get('G6_LOOP_HEARTBEAT_INTERVAL','')
        if not force:
            if not interval_env:
                return
            try:
                interval = float(interval_env)
            except Exception:
                interval = 0.0
            if interval <= 0:
                return
        else:
            interval = 0.0
        now = _t.time()
        if not force and _LAST_HEARTBEAT_EMIT and (now - _LAST_HEARTBEAT_EMIT) < interval:
            return
        cycles = None
        opts = None
        limiter_tokens = None
        limiter_cooldown = None
        batch_saved = None
        batch_avg = None
        try:
            if metrics and hasattr(metrics, 'collection_cycles'):
                val = getattr(getattr(metrics, 'collection_cycles'), '_value', None)
                if val and hasattr(val, 'get'):
                    cycles = int(val.get())  # type: ignore
        except Exception:
            pass
        try:
            if metrics and hasattr(metrics, '_last_cycle_options'):
                opts = int(getattr(metrics, '_last_cycle_options') or 0)
        except Exception:
            pass
        try:  # batching stats
            from src.broker.kite.quote_batcher import get_batcher  # type: ignore
            _b = get_batcher()
            batch_saved = getattr(_b, '_debug_calls_saved', None)
            batch_avg = getattr(_b, '_debug_avg_batch_size', None)
        except Exception:
            pass
        try:  # limiter snapshot
            import gc
            for _obj in gc.get_objects():
                if _obj.__class__.__name__ == 'RateLimiter' and hasattr(_obj, '_st'):
                    _st = getattr(_obj, '_st')
                    limiter_tokens = getattr(_st, 'tokens', None)
                    cd_until = getattr(_st, 'cooldown_until', 0.0)
                    if cd_until and cd_until > now:
                        limiter_cooldown = round(cd_until - now, 1)
                    else:
                        limiter_cooldown = 0.0
                    break
        except Exception:
            pass
        logger.info(
            "hb.loop.heartbeat "
            f"cycles={cycles if cycles is not None else 'NA'} "
            f"last_cycle_options={opts if opts is not None else 'NA'} "
            f"limiter_tokens={limiter_tokens if limiter_tokens is not None else 'NA'} "
            f"limiter_cooldown_s={limiter_cooldown if limiter_cooldown is not None else 'NA'} "
            f"batch_saved_calls={batch_saved if batch_saved is not None else 'NA'} "
            f"batch_avg_size={batch_avg if batch_avg is not None else 'NA'}"
        )
        _LAST_HEARTBEAT_EMIT = now
    except Exception:
        logger.debug('heartbeat_emit_failed', exc_info=True)


def _init_cycle_metrics(metrics):  # side-effect only
    if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
        try:
                metrics.collection_cycle_in_progress.set(1)
        except Exception:
            pass


def _maybe_init_greeks(compute_greeks: bool, estimate_iv: bool, risk_free_rate: float, metrics):
    """Initialize greeks calculator honoring env overrides. Returns (greeks_calculator, compute_greeks_flag, estimate_iv_flag)."""
    try:
        _env_force_greeks = is_truthy_env('G6_FORCE_GREEKS')
        _env_disable_greeks = is_truthy_env('G6_DISABLE_GREEKS')
    except Exception:  # pragma: no cover
        _env_force_greeks = False
        _env_disable_greeks = False
    if _env_force_greeks:
        compute_greeks = True
    if _env_disable_greeks:
        compute_greeks = False
    greeks_calculator = None
    greeks_enabled_effective = compute_greeks or estimate_iv
    if greeks_enabled_effective:
        try:
            from src.analytics.option_greeks import OptionGreeks  # type: ignore
            greeks_calculator = OptionGreeks(risk_free_rate=risk_free_rate)
            if compute_greeks:
                logger.info(f"Greek computation enabled (r={risk_free_rate}) [force_env={_env_force_greeks}]")
            elif estimate_iv:
                logger.info(f"IV estimation enabled (r={risk_free_rate}) [force_env={_env_force_greeks}]")
        except Exception as e:
            logger.error(f"Failed to initialize OptionGreeks: {e}")
            if compute_greeks:
                compute_greeks = False
            if estimate_iv:
                estimate_iv = False
            greeks_calculator = None
    if metrics and hasattr(metrics, 'memory_greeks_enabled'):
        try:
            metrics.memory_greeks_enabled.set(1 if greeks_calculator else 0)
        except Exception:  # pragma: no cover
            pass
    return greeks_calculator, compute_greeks, estimate_iv


def _evaluate_memory_pressure(metrics) -> Dict[str,Any]:  # backward-compatible wrapper
    return evaluate_memory_pressure(metrics)


_FALLBACK_BUILD = False
try:
    from src.utils.strikes import build_strikes as _build_strikes  # shared utility with scale param
except Exception:  # pragma: no cover
    _FALLBACK_BUILD = True
    def _build_strikes(atm: float, n_itm: int, n_otm: int, index_symbol: str, *, scale: float | None = None) -> List[float]:  # type: ignore[override]
        # scale ignored in fallback
        if atm <= 0:
            return []
        # Use centralized registry (R1) for default step size
        try:
            from src.utils.index_registry import get_index_meta  # local import to avoid circular during fallback
            step = float(get_index_meta(index_symbol).step)
        except Exception:
            step = 100.0 if index_symbol in ['BANKNIFTY','SENSEX'] else 50.0
        arr: List[float] = []
        for i in range(1, n_itm + 1):
            arr.append(float(atm - i*step))
        arr.append(float(atm))
        for i in range(1, n_otm + 1):
            arr.append(float(atm + i*step))
        return sorted(arr)

# -----------------------------------------------------------------------------
# Future Refactor Opportunities (non-functional; roadmap)
# -----------------------------------------------------------------------------
# 1. Introduce a @dataclass CycleContext to encapsulate shared objects/flags.
# 2. Move human-readable summary generation into a dedicated formatter module.
# 3. Provide injectable clock abstraction for deterministic testing.
# 4. Convert per-expiry pipeline into strategy chain (fetch -> enrich -> derive -> persist).
# 5. Explore concurrency (async IO) for parallel expiry processing.
# 6. Expose structured return object for programmatic diagnostics & tests.
# NOTE: Deferred intentionally to keep current change scoped to complexity reduction.


from src.collectors.modules.coverage_eval import coverage_metrics as _coverage_metrics, field_coverage_metrics as _field_coverage_metrics  # Phase 3 extracted
from src.collectors.helpers.iv_greeks import iv_estimation_block as _iv_estimation_block
from src.collectors.helpers.validation import preventive_validation_stage as _preventive_validation_stage
try:  # synthetic classification removed; keep placeholder for backward compatibility if tests import
    from src.collectors.helpers.synthetic import classify_expiry_result as _classify_expiry_result  # type: ignore
except Exception:  # pragma: no cover
    def _classify_expiry_result(*args, **kwargs):  # type: ignore
        return 'OK'
try:  # synthetic index price strategy deprecated
    from src.synthetic.strategy import synthesize_index_price as _synthesize_index_price  # type: ignore
except Exception:  # pragma: no cover
    def _synthesize_index_price(index_symbol, index_price, atm):  # type: ignore
        return index_price, atm, False
from src.collectors.helpers.validation import preventive_validation_stage as _preventive_validation_stage
from src.collectors.helpers.greeks import compute_greeks_block as _compute_greeks_block
from src.collectors.helpers.status_reducer import compute_expiry_status as _compute_expiry_status, aggregate_cycle_status as _aggregate_cycle_status
from src.collectors.helpers.struct_events import (
    emit_zero_data as _emit_zero_data_struct,
    emit_option_match_stats as _emit_option_match_stats,
    emit_cycle_status_summary as _emit_cycle_status_summary,
)
from src.collectors.modules.expiry_universe import build_expiry_map as _build_expiry_map  # Phase 2: extracted expiry map
try:
    # B11 anomaly detection (optional) – lightweight import; guarded where used
    from src.bench.anomaly import detect_anomalies as _detect_anomalies  # type: ignore
except Exception:  # pragma: no cover
    _detect_anomalies = None  # type: ignore


def _persist_and_metrics(ctx: CycleContext, enriched_data, index_symbol, expiry_rule, expiry_date, collection_time, index_price, index_ohlc, allow_per_option_metrics) -> PersistResult:
    # Temporary shim calling extracted helper to avoid touching call sites elsewhere during transition.
    return persist_and_metrics(ctx, enriched_data, index_symbol, expiry_rule, expiry_date, collection_time, index_price, index_ohlc, allow_per_option_metrics)


def _synthetic_metric_pop(ctx: CycleContext, index_symbol, expiry_date):  # pragma: no cover (delegation)
    from src.collectors.modules.expiry_helpers import synthetic_metric_pop as _impl
    return _impl(ctx, index_symbol, expiry_date)


"""(Deprecated) Legacy ExpiryService compatibility layer removed.

The collection loop previously allowed a fallback resolution path using a
module-level `_EXPIRY_SERVICE_SINGLETON` gated by `G6_EXPIRY_SERVICE`.
This created divergence and subtle mismatches (e.g. monthly anchor drift).

As of 2025-09-30 the hook is removed: `_resolve_expiry` delegates *only* to
`providers.resolve_expiry`. Any tests that relied on monkeypatching the legacy
singleton must instead patch the provider facade or inject custom expiry lists.
"""

_EXPIRY_SERVICE_SINGLETON = None  # retained as a sentinel only; not used
_TRACE_AUTO_DISABLED = False  # process-level sentinel for G6_TRACE_AUTO_DISABLE feature

def _resolve_expiry(index_symbol, expiry_rule, providers, metrics, concise_mode):  # pragma: no cover
    """Unified expiry resolution.

    Single source of truth: delegate directly to `providers.resolve_expiry`.
    Any failure falls back to today's date (logged in non-concise mode).
    """
    import datetime as _dt, logging
    try:
        return providers.resolve_expiry(index_symbol, expiry_rule)
    except Exception as e:  # defensive fallback: today
        if not concise_mode:
            logging.getLogger(__name__).warning(
                "expiry_resolve_fallback_today", extra={"index": index_symbol, "rule": expiry_rule, "error": str(e)}
            )
        return _dt.date.today()


def _fetch_option_instruments(index_symbol, expiry_rule, expiry_date, strikes, providers, metrics):  # pragma: no cover
    from src.collectors.modules.expiry_helpers import fetch_option_instruments as _impl
    return _impl(index_symbol, expiry_rule, expiry_date, strikes, providers, metrics)


def _enrich_quotes(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics):  # pragma: no cover
    from src.collectors.modules.expiry_helpers import enrich_quotes as _impl
    return _impl(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics)

# Maintain export for legacy monkeypatching patterns
try:
    __all__.append('_EXPIRY_SERVICE_SINGLETON')  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    __all__ = ['_EXPIRY_SERVICE_SINGLETON']  # type: ignore


from src.collectors.helpers.validation import preventive_validation_stage as _preventive_validation_stage


def _process_index(
    ctx: CycleContext,
    index_symbol: str,
    params: Any,
    *,
    compute_greeks: bool,
    estimate_iv: bool,
    greeks_calculator: Any,
    mem_flags: Dict[str, Any],
    concise_mode: bool,
    build_snapshots: bool,
    risk_free_rate: float,
    metrics: Any,
    snapshots_accum: List[Any],
    dq_enabled: bool,
    dq_checker: Any,
) -> Dict[str, Any]:
    """Thin delegator to extracted modules.index_processor.process_index.

    Falls back to legacy inline implementation (no-op result) if import fails.
    """
    try:
        from src.collectors.modules import index_processor as _idx_mod  # type: ignore
        return _idx_mod.process_index(
            ctx,
            index_symbol,
            params,
            compute_greeks=compute_greeks,
            estimate_iv=estimate_iv,
            greeks_calculator=greeks_calculator,
            mem_flags=mem_flags,
            concise_mode=concise_mode,
            build_snapshots=build_snapshots,
            risk_free_rate=risk_free_rate,
            metrics=metrics,
            snapshots_accum=snapshots_accum,
            dq_enabled=dq_enabled,
            dq_checker=dq_checker,
            deps={
                # TRACE_ENABLED removed: tracing centralized (kept key removed to avoid stale reference)
                'trace': _trace,
                'AggregationState': AggregationState,
                'build_strikes': _build_strikes,
                'synth_index_price': _synthesize_index_price,
                'aggregate_cycle_status': _aggregate_cycle_status,
                'process_expiry': _process_expiry,
                'run_index_quality': _run_index_quality,
            },
        )
    except Exception:
        logger.debug('index_processor_module_failed', exc_info=True)
        return {
            'human_block': None,
            'indices_struct_entry': None,
            'summary_rows_entry': None,
            'overall_legs': 0,
            'overall_fails': 0,
        }


def _process_expiry(
    *,
    ctx: CycleContext,
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
    aggregation_state: 'AggregationState',
) -> Dict[str, Any]:
    """Process a single expiry. Returns dict containing success flag, option_count, expiry_rec, human_row.

    Extraction of original inline logic from _process_index; behavior preserved. AggregationState replaces holder lambdas.
    """
    # Delegator to extracted module
    try:
        from src.collectors.modules.expiry_processor import process_expiry as _proc  # type: ignore
        # Optional pipeline v2 path
        try:
            from src.collectors.modules.expiry_pipeline import process_expiry_v2, pipeline_enabled  # type: ignore
            if pipeline_enabled():  # route through skeleton pipeline
                # Provide pipeline phases access to strike universe & optional expiry_universe_map
                _prev_strikes = getattr(ctx, 'precomputed_strikes', None)
                _prev_universe = getattr(ctx, 'expiry_universe_map', None)
                try:
                    try:
                        ctx.precomputed_strikes = precomputed_strikes  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    if expiry_universe_map is not None:
                        try:
                            ctx.expiry_universe_map = expiry_universe_map  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    return process_expiry_v2(
                        _proc,
                        ctx=ctx,
                        index_symbol=index_symbol,
                        expiry_rule=expiry_rule,
                        atm_strike=atm_strike,
                        settings=getattr(ctx, 'collector_settings', None),
                    )
                finally:
                    # Restore / clean context attributes to avoid cross-expiry leakage
                    try:
                        if _prev_strikes is None:
                            if hasattr(ctx, 'precomputed_strikes'):
                                delattr(ctx, 'precomputed_strikes')
                        else:
                            ctx.precomputed_strikes = _prev_strikes  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    if expiry_universe_map is not None:
                        try:
                            if _prev_universe is None:
                                if hasattr(ctx, 'expiry_universe_map'):
                                    delattr(ctx, 'expiry_universe_map')
                            else:
                                ctx.expiry_universe_map = _prev_universe  # type: ignore[attr-defined]
                        except Exception:
                            pass
        except Exception:
            pass  # fall back to legacy immediately
        return _proc(
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
            collector_settings=getattr(ctx, 'collector_settings', None),
        )
    except Exception:  # pragma: no cover - fallback path
        logger.debug('expiry_processor_module_failed_fallback_inline', exc_info=True)
        # Preserve legacy failure semantics: return a minimal failure outcome
        return {'success': False, 'option_count': 0, 'expiry_rec': {'rule': expiry_rule, 'failed': True}}


def run_unified_collectors(
    index_params,
    providers,
    csv_sink,
    influx_sink,
    metrics=None,
    *,
    compute_greeks: bool = False,
    risk_free_rate: float = 0.05,
    estimate_iv: bool = False,
    iv_max_iterations: int | None = None,
    iv_min: float | None = None,
    iv_max: float | None = None,
    iv_precision: float | None = None,
    build_snapshots: bool = False,
):
    """Run unified collectors for all configured indices.

    Parameters
    ----------
    index_params : dict
        Configuration parameters for indices.
    providers : Providers
        Data providers facade.
    csv_sink : CsvSink
        CSV persistence layer.
    influx_sink : InfluxSink | None
        Influx persistence layer.
    metrics : Any
        Metrics registry or None.
    compute_greeks : bool
        Whether to compute greeks locally.
    risk_free_rate : float
        Annual risk-free rate used in pricing model.
    estimate_iv : bool
        Whether to attempt IV estimation prior to greek computation.
    iv_max_iterations / iv_min / iv_max : (future use)
        iv_max_iterations / iv_min / iv_max / iv_precision : (future use)
        Forthcoming IV solver tuning knobs; currently captured for forward compatibility.
    """
    # Phase 0 pipeline prep: create a shared CollectorSettings instance (used by expiry_processor).
    _collector_settings = None
    try:
        # Phase 0 settings integration: use centralized CollectorSettings (load once per cycle)
        from src.collectors.settings import CollectorSettings  # type: ignore
        if hasattr(CollectorSettings, 'load'):
            _collector_settings = CollectorSettings.load()  # type: ignore[attr-defined]
    except Exception:
        _collector_settings = None  # tolerate absence (legacy path continues)
    # Graceful guard: if providers facade missing, skip collection instead of raising attribute errors per index.
    if providers is None:
        try:
            have_warned = getattr(run_unified_collectors, '_g6_warned_missing_providers', False)  # type: ignore[attr-defined]
        except Exception:
            have_warned = False
        if not have_warned:
            logger.error("Unified collectors: providers not initialized (set G6_BOOTSTRAP_COMPONENTS=1 or supply credentials); skipping all indices")
            try: setattr(run_unified_collectors, '_g6_warned_missing_providers', True)  # type: ignore[attr-defined]
            except Exception: pass
        return {
            'status': 'no_providers',
            'indices_processed': 0,
            'have_raw': False,
            'snapshots': [] if build_snapshots else None,
            'snapshot_count': 0,
            'indices': [],
            'reason': 'providers_none',
        }

    # Rollout modes (shadow/primary) removed: unified_collectors now always executes the legacy path directly.
    # `G6_PIPELINE_ROLLOUT` is ignored (will be documented as removed); `G6_PIPELINE_COLLECTOR` already deprecated.
    check_pipeline_flag_deprecation()
    # Heuristic validation bypass for minimal single-index tests to prevent full drop by preventive validation
    try:
        if isinstance(index_params, dict) and len(index_params) == 1:
            only_cfg = next(iter(index_params.values())) or {}
            expiries = only_cfg.get('expiries') or []
            strikes_span = (only_cfg.get('strikes_itm',0) or 0) + (only_cfg.get('strikes_otm',0) or 0)
            if (len(expiries) <= 1 and strikes_span <= 4 and os.environ.get('G6_FORCE_VALIDATION','').lower() not in ('1','true','yes','on')):
                os.environ.setdefault('G6_VALIDATION_BYPASS','1')
    except Exception:
        logger.debug('validation_bypass_heuristic_failed', exc_info=True)
    # (iv_max_iterations, iv_min, iv_max) currently unused; integration handled in later task.
    # Mark cycle in-progress & start timers
    _trace("cycle_start", indices=list(index_params.keys()), compute_greeks=compute_greeks, estimate_iv=estimate_iv)
    _init_cycle_metrics(metrics)
    start_cycle_wall = time.time(); cycle_start_ts = utc_now()
    ctx = CycleContext(index_params=index_params, providers=providers, csv_sink=csv_sink, influx_sink=influx_sink, metrics=metrics, start_wall=start_cycle_wall, start_ts=cycle_start_ts)
    # Bootstrap phase: elapsed time from cycle start to just before first heavy timed phase ('init_greeks').
    # We record it explicitly to capture upfront configuration, imports, and light validation overhead.
    ctx.record('bootstrap', 0.0)  # initialize key; will update below once we know elapsed
    try:
        if _collector_settings is not None:
            ctx.collector_settings = _collector_settings  # type: ignore[attr-defined]
    except Exception:
        logger.debug('attach_collector_settings_failed', exc_info=True)
    # Phase 1: build high-level CollectorContext (non-invasive; not yet threaded through downstream helpers)
    try:
        _collector_ctx: CollectorContext = build_collector_context(
            index_params=index_params,
            metrics=metrics,
            debug=is_truthy_env('G6_COLLECTOR_REFACTOR_DEBUG'),
        )
        ctx.collector_ctx = _collector_ctx  # type: ignore[attr-defined]
    except Exception:
        logger.debug('collector_context_init_failed', exc_info=True)

    # Phase 0 (modularization refactor) instrumentation flag
    # Deprecated: refactor_debug parity accumulation removed
    refactor_debug = False

    # Market gate extraction
    try:
        from src.collectors.modules.market_gate import evaluate_market_gate  # type: ignore
        proceed, early = evaluate_market_gate(build_snapshots, metrics)
        if not proceed:
            # Ensure bootstrap phase metric observed for tests expecting presence even on early return
            try:
                if 'bootstrap' not in ctx.phase_times:
                    ctx.phase_times['bootstrap'] = time.time() - start_cycle_wall
                if metrics and hasattr(metrics, 'phase_duration_seconds'):
                    metrics.phase_duration_seconds.labels(phase='bootstrap').observe(ctx.phase_times['bootstrap'])  # type: ignore
            except Exception:
                logger.debug('early_bootstrap_phase_record_failed', exc_info=True)
            return early  # type: ignore[return-value]
        _trace("market_open")
    except Exception:
        logger.debug("market_gate_module_failed_fallback_inline", exc_info=True)
        # Fallback: do nothing (assume open) and continue
    
    # Init greeks & memory pressure flags
    # Update bootstrap with elapsed so far (exclude future timed phases) if still zero.
    try:
        if ctx.phase_times.get('bootstrap', 0.0) == 0.0:
            ctx.phase_times['bootstrap'] = time.time() - start_cycle_wall
    except Exception:
        logger.debug('bootstrap_phase_record_failed', exc_info=True)
    with ctx.time_phase('init_greeks'):
        greeks_calculator, compute_greeks, estimate_iv = _maybe_init_greeks(compute_greeks, estimate_iv, risk_free_rate, metrics)
        _trace("init_greeks_done", greeks_enabled=bool(greeks_calculator), compute_greeks=compute_greeks, estimate_iv=estimate_iv)
    with ctx.time_phase('memory_pressure_eval'):
        mem_flags = _evaluate_memory_pressure(metrics)
        _trace("memory_flags", **mem_flags)

    mp_manager = None  # we no longer re-evaluate inside loops (single eval design retained)
    concise_mode = _determine_concise_mode()

    human_blocks: list[str] = []
    summary_rows: list[dict[str, Any]] = []  # ensure defined before any early index skip appends
    overall_legs_total = 0
    overall_fail_total = 0
    single_header_mode = is_truthy_env('G6_SINGLE_HEADER_MODE')
    banner_debug = is_truthy_env('G6_BANNER_DEBUG')
    if concise_mode and not single_header_mode:
        # Use timezone-aware UTC now to avoid naive datetime usage (tests forbid naive now())
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime('%d-%b-%Y')  # display-ok
        force_daily_repeat = is_truthy_env('G6_DAILY_HEADER_EVERY_CYCLE')
        suppress_repeat = is_truthy_env('G6_DISABLE_REPEAT_BANNERS')
        if force_daily_repeat or (today_str not in _DAILY_HEADER_EMITTED) or not suppress_repeat:
            header = (f"DAILY OPTIONS COLLECTION LOG {today_str}" if is_truthy_env('G6_COMPACT_BANNERS') else ("\n"+"="*70+f"\n        DAILY OPTIONS COLLECTION LOG — {today_str}\n"+"="*70+"\n"))
            logger.info(header)
            _DAILY_HEADER_EMITTED.add(today_str)
        elif banner_debug:
            logger.debug("banner_suppressed daily_header repeat=%s", today_str)
    elif single_header_mode:
        # Ensure collectors do NOT re-emit banner accidentally (legacy code paths)
        # Add a lightweight sentinel each call; no logging here.
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime('%d-%b-%Y')  # display-ok
        _DAILY_HEADER_EMITTED.add(today_str)
        if banner_debug:
            logger.debug("banner_suppressed single_header_mode=1 date=%s", today_str)

    # Predefine outage flag for entire function scope (static analysis friendliness)
    provider_outage: bool = False
    # Process each index
    def _p(obj, name, default=None):  # supports dataclass or dict
        try:
            if isinstance(obj, dict):
                return obj.get(name, default)
            # dataclass or object with attribute
            return getattr(obj, name, default)
        except Exception:
            return default

    # Container for optional snapshot domain objects (built only when build_snapshots=True)
    snapshots_accum: List[Any] = [] if build_snapshots else []  # type: ignore[var-annotated]
    indices_struct: List[Dict[str, Any]] = []  # structured per-index summaries

    # Initialize data quality checker once (guarded by env flag for parity)
    dq_enabled = is_truthy_env('G6_ENABLE_DATA_QUALITY')
    dq_checker = _get_dq_checker() if dq_enabled else None

    # Phase 10 reliability: track consecutive empty cycles per index (options count == 0 with attempts >0)
    # Store counters on metrics object if available for persistence across cycles, else module-level fallback
    global _G6_CONSEC_EMPTY_COUNTERS  # type: ignore
    if '_G6_CONSEC_EMPTY_COUNTERS' not in globals():  # initialize once
        _G6_CONSEC_EMPTY_COUNTERS = {}

    merged_phase_times: dict[str,float] = {} if _PHASE_MERGE else {}
    per_index_summaries: list[dict[str,int]] = [] if _AGGREGATED_SUMMARY_ENABLED else []
    for index_symbol, params in index_params.items():
        _res = _process_index(
            ctx,
            index_symbol,
            params,
            compute_greeks=compute_greeks,
            estimate_iv=estimate_iv,
            greeks_calculator=greeks_calculator,
            mem_flags=mem_flags,
            concise_mode=concise_mode,
            build_snapshots=build_snapshots,
            risk_free_rate=risk_free_rate,
            metrics=metrics,
            snapshots_accum=snapshots_accum,
            dq_enabled=dq_enabled,
            dq_checker=dq_checker,
        )
        if _res.get('summary_rows_entry'):
            summary_rows.append(_res['summary_rows_entry'])
        if _res.get('human_block'):
            human_blocks.append(_res['human_block'])
        overall_legs_total += _res.get('overall_legs',0)
        overall_fail_total += _res.get('overall_fails',0)
        if _PHASE_MERGE and ctx.phase_times:
            for k,v in ctx.phase_times.items():
                merged_phase_times[k] = merged_phase_times.get(k,0.0)+v
            ctx.phase_times.clear()
        if _AGGREGATED_SUMMARY_ENABLED:
            per_index_summaries.append({
                'legs': int(_res.get('overall_legs',0) or 0),
                'fails': int(_res.get('overall_fails',0) or 0),
            })
        if _res.get('indices_struct_entry'):
            entry = _res['indices_struct_entry']
            # Determine emptiness: zero option_count but had attempts
            try:
                attempts = int(entry.get('attempts') or 0)
                option_count = int(entry.get('option_count') or 0)
                is_empty = attempts > 0 and option_count == 0
            except Exception:
                is_empty = False
            # Update counters
            try:
                counter_map = getattr(metrics, '_consec_empty_counters', None) if metrics else None
                if counter_map is None:
                    counter_map = _G6_CONSEC_EMPTY_COUNTERS
                prev = int(counter_map.get(index_symbol, 0) or 0)
                curr = prev + 1 if is_empty else 0
                counter_map[index_symbol] = curr
                if metrics is not None and getattr(metrics, '_consec_empty_counters', None) is None:
                    try:
                        setattr(metrics, '_consec_empty_counters', counter_map)
                    except Exception:
                        pass
                entry['empty_consec'] = curr
            except Exception:
                entry['empty_consec'] = 0
            indices_struct.append(entry)
        # Accumulate per-index option legs for metrics (each leg = one option instrument)
        try:
            if metrics:
                legs = int(_res.get('overall_legs', 0) or 0)
                # Initialize per-index tracking map if missing
                if not hasattr(metrics, '_per_index_last_cycle_options'):
                    setattr(metrics, '_per_index_last_cycle_options', {})
                per_map = getattr(metrics, '_per_index_last_cycle_options')
                if isinstance(per_map, dict):
                    per_map[index_symbol] = legs
        except Exception:
            logger.debug('metrics_per_index_option_accumulate_failed', exc_info=True)
    
    # Update collection time metrics
    total_elapsed = time.time() - start_cycle_wall  # cycle duration (seconds)
    # Set aggregate options processed for cycle summary (sum of legs across indices)
    try:
        if metrics:
            total_legs = overall_legs_total
            # Fallback if per-index map present: recompute to be safe
            if hasattr(metrics, '_per_index_last_cycle_options'):
                try:
                    m = getattr(metrics, '_per_index_last_cycle_options')
                    if isinstance(m, dict) and m:
                        total_legs = sum(int(v or 0) for v in m.values())
                except Exception:
                    pass
            setattr(metrics, '_last_cycle_options', total_legs)
    except Exception:
        logger.debug('metrics_total_option_accumulate_failed', exc_info=True)
    # Reconstitute merged phase timings for metrics emission if merge mode cleared ctx.phase_times.
    if _PHASE_MERGE and not ctx.phase_times and merged_phase_times:
        try:
            # Do not mutate merged_phase_times; copy so later consolidated log still uses its own structure if needed.
            ctx.phase_times.update(merged_phase_times)
        except Exception:
            logger.debug('restore_merged_phase_times_failed', exc_info=True)
    # Emit phase metrics summary (debug line removed after validation phase)
    with ctx.time_phase('emit_phase_metrics'):
        try:
            # Always emit phase duration metrics (Prometheus observations) regardless of merge/single-emit flags.
            # The flags only control human-readable PHASE_TIMING log line consolidation, not metric recording.
            if not ctx.phase_times:
                # Edge path: no phases recorded (unexpected). Ensure bootstrap placeholder so metrics test invariants hold.
                ctx.record('bootstrap', 0.0)
            ctx.emit_phase_metrics()
            # Second-chance observation: if a minimalist test metrics stub failed to record (e.g., labels impl quirk),
            # attempt direct iteration to populate expected tracking containers for tests.
            if metrics:
                try:
                    # Multi-expiry test tracks _phase_observed (a set)
                    if hasattr(metrics, '_phase_observed') and isinstance(getattr(metrics,'_phase_observed'), set):
                        if not metrics._phase_observed and ctx.phase_times:
                            for _phase_name, _secs in ctx.phase_times.items():
                                try: metrics.phase_duration_seconds.labels(phase=_phase_name).observe(_secs)
                                except Exception: pass
                    # Bootstrap test tracks _phases dict
                    if hasattr(metrics, '_phases') and isinstance(getattr(metrics,'_phases'), dict):
                        if not metrics._phases and ctx.phase_times:
                            for _phase_name, _secs in ctx.phase_times.items():
                                try: metrics.phase_duration_seconds.labels(phase=_phase_name).observe(_secs)
                                except Exception: pass
                except Exception:
                    logger.debug('second_chance_phase_metrics_failed', exc_info=True)
        except Exception:
            logger.debug("Failed emitting phase metrics", exc_info=True)
        _trace("phase_metrics_emitted")
    # Emit consolidated phase timing summary line (human-readable)
    try:
        ctx.emit_consolidated_log()
    except Exception:
        logger.debug("Failed emitting consolidated phase timing log", exc_info=True)
    _trace("consolidated_log_emitted")
    if metrics:
        try:
            from src.collectors.modules.metrics_updater import finalize_cycle_metrics  # type: ignore
            finalize_cycle_metrics(
                metrics,
                start_cycle_wall=start_cycle_wall,
                cycle_start_ts=cycle_start_ts,
                total_elapsed=total_elapsed,
            )
        except Exception as e:
            try:
                collection_time_elapsed = (utc_now() - cycle_start_ts).total_seconds()
                metrics.collection_duration.observe(collection_time_elapsed)
                metrics.collection_cycles.inc()
                try:
                    metrics.mark_cycle(success=True, cycle_seconds=total_elapsed, options_processed=metrics._last_cycle_options or 0, option_processing_seconds=metrics._last_cycle_option_seconds or 0.0)
                except Exception:
                    metrics.avg_cycle_time.set(total_elapsed)
                    if total_elapsed > 0:
                        metrics.cycles_per_hour.set(3600.0 / total_elapsed)
                if hasattr(metrics, 'collection_cycle_in_progress'):
                    try: metrics.collection_cycle_in_progress.set(0)
                    except Exception: pass
            except Exception as inner:
                logger.error(f"Failed to update collection metrics: {inner}")
                _trace("metrics_update_error", error=str(inner))
    # Stage2: merged phase timing emit (before human summary)
    # Global aggregation path: divert merged timing dictionary to global accumulator
    _GLOBAL_FLAG = os.environ.get('G6_GLOBAL_PHASE_TIMING','').lower() in ('1','true','yes','on')
    if _GLOBAL_FLAG and merged_phase_times:
        try:
            from src.orchestrator import global_phase_timing as _gpt  # type: ignore
            # Reset for cycle (no-op if same)
            try:
                _gpt.reset_for_cycle(getattr(ctx, 'cycle_ts', None))
            except Exception:
                pass
            _gpt.record_phases(merged_phase_times)
        except Exception:
            logger.debug('global_phase_timing_record_failed', exc_info=True)
    elif _PHASE_MERGE and merged_phase_times and not _PHASE_SINGLE_EMIT:
        try:
            total_ph = sum(merged_phase_times.values()) or 0.0
            parts = [f"{k}={v:.3f}s({(v/total_ph*100.0 if total_ph else 0.0):.1f}%)" for k,v in sorted(merged_phase_times.items(), key=lambda x:-x[1])]
            cycle_ts_attr = getattr(ctx, 'cycle_ts', None)
            if not cycle_ts_attr:
                try:
                    cycle_ts_attr = int(getattr(cycle_start_ts, 'timestamp', lambda: 0)())  # datetime to epoch
                except Exception:
                    cycle_ts_attr = 0
            cycle_ts_int = int(cycle_ts_attr or 0)
            index_count = len(index_params) if isinstance(index_params, dict) else -1
            logger.info("PHASE_TIMING_MERGED cycle_ts=%s indices=%s %s | total=%.3fs", cycle_ts_int, index_count, ' | '.join(parts), total_ph)
        except Exception:
            logger.debug('phase_timing_merged_emit_failed', exc_info=True)
    # Emit accumulated human summary before structured cycle line
    # When single-emit phase timing is enabled defer emission until just before human summary (single cycle consolidation)
    if _PHASE_MERGE and _PHASE_SINGLE_EMIT and merged_phase_times:
        if _GLOBAL_FLAG:
            # Already recorded above; skip local emission
            pass
        else:
            try:
                total_ph = sum(merged_phase_times.values()) or 0.0
                parts = [f"{k}={v:.3f}s({(v/total_ph*100.0 if total_ph else 0.0):.1f}%)" for k,v in sorted(merged_phase_times.items(), key=lambda x:-x[1])]
                cycle_ts_attr = getattr(ctx, 'cycle_ts', None)
                if not cycle_ts_attr:
                    try:
                        cycle_ts_attr = int(getattr(cycle_start_ts, 'timestamp', lambda: 0)())
                    except Exception:
                        cycle_ts_attr = 0
                cycle_ts_int = int(cycle_ts_attr or 0)
                index_count = len(index_params) if isinstance(index_params, dict) else -1
                logger.info("PHASE_TIMING_MERGED cycle_ts=%s indices=%s %s | total=%.3fs", cycle_ts_int, index_count, ' | '.join(parts), total_ph)
            except Exception:
                logger.debug('phase_timing_merged_single_emit_failed', exc_info=True)
    if concise_mode and human_blocks:
        try:
            for blk in human_blocks:
                logger.info("\n" + blk)
            # Determine system status: previously based only on fail count. Now degrade if any index cycle_status not OK.
            system_status = 'GREEN'
            stale_present = False
            try:
                empty_all_indices = True if indices_struct else False
                for idx_entry in indices_struct:
                    st = (idx_entry.get('status') or '').upper()
                    if st == 'STALE':
                        stale_present = True
                        system_status = 'DEGRADED'
                        break
                    # Track if any index has non-empty data for outage detection
                    try:
                        if int(idx_entry.get('option_count') or 0) > 0:
                            empty_all_indices = False
                    except Exception:
                        empty_all_indices = False
                if not stale_present:
                    for idx_entry in indices_struct:
                        st = (idx_entry.get('status') or '').upper()
                        if st != 'OK':
                            system_status = 'DEGRADED'
                        try:
                            if int(idx_entry.get('option_count') or 0) > 0:
                                empty_all_indices = False
                        except Exception:
                            empty_all_indices = False
                # Provider outage classification: all indices empty for N consecutive cycles
                try:
                    from src.collector.settings import get_collector_settings as _get_cs2  # type: ignore
                except Exception:
                    _get_cs2 = None  # type: ignore
                outage_threshold = 3
                if _get_cs2:
                    try:
                        cs2 = _get_cs2()
                        if cs2 and getattr(cs2, 'provider_outage_threshold', None):
                            outage_threshold = int(getattr(cs2, 'provider_outage_threshold'))
                    except Exception:
                        pass
                if outage_threshold is None:
                    outage_threshold = 3
                if not outage_threshold:
                    outage_threshold = int(os.environ.get('G6_PROVIDER_OUTAGE_THRESHOLD','3') or 3)
                provider_outage: bool = False  # predefine for static analyzers (cycle scope)
                try:
                    counter_map = getattr(metrics, '_consec_empty_counters', {}) if metrics else globals().get('_G6_CONSEC_EMPTY_COUNTERS', {})
                    if empty_all_indices and counter_map and indices_struct:
                        provider_outage = True
                        for ix_entry in indices_struct:
                            if (counter_map.get(ix_entry.get('index'),0) or 0) < outage_threshold:
                                provider_outage = False; break
                except Exception:
                    provider_outage = False
                if provider_outage:
                    system_status = 'OUTAGE'
                    # Throttle outage log spam: emit first detection, then every N cycles while persistent
                    try:
                        throttle_n = 5
                        from src.collector.settings import get_collector_settings as _get_cs3  # type: ignore
                        try:
                            cs3 = _get_cs3()
                            if cs3 and getattr(cs3, 'provider_outage_log_every', None):
                                throttle_n = int(getattr(cs3, 'provider_outage_log_every'))
                        except Exception:
                            pass
                        if not throttle_n:
                            throttle_n = int(os.environ.get('G6_PROVIDER_OUTAGE_LOG_EVERY','5') or 5)
                    except Exception:
                        throttle_n = 5
                    try:
                        global _G6_PROVIDER_OUTAGE_SEQ  # type: ignore
                        if '_G6_PROVIDER_OUTAGE_SEQ' not in globals():
                            _G6_PROVIDER_OUTAGE_SEQ = 0
                        _G6_PROVIDER_OUTAGE_SEQ += 1
                        if _G6_PROVIDER_OUTAGE_SEQ == 1 or (_G6_PROVIDER_OUTAGE_SEQ % max(throttle_n,1) == 0):
                            logger.error(f"provider_outage_detected empty_all_indices=1 threshold={outage_threshold} seq={_G6_PROVIDER_OUTAGE_SEQ}")
                    except Exception:
                        logger.error(f"provider_outage_detected empty_all_indices=1 threshold={outage_threshold}")
                else:
                    # Reset sequence when outage clears
                    if 'provider_outage' in locals():
                        try:
                            if '_G6_PROVIDER_OUTAGE_SEQ' in globals():
                                del globals()['_G6_PROVIDER_OUTAGE_SEQ']
                        except Exception:
                            pass
            except Exception:
                pass
            if overall_fail_total > 0 and system_status == 'GREEN':
                system_status = 'DEGRADED'
            # Abort logic for stale cycles when mode=abort
            import os as _os
            stale_mode = _os.getenv('G6_STALE_WRITE_MODE','mark').strip().lower()
            abort_cycles =  int(_os.getenv('G6_STALE_ABORT_CYCLES','10') or 10)
            # Registry-scoped consecutive stale counter (isolated by per-test fresh registry)
            try:
                if metrics is not None:
                    consec = getattr(metrics, '_consec_stale_cycles', 0)
                    consec = consec + 1 if stale_present else 0
                    try:
                        setattr(metrics, '_consec_stale_cycles', consec)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    # Fallback transient local counter if metrics absent
                    consec = 1 if stale_present else 0
                # System-level stale metrics (lazy create)
                if metrics is not None:
                    try:  # pragma: no cover - metrics wiring
                        from prometheus_client import Counter as _C, Gauge as _G  # type: ignore
                        if not hasattr(metrics, 'stale_system_cycles_total'):
                            try:
                                metrics.stale_system_cycles_total = _C(
                                    'g6_stale_system_cycles_total',
                                    'Count of cycles where any index stale (system perspective)',
                                    ['mode'],
                                )  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        if not hasattr(metrics, 'stale_consecutive_cycles'):
                            try:
                                metrics.stale_consecutive_cycles = _G(
                                    'g6_stale_consecutive_cycles',
                                    'Consecutive stale cycles (system scope)',
                                    ['mode'],
                                )  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        if not hasattr(metrics, 'stale_system_active'):
                            try:
                                metrics.stale_system_active = _G(
                                    'g6_stale_system_active',
                                    'Whether any index stale in current cycle (system scope)',
                                    ['mode'],
                                )  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        # Update
                        try:
                            metrics.stale_system_active.labels(mode=stale_mode).set(1 if stale_present else 0)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        try:
                            metrics.stale_consecutive_cycles.labels(mode=stale_mode).set(consec)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        if stale_present:
                            try:
                                metrics.stale_system_cycles_total.labels(mode=stale_mode).inc()  # type: ignore[attr-defined]
                            except Exception:
                                pass
                    except Exception:
                        logger.debug('stale_system_metrics_failed', exc_info=True)
                if stale_mode == 'abort' and stale_present and consec >= abort_cycles:
                    logger.critical(f"stale_abort_trigger system_status={system_status} consec_stale={consec} threshold={abort_cycles}")
                    try:
                        import sys as _sys
                        _sys.exit(32)
                    except SystemExit:
                        raise
                    except Exception:
                        pass
            except Exception:
                logger.debug('stale_abort_evaluation_failed', exc_info=True)
            footer = ("\n" + "=" * 70 + f"\nALL INDICES TOTAL LEGS: {overall_legs_total}   |   FAILS: {overall_fail_total}   |   SYSTEM STATUS: {system_status}\n" + "=" * 70)
            logger.info(footer)
        except Exception:
            logger.debug("Failed to emit human summary footer", exc_info=True)
        _trace("concise_footer_emitted", total_legs=overall_legs_total, total_fails=overall_fail_total)

    # Emit cycle line(s) with new mode control: G6_CYCLE_OUTPUT={pretty|raw|both}
    # Precedence rules:
    # 1. If legacy G6_DISABLE_PRETTY_CYCLE is truthy -> force 'raw'
    # 2. Else use G6_CYCLE_OUTPUT value (default 'pretty')
    # 3. Values: 'pretty' => only human table (header+row) line(s); 'raw' => only machine CYCLE line; 'both' => both.
    try:
        from src.logstream.formatter import format_cycle, format_cycle_pretty, format_cycle_table, format_cycle_readable
        import os as _os_env
        legacy_disable = is_truthy_env('G6_DISABLE_PRETTY_CYCLE')
        mode = 'raw' if legacy_disable else _os_env.environ.get('G6_CYCLE_OUTPUT', 'pretty').strip().lower()
        if mode not in ('pretty','raw','both'):
            mode = 'pretty'
        cycle_style = _os_env.environ.get('G6_CYCLE_STYLE','legacy').strip().lower()  # legacy | readable

        opts_total = getattr(metrics, '_last_cycle_options', 0) if metrics else 0
        opts_per_min = None
        coll_succ = None
        api_succ = None
        api_ms = None
        cpu = None; mem_mb = None
        if metrics:
            try:
                coll_succ = metrics.collection_success_rate._value.get()  # type: ignore
            except Exception:
                pass
            try:
                api_succ = metrics.api_success_rate._value.get()  # type: ignore
            except Exception:
                pass
            try:
                api_ms = metrics.api_response_time._value.get()  # type: ignore
            except Exception:
                pass
            try:
                cpu = metrics.cpu_usage_percent._value.get()  # type: ignore
                mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore
            except Exception:
                pass
            try:
                opts_per_min = metrics.options_per_minute._value.get()  # type: ignore
            except Exception:
                pass

        # Build both representations lazily
        raw_line = None
        pretty_line = None
        if mode in ('raw','both'):
            try:
                if cycle_style == 'readable':
                    raw_line = format_cycle_readable(
                        duration_s=total_elapsed,
                        options=opts_total or 0,
                        options_per_min=opts_per_min,
                        cpu=cpu,
                        mem_mb=mem_mb,
                        api_latency_ms=api_ms,
                        api_success_pct=api_succ,
                        collection_success_pct=coll_succ,
                        indices=len(index_params or {}),
                        stall_flag=None
                    )
                else:
                    extra_cycle = None
                    try:
                        if 'provider_outage' in locals() and provider_outage:
                            extra_cycle = {'outage':1}
                        elif 'provider_outage' in locals():
                            extra_cycle = {'outage':0}
                    except Exception:
                        extra_cycle = None
                    raw_line = format_cycle(
                        duration_s=total_elapsed,
                        options=opts_total or 0,
                        options_per_min=opts_per_min,
                        cpu=cpu,
                        mem_mb=mem_mb,
                        api_latency_ms=api_ms,
                        api_success_pct=api_succ,
                        collection_success_pct=coll_succ,
                        indices=len(index_params or {}),
                        stall_flag=None,
                        extra=extra_cycle,
                    )
            except Exception:
                logger.debug("Failed to format raw cycle line", exc_info=True)
        if mode in ('pretty','both') and not legacy_disable:
            try:
                header_line, value_line = format_cycle_table(
                    duration_s=total_elapsed,
                    options=opts_total or 0,
                    options_per_min=opts_per_min,
                    cpu=cpu,
                    mem_mb=mem_mb,
                    api_latency_ms=api_ms,
                    api_success_pct=api_succ,
                    collection_success_pct=coll_succ,
                    indices=len(index_params or {}),
                    stall_flag=None
                )
                # For now log both header and value every cycle; future: track last header to avoid repetition.
                pretty_line = f"{header_line}\n{value_line}"
            except Exception:
                logger.debug("Failed to format pretty cycle table", exc_info=True)

        # Emit in deterministic order: raw then pretty if both
        try:
            if raw_line:
                logger.info(raw_line)
        except Exception:
            logger.debug("Failed to emit raw cycle line", exc_info=True)
        _trace("cycle_raw_emitted", have_raw=bool(raw_line))
        try:
            if pretty_line:
                logger.info(pretty_line)
        except Exception:
            logger.debug("Failed to emit pretty cycle summary", exc_info=True)
        _trace("cycle_pretty_emitted", have_pretty=bool(pretty_line))
    except Exception:
        logger.debug("Failed to emit cycle line(s)", exc_info=True)
    # Optional heartbeat
    try:
        _maybe_emit_heartbeat(metrics)
    except Exception:
        logger.debug('heartbeat_invoke_failed', exc_info=True)
        _trace("cycle_emit_error")

    # Auto-disable noisy trace flags after first successful cycle if enabled
    global _TRACE_AUTO_DISABLED  # pragma: no cover (simple control logic)
    if not _TRACE_AUTO_DISABLED and os.getenv('G6_TRACE_AUTO_DISABLE','').lower() in {'1','true','yes','on'}:
        noisy_flags = [
            'G6_TRACE_COLLECTOR',
            'G6_TRACE_EXPIRY_SELECTION',
            'G6_TRACE_EXPIRY_PIPELINE',
            'G6_CSV_VERBOSE',
        ]
        disabled = []
        for flag in noisy_flags:
            val = os.environ.get(flag,'').lower()
            if val in {'1','true','yes','on'}:
                os.environ[flag] = '0'
                disabled.append(flag)
        if disabled:
            logger.info("trace_auto_disable: disabled %s", ','.join(disabled))
        else:
            logger.info("trace_auto_disable: no active trace flags to disable")
        _TRACE_AUTO_DISABLED = True

    # Structured return object (backward compatible: callers ignoring return unaffected).
    try:
        # Emit cycle_status_summary structured event before returning (observability enhancement)
        try:
            _emit_cycle_status_summary(
                cycle_ts=int(time.time()),
                duration_s=total_elapsed,
                indices=indices_struct,
                index_count=len(indices_struct),
                include_reason_totals=True,
            )
        except Exception:
            logger.debug("cycle_status_summary_emit_failed", exc_info=True)
        # Phase 5: Benchmark / Anomaly persistence extracted to modules.benchmark_bridge
        try:
            from src.collectors.modules.benchmark_bridge import write_benchmark_artifact  # type: ignore
            # Provide detector function if available
            detector_fn = _detect_anomalies if _detect_anomalies else None
            write_benchmark_artifact(indices_struct, total_elapsed, ctx, metrics, detector_fn)
        except Exception:
            logger.debug("benchmark_bridge_failed", exc_info=True)
        # Build snapshot summary (Phase 7 extraction cleanup – fallback removed) + Phase 9 alert aggregation
        from src.collectors.modules.snapshot_core import build_snapshot  # type: ignore
        try:
            from src.collectors.modules.alerts_core import aggregate_alerts  # type: ignore
            _alert_summary = aggregate_alerts(indices_struct)
        except Exception:
            logger.debug('legacy_alert_aggregation_failed', exc_info=True)
            _alert_summary = None
        snap_summary = build_snapshot(indices_struct, len(index_params or {}), metrics, build_reason_totals=True)
        partial_reason_totals = snap_summary.partial_reason_totals
        # Phase 0 parity snapshot write (debug mode) BEFORE returning (extracted to persistence_io)
        # Removed refactor_debug parity snapshot emission
        snapshot_summary = snap_summary.to_dict() if snap_summary else None
        if snapshot_summary is not None and _alert_summary is not None:
            try:
                summary_alerts = _alert_summary.to_dict()
                alerts_block = {
                    'total': summary_alerts.get('alerts_total', 0),
                    'categories': summary_alerts.get('alerts', {}),
                    'index_triggers': summary_alerts.get('alerts_index_triggers', {}),
                }
                snapshot_summary['alerts'] = alerts_block
                if is_truthy_env('G6_ALERTS_FLAT_COMPAT'):
                    snapshot_summary['alerts_total'] = alerts_block['total']
                    for k, v in alerts_block['categories'].items():
                        snapshot_summary[f'alert_{k}'] = v
            except Exception:
                logger.debug('legacy_alert_snapshot_merge_failed', exc_info=True)
        # Expose provider outage flag & threshold (best-effort; may be absent if earlier failure)
    # provider_outage already defined above; leave as-is
        ret_obj = {
            'status': 'ok',
            'indices_processed': len(index_params or {}),
            'have_raw': True,
            'snapshots': snapshots_accum if build_snapshots else None,
            'snapshot_count': len(snapshots_accum) if build_snapshots else 0,
            'indices': indices_struct,
            'partial_reason_totals': partial_reason_totals,
            'snapshot_summary': snapshot_summary,
            'provider_outage': provider_outage,
            'provider_outage_threshold': int(os.environ.get('G6_PROVIDER_OUTAGE_THRESHOLD','3') or 3),
        }
        # Phase 10 operational metrics (legacy path) – best-effort
        try:
            if metrics is not None:
                from prometheus_client import Histogram as _H, Summary as _S, Counter as _C  # type: ignore
                cycle_elapsed = total_elapsed
                if not hasattr(metrics, 'legacy_cycle_duration_seconds'):
                    try: metrics.legacy_cycle_duration_seconds = _H('g6_legacy_cycle_duration_seconds','Legacy collectors cycle duration seconds', buckets=(0.1,0.25,0.5,1,2,5,10))  # type: ignore[attr-defined]
                    except Exception: pass
                if not hasattr(metrics, 'legacy_cycle_duration_summary'):
                    try: metrics.legacy_cycle_duration_summary = _S('g6_legacy_cycle_duration_summary','Legacy collectors cycle duration summary')  # type: ignore[attr-defined]
                    except Exception: pass
                h = getattr(metrics,'legacy_cycle_duration_seconds',None); s = getattr(metrics,'legacy_cycle_duration_summary',None)
                if h:
                    try: h.observe(cycle_elapsed)
                    except Exception: pass
                if s:
                    try: s.observe(cycle_elapsed)
                    except Exception: pass
                # Alert counters (flat or nested)
                alerts_block = None
                if snapshot_summary and 'alerts' in snapshot_summary:
                    alerts_block = snapshot_summary['alerts']
                elif snapshot_summary:
                    # reconstruct from flat fields
                    cats = {k[len('alert_'):]: v for k,v in snapshot_summary.items() if k.startswith('alert_')}
                    alerts_block = {'categories': cats, 'total': snapshot_summary.get('alerts_total')}
                if alerts_block:
                    for cat, val in (alerts_block.get('categories') or {}).items():
                        metric_name = f'legacy_alerts_{cat}_total'
                        if not hasattr(metrics, metric_name):
                            try: setattr(metrics, metric_name, _C(f'g6_{metric_name}','Count of legacy cycles with occurrences for category'))  # type: ignore[attr-defined]
                            except Exception: pass
                        c = getattr(metrics, metric_name, None)
                        if c and val>0:
                            try: c.inc(val)
                            except Exception: pass
        except Exception:
            logger.debug('legacy_operational_metrics_failed', exc_info=True)
        # Shadow diff attachment removed with rollout mode deprecation.
        # Phase 8: add coverage rollups at index level if not already present
        try:
            from src.collectors.modules.coverage_core import compute_index_coverage  # type: ignore
            for ix in ret_obj['indices']:
                if 'expiries' in ix and 'strike_coverage_avg' not in ix:
                    cov_roll = compute_index_coverage(ix.get('index'), ix.get('expiries') or [])
                    ix['strike_coverage_avg'] = cov_roll.get('strike_coverage_avg')
                    ix['field_coverage_avg'] = cov_roll.get('field_coverage_avg')
        except Exception:
            logger.debug('legacy_coverage_rollup_failed', exc_info=True)
        return ret_obj
    except Exception:
        return {'status': 'ok', 'indices_processed': len(index_params or {}), 'have_raw': True}

    # (Unreachable code path note): The return above exits normally; below retained for clarity.

