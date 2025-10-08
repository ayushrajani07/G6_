"""Pipeline executor with error taxonomy handling.

Replaces ad-hoc loops inside shadow orchestration with a reusable helper that
captures timing and classifies exceptions using collectors.errors taxonomy.
"""
from __future__ import annotations

from typing import List, Callable, Protocol, Any
import time, logging, os, random
from .state import ExpiryState
from .error_helpers import add_phase_error
from src.collectors.errors import PhaseRecoverableError, PhaseAbortError, PhaseFatalError, classify_exception

logger = logging.getLogger(__name__)

class Phase(Protocol):  # minimal structural contract
    def __call__(self, ctx, state: ExpiryState, *extra) -> ExpiryState: ...


def execute_phases(ctx, state: ExpiryState, phases: List[Callable[..., ExpiryState]]) -> ExpiryState:
    """Execute ordered phases with taxonomy-based control flow.

    Behavior:
      - PhaseAbortError: stop immediately, treat as clean early exit.
      - PhaseRecoverableError: stop further phases, mark error, continue outer cycle.
      - PhaseFatalError: stop, mark fatal, caller may escalate.
      - Other exceptions: treated as fatal for now (could map to recoverable via rule later).
    """
    # Retry configuration (env-driven; defaults preserve previous single-attempt semantics)
    retry_enabled = _truthy(os.getenv('G6_PIPELINE_RETRY_ENABLED','0'))
    try:
        max_attempts = int(os.getenv('G6_PIPELINE_RETRY_MAX_ATTEMPTS','3') or 3)
        if max_attempts < 1:
            max_attempts = 1
    except Exception:
        max_attempts = 3
    base_ms = _safe_int(os.getenv('G6_PIPELINE_RETRY_BASE_MS','50'), 50)
    jitter_ms = _safe_int(os.getenv('G6_PIPELINE_RETRY_JITTER_MS','0'), 0)

    # Optional config snapshot (captures active pipeline-related flags)
    try:
        if _truthy(os.getenv('G6_PIPELINE_CONFIG_SNAPSHOT','0')):
            import json as _json_cfg, time as _t_cfg, hashlib as _h_cfg
            snapshot = {
                'version': 1,
                'exported_at': int(_t_cfg.time()),
                'flags': {
                    'G6_PIPELINE_RETRY_ENABLED': retry_enabled,
                    'G6_PIPELINE_RETRY_MAX_ATTEMPTS': max_attempts,
                    'G6_PIPELINE_RETRY_BASE_MS': base_ms,
                    'G6_PIPELINE_RETRY_JITTER_MS': jitter_ms,
                    'G6_PIPELINE_STRUCT_ERROR_EXPORT': _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_EXPORT','0')),
                    'G6_PIPELINE_STRUCT_ERROR_METRIC': _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_METRIC','0')),
                    'G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT': _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT','0')),
                    'G6_PIPELINE_STRUCT_ERROR_ENRICH': _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_ENRICH','0')),
                    'G6_PIPELINE_CYCLE_SUMMARY': _truthy(os.getenv('G6_PIPELINE_CYCLE_SUMMARY','1')),
                    'G6_PIPELINE_CYCLE_SUMMARY_STDOUT': _truthy(os.getenv('G6_PIPELINE_CYCLE_SUMMARY_STDOUT','0')),
                    'G6_PIPELINE_PANEL_EXPORT': _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT','0')),
                    'G6_PIPELINE_PANEL_EXPORT_HISTORY': _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT_HISTORY','0')),
                    'G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT': os.getenv('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','20'),
                    'G6_PIPELINE_PANEL_EXPORT_HASH': _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT_HASH','1')),
                },
            }
            try:
                stable = _json_cfg.dumps(snapshot['flags'], sort_keys=True).encode()
                snapshot['content_hash'] = _h_cfg.sha256(stable).hexdigest()[:16]
            except Exception:
                pass
            panels_dir = os.getenv('G6_PANELS_DIR') or 'data/panels'
            try:
                os.makedirs(panels_dir, exist_ok=True)
                with open(os.path.join(panels_dir, 'pipeline_config_snapshot.json'), 'w', encoding='utf-8') as fh:
                    _json_cfg.dump(snapshot, fh, separators=(',',':'))
            except Exception:
                pass
            if _truthy(os.getenv('G6_PIPELINE_CONFIG_SNAPSHOT_STDOUT','0')):
                try:
                    print('pipeline.config_snapshot', _json_cfg.dumps(snapshot, separators=(',',':')))
                except Exception:
                    pass
    except Exception:
        pass

    phase_runs: list[dict[str, Any]] = []
    for fn in phases:
        phase_name = getattr(fn, '__name__', 'phase')
        attempts = 0
        phase_started = time.perf_counter()
        final_outcome = 'unknown'
        total_duration_ms = 0.0
        while True:
            attempts += 1
            attempt_start = time.perf_counter()
            try:
                result = fn(ctx, state)  # type: ignore[arg-type]
                if result is not None:
                    state = result
            except PhaseAbortError as e:
                add_phase_error(state, phase_name, 'abort', str(e), attempt=attempts, token=f"abort:{phase_name}:{e}")
                final_outcome = 'abort'
                _log_phase(phase_name, attempt_start, state, outcome='abort')
                break
            except PhaseRecoverableError as e:
                add_phase_error(state, phase_name, 'recoverable', str(e), attempt=attempts, token=f"recoverable:{phase_name}:{e}")
                _log_phase(phase_name, attempt_start, state, outcome='recoverable')
                if not retry_enabled or attempts >= max_attempts:
                    final_outcome = 'recoverable_exhausted' if retry_enabled and attempts >= max_attempts else 'recoverable'
                    break
                _sleep_backoff(base_ms, jitter_ms, attempts)
                continue
            except PhaseFatalError as e:
                add_phase_error(state, phase_name, 'fatal', str(e), attempt=attempts, token=f"fatal:{phase_name}:{e}")
                final_outcome = 'fatal'
                _log_phase(phase_name, attempt_start, state, outcome='fatal')
                break
            except Exception as e:
                cls = classify_exception(e)
                add_phase_error(state, phase_name, cls, str(e), attempt=attempts, token=f"{cls}:{phase_name}:{e}")
                _log_phase(phase_name, attempt_start, state, outcome=cls)
                if cls == 'recoverable' and retry_enabled and attempts < max_attempts:
                    _sleep_backoff(base_ms, jitter_ms, attempts)
                    continue
                # Map unknown recoverable exhaustion
                if cls == 'recoverable' and retry_enabled and attempts >= max_attempts:
                    final_outcome = 'recoverable_exhausted'
                else:
                    final_outcome = cls
                break
            else:
                final_outcome = 'ok'
                _log_phase(phase_name, attempt_start, state, outcome='ok')
                break
            finally:
                total_duration_ms = (time.perf_counter() - phase_started) * 1000.0
                _record_attempt_metrics(phase_name, attempts, final_outcome if final_outcome!='unknown' else None)
        # Final aggregated metrics (only once per phase sequence)
        _record_final_metrics(phase_name, total_duration_ms, final_outcome)
        try:
            phase_runs.append({
                'phase': phase_name,
                'final_outcome': final_outcome,
                'attempts': attempts,
                'duration_ms': round(total_duration_ms, 3),
            })
        except Exception:
            pass
        if final_outcome in ('abort','fatal','recoverable','recoverable_exhausted','unknown'):
            # stop further phases on any non-ok outcome to preserve original semantics
            break
    # Optional JSON export of structured errors (snapshot) when enabled
    try:
        if _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_EXPORT','0')) and state.error_records:
            import json, hashlib, time as _t
            # Stable lightweight projection
            records = [
                {
                    'phase': r.phase,
                    'classification': r.classification,
                    'message': r.message,
                    'attempt': r.attempt,
                    'ts': r.timestamp,
                } for r in state.error_records
            ]
            payload = {
                'count': len(records),
                'records': records,
                'exported_at': int(_t.time()),
            }
            # Hash for diff-friendly logs
            h = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:16]
            payload['hash'] = h
            state.meta['structured_errors'] = payload  # embed into state meta for downstream access
            if _truthy(os.getenv('G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT','0')):
                try:
                    print('pipeline.structured_errors', json.dumps(payload, separators=(',',':')))
                except Exception:
                    pass
        # Attach cycle summary optionally after structured errors projection
        if _truthy(os.getenv('G6_PIPELINE_CYCLE_SUMMARY','1')):  # default on
            try:
                ok_count = sum(1 for r in phase_runs if r['final_outcome']=='ok')
                errored = [r for r in phase_runs if r['final_outcome']!='ok']
                retries = [r for r in phase_runs if r['attempts']>1]
                summary = {
                    'phases_total': len(phase_runs),
                    'phases_ok': ok_count,
                    'phases_error': len(errored),
                    'phases_with_retries': len(retries),
                    'retry_enabled': bool(retry_enabled),
                    'error_outcomes': {o: sum(1 for r in phase_runs if r['final_outcome']==o) for o in {r['final_outcome'] for r in phase_runs if r['final_outcome']!='ok'}},
                    'aborted_early': any(r['final_outcome']=='abort' for r in phase_runs),
                    'fatal': any(r['final_outcome']=='fatal' for r in phase_runs),
                    'recoverable_exhausted': any(r['final_outcome']=='recoverable_exhausted' for r in phase_runs),
                }
                state.meta['pipeline_summary'] = summary
                # Cycle level metrics (success gauge + counters + ratios + rolling window + trends ingestion)
                try:  # pragma: no cover - metric emissions are straightforward
                    from src.metrics.metrics import get_metrics  # type: ignore
                    _m = get_metrics()
                    is_success = 1 if summary.get('phases_error', 0) == 0 else 0
                    if hasattr(_m, 'pipeline_cycle_success'):
                        try:
                            _m.pipeline_cycle_success.set(is_success)
                        except Exception:
                            pass
                    if hasattr(_m, 'pipeline_cycles_total'):
                        try:
                            _m.pipeline_cycles_total.inc()
                        except Exception:
                            pass
                    if is_success and hasattr(_m, 'pipeline_cycles_success_total'):
                        try:
                            _m.pipeline_cycles_success_total.inc()
                        except Exception:
                            pass
                    # Error ratio gauge
                    if hasattr(_m, 'pipeline_cycle_error_ratio'):
                        try:
                            pt = summary.get('phases_total', 0) or 0
                            pe = summary.get('phases_error', 0) or 0
                            ratio = (pe / pt) if pt else 0.0
                            _m.pipeline_cycle_error_ratio.set(ratio)
                        except Exception:
                            pass
                    # Rolling window success/error rate gauges
                    try:
                        _rw_size_env = int(os.getenv('G6_PIPELINE_ROLLING_WINDOW','0') or 0)
                    except Exception:
                        _rw_size_env = 0
                    if _rw_size_env > 0:
                        try:
                            from collections import deque as _deque
                            # Module-level cache (attribute on function object to avoid global) 
                            if not hasattr(execute_phases, '_rolling_window'):
                                execute_phases._rolling_window = _deque(maxlen=_rw_size_env)  # type: ignore
                            window = execute_phases._rolling_window  # type: ignore
                            window.append(1 if is_success else 0)
                            if hasattr(_m, 'pipeline_cycle_success_rate_window'):
                                try:
                                    _m.pipeline_cycle_success_rate_window.set(sum(window)/len(window))
                                except Exception:
                                    pass
                            if hasattr(_m, 'pipeline_cycle_error_rate_window'):
                                try:
                                    _m.pipeline_cycle_error_rate_window.set(1 - (sum(window)/len(window)))
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    # Trends file ingestion (long horizon gauges) gated by env flag
                    if os.getenv('G6_PIPELINE_TRENDS_METRICS','0') in ('1','true','yes','on'):  # lightweight file read
                        try:
                            panels_dir = os.getenv('G6_PANELS_DIR') or 'data/panels'
                            trend_path = os.path.join(panels_dir, 'pipeline_errors_trends.json')
                            import json as _json_trm
                            with open(trend_path, 'r', encoding='utf-8') as _tfm:
                                _trend_doc = _json_trm.load(_tfm)
                            agg = (_trend_doc.get('aggregate') or {}) if isinstance(_trend_doc, dict) else {}
                            cycles = agg.get('cycles') or 0
                            success_rate = agg.get('success_rate') or 0.0
                            if hasattr(_m, 'pipeline_trends_cycles'):
                                try: _m.pipeline_trends_cycles.set(cycles)
                                except Exception: pass
                            if hasattr(_m, 'pipeline_trends_success_rate'):
                                try: _m.pipeline_trends_success_rate.set(success_rate)
                                except Exception: pass
                        except Exception:
                            pass
                except Exception:
                    pass
                # Optional legacy cycle_tables integration
                try:
                    if _truthy(os.getenv('G6_CYCLE_TABLES_PIPELINE_INTEGRATION','0')):
                        try:
                            from src.collectors.helpers.cycle_tables import record_pipeline_summary  # type: ignore
                            record_pipeline_summary(summary)
                        except Exception:
                            pass
                except Exception:
                    pass
                if _truthy(os.getenv('G6_PIPELINE_CYCLE_SUMMARY_STDOUT','0')):
                    import json as _json
                    try:
                        print('pipeline.summary', _json.dumps(summary, separators=(',',':')))
                    except Exception:
                        pass
                # Panel export (errors + summary) if enabled
                if _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT','0')):
                    try:
                        panels_dir = os.getenv('G6_PANELS_DIR') or 'data/panels'
                        os.makedirs(panels_dir, exist_ok=True)
                        history_enabled = _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT_HISTORY','0'))
                        hash_enabled = _truthy(os.getenv('G6_PIPELINE_PANEL_EXPORT_HASH','1'))
                        try:
                            history_limit = int(os.getenv('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','20') or 20)
                        except Exception:
                            history_limit = 20
                        if history_limit < 1:
                            history_limit = 1
                        # Defensive redaction (messages already redacted at record creation; re-apply patterns if any changed mid-run)
                        _redact_patterns = os.getenv('G6_PIPELINE_REDACT_PATTERNS','')
                        _redact_repl = os.getenv('G6_PIPELINE_REDACT_REPLACEMENT','***')
                        def _apply_redact(msg: str) -> str:
                            if not _redact_patterns:
                                return msg
                            import re as _re
                            for _p in [p.strip() for p in _redact_patterns.split(',') if p.strip()]:
                                try:
                                    msg = _re.sub(_p, _redact_repl, msg)
                                except Exception:
                                    continue
                            return msg
                        export = {
                            'summary': summary,
                            'errors': [
                                {
                                    'phase': r.phase,
                                    'classification': r.classification,
                                    'message': _apply_redact(r.message),
                                    'attempt': r.attempt,
                                } for r in state.error_records
                            ],
                            'error_count': len(state.error_records),
                            'version': 1,
                        }
                        import json as _json2, time as _t2, hashlib as _hashlib
                        export['exported_at'] = int(_t2.time())
                        if hash_enabled:
                            try:
                                # Hash stable projection (summary + errors without exported_at or version ordering differences)
                                stable = {
                                    'summary': export['summary'],
                                    'errors': export['errors'],
                                    'error_count': export['error_count'],
                                    'version': export['version'],
                                }
                                export['content_hash'] = _hashlib.sha256(_json2.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]
                            except Exception:
                                pass
                        base_path = os.path.join(panels_dir, 'pipeline_errors_summary.json')
                        with open(base_path, 'w', encoding='utf-8') as fh:
                            _json2.dump(export, fh, separators=(',',':'))
                        # Optional rolling history: write timestamped file and prune, plus index
                        if history_enabled:
                            ts = export['exported_at']
                            # ensure uniqueness within same second by adding incremental suffix if needed
                            suffix = 0
                            while True:
                                hist_name = f"pipeline_errors_summary_{ts}{'' if suffix==0 else '_' + str(suffix)}.json"
                                hist_path = os.path.join(panels_dir, hist_name)
                                if not os.path.exists(hist_path):
                                    break
                                suffix += 1
                                if suffix > 100:  # safety cap
                                    break
                            try:
                                with open(hist_path, 'w', encoding='utf-8') as fh2:
                                    _json2.dump(export, fh2, separators=(',',':'))
                            except Exception:
                                pass
                            # Build / update index file listing newest first
                            try:
                                all_hist = [f for f in os.listdir(panels_dir) if f.startswith('pipeline_errors_summary_') and f.endswith('.json')]
                                # exclude the base file
                                # Sort by embedded timestamp descending
                                def _extract_ts(fn: str) -> int:
                                    try:
                                        # handle optional suffix: pipeline_errors_summary_<ts>[_n].json
                                        core = fn[len('pipeline_errors_summary_'):-5]
                                        base_ts = core.split('_')[0]
                                        return int(base_ts)
                                    except Exception:
                                        return 0
                                all_hist.sort(key=_extract_ts, reverse=True)
                                # Prune beyond limit
                                if len(all_hist) > history_limit:
                                    for old in all_hist[history_limit:]:
                                        try:
                                            os.remove(os.path.join(panels_dir, old))
                                        except Exception:
                                            pass
                                    all_hist = all_hist[:history_limit]
                                index_entries = []
                                if hash_enabled:
                                    # Build mapping filename->hash by opening each (bounded by history_limit)
                                    for fn in all_hist:
                                        try:
                                            with open(os.path.join(panels_dir, fn), 'r', encoding='utf-8') as _rf:
                                                _d = _json2.load(_rf)
                                            index_entries.append({'file': fn, 'hash': _d.get('content_hash'), 'ts': _d.get('exported_at')})
                                        except Exception:
                                            index_entries.append({'file': fn})
                                index_payload = {
                                    'version': 1,
                                    'count': len(all_hist),
                                    'limit': history_limit,
                                    'files': all_hist if not hash_enabled else index_entries,
                                }
                                with open(os.path.join(panels_dir, 'pipeline_errors_history_index.json'), 'w', encoding='utf-8') as fh3:
                                    _json2.dump(index_payload, fh3, separators=(',',':'))
                            except Exception:
                                pass
                        # Trend Aggregation
                        if _truthy(os.getenv('G6_PIPELINE_TRENDS_ENABLED','0')):
                            try:
                                trend_limit = int(os.getenv('G6_PIPELINE_TRENDS_LIMIT','200') or 200)
                            except Exception:
                                trend_limit = 200
                            if trend_limit < 1:
                                trend_limit = 1
                            try:
                                trend_path = os.path.join(panels_dir, 'pipeline_errors_trends.json')
                                import json as _json_tr
                                try:
                                    with open(trend_path, 'r', encoding='utf-8') as _tf:
                                        trend_doc = _json_tr.load(_tf)
                                except Exception:
                                    trend_doc = {'version':1,'records':[]}
                                rec = {
                                    'ts': export['exported_at'],
                                    'phases_total': summary['phases_total'],
                                    'phases_error': summary['phases_error'],
                                    'error_count': export['error_count'],
                                    'hash': export.get('content_hash'),
                                }
                                trend_doc['records'].append(rec)
                                # Prune
                                if len(trend_doc['records']) > trend_limit:
                                    trend_doc['records'] = trend_doc['records'][-trend_limit:]
                                # Aggregates
                                total_cycles = len(trend_doc['records'])
                                total_errors = sum(r.get('error_count',0) for r in trend_doc['records'])
                                total_phase_errors = sum(r.get('phases_error',0) for r in trend_doc['records'])
                                total_phases = sum(r.get('phases_total',0) for r in trend_doc['records'])
                                success_cycles = sum(1 for r in trend_doc['records'] if r.get('phases_error',0)==0)
                                trend_doc['aggregate'] = {
                                    'cycles': total_cycles,
                                    'success_cycles': success_cycles,
                                    'success_rate': (success_cycles/total_cycles) if total_cycles else 0.0,
                                    'errors_total': total_errors,
                                    'phase_errors_total': total_phase_errors,
                                    'phases_total': total_phases,
                                }
                                with open(trend_path, 'w', encoding='utf-8') as _tfw:
                                    _json_tr.dump(trend_doc, _tfw, separators=(',',':'))
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    return state

    


