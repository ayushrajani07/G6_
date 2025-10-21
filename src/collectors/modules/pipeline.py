"""Pipeline Orchestrator (Phase 6 – Initial Sequencing)

Implements the first real staged pipeline replacing the previous pure delegation
scaffold. The goal is functional parity with the legacy monolithic
`run_unified_collectors` while routing core per-index/expiry steps through
extracted modules. Scope purposefully excludes certain advanced behaviors on
this first cut (greeks/IV calc, parallelism, structured events richness), all of
which fall back to existing helper usage or log debug placeholders.

Stages (current implementation):
  1. Context bootstrap (CollectorContext) & timers.
  2. Per-index loop:
       a. Fetch ATM strike (best-effort; failure marks EMPTY index).
       b. Fetch raw instruments (provider method heuristic).
       c. Build expiry map via `expiry_universe.build_expiry_map`.
       d. For each expiry (date) build strike list (compute_strike_universe), then
          run coverage + field coverage metrics via `coverage_eval` wrappers.
       e. Enrichment placeholder (future extraction) – minimal option count + statuses.
       f. Adaptive strike logic (`adaptive_post_expiry`).
  3. Aggregate index summary & partial reason tallies.
  4. Benchmark artifact emission via `benchmark_bridge.write_benchmark_artifact`.

Not Yet Implemented (future phases):
  - Greeks/IV initialization & per-expiry greek computations.
  - Snapshot building / return when `build_snapshots` is set (pipeline currently
    returns the same structure legacy would when snapshots disabled; snapshot
    path remains handled by legacy until migrated).
  - Structured events emission parity (some events omitted for brevity; safe).
  - Detailed partial reason classification (placeholder counts kept at zero; can
    be backfilled from legacy logic once isolated cleanly).

Environment Guards:
  - Activated only when `G6_PIPELINE_COLLECTOR=1` in the legacy facade.
  - Internal recursion sentinel (`_G6_PIPELINE_REENTRY`) still used upstream to
    prevent accidental re-entry (pipeline never calls legacy now).

Failure Handling Philosophy:
  - All per-index failures captured; index marked EMPTY with `failures: 1`.
  - Exceptions inside a single expiry continue other expiries; catastrophic
    index-level exception aborts that index only.

Return Shape:
  Mirrors the legacy structured dict used in recent phases when snapshots are
  disabled:
    {
      'status': 'ok',
      'indices_processed': N,
      'have_raw': True/False,
      'snapshots': None,
      'snapshot_count': 0,
      'indices': [ { index summary ... } ],
      'partial_reason_totals': {...}
    }

Parity Note:
  Some fields (e.g., detailed partial_reason tallies) may remain zero in early
  pipeline mode if legacy logic previously populated them deep inside helpers.
  This is acceptable for the first sequencing milestone; tests focusing on
  benchmark/anomaly paths continue to pass (artifact emission unaffected).
"""
from __future__ import annotations

import datetime
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import (
  Any,
  Protocol,
  TypedDict,
  cast,
)

from src.collectors.pipeline.errors import PhaseFatalError, PhaseRecoverableError

# Logging schema import (phase_log structure used for consistent event framing)
from src.collectors.pipeline.logging_schema import phase_log

from .context import CollectorContext, build_collector_context
from .strike_depth import compute_strike_universe

# Optional dynamic helpers (annotated as Optional so None assignment type-safe)
_resolve_strike_depth: Callable[[CollectorContext, str, dict[str, Any]], tuple[int, int]] | None = None
try:  # optional runtime dependency
  from .strike_policy import resolve_strike_depth as _resolve_strike_depth  # noqa: F401
except Exception:  # pragma: no cover
  _resolve_strike_depth = None  # fallback when unavailable
from .coverage_eval import coverage_metrics, field_coverage_metrics
from .enrichment import enrich_quotes
from .expiry_universe import build_expiry_map

_enrich_quotes_async: Callable[[str, str, datetime.date, list[dict[str, Any]], Any, Any], dict[str, Any]] | None = None
try:  # Phase 9 optional async enrichment (top-level import for clarity)
  from .enrichment_async import enrich_quotes_async as _enrich_quotes_async  # noqa: F401
except Exception:  # pragma: no cover
  _enrich_quotes_async = None
from .adaptive_adjust import adaptive_post_expiry

# Phase 9 status finalization parity imports (lazy guarded inside loop if unavailable)
try:  # compute PARTIAL / OK classification parity with legacy
  from src.collectors.helpers.status_reducer import compute_expiry_status as _compute_expiry_status  # noqa: F401
except Exception:  # pragma: no cover
  # Optional – absence just disables status reduce refinement
  _compute_expiry_status = None
_finalize_expiry: Callable[[dict[str, Any], dict[str, Any], list[int], str, datetime.date, str, Any], None] | None = None
try:  # finalize_expiry attaches partial_reason + emits option_match stats (via facade)
  from .status_finalize_core import finalize_expiry as _finalize_expiry  # noqa: F401
except Exception:  # pragma: no cover
  _finalize_expiry = None  # fallback when finalizer unavailable
from .benchmark_bridge import write_benchmark_artifact
from .preventive_validate import run_preventive_validation

