"""Provider parity & micro-benchmark harness (A21).

Generates synthetic instrument universes and compares legacy provider
(expiry discovery) with modular components (InstrumentCache + ExpiryResolver).
Captures timing and memory deltas for sizes [default: 50, 200, 500].

Memory tracking uses psutil if available; otherwise falls back to None.
Set G6_BENCH_WRITE=1 to write JSON results to benchmarks/last_run.json.

Usage (module):
    from scripts.benchmarks.provider_parity import run_benchmark
    result = run_benchmark([50,200,500])

CLI:
    python -m scripts.benchmarks.provider_parity --sizes 50 200 500
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

# Synthetic generation -------------------------------------------------------

def make_instruments(index: str, size: int, base_date: dt.date) -> list[dict]:
    out = []
    # Two expiries a week apart
    e1 = base_date + dt.timedelta(days=7)
    e2 = base_date + dt.timedelta(days=14)
    strikes = list(range(100, 100 + size * 50, 50))
    for s in strikes:
        exp = e1 if (s // 50) % 2 == 0 else e2
        out.append({
            'segment': 'NFO-OPT',
            'tradingsymbol': f'{index}{s}',
            'strike': s,
            'expiry': exp.isoformat(),
        })
    return out

# Legacy provider wrappers (stubbed to avoid live API) ----------------------

def legacy_expiries_stub(instruments: list[dict], index: str) -> list[dt.date]:
    # Adapted from legacy logic with simplified ATM filtering window (ignore ATM strike check to keep deterministic)
    today = dt.date.today()
    expiries = set()
    for inst in instruments:
        if not isinstance(inst, dict):
            continue
        if not str(inst.get('segment','')).endswith('-OPT'): continue
        if index not in str(inst.get('tradingsymbol','')): continue
        exp = inst.get('expiry')
        if isinstance(exp, str):
            try:
                d = dt.date.fromisoformat(exp[:10])
                if d >= today:
                    expiries.add(d)
            except Exception:
                pass
    return sorted(expiries)

# Modular wrappers -----------------------------------------------------------
from src.provider.expiries import ExpiryResolver

# Memory helpers -------------------------------------------------------------

def current_rss_mb() -> float | None:
    if psutil is None:
        return None
    try:
        p = psutil.Process()
        return p.memory_info().rss / (1024*1024)
    except Exception:  # pragma: no cover
        return None

@dataclass
class BenchRun:
    size: int
    legacy_duration_ms: float
    modular_duration_ms: float
    legacy_expiry_count: int
    modular_expiry_count: int
    legacy_mem_delta_mb: float | None
    modular_mem_delta_mb: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            'size': self.size,
            'legacy': {
                'duration_ms': round(self.legacy_duration_ms, 3),
                'expiry_count': self.legacy_expiry_count,
                'mem_delta_mb': None if self.legacy_mem_delta_mb is None else round(self.legacy_mem_delta_mb, 3),
            },
            'modular': {
                'duration_ms': round(self.modular_duration_ms, 3),
                'expiry_count': self.modular_expiry_count,
                'mem_delta_mb': None if self.modular_mem_delta_mb is None else round(self.modular_mem_delta_mb, 3),
            },
            'delta_ms': {
                'expiry': round(self.modular_duration_ms - self.legacy_duration_ms, 3),
            }
        }

# Benchmark core -------------------------------------------------------------

def run_benchmark(sizes: Iterable[int]) -> dict[str, Any]:
    base_date = dt.date.today()
    resolver = ExpiryResolver()
    runs: list[BenchRun] = []
    for size in sizes:
        instruments = make_instruments('NIFTY', size, base_date)
        # Legacy timing
        mem_before = current_rss_mb()
        t0 = time.perf_counter()
        legacy_exp = legacy_expiries_stub(instruments, 'NIFTY')
        legacy_dt = (time.perf_counter() - t0) * 1000
        mem_after = current_rss_mb()
        legacy_mem_delta = None if (mem_before is None or mem_after is None) else (mem_after - mem_before)
        # Modular timing (simulate fetch -> resolve extract path)
        def fetch_instruments():
            return instruments
        def atm_provider(_):
            return 100 + (size//2)*50  # synthetic ATM approximation
        mem2_before = current_rss_mb()
        t1 = time.perf_counter()
        modular_exp = resolver.resolve('NIFTY', fetch_instruments, atm_provider, ttl=0.0, now_func=lambda: 0.0)
        modular_dt = (time.perf_counter() - t1) * 1000
        mem2_after = current_rss_mb()
        modular_mem_delta = None if (mem2_before is None or mem2_after is None) else (mem2_after - mem2_before)
        runs.append(BenchRun(size, legacy_dt, modular_dt, len(legacy_exp), len(modular_exp), legacy_mem_delta, modular_mem_delta))
    result = {
        'timestamp': time.time(),
        'runs': [r.to_dict() for r in runs],
        'meta': {
            'psutil_available': psutil is not None,
        }
    }
    if os.environ.get('G6_BENCH_WRITE','').lower() in ('1','true','yes','on'):
        os.makedirs('benchmarks', exist_ok=True)
        with open('benchmarks/last_run.json','w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
    return result

# CLI ------------------------------------------------------------------------
if __name__ == '__main__':  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', nargs='*', type=int, default=[50,200,500])
    args = ap.parse_args()
    res = run_benchmark(args.sizes)
    print(json.dumps(res, indent=2))