def _log_phase(name: str, started: float, state: ExpiryState, outcome: str):
    dt_ms = (time.perf_counter() - started) * 1000.0
    try:
        logger.debug(
            'expiry.phase.exec phase=%s outcome=%s ms=%.2f index=%s rule=%s errors=%d enriched=%d',
            name,
            outcome,
            dt_ms,
            getattr(state, 'index', '?'),
            getattr(state, 'rule', '?'),
            len(getattr(state, 'errors', []) or []),
            len(getattr(state, 'enriched', {}) or {}),
        )
    except Exception:
        pass

__all__ = ['execute_phases','Phase']


# --- internal helpers -------------------------------------------------------
def _truthy(v: str) -> bool:
    return v.lower() in ('1','true','yes','on','y') if isinstance(v,str) else False

def _safe_int(v: str, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _sleep_backoff(base_ms: int, jitter_ms: int, attempt: int):  # pragma: no cover (timing side effect)
    delay_ms = base_ms * (2 ** (attempt-1))
    if jitter_ms > 0:
        delay_ms += random.randint(0, jitter_ms)
    # Cap to a reasonable ceiling (5s) to avoid runaway
    delay_ms = min(delay_ms, 5000)
    time.sleep(delay_ms / 1000.0)

def _record_attempt_metrics(phase: str, attempts: int, final_if_known: str | None):
    """Increment attempt / retry counters. final_if_known ignored until finalization for outcome counters."""
    try:  # lazy registry import pattern consistent with existing code
        from src.metrics.metrics import MetricsRegistry  # type: ignore
        reg = MetricsRegistry()
        if getattr(reg, 'pipeline_phase_attempts', None):
            reg.pipeline_phase_attempts.labels(phase=phase).inc()
        if attempts > 1 and getattr(reg, 'pipeline_phase_retries', None):
            reg.pipeline_phase_retries.labels(phase=phase).inc()
    except Exception:
        pass

def _record_final_metrics(phase: str, duration_ms: float, final_outcome: str):
    try:
        from src.metrics.metrics import MetricsRegistry  # type: ignore
        reg = MetricsRegistry()
        if getattr(reg, 'pipeline_phase_outcomes', None):
            reg.pipeline_phase_outcomes.labels(phase=phase, final_outcome=final_outcome).inc()
        if getattr(reg, 'pipeline_phase_duration_ms', None):
            reg.pipeline_phase_duration_ms.labels(phase=phase, final_outcome=final_outcome).inc(duration_ms)
        if getattr(reg, 'pipeline_phase_runs', None):
            reg.pipeline_phase_runs.labels(phase=phase, final_outcome=final_outcome).inc()
        # Histogram observation (seconds) with lazy env bucket override (set once)
        if getattr(reg, 'pipeline_phase_duration_seconds', None):  # histogram
            try:
                hist = reg.pipeline_phase_duration_seconds
                # Optional one-time dynamic bucket override via env (if provided and not yet applied)
                if not hasattr(hist, '_g6_buckets_overridden'):
                    b_env = os.getenv('G6_PIPELINE_PHASE_DURATION_BUCKETS','')
                    if b_env:
                        try:
                            arr = [float(x.strip()) for x in b_env.split(',') if x.strip()]
                            if arr:
                                # Rebuild internal buckets: Prometheus client histograms don't support runtime mutation;
                                # We skip dynamic override if already created. Documented limitation.
                                pass  # placeholder: no-op; doc notes explain limitation.
                        except Exception:
                            pass
                    setattr(hist, '_g6_buckets_overridden', True)
                hist.labels(phase=phase, final_outcome=final_outcome).observe(duration_ms / 1000.0)
            except Exception:
                pass
    except Exception:
        pass
