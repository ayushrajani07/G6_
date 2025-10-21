#!/usr/bin/env python3
"""Benchmark harness (skeleton) comparing legacy vs pipeline collectors.

Usage (basic):
  python -m scripts.bench_collectors --indices NIFTY:2:2 --cycles 25

This intentionally avoids external deps; results are approximate and intended
for relative regression tracking, not absolute performance certification.

Outputs JSON to stdout:
{
  "config": {...},
  "legacy": {"cycles": n, "durations_s": [...], "p50_s": x, "p95_s": y},
  "pipeline": {...},
  "delta": {"p50_pct": ..., "p95_pct": ...}
}

Future Enhancements:
  - Provider call counting (needs lightweight instrumentation hook)
  - Optional warmup cycles discard
  - Statistical stability check (variance)
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

from src.collectors.modules.pipeline import run_pipeline  # type: ignore

# Import legacy & pipeline facades
from src.orchestrator.facade import run_collect_cycle  # type: ignore

DEFAULT_INDEX_CFG = {
    'strikes_itm': 1,
    'strikes_otm': 1,
    'expiries': ['2025-12-31']
}

class _DummyProviders:
    """Minimal provider stub (replace with real provider if environment configured)."""
    def get_atm_strike(self, index: str):
        return 100.0
    def get_instruments(self, index: str):  # simple synthetic chain
        base = 100
        chain = []
        for strike in (base-100, base, base+100):
            chain.append({'strike': strike, 'index': index, 'kind': 'CE'})
            chain.append({'strike': strike, 'index': index, 'kind': 'PE'})
        # add dummy expiry field consumed by expiry_map builder if needed
        for rec in chain:
            rec['expiry'] = '2025-12-31'
        return chain


def _build_index_params(specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: {**DEFAULT_INDEX_CFG, **v} for k,v in specs.items()}


def _percentile(vals, p: float):
    if not vals:
        return None
    vs = sorted(vals)
    k = int(round((len(vs)-1)*p))
    return vs[k]


def _summarize(durations):
    return {
        'cycles': len(durations),
        'p50_s': _percentile(durations, 0.50),
        'p95_s': _percentile(durations, 0.95),
        'mean_s': statistics.mean(durations) if durations else None,
        'min_s': min(durations) if durations else None,
        'max_s': max(durations) if durations else None,
    }


def main():  # noqa: D401
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', help='Comma list like NIFTY:2:2,BANKNIFTY:1:1 (itm:otm)', default='NIFTY:1:1')
    ap.add_argument('--cycles', type=int, default=20)
    ap.add_argument('--warmup', type=int, default=2)
    ap.add_argument('--provider', choices=['dummy'], default='dummy')
    ap.add_argument('--json', action='store_true', help='Force JSON (default)')
    args = ap.parse_args()

    specs: dict[str, dict[str, Any]] = {}
    for token in args.indices.split(','):
        if not token:
            continue
        parts = token.split(':')
        name = parts[0]
        try:
            itm = int(parts[1]) if len(parts) > 1 else 1
            otm = int(parts[2]) if len(parts) > 2 else 1
        except Exception:
            itm, otm = 1, 1
        specs[name] = {'strikes_itm': itm, 'strikes_otm': otm}
    index_params = _build_index_params(specs)
    providers = _DummyProviders()

    legacy_durations = []
    pipeline_durations = []

    # Warmup (legacy)
    for _ in range(args.warmup):
        run_collect_cycle(index_params, providers, None, None, None, mode='legacy')
    # Warmup (pipeline)
    for _ in range(args.warmup):
        run_pipeline(index_params, providers, None, None, None)

    for i in range(args.cycles):
        t0 = time.perf_counter()
        run_collect_cycle(index_params, providers, None, None, None, mode='legacy')
        legacy_durations.append(time.perf_counter()-t0)
        t1 = time.perf_counter()
        run_pipeline(index_params, providers, None, None, None)
        pipeline_durations.append(time.perf_counter()-t1)

    legacy_summary = _summarize(legacy_durations)
    pipeline_summary = _summarize(pipeline_durations)

    def _pct_delta(a, b):
        if a is None or b is None or a == 0:
            return None
        return round(((b - a) / a) * 100.0, 2)

    delta = {
        'p50_pct': _pct_delta(legacy_summary['p50_s'], pipeline_summary['p50_s']),
        'p95_pct': _pct_delta(legacy_summary['p95_s'], pipeline_summary['p95_s']),
        'mean_pct': _pct_delta(legacy_summary['mean_s'], pipeline_summary['mean_s']),
    }

    out = {
        'config': {
            'indices': specs,
            'cycles': args.cycles,
            'warmup': args.warmup,
            'provider': args.provider,
        },
        'legacy': legacy_summary,
        'pipeline': pipeline_summary,
        'delta': delta,
    }
    print(json.dumps(out, indent=2, sort_keys=True))

if __name__ == '__main__':  # pragma: no cover
    main()
