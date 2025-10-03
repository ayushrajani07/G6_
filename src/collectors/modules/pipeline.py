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
from typing import Any, Dict, List, Tuple
import time, os, logging, datetime

from .context import build_collector_context, CollectorContext
from .strike_depth import compute_strike_universe
try:
  from .strike_policy import resolve_strike_depth as _resolve_strike_depth  # type: ignore
except Exception:  # pragma: no cover
  _resolve_strike_depth = None  # type: ignore
from .expiry_universe import build_expiry_map
from .coverage_eval import coverage_metrics, field_coverage_metrics
from .enrichment import enrich_quotes
try:  # Phase 9 optional async enrichment (top-level import for clarity)
  from .enrichment_async import enrich_quotes_async as _enrich_quotes_async  # type: ignore
except Exception:  # pragma: no cover
  _enrich_quotes_async = None  # type: ignore
from .adaptive_adjust import adaptive_post_expiry
# Phase 9 status finalization parity imports (lazy guarded inside loop if unavailable)
try:  # compute PARTIAL / OK classification parity with legacy
  from src.collectors.helpers.status_reducer import compute_expiry_status as _compute_expiry_status  # type: ignore
except Exception:  # pragma: no cover
  _compute_expiry_status = None  # type: ignore
try:  # finalize_expiry attaches partial_reason + emits option_match stats (via facade)
  from .status_finalize_core import finalize_expiry as _finalize_expiry  # type: ignore
except Exception:  # pragma: no cover
  _finalize_expiry = None  # type: ignore
from .benchmark_bridge import write_benchmark_artifact
from .synthetic_quotes import build_synthetic_quotes, record_synthetic_metrics
from .preventive_validate import run_preventive_validation

logger = logging.getLogger(__name__)

def _detect_anomalies(series: List[float], threshold: float) -> Tuple[List[bool], List[float]]:
  """Median+MAD robust z-score detector (small duplication to avoid legacy import)."""
  import statistics, math
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

