"""Sanity guard for unified summary performance.

Runs a tiny benchmark (few warmup + measured cycles) and asserts latency and
hit ratio thresholds so catastrophic regressions are caught early.

Thresholds chosen to be lenient for CI variability; adjust as architecture evolves.
Skip via env G6_BENCH_SKIP=1 for extremely resource constrained runs.
"""
from __future__ import annotations
import os, json, subprocess, sys
from pathlib import Path

import pytest

MIN_HIT_RATIO = float(os.getenv("G6_BENCH_MIN_HIT_RATIO", "0.30"))  # allow low initial diff efficiency
MAX_P95_MS = float(os.getenv("G6_BENCH_MAX_P95_MS", "150.0"))       # generous CI cap

@pytest.mark.skipif(os.getenv("G6_BENCH_SKIP") in ("1","true","yes"), reason="Benchmark guard skipped by env")
def test_benchmark_sanity():
    repo_root = Path(__file__).resolve().parent.parent
    bench_script = repo_root / "scripts" / "summary" / "bench_cycle.py"
    # Use small numbers to keep test fast
    cmd = [sys.executable, str(bench_script), "--warmup", "2", "--measure", "12"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = proc.stdout.strip().splitlines()[-1]
    data = json.loads(out)
    assert data["cycles"] == 12
    # Basic structural expectations
    for key in ("mean_ms","p95_ms","median_ms","hit_ratio"):
        assert key in data, f"missing key {key} in benchmark output"
    # Guard conditions
    assert data["p95_ms"] <= MAX_P95_MS, f"p95_ms {data['p95_ms']:.2f} exceeds cap {MAX_P95_MS}" 
    # Only enforce hit ratio if some panels were observed
    if data.get("panels_total",0) > 0:
        assert data["hit_ratio"] >= MIN_HIT_RATIO, f"hit_ratio {data['hit_ratio']:.3f} below floor {MIN_HIT_RATIO}" 
