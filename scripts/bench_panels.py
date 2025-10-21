"""Panel Read Performance Benchmark (Wave 4 – W4-19)

Measures JSON load latency for all *_enveloped.json panel files in a directory.
Intended for lightweight regression detection after schema / size changes.

Outputs a JSON report with per-panel distribution stats (mean, p95, min, max, count)
plus aggregate summary.

Usage (PowerShell):
  python scripts/bench_panels.py --panels-dir data/panels --iterations 50 --output panels_bench.json

Notes:
- Uses time.perf_counter() around full read + json.loads of each panel.
- Re-reads files each iteration (no in-process caching) to capture raw IO + parse cost.
- p95 computed via sorted list index (floor for simplicity) with guard.
- If a panel file disappears mid-run it is skipped (warning counter incremented).
- Designed to be fast: typical iterations=50 across small panels completes quickly (<1s on SSD).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    idx = max(int(len(values) * 0.95) - 1, 0)
    values_sorted = sorted(values)
    return values_sorted[idx]


def benchmark(panels_dir: str, iterations: int) -> dict[str, Any]:
    panels_dir = os.path.abspath(panels_dir)
    # Discover panel files once (restrict to enveloped)
    try:
        all_files = [f for f in os.listdir(panels_dir) if f.endswith('_enveloped.json')]
    except FileNotFoundError:
        raise SystemExit(f"Panels directory not found: {panels_dir}")
    per_panel: dict[str, list[float]] = {f: [] for f in all_files}
    missing_during = 0
    for _ in range(iterations):
        for fname in all_files:
            path = os.path.join(panels_dir, fname)
            start = time.perf_counter()
            try:
                with open(path, encoding='utf-8') as fh:
                    raw = fh.read()
                json.loads(raw)
                elapsed = time.perf_counter() - start
                per_panel[fname].append(elapsed)
            except FileNotFoundError:
                missing_during += 1
            except Exception:
                # Skip but still record a sentinel (omit from stats to avoid skew)
                pass
    report: dict[str, Any] = {
        'panels_dir': panels_dir,
        'iterations': iterations,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'missing_read_errors': missing_during,
        'panels': {},
    }
    agg_all: list[float] = []
    for fname, vals in per_panel.items():
        if not vals:
            continue
        agg_all.extend(vals)
        report['panels'][fname] = {
            'count': len(vals),
            'mean_s': statistics.mean(vals),
            'p95_s': _p95(vals),
            'min_s': min(vals),
            'max_s': max(vals),
        }
    if agg_all:
        report['aggregate'] = {
            'samples': len(agg_all),
            'mean_s': statistics.mean(agg_all),
            'p95_s': _p95(agg_all),
            'min_s': min(agg_all),
            'max_s': max(agg_all),
        }
    else:
        report['aggregate'] = {
            'samples': 0,
            'mean_s': 0.0,
            'p95_s': 0.0,
            'min_s': 0.0,
            'max_s': 0.0,
        }
    return report


def main():  # pragma: no cover (thin CLI wrapper)
    ap = argparse.ArgumentParser()
    ap.add_argument('--panels-dir', default='data/panels', help='Directory containing *_enveloped.json panel files')
    ap.add_argument('--iterations', type=int, default=30, help='Iterations (per panel reads)')
    ap.add_argument('--output', default='panels_bench.json', help='Output JSON report path')
    ap.add_argument('--json', action='store_true', help='Print JSON to stdout')
    args = ap.parse_args()
    report = benchmark(args.panels_dir, args.iterations)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    if args.json:
        print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