# --- Wave 4 (W4-09) Benchmark Cycle Integration ---------------------------------
# Periodically run a lightweight internal benchmark (legacy vs pipeline collectors)
# and emit delta gauges inside the normal runtime, enabling continuous regression
# visibility without separate CI invocation. Fully gated via env vars:
#   G6_BENCH_CYCLE=1                      -> master enable
#   G6_BENCH_CYCLE_INTERVAL_SECONDS=300   -> minimum seconds between runs (default 300)
#   G6_BENCH_CYCLE_INDICES="NIFTY:1:1"     -> indices spec passed to bench harness
#   G6_BENCH_CYCLE_CYCLES=8               -> number of measurement cycles (small to limit overhead)
#   G6_BENCH_CYCLE_WARMUP=2               -> warmup cycles (discarded)
# Safety / guardrails:
#   * Never blocks main pipeline longer than a soft timeout (~ interval * 0.8 upper bound)
#   * Execution best-effort: any exception suppressed with debug log.
#   * Reuses scripts.bench_collectors in-process (like bench_delta) to avoid code dup.
#   * Will NOT run if prometheus_client unavailable OR metrics object missing.
# Metrics emitted (matching bench_delta naming for continuity):
#   g6_bench_legacy_p50_seconds, g6_bench_pipeline_p50_seconds,
#   g6_bench_legacy_p95_seconds, g6_bench_pipeline_p95_seconds,
#   g6_bench_delta_p50_pct, g6_bench_delta_p95_pct, g6_bench_delta_mean_pct
# -------------------------------------------------------------------------------

_last_bench_cycle_ts: float | None = None

class BenchMetricsLike(Protocol):  # minimal dynamic surface for benchmark gauges
  def __getattr__(self, name: str) -> Any: ...
  def __setattr__(self, name: str, value: Any) -> None: ...

class BenchCycleResult(TypedDict, total=False):  # possible parsed JSON keys
  legacy: dict[str, Any]
  pipeline: dict[str, Any]
  delta: dict[str, Any]

def _parse_bench_output(out_txt: str) -> BenchCycleResult:
  """Parse bench harness JSON output defensively.

  Keeps result shape permissive; missing sections yield empty dicts.
  """
  import json
  try:
    data = json.loads(out_txt)
    if not isinstance(data, dict):  # pragma: no cover
      return {}
    return {
      'legacy': data.get('legacy', {}) if isinstance(data.get('legacy'), dict) else {},
      'pipeline': data.get('pipeline', {}) if isinstance(data.get('pipeline'), dict) else {},
      'delta': data.get('delta', {}) if isinstance(data.get('delta'), dict) else {},
    }
  except Exception:  # pragma: no cover
    return {}

