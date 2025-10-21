"""Pipeline executor with error taxonomy handling.

Replaces ad-hoc loops inside shadow orchestration with a reusable helper that
captures timing and classifies exceptions using collectors.errors taxonomy.
"""
from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import Any, Protocol, cast

from src.collectors.env_adapter import get_bool as _env_bool
from src.collectors.env_adapter import get_int as _env_int
from src.collectors.env_adapter import get_str as _env_str
from src.collectors.errors import PhaseAbortError, PhaseFatalError, PhaseRecoverableError, classify_exception

from .error_helpers import add_phase_error
from .state import ExpiryState
from .struct_events import emit_struct_event

logger = logging.getLogger(__name__)

class Phase(Protocol):  # minimal structural contract
    def __call__(self, ctx: Any, state: ExpiryState, *extra: Any) -> ExpiryState: ...


def execute_phases(ctx: Any, state: ExpiryState, phases: list[Callable[..., ExpiryState]]) -> ExpiryState:
    """Execute ordered phases with taxonomy-based control flow.

    Behavior:
      - PhaseAbortError: stop immediately, treat as clean early exit.
      - PhaseRecoverableError: stop further phases, mark error, continue outer cycle.
      - PhaseFatalError: stop, mark fatal, caller may escalate.
      - Other exceptions: treated as fatal for now (could map to recoverable via rule later).
    """
    # Retry configuration (env-driven; defaults preserve previous single-attempt semantics)
    retry_enabled = _env_bool('G6_PIPELINE_RETRY_ENABLED', False)
    try:
        max_attempts = _env_int('G6_PIPELINE_RETRY_MAX_ATTEMPTS', 3)
        if max_attempts < 1:
            max_attempts = 1
    except Exception:
        max_attempts = 3
    base_ms = _safe_int(_env_str('G6_PIPELINE_RETRY_BASE_MS','50'), 50)
    jitter_ms = _safe_int(_env_str('G6_PIPELINE_RETRY_JITTER_MS','0'), 0)

    # Optional config snapshot (captures active pipeline-related flags)
    try:
        if _env_bool('G6_PIPELINE_CONFIG_SNAPSHOT', False):
            import hashlib as _h_cfg
            import json as _json_cfg
            import time as _t_cfg
            snapshot = {
                'version': 1,
                'exported_at': int(_t_cfg.time()),
                'flags': {
                    'G6_PIPELINE_RETRY_ENABLED': retry_enabled,
                    'G6_PIPELINE_RETRY_MAX_ATTEMPTS': max_attempts,
                    'G6_PIPELINE_RETRY_BASE_MS': base_ms,
                    'G6_PIPELINE_RETRY_JITTER_MS': jitter_ms,
                    'G6_PIPELINE_STRUCT_ERROR_EXPORT': _env_bool('G6_PIPELINE_STRUCT_ERROR_EXPORT', False),
                    'G6_PIPELINE_STRUCT_ERROR_METRIC': _env_bool('G6_PIPELINE_STRUCT_ERROR_METRIC', False),
                    'G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT': _env_bool('G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT', False),
                    'G6_PIPELINE_STRUCT_ERROR_ENRICH': _env_bool('G6_PIPELINE_STRUCT_ERROR_ENRICH', False),
                    'G6_PIPELINE_CYCLE_SUMMARY': _env_bool('G6_PIPELINE_CYCLE_SUMMARY', True),
                    'G6_PIPELINE_CYCLE_SUMMARY_STDOUT': _env_bool('G6_PIPELINE_CYCLE_SUMMARY_STDOUT', False),
                    'G6_PIPELINE_PANEL_EXPORT': _env_bool('G6_PIPELINE_PANEL_EXPORT', False),
                    'G6_PIPELINE_PANEL_EXPORT_HISTORY': _env_bool('G6_PIPELINE_PANEL_EXPORT_HISTORY', False),
                    'G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT': _env_str('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT','20'),
                    'G6_PIPELINE_PANEL_EXPORT_HASH': _env_bool('G6_PIPELINE_PANEL_EXPORT_HASH', True),
                },
            }
            try:
                flags_stable_bytes = _json_cfg.dumps(snapshot['flags'], sort_keys=True).encode()
                snapshot['content_hash'] = _h_cfg.sha256(flags_stable_bytes).hexdigest()[:16]
            except Exception:
                pass
            panels_dir = _env_str('G6_PANELS_DIR','') or 'data/panels'
            try:
                os.makedirs(panels_dir, exist_ok=True)
                with open(os.path.join(panels_dir, 'pipeline_config_snapshot.json'), 'w', encoding='utf-8') as fh:
                    _json_cfg.dump(snapshot, fh, separators=(',',':'))
            except Exception:
                pass
            if _env_bool('G6_PIPELINE_CONFIG_SNAPSHOT_STDOUT', False):
                try:
                    print('pipeline.config_snapshot', _json_cfg.dumps(snapshot, separators=(',',':')))
                except Exception:
                    pass
    except Exception:
        pass

    phase_runs: list[dict[str, Any]] = []
    # Metrics gating (Wave 4 W4-05)
    _retry_metrics_enabled = _env_bool('G6_PIPELINE_RETRY_METRICS', True)
    # Lazy metric holders (attached once to avoid repeated registry lookups)
    _metrics_cache = {'backoff_hist': None, 'last_attempts_gauge': None}

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
                result = fn(ctx, state)
                if result is not None:
                    state = result
            except PhaseAbortError as e:
                add_phase_error(state, phase_name, 'abort', str(e), attempt=attempts, token=f"abort:{phase_name}:{e}")
                final_outcome = 'abort'
                _log_phase(phase_name, attempt_start, state, outcome='abort')
                try:
                    emit_struct_event(
                        'expiry.phase.event',
                        {
                            'phase': phase_name,
                            'outcome': 'abort',
                            'attempt': attempts,
                            'index': getattr(state,'index','?'),
                            'rule': getattr(state,'rule','?'),
                            'errors': len(getattr(state,'errors',[]) or []),
                            'enriched': len(getattr(state,'enriched',{}) or {}),
                        },
                        state=state,
                    )
                except Exception:
                    pass
                break
            except PhaseRecoverableError as e:
                add_phase_error(state, phase_name, 'recoverable', str(e), attempt=attempts, token=f"recoverable:{phase_name}:{e}")
                _log_phase(phase_name, attempt_start, state, outcome='recoverable')
                try:
                    emit_struct_event(
                        'expiry.phase.event',
                        {
                            'phase': phase_name,
                            'outcome': 'recoverable',
                            'attempt': attempts,
                            'index': getattr(state,'index','?'),
                            'rule': getattr(state,'rule','?'),
                            'errors': len(getattr(state,'errors',[]) or []),
                            'enriched': len(getattr(state,'enriched',{}) or {}),
                        },
                        state=state,
                    )
                except Exception:
                    pass
                if not retry_enabled or attempts >= max_attempts:
                    final_outcome = 'recoverable_exhausted' if retry_enabled and attempts >= max_attempts else 'recoverable'
                    break
                _sleep_backoff(base_ms, jitter_ms, attempts, phase_name if _retry_metrics_enabled else None, _metrics_cache if _retry_metrics_enabled else None)
                continue
            except PhaseFatalError as e:
                add_phase_error(state, phase_name, 'fatal', str(e), attempt=attempts, token=f"fatal:{phase_name}:{e}")
                final_outcome = 'fatal'
                _log_phase(phase_name, attempt_start, state, outcome='fatal')
                try:
                    emit_struct_event(
                        'expiry.phase.event',
                        {
                            'phase': phase_name,
                            'outcome': 'fatal',
                            'attempt': attempts,
                            'index': getattr(state,'index','?'),
                            'rule': getattr(state,'rule','?'),
                            'errors': len(getattr(state,'errors',[]) or []),
                            'enriched': len(getattr(state,'enriched',{}) or {}),
                        },
                        state=state,
                    )
                except Exception:
                    pass
                break
            except Exception as e:
                cls = classify_exception(e)
                add_phase_error(state, phase_name, cls, str(e), attempt=attempts, token=f"{cls}:{phase_name}:{e}")
                _log_phase(phase_name, attempt_start, state, outcome=cls)
                try:
                    emit_struct_event(
                        'expiry.phase.event',
                        {
                            'phase': phase_name,
                            'outcome': cls,
                            'attempt': attempts,
                            'index': getattr(state,'index','?'),
                            'rule': getattr(state,'rule','?'),
                            'errors': len(getattr(state,'errors',[]) or []),
                            'enriched': len(getattr(state,'enriched',{}) or {}),
                        },
                        state=state,
                    )
                except Exception:
                    pass
                if cls == 'recoverable' and retry_enabled and attempts < max_attempts:
                    _sleep_backoff(base_ms, jitter_ms, attempts, phase_name if _retry_metrics_enabled else None, _metrics_cache if _retry_metrics_enabled else None)
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
                try:
                    emit_struct_event(
                        'expiry.phase.event',
                        {
                            'phase': phase_name,
                            'outcome': 'ok',
                            'attempt': attempts,
                            'index': getattr(state,'index','?'),
                            'rule': getattr(state,'rule','?'),
                            'errors': len(getattr(state,'errors',[]) or []),
                            'enriched': len(getattr(state,'enriched',{}) or {}),
                        },
                        state=state,
                    )
                except Exception:
                    pass
                break
            finally:
                total_duration_ms = (time.perf_counter() - phase_started) * 1000.0
                _record_attempt_metrics(phase_name, attempts, final_outcome if final_outcome!='unknown' else None)
        # Final aggregated metrics (only once per phase sequence)
        _record_final_metrics(phase_name, total_duration_ms, final_outcome)
        # Final per-phase event (aggregate)
        try:
            emit_struct_event(
                'expiry.phase.final',
                {
                    'phase': phase_name,
                    'final_outcome': final_outcome,
                    'attempts': attempts,
                    'duration_ms': round(total_duration_ms, 3),
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                },
                state=state,
            )
        except Exception:
            pass
        # Phase last attempts gauge
        if _retry_metrics_enabled:
            try:
                _ensure_retry_metrics(_metrics_cache)
                g = _metrics_cache.get('last_attempts_gauge')
                if g is not None:
                    try:
                        g.labels(phase=phase_name).set(attempts)
                    except Exception:
                        pass
            except Exception:
                pass
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
        if _env_bool('G6_PIPELINE_STRUCT_ERROR_EXPORT', False) and state.error_records:
            import hashlib
            import json
            import time as _t
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
            _hash_val = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:16]
            payload['hash'] = _hash_val
            state.meta['structured_errors'] = payload  # embed into state meta for downstream access
            if _env_bool('G6_PIPELINE_STRUCT_ERROR_EXPORT_STDOUT', False):
                try:
                    print('pipeline.structured_errors', json.dumps(payload, separators=(',',':')))
                except Exception:
                    pass
        # Attach cycle summary optionally after structured errors projection
        if _env_bool('G6_PIPELINE_CYCLE_SUMMARY', True):  # default on
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
                    from src.metrics import get_metrics  # optional metrics facade
                    _m = get_metrics()
                    is_success = 1 if summary.get('phases_error', 0) == 0 else 0
                    _pcs = getattr(_m, 'pipeline_cycle_success', None)
                    if _pcs is not None:
                        try: _pcs.set(is_success)
                        except Exception: pass
                    _pct = getattr(_m, 'pipeline_cycles_total', None)
                    if _pct is not None:
                        try: _pct.inc()
                        except Exception: pass
                    if is_success:
                        _pcst = getattr(_m, 'pipeline_cycles_success_total', None)
                        if _pcst is not None:
                            try: _pcst.inc()
                            except Exception: pass
                    # Error ratio gauge
                    _pcer = getattr(_m, 'pipeline_cycle_error_ratio', None)
                    if _pcer is not None:
                        try:
                            raw_pt = summary.get('phases_total', 0) or 0
                            raw_pe = summary.get('phases_error', 0) or 0
                            pt_val = int(raw_pt) if isinstance(raw_pt, (int, float)) else 0
                            pe_val = int(raw_pe) if isinstance(raw_pe, (int, float)) else 0
                            ratio = (float(pe_val) / float(pt_val)) if pt_val else 0.0
                            _pcer.set(ratio)
                        except Exception:
                            pass
                    # Rolling window success/error rate gauges
                    try:
                        _rw_size_env = _env_int('G6_PIPELINE_ROLLING_WINDOW', 0)
                    except Exception:
                        _rw_size_env = 0
                    if _rw_size_env > 0:
                        try:
                            from collections import deque as _deque
                            # Module-level cache (attribute on function object to avoid global)
                            if not hasattr(execute_phases, '_rolling_window'):
                                # attach deque lazily; use cast for type checker since attribute added dynamically
                                execute_phases._rolling_window = _deque(maxlen=_rw_size_env)
                            window = cast(_deque[int], execute_phases._rolling_window)
                            window.append(1 if is_success else 0)
                            _pcsrw = getattr(_m, 'pipeline_cycle_success_rate_window', None)
                            if _pcsrw is not None:
                                try: _pcsrw.set(sum(window)/len(window))
                                except Exception: pass
                            _pcerw = getattr(_m, 'pipeline_cycle_error_rate_window', None)
                            if _pcerw is not None:
                                try: _pcerw.set(1 - (sum(window)/len(window)))
                                except Exception: pass
                        except Exception:
                            pass
                    # Trends file ingestion (long horizon gauges) gated by env flag
                    if _env_bool('G6_PIPELINE_TRENDS_METRICS', False):  # lightweight file read
                        try:
                            panels_dir = _env_str('G6_PANELS_DIR', 'data/panels') or 'data/panels'
                            trend_path = os.path.join(panels_dir, 'pipeline_errors_trends.json')
                            import json as _json_trm
                            with open(trend_path, encoding='utf-8') as _tfm:
                                _trend_doc = _json_trm.load(_tfm)
                            agg = (_trend_doc.get('aggregate') or {}) if isinstance(_trend_doc, dict) else {}
                            cycles = agg.get('cycles') or 0
                            success_rate = agg.get('success_rate') or 0.0
                            _ptc = getattr(_m, 'pipeline_trends_cycles', None)
                            if _ptc is not None:
                                try: _ptc.set(cycles)
                                except Exception: pass
                            _ptsr = getattr(_m, 'pipeline_trends_success_rate', None)
                            if _ptsr is not None:
                                try: _ptsr.set(success_rate)
                                except Exception: pass
                        except Exception:
                            pass
                except Exception:
                    pass
                # Optional legacy cycle_tables integration
                try:
                    if _env_bool('G6_CYCLE_TABLES_PIPELINE_INTEGRATION', False):
                        try:
                            from src.collectors.helpers.cycle_tables import (
                                record_pipeline_summary,  # optional dependency
                            )
                            record_pipeline_summary(summary)
                        except Exception:
                            pass
                except Exception:
                    pass
                if _env_bool('G6_PIPELINE_CYCLE_SUMMARY_STDOUT', False):
                    import json as _json
                    try:
                        print('pipeline.summary', _json.dumps(summary, separators=(',',':')))
                    except Exception:
                        pass
                # Panel export (errors + summary) if enabled
                if _env_bool('G6_PIPELINE_PANEL_EXPORT', False):
                    try:
                        panels_dir = _env_str('G6_PANELS_DIR', 'data/panels') or 'data/panels'
                        os.makedirs(panels_dir, exist_ok=True)
                        history_enabled = _env_bool('G6_PIPELINE_PANEL_EXPORT_HISTORY', False)
                        hash_enabled = _env_bool('G6_PIPELINE_PANEL_EXPORT_HASH', True)
                        try:
                            history_limit = _env_int('G6_PIPELINE_PANEL_EXPORT_HISTORY_LIMIT', 20)
                        except Exception:
                            history_limit = 20
                        if history_limit < 1:
                            history_limit = 1
                        # Defensive redaction (messages already redacted at record creation; re-apply patterns if any changed mid-run)
                        _redact_patterns = _env_str('G6_PIPELINE_REDACT_PATTERNS', '')
                        _redact_repl = _env_str('G6_PIPELINE_REDACT_REPLACEMENT', '***') or '***'
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
                        import hashlib as _hashlib
                        import json as _json2
                        import time as _t2
                        export['exported_at'] = int(_t2.time())
                        if hash_enabled:
                            try:
                                # Hash stable projection (summary + errors without exported_at or version ordering differences)
                                content_projection = {
                                    'summary': export['summary'],
                                    'errors': export['errors'],
                                    'error_count': export['error_count'],
                                    'version': export['version'],
                                }
                                export['content_hash'] = _hashlib.sha256(_json2.dumps(content_projection, sort_keys=True).encode()).hexdigest()[:16]
                            except Exception:
                                pass
                        export_path = os.path.join(panels_dir, 'pipeline_errors_summary.json')
                        with open(export_path, 'w', encoding='utf-8') as fh:
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
                                    for fname in all_hist:
                                        try:
                                            with open(os.path.join(panels_dir, fname), encoding='utf-8') as _rf:
                                                _d = _json2.load(_rf)
                                            index_entries.append({'file': fname, 'hash': _d.get('content_hash'), 'ts': _d.get('exported_at')})
                                        except Exception:
                                            index_entries.append({'file': fname})
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
                        if _env_bool('G6_PIPELINE_TRENDS_ENABLED', False):
                            try:
                                trend_limit = _env_int('G6_PIPELINE_TRENDS_LIMIT', 200)
                            except Exception:
                                trend_limit = 200
                            if trend_limit < 1:
                                trend_limit = 1
                            try:
                                trend_path = os.path.join(panels_dir, 'pipeline_errors_trends.json')
                                import json as _json_tr
                                try:
                                    with open(trend_path, encoding='utf-8') as _tf:
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




