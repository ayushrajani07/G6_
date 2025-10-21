"""SSE Publisher micro-benchmark.

Generates synthetic SummarySnapshot objects with controlled change ratios to
benchmark diff build performance and event throughput.

Usage (PowerShell):
  python scripts/bench_sse_loop.py --cycles 500 --panels 60 --change-ratio 0.15

Env interaction:
    Optional: G6_SSE_STRUCTURED=1 to test structured diff mode.
  Optional: G6_SSE_PERF_PROFILE=1 for Prometheus histograms.

Outputs:
  - Total events, diff events/sec, avg hash+diff build time (ms) if perf enabled.
  - Simple percentile approximations for diff build using recorded timings (if hist not available).

NOTE: This avoids network layer—focuses solely on publisher process() costs.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from typing import Any

from scripts.summary.plugins.base import SummarySnapshot
from scripts.summary.plugins.sse import SSEPublisher

# Minimal synthetic panel status builder
PANEL_KEYS = [
    'indices','alerts','providers','latency','dq','perf','memory','gc','extra_a','extra_b','extra_c','extra_d'
]


def make_status(panel_pool: list[str], change_fraction: float, cycle: int) -> dict[str, Any]:
    status: dict[str, Any] = {
        'indices': ['NIFTY','BANKNIFTY'],
        'alerts': {'total': random.randint(0,10)},
        'panel_push_meta': {},
        'app': {'version': 'benchmark'}
    }
    # Add synthetic panels with deterministic-ish content
    for p in panel_pool:
        base = cycle if random.random() < change_fraction else cycle // 2
        status[p] = {'lines': [f"{p}:{base}:{random.randint(0,5)}"]}
    return status

def run_bench(cycles: int, panel_count: int, change_ratio: float, structured: bool) -> dict:
    # Expand panel pool beyond baseline keys
    pool = PANEL_KEYS + [f"p{i}" for i in range(panel_count - len(PANEL_KEYS))] if panel_count > len(PANEL_KEYS) else PANEL_KEYS[:panel_count]
    pub = SSEPublisher(diff=True)  # Always enabled (legacy G6_SSE_ENABLED removed)
    timings: list[float] = []
    start = time.time()
    for c in range(1, cycles+1):
        status = make_status(pool, change_ratio, c)
        snap = SummarySnapshot(status=status, derived={}, panels={}, ts_read=time.time(), ts_built=time.time(), cycle=c, errors=())
        t0 = time.perf_counter()
        pub.process(snap)
        t1 = time.perf_counter()
        timings.append(t1 - t0)
    elapsed = time.time() - start
    events = len(pub.events)
    diff_events = sum(1 for e in pub.events if e.get('event') in ('panel_update','panel_diff'))
    ms = [t*1000.0 for t in timings]
    stats = {
        'cycles': cycles,
        'panels': panel_count,
        'change_ratio': change_ratio,
        'structured': structured,
        'total_events': events,
        'diff_events': diff_events,
        'runtime_sec': elapsed,
        'events_per_sec': events/elapsed if elapsed else 0.0,
        'per_process_ms_avg': statistics.mean(ms),
        'per_process_ms_p50': percentile(ms,50),
        'per_process_ms_p95': percentile(ms,95),
        'per_process_ms_p99': percentile(ms,99),
    }
    return stats


def percentile(seq, p):
    if not seq:
        return 0.0
    s = sorted(seq)
    k = (len(s)-1) * (p/100.0)
    f = int(k); c = min(f+1, len(s)-1)
    if f == c:
        return s[f]
    d = k - f
    return s[f] + (s[c]-s[f]) * d


def main() -> int:
    ap = argparse.ArgumentParser(description='SSE publisher benchmark')
    ap.add_argument('--cycles', type=int, default=200)
    ap.add_argument('--panels', type=int, default=50)
    ap.add_argument('--change-ratio', type=float, default=0.10, help='Fraction (0-1) of panels likely to change per cycle')
    ap.add_argument('--structured', action='store_true', help='Assume structured diff mode (sets env)')
    ap.add_argument('--json', action='store_true', help='Emit JSON stats only')
    ap.add_argument('--budget-p95-ms', type=float, default=None, help='Fail (exit 2) if p95 per-process exceeds this (ms)')
    args = ap.parse_args()

    if args.structured:
        import os
        os.environ['G6_SSE_STRUCTURED'] = '1'
    stats = run_bench(args.cycles, args.panels, args.change_ratio, args.structured)
    if args.json:
        print(json.dumps({'bench': stats}, indent=2))
    else:
        print(f"[bench] cycles={stats['cycles']} panels={stats['panels']} change_ratio={stats['change_ratio']} structured={stats['structured']}")
        print(f"[bench] total_events={stats['total_events']} diff_events={stats['diff_events']} runtime={stats['runtime_sec']:.3f}s events_per_sec={stats['events_per_sec']:.1f}")
        print(f"[bench] per_process_ms avg={stats['per_process_ms_avg']:.3f} p50={stats['per_process_ms_p50']:.3f} p95={stats['per_process_ms_p95']:.3f} p99={stats['per_process_ms_p99']:.3f}")
    if args.budget_p95_ms is not None and stats['per_process_ms_p95'] > args.budget_p95_ms:
        print(f"[bench][BREACH] p95 {stats['per_process_ms_p95']:.2f}ms > budget {args.budget_p95_ms}ms")
        return 2
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
