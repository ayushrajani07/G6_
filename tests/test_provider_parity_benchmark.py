"""Structural test for provider parity benchmark (A21)."""
from __future__ import annotations
from scripts.benchmarks.provider_parity import run_benchmark


def test_run_benchmark_structure():
    res = run_benchmark([50])
    assert 'runs' in res and isinstance(res['runs'], list) and res['runs']
    r0 = res['runs'][0]
    assert 'legacy' in r0 and 'modular' in r0 and 'delta_ms' in r0
    assert 'expiry_count' in r0['legacy'] and 'expiry_count' in r0['modular']
    # Memory keys present (may be None depending on environment)
    assert 'mem_delta_mb' in r0['legacy']
    assert 'mem_delta_mb' in r0['modular']
