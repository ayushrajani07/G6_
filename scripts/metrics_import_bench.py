#!/usr/bin/env python3
"""Measure cold import latency for key metrics modules.

Runs N isolated subprocesses (default 5) each importing the target modules
and records wall-clock duration. Outputs JSON summary suitable for CI trend tracking.

Usage:
  python scripts/metrics_import_bench.py --runs 7 --modules src.metrics.generated src.metrics.cardinality_guard --json

Exit codes:
 0 success
 1 internal error / bad args

JSON schema (v0):
{
  "schema": "g6.metrics.import_bench.v0",
  "runs": <int>,
  "modules": [..],
  "samples_sec": [float,...],
  "stats": { "min_sec": float, "p50_sec": float, "p95_sec": float, "max_sec": float, "mean_sec": float },
  "python": "3.11.5",
  "timestamp_utc": "2025-10-04T12:00:00Z"
}
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import statistics
import subprocess
import sys
import time

DEF_MODULES = ["src.metrics.generated"]


def run_import(mods: list[str]) -> float:
    code = "import time,importlib; s=time.time();\n" + \
           "".join([f"import importlib; importlib.import_module('{m}');\n" for m in mods]) + \
           "print(time.time()-s)\n"
    # Use -S to skip site packages overhead? Keep defaults for realistic measure.
    proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"import subprocess failed rc={proc.returncode} stderr={proc.stderr.strip()}")
    try:
        return float(proc.stdout.strip().splitlines()[-1])
    except Exception as err:
        raise RuntimeError(f"unexpected subprocess output: {proc.stdout!r}") from err


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return math.nan
    k = (len(data)-1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[f] * (c-k)
    d1 = data[c] * (k-f)
    return d0 + d1


def main() -> int:
    ap = argparse.ArgumentParser(description='Metrics import latency benchmark')
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--modules', nargs='*', default=DEF_MODULES)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--sleep-between', type=float, default=0.0, help='Optional sleep between runs (seconds)')
    args = ap.parse_args()

    runs = max(1, args.runs)
    samples: list[float] = []
    for i in range(runs):
        t = run_import(args.modules)
        samples.append(t)
        if args.sleep_between > 0 and i < runs-1:
            time.sleep(args.sleep_between)

    ordered = sorted(samples)
    stats = {
        'min_sec': min(ordered),
        'p50_sec': percentile(ordered, 0.50),
        'p95_sec': percentile(ordered, 0.95),
        'max_sec': max(ordered),
        'mean_sec': statistics.fmean(samples),
    }
    out = {
        'schema': 'g6.metrics.import_bench.v0',
        'runs': runs,
        'modules': args.modules,
        'samples_sec': samples,
        'stats': stats,
        'python': sys.version.split()[0],
    'timestamp_utc': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        mods = ",".join(args.modules)
        print(
            f"[import-bench] runs={runs} min={stats['min_sec']:.4f}s "
            f"p50={stats['p50_sec']:.4f}s p95={stats['p95_sec']:.4f}s "
            f"max={stats['max_sec']:.4f}s mean={stats['mean_sec']:.4f}s modules={mods}"
        )
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
