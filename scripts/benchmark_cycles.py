"""Benchmark cycle execution time in mock mode.

Runs unified_main for a specified number of cycles using the internal
G6_MAX_CYCLES limiter and reports timing statistics as JSON to stdout.

Example (PowerShell):
  $env:G6_ENABLE_OPTIONAL_TESTS='1'
  python scripts/benchmark_cycles.py --cycles 5 --interval 2

Output JSON fields:
  cycles: number of cycles requested
  interval: interval seconds provided
  total_time: wall time (seconds) for run
  per_cycle: list of per-cycle durations (if available, else empty)
  avg_cycle: average per-cycle duration (total_time / cycles)
  stddev_cycle: population stddev over per_cycle if collected else null
  timestamp_utc: ISO8601 UTC timestamp when benchmark completed

Currently per-cycle granular times are not emitted by unified_main, so we
approximate per-cycle list evenly. This still allows rough comparisons.
Future enhancement: instrument unified_main to emit per-cycle timings.
"""
from __future__ import annotations
import os
import sys
import json
import time
import argparse
from statistics import pstdev
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.unified_main import main as unified_main  # noqa: E402

def run_benchmark(cycles: int, interval: int) -> dict:
    start = time.perf_counter()
    os.environ['G6_USE_MOCK_PROVIDER'] = '1'
    os.environ['G6_FANCY_CONSOLE'] = '0'  # minimize console overhead
    os.environ['G6_FORCE_UNICODE'] = '1'
    os.environ['G6_MAX_CYCLES'] = str(cycles)
    os.environ['G6_SKIP_PROVIDER_READINESS'] = '1'

    argv = [
        'unified_main',
        '--config','config/g6_config.json',
        '--mock-data',
        '--interval', str(interval),
        '--metrics-custom-registry',
        '--metrics-reset',
    ]
    old_argv = sys.argv
    try:
        sys.argv = argv
        rc = unified_main()
        if rc not in (0, None):  # pragma: no cover (defensive)
            raise SystemExit(rc)
    finally:
        sys.argv = old_argv
    end = time.perf_counter()
    total = end - start
    # Approximate per cycle evenly until granular instrumentation available
    per_cycle = [total / cycles] * cycles if cycles else []
    avg = total / cycles if cycles else 0.0
    stddev = pstdev(per_cycle) if per_cycle else None
    return {
        'cycles': cycles,
        'interval': interval,
        'total_time': total,
        'per_cycle': per_cycle,
        'avg_cycle': avg,
        'stddev_cycle': stddev,
        'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Benchmark unified_main cycles (mock mode).')
    parser.add_argument('--cycles', type=int, default=3, help='Number of cycles to run (default: 3)')
    parser.add_argument('--interval', type=int, default=2, help='Interval between cycles seconds (default: 2)')
    parser.add_argument('--pretty', action='store_true', help='Pretty print JSON output')
    args = parser.parse_args(argv)

    if args.cycles <= 0:
        parser.error('cycles must be positive')

    result = run_benchmark(args.cycles, args.interval)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