def _maybe_run_benchmark_cycle(metrics: BenchMetricsLike | None) -> None:
  import json
  import logging
  import os
  import time
  global _last_bench_cycle_ts
  if os.getenv('G6_BENCH_CYCLE','0').lower() not in ('1','true','yes','on'):
    return
  now = time.time()
  # Early ensure threshold gauge exists if env configured even if we later return due to interval gating.
  try:
    from prometheus_client import Gauge as _EarlyG
    thr_env_pre = os.getenv('G6_BENCH_P95_ALERT_THRESHOLD')
    if thr_env_pre is not None and metrics is not None and not hasattr(metrics, 'bench_p95_regression_threshold_pct'):
      try:
        g_pre = _EarlyG('g6_bench_p95_regression_threshold_pct','Configured allowed p95 regression % threshold (early)')
        try:
          v_pre = float(thr_env_pre)
          g_pre.set(v_pre)
        except Exception:
          pass
        metrics.bench_p95_regression_threshold_pct = g_pre
      except Exception:
        pass
  except Exception:
    pass
  try:
    interval = float(os.getenv('G6_BENCH_CYCLE_INTERVAL_SECONDS','300') or 300)
  except Exception:
    interval = 300.0
  # Interval <= 0 disables gating (run every invocation)
  if interval < 0:
    interval = 0.0
  if interval > 0 and _last_bench_cycle_ts is not None and (now - _last_bench_cycle_ts) < interval:
    return
  # Soft concurrency guard: update timestamp early to avoid thundering herd
  _last_bench_cycle_ts = now
  logger = logging.getLogger('src.collectors.pipeline')
  if metrics is None:
    return
  try:
    from prometheus_client import Gauge as _G
  except Exception:
    return
  # Import bench_collectors in-process (same pattern as bench_delta)
  bench_mod: Any | None = None
  try:
    import scripts.bench_collectors as _bench_mod
    bench_mod = cast(Any, _bench_mod)
  except Exception:  # pragma: no cover
    bench_mod = None
  if bench_mod is None:
    logger.debug('benchmark_cycle_import_failed')
    return
  indices_spec = os.getenv('G6_BENCH_CYCLE_INDICES','NIFTY:1:1')
  try:
    cycles = int(os.getenv('G6_BENCH_CYCLE_CYCLES','8') or 8)
  except Exception:
    cycles = 8
  try:
    warmup = int(os.getenv('G6_BENCH_CYCLE_WARMUP','2') or 2)
  except Exception:
    warmup = 2
  # Guard upper bounds to avoid runaway overhead
  if cycles > 40:
    cycles = 40
  if warmup > 10:
    warmup = 10
  # Execute harness capturing its stdout JSON (mirror bench_delta.run_bench logic)
  import io
  import sys
  argv_backup = sys.argv[:]
  sys.argv = [sys.argv[0], '--indices', indices_spec, '--cycles', str(cycles), '--warmup', str(warmup), '--json']
  buf = io.StringIO()
  try:
    from contextlib import redirect_stdout
    with redirect_stdout(buf):
      bench_mod.main()
    out_txt = buf.getvalue().strip()
    result = json.loads(out_txt)
  except Exception:
    logger.debug('benchmark_cycle_run_failed', exc_info=True)
    return
  finally:
    sys.argv = argv_backup
  parsed = _parse_bench_output(out_txt)
  legacy = parsed.get('legacy', {})
  pipeline = parsed.get('pipeline', {})
  delta = parsed.get('delta', {})
  # Lazily create gauges if not present (attach to metrics object for reuse)
  def _lazy(name: str, desc: str) -> Any | None:
    if not hasattr(metrics, name):
      try:
        setattr(metrics, name, _G(f'g6_{name}', desc))
      except Exception:
        setattr(metrics, name, None)
    return getattr(metrics, name, None)
  g_legacy_p50 = _lazy('bench_legacy_p50_seconds','Legacy collector p50 latency (s)')
  g_pipeline_p50 = _lazy('bench_pipeline_p50_seconds','Pipeline collector p50 latency (s)')
  g_legacy_p95 = _lazy('bench_legacy_p95_seconds','Legacy collector p95 latency (s)')
  g_pipeline_p95 = _lazy('bench_pipeline_p95_seconds','Pipeline collector p95 latency (s)')
  g_delta_p50 = _lazy('bench_delta_p50_pct','Delta p50 % pipeline vs legacy')
  g_delta_p95 = _lazy('bench_delta_p95_pct','Delta p95 % pipeline vs legacy')
  g_delta_mean = _lazy('bench_delta_mean_pct','Delta mean % pipeline vs legacy')
  # Threshold gauge (W4-10) for alert rule comparison (unified logic)
  thr_env = os.getenv('G6_BENCH_P95_ALERT_THRESHOLD')
  if thr_env is not None:
    try:
      thr_val = float(thr_env)
    except Exception:
      logger.debug('benchmark_cycle_threshold_parse_failed', extra={'value': thr_env})
    else:
      g_thr = _lazy('bench_p95_regression_threshold_pct','Configured allowed p95 regression % threshold')
      if g_thr:
        try: g_thr.set(thr_val)
        except Exception: pass
  try:
    if g_legacy_p50 and legacy.get('p50_s') is not None: g_legacy_p50.set(float(legacy['p50_s']))
    if g_pipeline_p50 and pipeline.get('p50_s') is not None: g_pipeline_p50.set(float(pipeline['p50_s']))
    if g_legacy_p95 and legacy.get('p95_s') is not None: g_legacy_p95.set(float(legacy['p95_s']))
    if g_pipeline_p95 and pipeline.get('p95_s') is not None: g_pipeline_p95.set(float(pipeline['p95_s']))
    if g_delta_p50 and delta.get('p50_pct') is not None: g_delta_p50.set(float(delta['p50_pct']))
    if g_delta_p95 and delta.get('p95_pct') is not None: g_delta_p95.set(float(delta['p95_pct']))
    if g_delta_mean and delta.get('mean_pct') is not None: g_delta_mean.set(float(delta['mean_pct']))
  except Exception:
    logger.debug('benchmark_cycle_metric_set_failed', exc_info=True)
  logger.debug('benchmark_cycle_run_complete', extra={'cycles': cycles, 'indices': indices_spec})

logger = logging.getLogger(__name__)

# --- Wave 4 Taxonomy Mapping Reference (W4-01) ---
# Phase -> Failure classification rules:
#   atm: provider exception => recoverable (index continues if other expiries viable)
#   instrument_fetch: provider method resolution failure or empty universe => PhaseFatalError
#   expiry_map: build_expiry_map structural error => PhaseFatalError
#   strike_universe: computation error => recoverable (exp strikes empty -> downstream low coverage)
#   enrich: async fail -> recoverable warn; sync fail -> recoverable (expiry still represented)
#   preventive_validate: internal validation exception -> recoverable warn
#   coverage: strike or field coverage calculation error -> recoverable warn
#   finalize: finalize_expiry exception -> PhaseRecoverableError (expiry-level only)
#   adaptive: adaptive_post_expiry exception -> recoverable warn
#   parity scoring / metrics emission: never fatal; degrade silently
#   snapshot merge: alerts integration failure -> recoverable (log debug)
#   benchmark artifact: write failure -> recoverable (debug log)
# Invariants:
#   * No bare except blocks: taxonomy errors surfaced explicitly.
#   * Only fatal escalations for index-wide preconditions (instrument universe & expiry map).
#   * All expiry-level anomalies captured as recoverable to preserve partial observability.
# Any new phase must document classification here and in PIPELINE_DESIGN.md.
# --------------------------------------------------

def _detect_anomalies(series: list[float], threshold: float) -> tuple[list[bool], list[float]]:
  """Median+MAD robust z-score detector (small duplication to avoid legacy import)."""
  import statistics
  if not series:
    return [], []
  med = statistics.median(series)
  mad_vals = [abs(x - med) for x in series]
  mad = statistics.median(mad_vals) if mad_vals else 0.0
  # Fallback to stdev style if MAD zero (flat series) – scores all zeros
  if mad == 0:
    return [False]*len(series), [0.0]*len(series)
  scores = [0.6745 * (x - med) / mad for x in series]
  flags = [abs(s) >= threshold for s in scores]
  return flags, scores

