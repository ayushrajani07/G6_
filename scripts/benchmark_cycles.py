"""DEPRECATED STUB: benchmark_cycles.py

Original benchmarking script superseded by internal profiling & unified test harnesses.
Stub Added: 2025-09-30 (Phase 1 Cleanup). Will be removed after grace period.

Tests currently import `run_benchmark` to assert deprecation notice behavior;
this stub preserves the signature with a minimal fast return structure.
"""
from __future__ import annotations
import os, sys, time, json, argparse, logging

_LOG = logging.getLogger("benchmark_cycles_stub")
_WARN = not (os.environ.get('G6_SUPPRESS_DEPRECATIONS','').lower() in {'1','true','yes','on'})

def run_benchmark(cycles: int, interval: float) -> dict:  # type: ignore[override]
    if _WARN:
        _LOG.info("Benchmark script using orchestrator path (legacy unified_main benchmarking deprecated)")
    now = time.time()
    return {
        'cycles': cycles,
        'interval': interval,
        'total_time': 0.0,
        'per_cycle': [0.0]*max(0, cycles),
        'avg_cycle': 0.0,
        'stddev_cycle': 0.0,
        'detail_mode': None,
        'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Deprecated benchmark stub (use modern profiling tools).')
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args(argv)
    result = run_benchmark(args.cycles, args.interval)
    print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
