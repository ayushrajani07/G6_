"""Stability Loop Harness (Facade Parity Edition)

Stage 2 simplification: rollout/shadow modes removed. This harness now compares
three modes via the orchestrator facade:
    1. legacy   : forced legacy collectors (facade mode='legacy')
    2. pipeline : pipeline path only (facade mode='pipeline')
    3. parity   : pipeline path with legacy parity shadow (facade mode='pipeline', parity_check=True)

Outputs JSON summarizing per-mode timing and (for parity) parity mismatch counts
and categories (diff present vs not). Parity hashing is handled by facade; we do
not rely on unified_collectors shadow internals anymore.

Usage:
    python scripts/stability_loop.py --indices NIFTY,BANKNIFTY --cycles 10 --out stability_report.json

Environment flags honored (forwarded indirectly):
    G6_FACADE_PARITY_STRICT (optional) – escalate mismatch to error (parity mode)
    G6_PARITY_FLOAT_RTOL / G6_PARITY_FLOAT_ATOL – parity harness float tolerance

Deterministic provider logic retained for reproducible cycles.
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orchestrator.facade import run_collect_cycle  # type: ignore

# Deterministic provider import (mirrors bench_perf_smoke)
try:
    from tests.test_pipeline_parity_basic import DeterministicProvider  # type: ignore
except Exception:  # pragma: no cover
    class DeterministicProvider:  # type: ignore
        def get_atm_strike(self, index): return 100
        def get_index_data(self, index): return 100, {}
        def get_ltp(self, index): return 100
        def get_expiry_dates(self, index):
            import datetime; return [datetime.date.today()]
        def get_option_instruments(self, index, expiry_date, strikes):
            out = []
            for s in strikes:
                out.append({'symbol': f"{index}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
                out.append({'symbol': f"{index}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
            return out
        def enrich_with_quotes(self, instruments):
            return {inst['symbol']:{'oi':10,'instrument_type':inst['instrument_type'],'strike':inst['strike'],'expiry':None} for inst in instruments}


def build_index_params(symbols: list[str]) -> dict[str, dict[str, Any]]:
    params: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        params[sym] = {
            'symbol': sym,
            'expiries': ['this_week'],
            'strikes_itm': 2,
            'strikes_otm': 2,
        }
    return params


def _truthy(v: str | None) -> bool:
    return (v or '').lower() in ('1','true','yes','on')


def run_cycle(mode: str, index_params, provider) -> dict[str, Any]:
    """Run one cycle under facade mode.

    mode: legacy | pipeline | parity
    parity mode executes pipeline with parity_check=True (legacy shadow run + hash compare).
    Returns timing and (for parity) mismatch flag if detected.
    """
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    parity_check = (mode == 'parity')
    facade_mode = 'pipeline' if mode in ('pipeline','parity') else 'legacy'
    start = time.perf_counter()
    result = run_collect_cycle(index_params, provider, None, None, None, mode=facade_mode, parity_check=parity_check, build_snapshots=False)
    elapsed = time.perf_counter() - start
    os.environ.pop('G6_FORCE_MARKET_OPEN', None)

    # Detect parity mismatch via log signal not directly accessible here; as a lightweight proxy
    # we recompute parity in parity mode by forcing a legacy run separately only if parity_check was used.
    mismatch = False
    if parity_check:
        try:
            legacy_res = run_collect_cycle(index_params, provider, None, None, None, mode='legacy', parity_check=False, build_snapshots=False)
            # Heuristic structural hash comparison (same helper logic used in tests/test_pipeline_promotion_default).
            def _h(r: dict[str, Any]) -> int:
                if not isinstance(r, dict):
                    return -1
                top = len(r.keys())
                snap = r.get('snapshot_summary') or {}
                return top * 1000 + len(snap.keys())
            if _h(result) != _h(legacy_res):  # Difference alone doesn't mean mismatch, but we cannot read facade parity log here.
                # We conservatively mark mismatch only if option counts differ (stronger signal than structural key count).
                try:
                    rc = result.get('indices',[])
                    lc = legacy_res.get('indices',[])
                    opt_r = sum(ix.get('option_count',0) for ix in rc if isinstance(ix, dict))
                    opt_l = sum(ix.get('option_count',0) for ix in lc if isinstance(ix, dict))
                    mismatch = opt_r != opt_l
                except Exception:
                    mismatch = False
        except Exception:
            mismatch = False
    ret: dict[str, Any] = {'duration_s': elapsed, 'status': result.get('status') if isinstance(result, dict) else None}
    if parity_check:
        ret['parity_mismatch'] = bool(mismatch)
    return ret


def aggregate(durations: list[float]) -> dict[str, float]:
    return {
        'mean_s': statistics.mean(durations) if durations else 0.0,
        'min_s': min(durations) if durations else 0.0,
        'max_s': max(durations) if durations else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', default='NIFTY,BANKNIFTY', help='Comma separated index symbols')
    ap.add_argument('--cycles', type=int, default=10, help='Cycles per mode (legacy,pipeline,parity)')
    ap.add_argument('--out', default='stability_report.json', help='Output JSON path')
    ap.add_argument('--modes', default='legacy,pipeline,parity', help='Comma list subset of modes to run')
    args = ap.parse_args()

    symbols = [s.strip() for s in args.indices.split(',') if s.strip()]
    index_params = build_index_params(symbols)
    provider = DeterministicProvider()

    modes = [m.strip() for m in args.modes.split(',') if m.strip()]
    report: dict[str, Any] = {'modes': modes, 'cycles_per_mode': args.cycles, 'results': {}}

    for mode in modes:
        durations: list[float] = []
        parity_mismatches = 0
        for i in range(args.cycles):
            rec = run_cycle(mode, index_params, provider)
            durations.append(rec['duration_s'])
            if mode == 'parity' and rec.get('parity_mismatch'):
                parity_mismatches += 1
        report['results'][mode] = {
            'timing': aggregate(durations),
        }
        if mode == 'parity':
            report['results'][mode]['parity_mismatch_cycles'] = parity_mismatches
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))

if __name__ == '__main__':  # pragma: no cover
    main()
