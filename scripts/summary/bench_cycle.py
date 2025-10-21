"""Benchmark unified loop cycle performance & diff efficiency.

Produces machine-readable JSON with latency distribution and panel diff stats
so CI can assert guardrails (cycle latency & minimum diff hit ratio).

Features:
* Warmup cycles (excluded from stats) to stabilize imports / caches.
* Captures per-cycle ms, panel_updates, total_panels to derive hit ratio.
* Optionally includes SSE publisher plugin to reflect hashing overhead.
* Zero sleep (refresh=0) tight loop focusing on pure processing cost.

JSON schema (example keys):
{
    "cycles": 40,              # measured cycles
    "warmup": 5,               # warmup cycles excluded
    "mean_ms": 3.21,
    "p95_ms": 5.44,
    "median_ms": 3.05,
    "max_ms": 7.1,
    "updates_total": 62,
    "panels_total": 480,
    "updates_per_cycle_avg": 1.55,
    "hit_ratio": 0.968,        # 1 - (updates_total / panels_total) aggregated
    "sse_enabled": true,
    "metrics_enabled": false,
    "latency_ms": [ ... ]      # per-cycle list (optional, gated by --emit-samples)
}

Usage (PowerShell examples):
    python scripts/summary/bench_cycle.py --warmup 5 --measure 40
    python scripts/summary/bench_cycle.py --measure 100 --emit-samples > bench.json

Env Overrides (fallback if args omitted):
    G6_BENCH_WARMUP, G6_BENCH_MEASURE
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

try:
    from .config import SummaryConfig  # type: ignore
    from .plugins.base import OutputPlugin  # type: ignore
    from .unified_loop import UnifiedLoop  # type: ignore
except Exception:  # pragma: no cover - standalone execution fallback
    import pathlib
    import sys
    # Add repository root so absolute imports resolve when run as script
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.summary.config import SummaryConfig  # type: ignore
    from scripts.summary.plugins.base import OutputPlugin  # type: ignore
    from scripts.summary.unified_loop import UnifiedLoop  # type: ignore

# Minimal stub plugin to measure baseline loop overhead without rendering side effects
class NoopPlugin(OutputPlugin):
    name = 'noop'
    def setup(self, context: Any) -> None:
        return
    def process(self, snap: Any) -> None:  # noqa: D401
        return
    def teardown(self) -> None:
        return

@dataclass
class BenchResult:
    cycles: int
    warmup: int
    mean_ms: float
    p95_ms: float
    median_ms: float
    max_ms: float
    updates_total: int
    panels_total: int
    updates_per_cycle_avg: float
    hit_ratio: float
    sse_enabled: bool
    metrics_enabled: bool
    latency_ms: list[float] | None


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    # simple fallback if statistics.quantiles not granular enough
    try:
        import numpy as _np  # type: ignore
        return float(_np.quantile(vals, q))
    except Exception:
        vals_sorted = sorted(vals)
        idx = int(q * (len(vals_sorted)-1))
        return vals_sorted[idx]


def run_bench(warmup: int, measure: int, emit_samples: bool=False) -> BenchResult:
    cfg = SummaryConfig.load()
    plugins: list[OutputPlugin] = [NoopPlugin()]
    # Optionally include SSE plugin to reflect cost of hashing/diff path
    if cfg.sse_enabled:
        try:
            from .plugins.sse import SSEPublisher
            plugins.append(SSEPublisher(diff=True))
        except Exception:
            pass
    loop = UnifiedLoop(plugins, panels_dir=cfg.panels_dir, refresh=0)
    # Warmup cycles (ignore stats)
    for _ in range(warmup):
        snap = loop._build_snapshot()  # noqa: SLF001
        for p in plugins:
            try:  # noqa: PERF203 - isolate per-plugin failures during warmup
                p.process(snap)
            except Exception:  # noqa: PERF203 - continue even if a plugin fails
                pass
    timings: list[float] = []
    updates_total = 0
    panels_total = 0
    for _ in range(measure):
        t0 = time.time()
        snap = loop._build_snapshot()  # noqa: SLF001
        # Derive diff stats if present on snapshot (expected field name diff_stats / panel_hashes)
        diff_stats = getattr(snap, 'diff_stats', None)
        if diff_stats and isinstance(diff_stats, dict):
            # Expect keys: panel_updates_last, total_panel_updates?
            # For aggregated we use current cycle panel_updates_last
            upd_last = diff_stats.get('panel_updates_last') or diff_stats.get('updates_last') or 0
            updates_total += int(upd_last)
        ph = getattr(snap, 'panel_hashes', None)
        if ph and isinstance(ph, dict):
            panels_total += len(ph)
        for p in plugins:
            try:  # noqa: PERF203 - continue processing other plugins if one fails
                p.process(snap)
            except Exception:  # noqa: PERF203 - continue even if a plugin fails
                pass
        timings.append((time.time() - t0) * 1000.0)
    mean_ms = sum(timings)/len(timings) if timings else 0.0
    p95_ms = _quantile(timings, 0.95)
    median_ms = _quantile(timings, 0.5)
    hit_ratio = 0.0
    if panels_total > 0:
        # panels_total is sum of per-cycle panel counts; approximate total panels = panels_total/measure
        approx_total_panels = panels_total / measure
        if approx_total_panels > 0:
            hit_ratio = 1.0 - (updates_total / (approx_total_panels * measure))
            if hit_ratio < 0:
                hit_ratio = 0.0
    return BenchResult(
        cycles=measure,
        warmup=warmup,
        mean_ms=mean_ms,
        p95_ms=p95_ms,
        median_ms=median_ms,
        max_ms=max(timings) if timings else 0.0,
        updates_total=updates_total,
        panels_total=panels_total,
        updates_per_cycle_avg=(updates_total/measure) if measure else 0.0,
        hit_ratio=hit_ratio,
        sse_enabled=cfg.sse_enabled,
        metrics_enabled=cfg.unified_metrics,
        latency_ms=timings if emit_samples else None,
    )


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description='Run unified summary benchmark')
    ap.add_argument('--warmup', type=int, default=int(os.getenv('G6_BENCH_WARMUP', '5') or 5))
    ap.add_argument('--measure', type=int, default=int(os.getenv('G6_BENCH_MEASURE', '40') or 40))
    ap.add_argument('--emit-samples', action='store_true', help='Include per-cycle latency list')
    args = ap.parse_args()
    res = run_bench(args.warmup, args.measure, emit_samples=args.emit_samples)
    payload: dict[str, Any] = res.__dict__.copy()
    if not args.emit_samples:
        payload.pop('latency_ms', None)
    print(json.dumps(payload, separators=(',', ':' )))

if __name__ == '__main__':
    main()