def run_pipeline(index_params, providers, csv_sink, influx_sink, metrics=None, *,
         compute_greeks: bool = False, risk_free_rate: float = 0.05, estimate_iv: bool = False,
         iv_max_iterations: int | None = None, iv_min: float | None = None, iv_max: float | None = None,
         iv_precision: float | None = None, build_snapshots: bool = False):  # noqa: D401
  """Run collectors via staged pipeline (initial sequencing implementation)."""
  start_wall = time.time()
  phase_timings = {}
  ctx: CollectorContext = build_collector_context(index_params=index_params, metrics=metrics, debug=os.environ.get('G6_COLLECTOR_REFACTOR_DEBUG','').lower() in ('1','true','yes','on'))
  indices_struct: List[Dict[str, Any]] = []
  partial_reason_totals = { 'low_strike': 0, 'low_field': 0, 'low_both': 0, 'unknown': 0 }
  # Latency profiling accumulators (Phase 10 Task 7)
  enrich_phase_durations: List[float] = []  # per-expiry enrichment duration
  finalize_phase_durations: List[float] = []  # per-expiry finalize_expiry duration
  provider_call_durations: Dict[str, List[float]] = { 'atm': [], 'instrument_fetch': [] }
  for index_symbol, cfg in index_params.items():
    index_start = time.time()
    expiries_out: List[Dict[str, Any]] = []
    failures = 0
    attempts = 0
    option_count_total = 0
    status = 'EMPTY'
    try:
      attempts += 1
      # ATM strike (best-effort)
      # ATM strike timing
      try:
        _t0_atm = time.time()
        atm = providers.get_atm_strike(index_symbol)  # type: ignore[attr-defined]
        provider_call_durations['atm'].append(time.time() - _t0_atm)
      except Exception:
        atm = None
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
        raise RuntimeError('instrument_fetch_failed')
      if not instruments:
        raise RuntimeError('empty_instrument_universe')
      # Expiry map
      try:
        expiry_map, expiry_stats = build_expiry_map(instruments)
      except Exception:
        logger.debug('pipeline_expiry_map_failed', exc_info=True)
        raise
      # Iterate expiries (date ordered)
      for expiry_date in sorted(expiry_map.keys()):
        exp_instruments = expiry_map[expiry_date]
        rule = _infer_expiry_rule(expiry_date)
        # Strike universe
        # Phase 10 adaptive strike policy v2 (pre-strike universe)
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
        strikes, strikes_meta = compute_strike_universe(atm or 0, strikes_itm, strikes_otm, index_symbol)
        # Enrichment (quotes) + synthetic fallback (Phase 9 async aware)
        enriched = {}
        synthetic_used_flag = False
        async_flag = os.environ.get('G6_ENRICH_ASYNC','0').lower() in ('1','true','on','yes') and _enrich_quotes_async is not None
        # Enrichment timing (sync or async path)
        _t0_enrich = time.time()
        if async_flag and _enrich_quotes_async is not None:
          try:
            enriched = _enrich_quotes_async(index_symbol, rule, expiry_date, exp_instruments, providers, metrics)  # type: ignore[misc]
          except Exception:
            logger.debug('pipeline_enrichment_async_failed', exc_info=True)
        if not enriched:
          try:
            enriched = enrich_quotes(index_symbol, rule, expiry_date, exp_instruments, providers, metrics)
          except Exception:
            logger.debug('pipeline_enrichment_failed', exc_info=True)
        enrich_phase_durations.append(time.time() - _t0_enrich)
        if not enriched:
          try:
            enriched = build_synthetic_quotes(exp_instruments)
            if enriched:
              logger.warning(f"Synthetic quotes generated for {index_symbol} {rule} count={len(enriched)} (pipeline fallback)")
              record_synthetic_metrics(ctx, index_symbol, expiry_date)
              synthetic_used_flag = True
          except Exception:
            logger.debug('pipeline_synthetic_fallback_failed', exc_info=True)
        # Preventive validation (clean enriched data) BEFORE field coverage
        cleaned_enriched = enriched
        try:
          cleaned_enriched, prevent_report = run_preventive_validation(index_symbol, rule, expiry_date, exp_instruments, enriched, None)
        except Exception:
          logger.debug('pipeline_preventive_validation_failed', exc_info=True)
        # Coverage metrics (strike uses instruments; field uses cleaned enriched)
        strike_cov = None; field_cov = None
        try:
          cov = coverage_metrics(ctx, exp_instruments, strikes, index_symbol, rule, expiry_date)
          strike_cov = cov.get('strike_coverage') if isinstance(cov, dict) else None
        except Exception:
          logger.debug('pipeline_strike_coverage_failed', exc_info=True)
        try:
          fcov = field_coverage_metrics(ctx, cleaned_enriched, index_symbol, rule, expiry_date)
          field_cov = fcov.get('field_coverage') if isinstance(fcov, dict) else None
        except Exception:
          logger.debug('pipeline_field_coverage_failed', exc_info=True)
        # Option count (simplified: length of instruments slice)
        opt_cnt = len(exp_instruments)
        option_count_total += opt_cnt
        expiry_rec = {
          'rule': rule,
          'status': 'OK' if opt_cnt > 0 else 'EMPTY',  # provisional; may become PARTIAL after classification
          'options': opt_cnt,
          'strike_coverage': strike_cov,
          'field_coverage': field_cov,
          'partial_reason': None,
          'synthetic_quotes': synthetic_used_flag,
          'synthetic_fallback': synthetic_used_flag,  # alias for legacy finalize_expiry expectations
        }
        # Phase 9: apply status reducer to derive PARTIAL based on coverage thresholds
        if _compute_expiry_status is not None:
          try:
            expiry_rec['status'] = _compute_expiry_status(expiry_rec)  # type: ignore
          except Exception:
            logger.debug('pipeline_compute_expiry_status_failed', exc_info=True)
        # Phase 9: finalize expiry (partial_reason derivation + strike footprint stats emission)
        if _finalize_expiry is not None:
          _t0_finalize = time.time()
          try:
            int_strikes: list[int] = []
            for s in (strikes or []):
              try:
                int_strikes.append(int(s))
              except Exception:
                continue
            _finalize_expiry(expiry_rec, cleaned_enriched, int_strikes, index_symbol, expiry_date, rule, metrics)
          except Exception:
            logger.debug('pipeline_finalize_expiry_failed', exc_info=True)
          finally:
            finalize_phase_durations.append(time.time() - _t0_finalize)
        expiries_out.append(expiry_rec)
        # Adaptive logic post-expiry
        try:
          adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule)
        except Exception:
          logger.debug('pipeline_adaptive_post_failed', exc_info=True)
      # Index status heuristic
      status = 'OK' if option_count_total > 0 else 'EMPTY'
    except Exception:
      failures += 1
      logger.debug('pipeline_index_failed', extra={'index': index_symbol}, exc_info=True)
      if not expiries_out:
        expiries_out.append({'failed': True})
    elapsed_index = time.time() - index_start
    # Coverage rollup (Phase 8) – compute index-level averages from built expiries
    try:
      from .coverage_core import compute_index_coverage  # type: ignore
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
  total_elapsed = time.time() - start_wall
  # Benchmark artifact (anomalies) – pass anomaly detector
  try:
    write_benchmark_artifact(indices_struct, total_elapsed, ctx_like=ctx, metrics=metrics, detect_anomalies_fn=lambda series, thr: _detect_anomalies(series, thr))
  except Exception:
    logger.debug('pipeline_benchmark_artifact_failed', exc_info=True)
  # Phase 9: alert aggregation prior to snapshot summary
  try:
    from .alerts_core import aggregate_alerts  # type: ignore
    alert_summary = aggregate_alerts(indices_struct)
  except Exception:
    logger.debug('pipeline_alert_aggregation_failed', exc_info=True)
    alert_summary = None
  phase_timings['alerts'] = time.time() - start_wall - total_elapsed  # approximate post main loop delta
  # Phase 7: build snapshot summary (fallback removed post-stabilization)
  from .snapshot_core import build_snapshot  # type: ignore
  snap_summary = build_snapshot(indices_struct, len(indices_struct), metrics, build_reason_totals=True)
  partial_reason_totals = snap_summary.partial_reason_totals or partial_reason_totals
  snapshot_summary = snap_summary.to_dict() if snap_summary else None
  if snapshot_summary is not None and alert_summary is not None:
    try:
      summary_alerts = alert_summary.to_dict()  # {'alerts_total','alerts', 'alerts_index_triggers'}
      # New Phase 10 canonical nesting: snapshot_summary['alerts'] holds categories & total
      alerts_block = {
        'total': summary_alerts.get('alerts_total', 0),
        'categories': summary_alerts.get('alerts', {}),
        'index_triggers': summary_alerts.get('alerts_index_triggers', {}),
      }
      snapshot_summary['alerts'] = alerts_block
      # Optional backward compatibility: export flat fields if flag set
      if os.environ.get('G6_ALERTS_FLAT_COMPAT','1').lower() in ('1','true','yes','on'):
        snapshot_summary['alerts_total'] = alerts_block['total']
        for k, v in alerts_block['categories'].items():
          snapshot_summary[f'alert_{k}'] = v
    except Exception:
      logger.debug('pipeline_snapshot_alert_merge_failed', exc_info=True)
  # Operational metrics (Phase 10) – best-effort
  total_cycle = time.time() - start_wall
  try:
    if metrics is not None:
      from prometheus_client import Histogram as _H, Summary as _S, Counter as _C, Gauge as _G  # type: ignore
      # Cycle duration histogram (bucket selection conservative)
      if not hasattr(metrics, 'pipeline_cycle_duration_seconds'):
        try: metrics.pipeline_cycle_duration_seconds = _H('g6_pipeline_cycle_duration_seconds','Pipeline cycle duration seconds', buckets=(0.05,0.1,0.25,0.5,1,2,5,10))  # type: ignore[attr-defined]
        except Exception: pass
      if not hasattr(metrics, 'pipeline_cycle_duration_summary'):
        try: metrics.pipeline_cycle_duration_summary = _S('g6_pipeline_cycle_duration_summary','Pipeline cycle duration summary')  # type: ignore[attr-defined]
        except Exception: pass
      h = getattr(metrics,'pipeline_cycle_duration_seconds',None); s = getattr(metrics,'pipeline_cycle_duration_summary',None)
      if h:
        try: h.observe(total_cycle)
        except Exception: pass
      if s:
        try: s.observe(total_cycle)
        except Exception: pass
      # Phase latency histograms
      if not hasattr(metrics, 'pipeline_enrich_duration_seconds'):
        try: metrics.pipeline_enrich_duration_seconds = _H('g6_pipeline_enrich_duration_seconds','Per-expiry enrichment duration seconds', buckets=(0.001,0.005,0.01,0.02,0.05,0.1,0.25,0.5,1,2))  # type: ignore[attr-defined]
        except Exception: pass
      if not hasattr(metrics, 'pipeline_finalize_duration_seconds'):
        try: metrics.pipeline_finalize_duration_seconds = _H('g6_pipeline_finalize_duration_seconds','Per-expiry finalize_expiry duration seconds', buckets=(0.0005,0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.25))  # type: ignore[attr-defined]
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
              setattr(metrics, metric_name, _C(f'g6_{metric_name}','Count of pipeline cycles with occurrences for category'))  # type: ignore[attr-defined]
            except Exception: pass
          c = getattr(metrics, metric_name, None)
          if c and val>0:
            try: c.inc(val)
            except Exception: pass
  except Exception:
    logger.debug('pipeline_operational_metrics_failed', exc_info=True)
  # Compute percentile helper (local, no external deps)
  def _pct(vals: List[float], p: float) -> float | None:
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
      from src.collectors.partial_reasons import group_reason_counts, STABLE_REASON_ORDER, STABLE_GROUP_ORDER  # type: ignore
      groups = group_reason_counts(partial_reason_totals)
      if groups:
        ret_obj['partial_reason_groups'] = groups
        ret_obj['partial_reason_order'] = STABLE_REASON_ORDER
        ret_obj['partial_reason_group_order'] = STABLE_GROUP_ORDER
  except Exception:
    pass
  if _include_diag:
    ret_obj['diagnostics'] = diagnostics
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