def _log_phase(name: str, started: float, state: ExpiryState, outcome: str) -> None:
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

def _sleep_backoff(base_ms: int, jitter_ms: int, attempt: int, phase: str | None = None, metrics_cache: dict | None = None) -> None:  # pragma: no cover (timing side effect)
    delay_ms = base_ms * (2 ** (attempt-1))
    if jitter_ms > 0:
        delay_ms += random.randint(0, jitter_ms)
    delay_ms = min(delay_ms, 5000)  # ceiling
    if phase and metrics_cache is not None:
        try:
            _ensure_retry_metrics(metrics_cache)
            h = metrics_cache.get('backoff_hist')
            if h:
                try: h.labels(phase=phase).observe(delay_ms / 1000.0)
                except Exception: pass
        except Exception:
            pass
    time.sleep(delay_ms / 1000.0)

def _ensure_retry_metrics(cache: dict) -> None:
    if cache.get('initialized'):
        return
    try:
        from src.metrics import MetricsRegistry  # optional metrics registry
        reg = MetricsRegistry()
        h = getattr(reg, 'pipeline_phase_retry_backoff_seconds', None)
        if h is not None:
            cache['backoff_hist'] = h
        g = getattr(reg, 'pipeline_phase_last_attempts', None)
        if g is not None:
            cache['last_attempts_gauge'] = g
    except Exception:
        pass
    cache['initialized'] = True