def run_pipeline(
    index_params: Mapping[str, dict[str, Any]],
    providers: Any,
    csv_sink: Any,
    influx_sink: Any,
    metrics: Any | None = None,
    *,
    compute_greeks: bool = False,
    risk_free_rate: float = 0.05,
    estimate_iv: bool = False,
    iv_max_iterations: int | None = None,
    iv_min: float | None = None,
    iv_max: float | None = None,
    iv_precision: float | None = None,
    build_snapshots: bool = False,
    legacy_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:  # noqa: D401
  """Run collectors via staged pipeline (synthetic quote fallback removed)."""
  start_wall = time.time()
  phase_timings = {}
  ctx: CollectorContext = build_collector_context(index_params=index_params, metrics=metrics, debug=os.environ.get('G6_COLLECTOR_REFACTOR_DEBUG','').lower() in ('1','true','yes','on'))
  indices_struct: list[dict[str, Any]] = []
  # Partial reason tallies (may be replaced by snapshot summary; keep explicit type)
  partial_reason_totals: dict[str, int] = { 'low_strike': 0, 'low_field': 0, 'low_both': 0, 'unknown': 0 }
  # Latency profiling accumulators (Phase 10 Task 7)
  enrich_phase_durations: list[float] = []  # per-expiry enrichment duration
  finalize_phase_durations: list[float] = []  # per-expiry finalize_expiry duration
  provider_call_durations: dict[str, list[float]] = { 'atm': [], 'instrument_fetch': [] }
  # Use taxonomy-aware phase_log
  for index_symbol, cfg in index_params.items():
    index_start = time.time()
    expiries_out: list[dict[str, Any]] = []
    failures = 0
    attempts = 0
    option_count_total = 0
    status = 'EMPTY'
    try:
      attempts += 1
      # ATM strike (best-effort)
      with phase_log('atm', index=index_symbol, rule='n/a') as rec:
        try:
            _t0_atm = time.time()
            atm = providers.get_atm_strike(index_symbol)
            provider_call_durations['atm'].append(time.time() - _t0_atm)
            rec.add_meta(found=bool(atm))
        except Exception:
            atm = None
            rec.warn(reason='fetch_error')
            logger.debug('pipeline_atm_failed', exc_info=True)
      # Raw instruments fetch – heuristic method names
      instruments = []
      fetched = False
      for meth_name in ('get_instrument_chain','get_option_chain','get_instruments'):
        if hasattr(providers, meth_name):
          try:
            _t0_fetch = time.time()
            instruments = getattr(providers, meth_name)(index_symbol)
            provider_call_durations['instrument_fetch'].append(time.time() - _t0_fetch)
            fetched = True
            break
          except Exception:
            logger.debug('pipeline_instruments_fetch_failed', extra={'method': meth_name}, exc_info=True)
      if not fetched:
        raise PhaseFatalError('instrument_fetch_failed')
      if not instruments:
        raise PhaseFatalError('empty_instrument_universe')
      # Expiry map
      with phase_log('expiry_map', index=index_symbol, rule='n/a') as rec:
        try:
          expiry_map, expiry_stats = build_expiry_map(instruments)
          rec.add_meta(expiry_count=len(expiry_map))
        except Exception:
          rec.fail(reason='map_error')
          logger.debug('pipeline_expiry_map_failed', exc_info=True)
          raise PhaseFatalError('expiry_map_error')
      # Iterate expiries (date ordered)
      for expiry_date in sorted(expiry_map.keys()):
        exp_instruments = expiry_map[expiry_date]
        rule = _infer_expiry_rule(expiry_date)
        # Strike universe
        if _resolve_strike_depth is not None:
          try:
            dynamic_itm, dynamic_otm = _resolve_strike_depth(ctx, index_symbol, cfg)
            strikes_itm = int(dynamic_itm)
            strikes_otm = int(dynamic_otm)
          except Exception:
            logger.debug('pipeline_strike_policy_failed', exc_info=True)
            strikes_itm = int(cfg.get('strikes_itm', 2) or 2)
            strikes_otm = int(cfg.get('strikes_otm', 2) or 2)
        else:
            strikes_itm = int(cfg.get('strikes_itm', 2) or 2)
            strikes_otm = int(cfg.get('strikes_otm', 2) or 2)
        with phase_log('strike_universe', index=index_symbol, rule=rule) as rec:
          try:
            strikes, strikes_meta = compute_strike_universe(atm or 0, strikes_itm, strikes_otm, index_symbol)
            rec.add_meta(strikes_itm=strikes_itm, strikes_otm=strikes_otm, strike_count=len(strikes))
          except Exception:
            rec.fail(reason='strike_universe_error')
            logger.debug('pipeline_strike_universe_failed', exc_info=True)
            strikes = []
            strikes_meta = {}
        # Enrichment (quotes)
        enriched = {}
        synthetic_used_flag = False
        async_flag = os.environ.get('G6_ENRICH_ASYNC','0').lower() in ('1','true','on','yes') and _enrich_quotes_async is not None
        _t0_enrich = time.time()
        with phase_log('enrich', index=index_symbol, rule=rule) as rec:
          rec.add_meta(async_enabled=bool(async_flag))
          if async_flag and _enrich_quotes_async is not None:
            try:
              enriched = _enrich_quotes_async(index_symbol, rule, expiry_date, exp_instruments, providers, metrics)  # dynamic async enrichment call
            except Exception:
              rec.warn(reason='async_fail')
              logger.debug('pipeline_enrichment_async_failed', exc_info=True)
          if not enriched:
            try:
              enriched = enrich_quotes(index_symbol, rule, expiry_date, exp_instruments, providers, metrics)
            except Exception:
              rec.fail(reason='sync_fail')
              logger.debug('pipeline_enrichment_failed', exc_info=True)
          rec.add_meta(enriched_count=len(enriched))
        enrich_phase_durations.append(time.time() - _t0_enrich)
        cleaned_enriched = enriched
        with phase_log('preventive_validate', index=index_symbol, rule=rule) as rec:
          try:
            cleaned_enriched, prevent_report = run_preventive_validation(index_symbol, rule, expiry_date, exp_instruments, enriched, None)
          except Exception:
            rec.warn(reason='validate_fail')
            logger.debug('pipeline_preventive_validation_failed', exc_info=True)
        strike_cov: float | None = None
        field_cov: float | None = None
        with phase_log('coverage', index=index_symbol, rule=rule) as rec:
          try:
            cov_any = coverage_metrics(ctx, exp_instruments, strikes, index_symbol, rule, expiry_date)
            cov_dict2: dict[str, Any] | None = cov_any if isinstance(cov_any, dict) else None
            if cov_dict2 is not None:
              _tmp_sc = cov_dict2.get('strike_coverage')
              if isinstance(_tmp_sc, (int, float)):
                strike_cov = float(_tmp_sc)
          except Exception:
            rec.warn(reason='strike_cov_fail')
            logger.debug('pipeline_strike_coverage_failed', exc_info=True)
          try:
            fcov_any = field_coverage_metrics(ctx, cleaned_enriched, index_symbol, rule, expiry_date)
            fcov_dict2: dict[str, Any] | None = fcov_any if isinstance(fcov_any, dict) else None
            if fcov_dict2 is not None:
              _tmp_fc = fcov_dict2.get('field_coverage')
              if isinstance(_tmp_fc, (int, float)):
                field_cov = float(_tmp_fc)
          except Exception:
            rec.warn(reason='field_cov_fail')
            logger.debug('pipeline_field_coverage_failed', exc_info=True)
          rec.add_meta(strike_cov=strike_cov, field_cov=field_cov)
        opt_cnt = len(exp_instruments)
        option_count_total += opt_cnt
        expiry_rec = {
          'rule': rule,
          'status': 'OK' if opt_cnt > 0 else 'EMPTY',
          'options': opt_cnt,
          'strike_coverage': strike_cov,
          'field_coverage': field_cov,
          'partial_reason': None,
          'synthetic_quotes': False,
        }
        with phase_log('status_reduce', index=index_symbol, rule=rule) as rec:
          if _compute_expiry_status is not None:
            try:
              # _compute_expiry_status returns a string classification
              status_val = _compute_expiry_status(expiry_rec)
              if isinstance(status_val, str):
                expiry_rec['status'] = status_val
            except Exception:
              rec.warn(reason='status_reduce_fail')
              logger.debug('pipeline_compute_expiry_status_failed', exc_info=True)
        if _finalize_expiry is not None:
          _t0_finalize = time.time()
          with phase_log('finalize', index=index_symbol, rule=rule) as rec:
            try:
              int_strikes: list[int] = []
              for s in (strikes or []):
                try:
                  int_strikes.append(int(s))
                except Exception:
                  continue
              _finalize_expiry(expiry_rec, cleaned_enriched, int_strikes, index_symbol, expiry_date, rule, metrics)
              rec.add_meta(partial=bool(expiry_rec.get('partial_reason')))
            except Exception as e:
              rec.fail(reason='finalize_fail')
              logger.debug('pipeline_finalize_expiry_failed', exc_info=True)
              # Raise recoverable error for expiry-level failure
              raise PhaseRecoverableError(f'finalize_expiry_failed: {e}')
            finally:
              finalize_phase_durations.append(time.time() - _t0_finalize)
        expiries_out.append(expiry_rec)
        with phase_log('adaptive', index=index_symbol, rule=rule) as rec:
          try:
            adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule)
          except Exception:
            rec.warn(reason='adaptive_fail')
            logger.debug('pipeline_adaptive_post_failed', exc_info=True)
      status = 'OK' if option_count_total > 0 else 'EMPTY'
    except PhaseRecoverableError as e:
      failures += 1
      logging.getLogger('src.collectors.pipeline').error('pipeline_index_failed', extra={'index': index_symbol, 'kind': 'recoverable', 'error': str(e)})
      try:  # taxonomy counter increment (recoverable)
        from src.metrics import get_counter, get_metrics_singleton
        # Ensure registry exists so counter attaches to real registry rather than local fallback
        try:
          get_metrics_singleton()
        except Exception:
          pass
        get_counter('pipeline_expiry_recoverable_total','Recoverable expiry-level failures', []).inc()
      except Exception:
        pass
      if not expiries_out:
        expiries_out.append({'failed': True, 'reason': str(e)})
    except PhaseFatalError as e:
      failures += 1
      logging.getLogger('src.collectors.pipeline').error('pipeline_index_failed', extra={'index': index_symbol, 'kind': 'fatal', 'error': str(e)})
      try:  # taxonomy counter increment (fatal)
        from src.metrics import get_counter, get_metrics_singleton
        try:
          get_metrics_singleton()
        except Exception:
          pass
        get_counter('pipeline_index_fatal_total','Fatal index-level failures', []).inc()
      except Exception:
        pass
      if not expiries_out:
        expiries_out.append({'failed': True, 'reason': str(e)})
      status = 'EMPTY'
    elapsed_index = time.time() - index_start
    # Coverage rollup (Phase 8) – compute index-level averages from built expiries
    try:
      from .coverage_core import compute_index_coverage
      cov_rollup = compute_index_coverage(index_symbol, expiries_out)
      strike_cov_avg = cov_rollup.get('strike_coverage_avg')
      field_cov_avg = cov_rollup.get('field_coverage_avg')
    except Exception:
      logger.debug('pipeline_index_coverage_rollup_failed', exc_info=True)
      strike_cov_avg = None; field_cov_avg = None
    indices_struct.append({
      'index': index_symbol,
      'attempts': attempts,
      'failures': failures,
      'option_count': option_count_total,
      'status': status,
      'expiries': expiries_out,
      'elapsed_s': elapsed_index,
      'strike_coverage_avg': strike_cov_avg,
      'field_coverage_avg': field_cov_avg,
    })

  # (Moved parity logging after snapshot assembly to avoid unbound snapshot_summary)
  total_elapsed = time.time() - start_wall
  # Benchmark artifact (anomalies) – pass anomaly detector
  try:
    write_benchmark_artifact(indices_struct, total_elapsed, ctx_like=ctx, metrics=metrics, detect_anomalies_fn=lambda series, thr: _detect_anomalies(series, thr))
  except Exception:
    logger.debug('pipeline_benchmark_artifact_failed', exc_info=True)
  # Phase 9: alert aggregation prior to snapshot summary
  try:
    from .alerts_core import aggregate_alerts
    alert_summary = aggregate_alerts(indices_struct)
  except Exception:
    logger.debug('pipeline_alert_aggregation_failed', exc_info=True)
    alert_summary = None
  phase_timings['alerts'] = time.time() - start_wall - total_elapsed  # approximate post main loop delta
  # Phase 7: build snapshot summary (fallback removed post-stabilization)
  from .snapshot_core import build_snapshot
  snap_summary = build_snapshot(indices_struct, len(indices_struct), metrics, build_reason_totals=True)
  # Snapshot summary may provide refined partial_reason_totals (ensure dict type preserved)
  if getattr(snap_summary, 'partial_reason_totals', None):
    _prt = snap_summary.partial_reason_totals
    if isinstance(_prt, dict):
      # Defensive: ensure int values (fallback to previous if unexpected types)
      try:
        partial_reason_totals = {k: int(v) for k, v in _prt.items()}
      except Exception:
        pass
  snapshot_summary = snap_summary.to_dict() if snap_summary else None
  # Parity scoring invocation (Wave 2 + rolling aggregation Wave 3 + alert parity enhancements)
  if os.environ.get('G6_PIPELINE_PARITY_LOG','0').lower() in ('1','true','on','yes') and legacy_baseline is not None:
    _plogger = logging.getLogger('src.collectors.pipeline')
    try:
      from src.collectors.pipeline.parity import compute_parity_score, record_parity_score
      pipeline_view: dict[str, Any] = {'indices': indices_struct}
      try:
        if snapshot_summary and isinstance(snapshot_summary, dict) and 'alerts' in snapshot_summary:
          pipeline_view['alerts'] = snapshot_summary['alerts']
      except Exception:
        pass
      parity_score = compute_parity_score(legacy_baseline, pipeline_view)
      score_val = parity_score.get('score')
      rolling_info = record_parity_score(score_val)
      alerts_detail = None
      try:
        alerts_detail = parity_score.get('details',{}).get('alerts')
      except Exception:
        alerts_detail = None
      _plogger.info('pipeline_parity_score', extra={'score': score_val, 'components': parity_score.get('components'), 'missing': parity_score.get('missing'), 'version': parity_score.get('version'), 'rolling_avg': rolling_info.get('avg'), 'rolling_count': rolling_info.get('count'), 'rolling_window': rolling_info.get('window'), 'alerts_detail': alerts_detail})
      try:
        if metrics is not None and rolling_info.get('window',0) and rolling_info.get('avg') is not None:
          from prometheus_client import Gauge as _G
          if not hasattr(metrics, 'pipeline_parity_rolling_avg'):
            try: metrics.pipeline_parity_rolling_avg = _G('g6_pipeline_parity_rolling_avg','Rolling average pipeline parity score')
            except Exception: pass
          g = getattr(metrics,'pipeline_parity_rolling_avg',None)
          if g:
            # rolling_info['avg'] is float | None; guard before coercion
            try:
              avg_val = rolling_info.get('avg')
            except Exception:
              avg_val = None
            if avg_val is not None:
              try:
                g.set(float(avg_val))
              except Exception:
                pass
        # Alert mismatch gauge
        try:
          details_block = parity_score.get('details') if isinstance(parity_score, dict) else None
          alerts_dict: dict[str, Any] | None = None
          if isinstance(details_block, dict):
            _alerts_tmp = details_block.get('alerts')
            if isinstance(_alerts_tmp, dict):
              alerts_dict = _alerts_tmp
          if metrics is not None and alerts_dict is not None:
            from prometheus_client import Gauge as _G
            if not hasattr(metrics, 'pipeline_alert_parity_diff'):
              try: metrics.pipeline_alert_parity_diff = _G('g6_pipeline_alert_parity_diff','Weighted normalized alert parity difference (0 perfect, 1 worst)')
              except Exception: pass
            _alerts = alerts_dict
            frac: float | None = None
            if _alerts is not None:
              if 'weighted_diff_norm' in _alerts:
                frac_val = _alerts.get('weighted_diff_norm')
                try:
                  if frac_val is not None:
                    frac = float(frac_val)
                except Exception:
                  frac = None
              elif 'sym_diff' in _alerts and 'union' in _alerts:
                try:
                  union = _alerts.get('union') or 0
                  sym = _alerts.get('sym_diff') or 0
                  frac = (sym / union) if union else 0.0
                except Exception:
                  frac = None
            if frac is not None:
              g2 = getattr(metrics,'pipeline_alert_parity_diff', None)
              if g2:
                try: g2.set(float(frac))
                except Exception: pass
            # Anomaly structured event emission (Wave 4 W4-15)
            try:
              from src.collectors.pipeline.anomaly import maybe_emit_alert_parity_anomaly
              # ParityResult is a TypedDict-like dict; ensure plain dict for function expectation
              if isinstance(parity_score, dict):
                from typing import cast as _cast
                maybe_emit_alert_parity_anomaly(_cast(dict[str, Any], parity_score))
            except Exception:
              _plogger.debug('pipeline_parity_anomaly_emit_failed', exc_info=True)
        except Exception:
          _plogger.debug('pipeline_alert_parity_metric_failed', exc_info=True)
      except Exception:
        _plogger.debug('pipeline_parity_rolling_metric_failed', exc_info=True)
    except Exception:
      _plogger.debug('pipeline_parity_score_failed', exc_info=True)
  if snapshot_summary is not None and alert_summary is not None:
    try:
      summary_alerts = alert_summary.to_dict()  # {'alerts_total','alerts', 'alerts_index_triggers'}
      # New Phase 10 canonical nesting: snapshot_summary['alerts'] holds categories & total
      alerts_block = {
        'total': summary_alerts.get('alerts_total', 0),
        'categories': summary_alerts.get('alerts', {}),
        'index_triggers': summary_alerts.get('alerts_index_triggers', {}),
      }
      sev_map = summary_alerts.get('alerts_severity')
      if isinstance(sev_map, dict) and sev_map:
        alerts_block['severity'] = sev_map
      snapshot_summary['alerts'] = alerts_block
      # Optional backward compatibility: export flat fields if flag set
      if os.environ.get('G6_ALERTS_FLAT_COMPAT','1').lower() in ('1','true','yes','on'):
        snapshot_summary['alerts_total'] = alerts_block['total']
        for k, v in alerts_block['categories'].items():
          snapshot_summary[f'alert_{k}'] = v
    except Exception:
      logger.debug('pipeline_snapshot_alert_merge_failed', exc_info=True)
  # Operational metrics (Phase 10) – best-effort
  total_cycle_s: float = time.time() - start_wall
  try:
    if metrics is not None:
      from prometheus_client import Counter as _C
      from prometheus_client import Gauge as _G
      from prometheus_client import Histogram as _H
      from prometheus_client import Summary as _S
      # Cycle duration histogram (bucket selection conservative)
      if not hasattr(metrics, 'pipeline_cycle_duration_seconds'):
        try:
          metrics.pipeline_cycle_duration_seconds = _H('g6_pipeline_cycle_duration_seconds','Pipeline cycle duration seconds', buckets=(0.05,0.1,0.25,0.5,1,2,5,10))
        except Exception: pass
      if not hasattr(metrics, 'pipeline_cycle_duration_summary'):
        try:
          metrics.pipeline_cycle_duration_summary = _S('g6_pipeline_cycle_duration_summary','Pipeline cycle duration summary')
        except Exception: pass
      h = getattr(metrics,'pipeline_cycle_duration_seconds',None)
      s_summary = getattr(metrics,'pipeline_cycle_duration_summary',None)
      if h:
        try: h.observe(total_cycle_s)
        except Exception: pass
      if s_summary:
        try: s_summary.observe(total_cycle_s)
        except Exception: pass
      # Phase latency histograms
      if not hasattr(metrics, 'pipeline_enrich_duration_seconds'):
        try:
          metrics.pipeline_enrich_duration_seconds = _H('g6_pipeline_enrich_duration_seconds','Per-expiry enrichment duration seconds', buckets=(0.001,0.005,0.01,0.02,0.05,0.1,0.25,0.5,1,2))
        except Exception: pass
      if not hasattr(metrics, 'pipeline_finalize_duration_seconds'):
        try:
          metrics.pipeline_finalize_duration_seconds = _H('g6_pipeline_finalize_duration_seconds','Per-expiry finalize_expiry duration seconds', buckets=(0.0005,0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.25))
        except Exception: pass
      _h_enrich = getattr(metrics,'pipeline_enrich_duration_seconds',None)
      _h_final = getattr(metrics,'pipeline_finalize_duration_seconds',None)
      if _h_enrich:
        for d in enrich_phase_durations:
          try: _h_enrich.observe(d)
          except Exception: pass
      if _h_final:
        for d in finalize_phase_durations:
          try: _h_final.observe(d)
          except Exception: pass
      # Alert category counters
      if alert_summary is not None:
        for cat, val in alert_summary.categories.items():
          metric_name = f'pipeline_alerts_{cat}_total'
          if not hasattr(metrics, metric_name):
            try:
              setattr(metrics, metric_name, _C(f'g6_{metric_name}','Count of pipeline cycles with occurrences for category'))
            except Exception: pass
          c = getattr(metrics, metric_name, None)
          if c and val>0:
            try: c.inc(val)
            except Exception: pass
  except Exception:
    logger.debug('pipeline_operational_metrics_failed', exc_info=True)
  # Wave 4 (W4-06): Memory footprint gauge (RSS in MB). Best-effort, gated.
  try:
    if os.environ.get('G6_PIPELINE_MEMORY_GAUGE','1').lower() in ('1','true','yes','on') and metrics is not None:
      from prometheus_client import Gauge as _G
      if not hasattr(metrics, 'pipeline_memory_rss_mb'):
        try:
          metrics.pipeline_memory_rss_mb = _G('g6_pipeline_memory_rss_mb','Approximate process RSS memory (MB) for pipeline process')
        except Exception:
          metrics.pipeline_memory_rss_mb = None
      gmem = getattr(metrics, 'pipeline_memory_rss_mb', None)
      if gmem:
        # Explicit Optional[float] annotation to avoid mypy inferring int then widening
        rss_mb: float | None = None
        # Try psutil first
        try:
          import psutil
          p = psutil.Process()
          rss_mb = p.memory_info().rss / (1024*1024)
        except Exception:
          pass
        if rss_mb is None:
          # Try resource (Unix) - may not exist on Windows but harmless
          try:
            import resource
            _getrusage = getattr(resource, 'getrusage', None)
            _rself = getattr(resource, 'RUSAGE_SELF', None)
            if _getrusage and _rself is not None:
              usage = _getrusage(_rself)
              # ru_maxrss may be int on Unix or absent; ensure typed as Optional[float|int]
              _val_any = getattr(usage, 'ru_maxrss', None)
              # Distinct variable name to avoid clashing with earlier loop variable 'val'
              ru_maxrss_val: float | int | None = _val_any if isinstance(_val_any, (int, float)) else None
              if ru_maxrss_val is not None:
                if ru_maxrss_val > 10_000_000:  # assume bytes -> convert to MB
                  rss_mb = ru_maxrss_val / (1024*1024)
                else:  # assume KB
                  rss_mb = ru_maxrss_val / 1024
          except Exception:
            pass
        if rss_mb is None:
          # Fallback: parse /proc/self/status (Linux only)
          try:
            if os.path.exists('/proc/self/status'):
              with open('/proc/self/status') as f:
                for line in f:
                  if line.startswith('VmRSS:'):
                    parts = line.split()
                    if len(parts) >= 2:
                      kb = float(parts[1])
                      rss_mb = kb / 1024
                      break
          except Exception:
            pass
        if rss_mb is not None:
          try:
            gmem.set(float(rss_mb))
          except Exception:
            pass
  except Exception:
    logger.debug('pipeline_memory_gauge_failed', exc_info=True)
  # Compute percentile helper (local, no external deps)
  def _pct(vals: list[float], p: float) -> float | None:
    try:
      if not vals:
        return None
      vs = sorted(vals)
      k = int(round((len(vs)-1)*p))
      return vs[k]
    except Exception:
      return None
  diagnostics = {
    'phase_timings': {
      'enrich_count': len(enrich_phase_durations),
      'enrich_total_s': sum(enrich_phase_durations) if enrich_phase_durations else 0.0,
      'finalize_count': len(finalize_phase_durations),
      'finalize_total_s': sum(finalize_phase_durations) if finalize_phase_durations else 0.0,
    },
    'provider_latency': {
      'atm_p50_s': _pct(provider_call_durations['atm'], 0.50),
      'atm_p95_s': _pct(provider_call_durations['atm'], 0.95),
      'instrument_fetch_p50_s': _pct(provider_call_durations['instrument_fetch'], 0.50),
      'instrument_fetch_p95_s': _pct(provider_call_durations['instrument_fetch'], 0.95),
    }
  }
  _include_diag = os.environ.get('G6_PIPELINE_INCLUDE_DIAGNOSTICS','').lower() in ('1','true','yes','on')
  ret_obj = {
    'status': 'ok',
    'indices_processed': len(indices_struct),
    'have_raw': True,
    'snapshots': None,
    'snapshot_count': 0,
    'indices': indices_struct,
    'partial_reason_totals': partial_reason_totals,
    'snapshot_summary': snapshot_summary,
  }
  try:
    if partial_reason_totals is not None:
      from src.collectors.partial_reasons import STABLE_GROUP_ORDER, STABLE_REASON_ORDER, group_reason_counts
      groups = group_reason_counts(partial_reason_totals)
      if groups:
        ret_obj['partial_reason_groups'] = groups
        ret_obj['partial_reason_order'] = STABLE_REASON_ORDER
        ret_obj['partial_reason_group_order'] = STABLE_GROUP_ORDER
  except Exception:
    pass
  if _include_diag:
    ret_obj['diagnostics'] = diagnostics
  # W4-09: periodic benchmark cycle integration (best-effort, post main work)
  try:
    _maybe_run_benchmark_cycle(metrics)
  except Exception:
    logger.debug('benchmark_cycle_integration_failed', exc_info=True)
  return ret_obj

def _infer_expiry_rule(expiry_date: datetime.date) -> str:
  """Simple rule inference placeholder; legacy had richer mapping (week/month tags)."""
  # Weekly vs monthly heuristic: last Thursday of month treated as 'monthly'
  try:
    # Determine last Thursday of month
    import calendar
    cal = calendar.monthcalendar(expiry_date.year, expiry_date.month)
    thursdays = [week[3] for week in cal if week[3] != 0]
    last_thu = thursdays[-1]
    if expiry_date.weekday() == 3 and expiry_date.day == last_thu:
      return 'monthly'
    return 'this_week'
  except Exception:
    return 'this_week'
