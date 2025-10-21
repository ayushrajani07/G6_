"""Performance Smoke Benchmark (Phase 9)

Measures wall time for one collectors cycle under:
  1. Legacy path (pipeline disabled)
  2. Pipeline path + sync enrichment
  3. Pipeline path + async enrichment (if async executor available)

Outputs a simple JSON report with timings and relative speedups.
Not a rigorous benchmark; intended for quick regression detection in CI or dev.

Usage (powershell):
  python scripts/bench_perf_smoke.py --indices NIFTY,BANKNIFTY --cycles 3

Env flags honored:
  G6_FORCE_MARKET_OPEN=1 (auto-set by script for determinism)
  G6_ENRICH_ASYNC=1 (for async variant)

"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any, cast

# Ensure project root on path when executed directly (not via module runner)
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.collectors.unified_collectors import run_unified_collectors  # type: ignore

# Reuse existing deterministic provider if available else fallback minimal
try:
    from tests.test_pipeline_parity_basic import DeterministicProvider  # type: ignore
except Exception:  # pragma: no cover
    class DeterministicProvider:  # type: ignore
        def __init__(self):
            self._ltp = 100.0
        def get_atm_strike(self, index):
            return 100
        def get_index_data(self, index):
            return 100, {}
        def get_ltp(self, index):
            return 100
        def get_expiry_dates(self, index):
            import datetime
            return [datetime.date.today()]
        def get_option_instruments(self, index, expiry_date, strikes):
            out = []
            for s in strikes:
                out.append({'symbol': f"{index}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
                out.append({'symbol': f"{index}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
            return out
        def enrich_with_quotes(self, instruments):
            data = {}
            for inst in instruments:
                data[inst['symbol']] = {
                    'oi': 10,
                    'instrument_type': inst['instrument_type'],
                    'strike': inst['strike'],
                    'expiry': None,
                }
            return data


def _build_index_params(symbols: list[str]) -> dict[str, dict[str, Any]]:
    params: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        params[sym] = {
            'symbol': sym,
            'expiries': ['this_week'],
            'strikes_itm': 2,
            'strikes_otm': 2,
        }
    return params


def _run_cycle(index_params, provider, *, pipeline: bool, async_enrich: bool) -> float:
    prev_pipeline = os.environ.get('G6_PIPELINE_COLLECTOR')
    prev_async = os.environ.get('G6_ENRICH_ASYNC')
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    if pipeline:
        os.environ['G6_PIPELINE_COLLECTOR'] = '1'
    else:
        os.environ.pop('G6_PIPELINE_COLLECTOR', None)
    if async_enrich:
        os.environ['G6_ENRICH_ASYNC'] = '1'
    else:
        os.environ.pop('G6_ENRICH_ASYNC', None)
    start = time.perf_counter()
    run_unified_collectors(index_params, provider, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)
    elapsed = time.perf_counter() - start
    # restore
    if prev_pipeline is None:
        os.environ.pop('G6_PIPELINE_COLLECTOR', None)
    else:
        os.environ['G6_PIPELINE_COLLECTOR'] = prev_pipeline
    if prev_async is None:
        os.environ.pop('G6_ENRICH_ASYNC', None)
    else:
        os.environ['G6_ENRICH_ASYNC'] = prev_async
    os.environ.pop('G6_FORCE_MARKET_OPEN', None)
    return elapsed


def benchmark(symbols: list[str], cycles: int) -> dict[str, Any]:
    provider = DeterministicProvider()
    index_params = _build_index_params(symbols)
    results: dict[str, list[float]] = {
        'legacy': [],
        'pipeline_sync': [],
        'pipeline_async': [],
    }
    for i in range(cycles):
        results['legacy'].append(_run_cycle(index_params, provider, pipeline=False, async_enrich=False))
        results['pipeline_sync'].append(_run_cycle(index_params, provider, pipeline=True, async_enrich=False))
        # Async path optional – if enrichment_async not available call still falls back, so include
        results['pipeline_async'].append(_run_cycle(index_params, provider, pipeline=True, async_enrich=True))
    def _summary(vals: list[float]) -> dict[str, float]:
        return {
            'mean_s': statistics.mean(vals),
            'p95_s': sorted(vals)[int(len(vals)*0.95)-1] if vals else 0.0,
            'min_s': min(vals),
            'max_s': max(vals),
        }
    out: dict[str, Any] = {k: _summary(v) for k,v in results.items()}
    # Relative speedups
    base = out['legacy']['mean_s'] or 1.0
    # Store speedups as floats (0.0 sentinel if division invalid) for schema stability
    out['speedup_pipeline_sync_vs_legacy'] = cast(Any, (
        base / out['pipeline_sync']['mean_s'] if out['pipeline_sync']['mean_s'] else 0.0
    ))
    out['speedup_pipeline_async_vs_legacy'] = cast(Any, (
        base / out['pipeline_async']['mean_s'] if out['pipeline_async']['mean_s'] else 0.0
    ))
    out['speedup_async_vs_sync_pipeline'] = cast(Any, (
        (out['pipeline_sync']['mean_s'] / out['pipeline_async']['mean_s']) if out['pipeline_async']['mean_s'] else 0.0
    ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', default='NIFTY,BANKNIFTY', help='Comma separated index symbols')
    ap.add_argument('--cycles', type=int, default=3, help='Number of cycles per variant')
    ap.add_argument('--output', default='perf_smoke.json', help='Output JSON path')
    args = ap.parse_args()
    symbols = [s.strip() for s in args.indices.split(',') if s.strip()]
    report = benchmark(symbols, args.cycles)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
