#!/usr/bin/env python3
"""Automated benchmark delta evaluator.

Purpose:
  Run the existing bench_collectors harness for a chosen configuration and emit a
  compact JSON artifact (optionally writing to file) plus best-effort Prometheus
  metrics (if registry provided via env).

Features:
  - Invokes bench_collectors in-process for reuse of logic.
  - Accepts thresholds for p50 and p95 regression (percentage delta).
  - Exits with code 1 if thresholds violated (for CI gating) unless --no-fail.
  - Optional output file (--out) for artifact persistence.
  - Optional metrics emission (G6_BENCH_METRICS=1) producing counters/gauges.

Environment Flags:
  G6_BENCH_METRICS=1 => emit metrics via prometheus_client using default registry.

Example:
  python -m scripts.bench_delta --indices NIFTY:2:2 --cycles 30 --p50-thr 15 --p95-thr 20 --out bench_delta.json

"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from contextlib import redirect_stdout
from typing import Any

# Reuse bench_collectors main internals by importing module
try:
    import scripts.bench_collectors as bench_mod  # type: ignore
except Exception:  # fallback when scripts not on sys.path
    import importlib.machinery
    import importlib.util
    import pathlib
    this_dir = pathlib.Path(__file__).resolve().parent
    project_root = this_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    bench_path = this_dir / 'bench_collectors.py'
    loader = importlib.machinery.SourceFileLoader('bench_collectors_fallback', str(bench_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec and spec.loader:
        bench_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench_mod)  # type: ignore
    else:
        raise


def run_bench(indices: str, cycles: int, warmup: int) -> dict[str, Any]:
    # Build argv simulation for bench_mod.main but capture its stdout JSON
    argv_backup = sys.argv[:]
    sys.argv = [sys.argv[0], '--indices', indices, '--cycles', str(cycles), '--warmup', str(warmup), '--json']
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            bench_mod.main()
    finally:
        sys.argv = argv_backup
    out_txt = buf.getvalue().strip()
    return json.loads(out_txt)


def emit_metrics(result: dict[str, Any]):
    try:
        from prometheus_client import Gauge  # type: ignore
    except Exception:
        return
    legacy = result.get('legacy', {})
    pipeline = result.get('pipeline', {})
    delta = result.get('delta', {})
    # Gauges for absolute times
    g_p50_legacy = Gauge('g6_bench_legacy_p50_seconds','Legacy collector p50 latency (s)')
    g_p50_pipeline = Gauge('g6_bench_pipeline_p50_seconds','Pipeline collector p50 latency (s)')
    g_p95_legacy = Gauge('g6_bench_legacy_p95_seconds','Legacy collector p95 latency (s)')
    g_p95_pipeline = Gauge('g6_bench_pipeline_p95_seconds','Pipeline collector p95 latency (s)')
    g_p50_legacy.set(legacy.get('p50_s') or 0)
    g_p50_pipeline.set(pipeline.get('p50_s') or 0)
    g_p95_legacy.set(legacy.get('p95_s') or 0)
    g_p95_pipeline.set(pipeline.get('p95_s') or 0)
    # Delta gauges
    g_p50_delta = Gauge('g6_bench_delta_p50_pct','Delta p50 % pipeline vs legacy')
    g_p95_delta = Gauge('g6_bench_delta_p95_pct','Delta p95 % pipeline vs legacy')
    g_mean_delta = Gauge('g6_bench_delta_mean_pct','Delta mean % pipeline vs legacy')
    if delta.get('p50_pct') is not None:
        g_p50_delta.set(delta['p50_pct'])
    if delta.get('p95_pct') is not None:
        g_p95_delta.set(delta['p95_pct'])
    if delta.get('mean_pct') is not None:
        g_mean_delta.set(delta['mean_pct'])


def main():  # noqa: D401
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', default='NIFTY:1:1')
    ap.add_argument('--cycles', type=int, default=20)
    ap.add_argument('--warmup', type=int, default=2)
    ap.add_argument('--p50-thr', type=float, default=25.0, help='Max allowed p50 regression % (positive)')
    ap.add_argument('--p95-thr', type=float, default=25.0, help='Max allowed p95 regression % (positive)')
    ap.add_argument('--out', help='Write JSON artifact to file')
    ap.add_argument('--no-fail', action='store_true', help='Do not exit non-zero on threshold breach')
    args = ap.parse_args()

    result = run_bench(args.indices, args.cycles, args.warmup)

    # Evaluate thresholds
    delta = result.get('delta', {})
    breaches = []
    p50 = delta.get('p50_pct')
    p95 = delta.get('p95_pct')
    if p50 is not None and p50 > args.p50_thr:
        breaches.append(f"p50 regression {p50}% > {args.p50_thr}%")
    if p95 is not None and p95 > args.p95_thr:
        breaches.append(f"p95 regression {p95}% > {args.p95_thr}%")

    status = 'ok' if not breaches else 'regression'
    wrapped = {
        'status': status,
        'breaches': breaches,
        'thresholds': {'p50_thr': args.p50_thr, 'p95_thr': args.p95_thr},
        'bench': result,
    }

    # Optional metrics emission
    if os.getenv('G6_BENCH_METRICS','0').lower() in ('1','true','yes','on'):
        emit_metrics(result)

    if args.out:
        try:
            with open(args.out, 'w', encoding='utf-8') as fh:
                json.dump(wrapped, fh, indent=2, sort_keys=True)
        except Exception as e:
            print(f"Failed to write artifact: {e}", file=sys.stderr)

    print(json.dumps(wrapped, indent=2, sort_keys=True))

    if breaches and not args.no_fail:
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    main()
