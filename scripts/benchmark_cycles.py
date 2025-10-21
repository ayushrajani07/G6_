"""DEPRECATED STUB: benchmark_cycles.py

Original cycle benchmark script superseded by consolidated tooling in `bench_tools.py`
and targeted profiling harnesses (e.g., `profile_unified_cycle.py`).

Timeline:
    - Stub Added: 2025-09-30 (Phase 1 Cleanup)
    - Final Removal Target: 2025-10-31 (next wave after consolidation validation)

Behavior:
    - Keeps `run_benchmark(cycles, interval)` signature so existing imports/tests remain green.
    - Emits INFO deprecation banner unless suppressed by `G6_SUPPRESS_DEPRECATIONS`.
    - Returns minimal synthetic metrics (zero timings) to avoid misleading performance data.

Migration:
    Use: `python scripts/bench_tools.py aggregate|diff|verify ...` for artifact workflows or
    `python scripts/profile_unified_cycle.py` for precise per-cycle timing.

This file may be deleted any time after the target removal date without further notice.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time

_LOG = logging.getLogger("benchmark_cycles_stub")
_WARN = os.environ.get('G6_SUPPRESS_DEPRECATIONS','').lower() not in {'1','true','yes','on'}

def run_benchmark(cycles: int, interval: float) -> dict:  # type: ignore[override]
    if _WARN:
        _LOG.info("[DEPRECATED] benchmark_cycles.py -> use bench_tools.py or profile_unified_cycle.py (removal target 2025-10-31)")
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
