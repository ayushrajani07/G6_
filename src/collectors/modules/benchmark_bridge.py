"""Benchmark / Anomaly Bridge (Phase 5 extraction)

Responsibility: Encapsulate benchmark artifact assembly, optional anomaly annotation,
compression selection, digest computation, write, retention pruning, and associated
Prometheus metrics updates. This isolates persistence + anomaly logic from the
monolithic `unified_collectors` file for clearer testing and future evolution.

Design Goals:
- Pure-ish core assembly function returning the payload dict (side-effect free)
- Wrapper apply side-effects (file IO, compression, retention, metrics)
- Accept already prepared index summary structure (indices_struct) identical to legacy
- Preserve field names & ordering to ensure parity (digest must remain stable)

Key Environment Variables (documented in env_dict.md):
- G6_BENCHMARK_DUMP (path)
- G6_BENCHMARK_COMPRESS (bool)
- G6_BENCHMARK_KEEP_N (int)
- G6_BENCHMARK_ANNOTATE_OUTLIERS (bool)
- G6_BENCHMARK_ANOMALY_HISTORY (int)
- G6_BENCHMARK_ANOMALY_THRESHOLD (float)

Public Entry:
    write_benchmark_artifact(indices_struct, total_elapsed, ctx_like, metrics, detect_anomalies_fn)

`ctx_like` is any object providing optional attributes: phase_times, phase_failures, logger-like.

Parity Notes:
- Filename pattern benchmark_cycle_<UTC_ISO>.json(.gz) preserved.
- Microsecond timestamp formatting identical.
- Digest computed before indentation using sorted keys, separators (',',':'), ensure_ascii=False.
- Collision handling for duplicate timestamps retained.
- Anomaly payload identical (keys: anomalies, anomaly_summary, thresholds etc.).
- Metrics instantiation lazy & guarded by attribute existence checks.

Future (Phase 6+): Could be invoked from pipeline orchestrator; stateful anomaly history
could move to ring buffer avoiding disk scan if needed.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import os
import pathlib
from collections.abc import Callable
from typing import Any

# Type alias for anomaly detector (series, threshold) -> (flags, scores)
# NOTE: Downstream `src.bench.anomaly.detect_anomalies` signature is
#   detect_anomalies(series: Iterable[float], threshold: float = 3.5, min_points: int = 5)
# so our injected callable must accept (series, threshold) and return (flags, scores).
AnomalyDetector = Callable[[list[float], float], tuple[list[bool], list[float]]]

# Sentinel environment parsing helpers
_BOOL_TRUE = {'1','true','yes','on'}

def _bool_env(name: str) -> bool:
    return os.environ.get(name,'').lower() in _BOOL_TRUE

def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default

def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default

def _make_payload(indices_struct: list[dict[str, Any]], total_elapsed: float, ctx_like: Any) -> dict[str, Any]:
    phase_times = getattr(ctx_like, 'phase_times', {})
    phase_failures = getattr(ctx_like, 'phase_failures', {})
    # Sum options_total replicating legacy computation
    options_total = sum((ex.get('options') or 0) for ix in indices_struct for ex in (ix.get('expiries') or []))
    ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S%fZ')
    payload: dict[str, Any] = {
        'version': 1,
        'timestamp': ts,
        'duration_s': total_elapsed,
        'phase_times': phase_times,
        'phase_failures': phase_failures,
        'options_total': options_total,
        'indices': [
            {
                'index': ix.get('index'),
                'status': ix.get('status'),
                'expiries': [
                    {
                        'rule': ex.get('rule'),
                        'status': ex.get('status'),
                        'options': ex.get('options'),
                        'strike_coverage': ex.get('strike_coverage'),
                        'field_coverage': ex.get('field_coverage'),
                        'partial_reason': ex.get('partial_reason'),
                    } for ex in (ix.get('expiries') or [])
                ]
            } for ix in indices_struct
        ],
        'partial_reason_totals': None,  # filled opportunistically by caller (struct event helper)
    }
    # Caller will compute partial_reason_totals like legacy; we leave placeholder for parity
    return payload

def _annotate_anomalies(payload: dict[str, Any], dump_root: pathlib.Path, detect_fn: Callable[[list[float], float], tuple[list[bool], list[float]]], logger: Any) -> None:
    if not _bool_env('G6_BENCHMARK_ANNOTATE_OUTLIERS'):
        return
    # History window (legacy default 60)
    hist_limit = _int_env('G6_BENCHMARK_ANOMALY_HISTORY', 60)
    threshold_val = _float_env('G6_BENCHMARK_ANOMALY_THRESHOLD', 3.5)
    prev_opts: list[float] = []
    prev_durs: list[float] = []
    try:
        files = sorted([p for p in dump_root.glob('benchmark_cycle_*.json*') if p.is_file()])
        if files:
            files = files[-hist_limit:]
        for fp in files:
            # Skip collision with current timestamp (not yet written) -> file starting same ts (rare) ignored
            if fp.name.startswith(f"benchmark_cycle_{payload['timestamp']}"):
                continue
            try:
                if fp.suffix == '.gz' or fp.name.endswith('.json.gz'):
                    with gzip.open(fp, 'rt', encoding='utf-8') as fh:
                        data = json.load(fh)
                else:
                    with open(fp, encoding='utf-8') as fh:
                        data = json.load(fh)
                if isinstance(data, dict):
                    ot = data.get('options_total')
                    if isinstance(ot, (int, float)):
                        prev_opts.append(float(ot))
                    dur = data.get('duration_s')
                    if isinstance(dur, (int, float)):
                        prev_durs.append(float(dur))
            except Exception:
                continue
    except Exception:
        pass
    cur_opts_series = prev_opts + [float(payload.get('options_total') or 0)]
    cur_dur_series = prev_durs + [float(payload.get('duration_s') or 0.0)]
    anomalies_struct: dict[str, Any] = {}
    try:
        if len(cur_opts_series) >= 5:
            # Pass threshold explicitly; detector expected to apply robust z-score logic.
            flags, scores = detect_fn(cur_opts_series, threshold_val)
            anomalies_struct['options_total'] = {
                'is_anomaly': bool(flags[-1]),
                'score': float(scores[-1]),
                'threshold': threshold_val,
                'history_len': len(cur_opts_series),
                'recent_flags': int(sum(flags)),
            }
    except Exception:
        if logger:
            logger.debug('benchmark_anomaly_options_failed', exc_info=True)
    try:
        if len(cur_dur_series) >= 5:
            flags, scores = detect_fn(cur_dur_series, threshold_val)
            anomalies_struct['duration_s'] = {
                'is_anomaly': bool(flags[-1]),
                'score': float(scores[-1]),
                'threshold': threshold_val,
                'history_len': len(cur_dur_series),
                'recent_flags': int(sum(flags)),
            }
    except Exception:
        if logger:
            logger.debug('benchmark_anomaly_duration_failed', exc_info=True)
    if anomalies_struct:
        try:
            max_sev = 0.0
            total_flags = 0
            for meta in anomalies_struct.values():
                try:
                    total_flags += 1 if meta.get('is_anomaly') else 0
                    max_sev = max(max_sev, abs(float(meta.get('score') or 0.0)))
                except Exception:
                    pass
            payload['anomalies'] = anomalies_struct
            payload['anomaly_summary'] = {'active_flags': total_flags, 'max_severity': max_sev}
        except Exception:
            payload['anomalies'] = anomalies_struct


def write_benchmark_artifact(indices_struct: list[dict[str, Any]], total_elapsed: float, ctx_like: Any, metrics: Any, detect_anomalies_fn: Callable[[list[float], float], tuple[list[bool], list[float]]] | None = None) -> None:
    """High-level entry to perform benchmark artifact lifecycle.

    Mirrors semantics of legacy inline block in `unified_collectors` for parity.
    Swallows all exceptions (non-fatal path).
    """
    dump_root = os.environ.get('G6_BENCHMARK_DUMP')
    if not dump_root:
        return
    logger = getattr(ctx_like, 'logger', None)
    try:
        root = pathlib.Path(dump_root)
        root.mkdir(parents=True, exist_ok=True)
        payload = _make_payload(indices_struct, total_elapsed, ctx_like)
        # partial_reason_totals population remains in caller after struct event emission; left None here for parity
        if detect_anomalies_fn and _bool_env('G6_BENCHMARK_ANNOTATE_OUTLIERS'):
            try:
                _annotate_anomalies(payload, root, detect_anomalies_fn, logger)
            except Exception:
                pass
        # Digest computed before pretty dump
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(',',':'), ensure_ascii=False)
            payload['digest_sha256'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        except Exception:
            payload['digest_sha256'] = None
        compress = _bool_env('G6_BENCHMARK_COMPRESS')
        suffix = 'json.gz' if compress else 'json'
        out_file = root / f"benchmark_cycle_{payload['timestamp']}.{suffix}"
        if out_file.exists():
            ctr = 1
            base = out_file.stem
            while out_file.exists() and ctr < 1000:
                out_file = root / f"benchmark_cycle_{payload['timestamp']}_{ctr}.{suffix}"
                ctr += 1
        try:
            if compress:
                with gzip.open(out_file, 'wt', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            else:
                with open(out_file, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            if logger:
                logger.debug(f"Benchmark baseline artifact written: {out_file}")
        except Exception:
            if logger:
                logger.debug('benchmark_dump_write_failed', exc_info=True)
        # Metrics (best-effort)
        if metrics is not None:
            try:
                from prometheus_client import Counter as _C
                from prometheus_client import Gauge as _G
                from prometheus_client import Summary as _S
                # Last options total gauge
                if not hasattr(metrics, 'benchmark_last_options_total'):
                    try: metrics.benchmark_last_options_total = _G('g6_benchmark_last_options_total','Last cycle aggregate options_total')
                    except Exception: pass
                # Cycle duration summary
                if not hasattr(metrics, 'benchmark_cycle_duration_seconds'):
                    try: metrics.benchmark_cycle_duration_seconds = _S('g6_benchmark_cycle_duration_seconds','Benchmark cycle duration seconds summary')
                    except Exception: pass
                # Anomaly metrics (if anomalies present)
                if 'anomalies' in payload:
                    if not hasattr(metrics, 'benchmark_anomalies_total'):
                        try: metrics.benchmark_anomalies_total = _C('g6_benchmark_anomalies_total','Count of benchmark cycles with at least one anomaly detected')
                        except Exception: pass
                    if not hasattr(metrics, 'benchmark_last_anomaly_severity'):
                        try: metrics.benchmark_last_anomaly_severity = _G('g6_benchmark_last_anomaly_severity','Max anomaly severity (abs robust z-score) for latest cycle')
                        except Exception: pass
                g_last = getattr(metrics, 'benchmark_last_options_total', None)
                s_dur = getattr(metrics, 'benchmark_cycle_duration_seconds', None)
                if g_last:
                    try: g_last.set(payload.get('options_total') or 0)
                    except Exception: pass
                if s_dur:
                    try: s_dur.observe(payload.get('duration_s') or 0)
                    except Exception: pass
                if 'anomalies' in payload:
                    c = getattr(metrics, 'benchmark_anomalies_total', None)
                    g = getattr(metrics, 'benchmark_last_anomaly_severity', None)
                    if c and any(m.get('is_anomaly') for m in payload.get('anomalies', {}).values()):
                        try: c.inc()
                        except Exception: pass
                    if g and 'anomaly_summary' in payload:
                        try: g.set(payload['anomaly_summary'].get('max_severity') or 0)
                        except Exception: pass
            except Exception:
                if logger:
                    logger.debug('benchmark_cycle_metrics_failed', exc_info=True)
        # Retention pruning
        keep_n = _int_env('G6_BENCHMARK_KEEP_N', 0)
        if keep_n > 0:
            try:
                files = sorted([p for p in root.glob('benchmark_cycle_*.json*') if p.is_file()])
                if len(files) > keep_n:
                    for old in files[:len(files)-keep_n]:
                        try: old.unlink()
                        except Exception: pass
                if metrics is not None:
                    try:
                        from prometheus_client import Gauge as _G
                        if not hasattr(metrics, 'benchmark_artifacts_retained'):
                            try: metrics.benchmark_artifacts_retained = _G('g6_benchmark_artifacts_retained','Count of benchmark artifacts retained after pruning')
                            except Exception: pass
                        g_art = getattr(metrics, 'benchmark_artifacts_retained', None)
                        if g_art:
                            remaining = [p for p in root.glob('benchmark_cycle_*.json*') if p.is_file()]
                            try: g_art.set(len(remaining))
                            except Exception: pass
                    except Exception:
                        if logger:
                            logger.debug('benchmark_artifacts_retained_metric_failed', exc_info=True)
            except Exception:
                if logger:
                    logger.debug('benchmark_dump_retention_failed', exc_info=True)
    except Exception:
        if logger:
            logger.debug('benchmark_dump_failed', exc_info=True)