def _record_attempt_metrics(phase: str, attempts: int, final_if_known: str | None) -> None:
    """Increment attempt / retry counters. final_if_known ignored until finalization for outcome counters."""
    try:  # lazy registry import pattern consistent with existing code
        from src.metrics import MetricsRegistry  # optional metrics registry
        reg = MetricsRegistry()
        _ppa = getattr(reg, 'pipeline_phase_attempts', None)
        if _ppa is not None:
            try: _ppa.labels(phase=phase).inc()
            except Exception: pass
        if attempts > 1:
            _ppr = getattr(reg, 'pipeline_phase_retries', None)
            if _ppr is not None:
                try: _ppr.labels(phase=phase).inc()
                except Exception: pass
    except Exception:
        pass

def _record_final_metrics(phase: str, duration_ms: float, final_outcome: str) -> None:
    try:
        from src.metrics import MetricsRegistry  # optional metrics registry
        reg = MetricsRegistry()
        _ppo = getattr(reg, 'pipeline_phase_outcomes', None)
        if _ppo is not None:
            try: _ppo.labels(phase=phase, final_outcome=final_outcome).inc()
            except Exception: pass
        _ppd = getattr(reg, 'pipeline_phase_duration_ms', None)
        if _ppd is not None:
            try: _ppd.labels(phase=phase, final_outcome=final_outcome).inc(duration_ms)
            except Exception: pass
        _ppruns = getattr(reg, 'pipeline_phase_runs', None)
        if _ppruns is not None:
            try: _ppruns.labels(phase=phase, final_outcome=final_outcome).inc()
            except Exception: pass
        # Histogram observation (seconds) with lazy env bucket override (set once)
        _ppds = getattr(reg, 'pipeline_phase_duration_seconds', None)
        if _ppds is not None:  # histogram
            try:
                hist = _ppds
                if not hasattr(hist, '_g6_buckets_overridden'):
                    try:
                        from src.collectors.env_adapter import get_str as _env_str
                    except Exception:
                        _env_str = lambda k, d=None: (os.getenv(k, d) if d is not None else (os.getenv(k) or '')).strip()
                    b_env = _env_str('G6_PIPELINE_PHASE_DURATION_BUCKETS','')
                    if b_env:
                        try:
                            arr = [float(x.strip()) for x in b_env.split(',') if x.strip()]
                            if arr:
                                pass  # Documented limitation; cannot mutate buckets at runtime.
                        except Exception:
                            pass
                    hist._g6_buckets_overridden = True
                hist.labels(phase=phase, final_outcome=final_outcome).observe(duration_ms / 1000.0)
            except Exception:
                pass
    except Exception:
        pass
