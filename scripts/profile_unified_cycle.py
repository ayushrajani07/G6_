#!/usr/bin/env python3
"""Adaptive multi‑cycle profiling harness for unified collectors.

Primary goals:
 1. Exercise strike coverage + adaptive expansion path over multiple cycles.
 2. Simulate improving strike coverage (coverage ramp) and field coverage quality.
 3. Provide per‑cycle structured summary lines (no external log scraping needed).
 4. Silence persistence errors with an in‑memory CSV sink (keeps logic intact while
        avoiding noisy AttributeErrors in profiling output).

Usage (PowerShell examples):
    # Basic single cycle
    python scripts/profile_unified_cycle.py --indices NIFTY --cycles 1 --report 25 --force-open

    # Multi‑cycle adaptive demo (start with low strike + field coverage, ramp each cycle)
    python scripts/profile_unified_cycle.py --indices NIFTY --cycles 4 --itm 6 --otm 6 `
        --coverage 0.30 --coverage-step 0.25 --field-coverage 0.55 --force-open

Key Options:
    --indices LIST           Comma-separated indices (default NIFTY)
    --cycles N               Number of cycles to run (default 1)
    --report N               Top N cumulative functions in cProfile (default 40)
    --itm / --otm            Initial requested strikes ITM/OTM (default 10/10)
    --step N                 Strike step size fed to synthetic builder (default 50)
    --coverage F             Initial instrument strike coverage fraction (0..1, default 1.0)
    --coverage-step F        Increment added to coverage before each *subsequent* cycle (default 0)
    --field-coverage F       Fraction (0..1) of options given an avg_price to achieve full field coverage (default 1.0)
    --seed N                 RNG seed for deterministic field coverage simulation
    --low-strike-trigger     Shortcut: set initial coverage to 0.4 (handy trigger for adaptive expansion)
    --disable-events         Set G6_DISABLE_STRUCT_EVENTS=1 (measure structured event overhead)
    --force-open             Set G6_FORCE_MARKET_OPEN=1 (bypass market hours logic)
    --open-market            Alias that sets G6_SNAPSHOT_TEST_MODE=1 (legacy test bypass)

Per-cycle summary line format (example):
    CYCLE 2 | strikes_itm 6->8 strikes_otm 6->8 strike_cov 0.55 field_cov 0.60 status PARTIAL reason low_both

Notes:
    * strike_cov is the first expiry's strike coverage (ratio 0..1 rounded to 2dp)
    * field_cov is the first expiry's full-field coverage ratio
    * reason uses current derive_partial_reason logic when status=PARTIAL else '-'
    * Adaptive expansion lines show previous->new depths when an expansion occurred
"""
from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import random
import sys
import time
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.collectors.cycle_context import CycleContext  # type: ignore
from src.collectors.unified_collectors import run_unified_collectors  # type: ignore

try:  # Optional import; profiling hook only
    from src.collectors.helpers.expiry_map import build_expiry_map as _build_expiry_map  # type: ignore
except Exception:  # pragma: no cover
    _build_expiry_map = None  # type: ignore
class _DummyProvider:
    """Synthetic provider implementing subset of expected provider facade used by collectors.

    Exposed methods (best-effort minimal versions):
      - get_index_data(index): returns dict with last_price.
      - get_option_chain(index, expiry): returns (quotes_dict, meta) where quotes_dict keyed by token.
      - list_expiries(index): returns list of 1 synthetic expiry.
    """
    name = 'synthetic'
    def __init__(self, strikes_itm: int, strikes_otm: int, step: int, coverage: float, field_coverage: float, seed: int | None = None):
        self.strikes_itm = strikes_itm
        self.strikes_otm = strikes_otm
        self.step = step
        self.coverage = max(0.0, min(1.0, coverage))
        self.field_coverage = max(0.0, min(1.0, field_coverage))
        self._rng = random.Random(seed if seed is not None else 8675309)
        import datetime as _dt
        self._expiry = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=7)).date()
    def get_index_data(self, index):
        return {'last_price': 100.0, 'index': index}
    def list_expiries(self, index):
        return [self._expiry]
    def get_option_chain(self, index, expiry):
        strikes = [100 - self.step * i for i in range(self.strikes_itm,0,-1)] + [100] + [100 + self.step * i for i in range(1,self.strikes_otm+1)]
        emit_count = max(1, int(len(strikes) * self.coverage))
        strikes_emit = strikes[:emit_count]
        quotes = {}
        for i, k in enumerate(strikes_emit):
            typ = 'CE' if i % 2 == 0 else 'PE'
            token = f"SYNTH|{int(k)}|{typ}"
            quotes[token] = {
                'instrument_type': typ,
                'strike': k,
                'bid': 1.0 + i*0.1,
                'ask': 1.2 + i*0.1,
                'oi': 10 + i,
                'volume': 5 + i,
                # avg_price only if within field coverage fraction
                'avg_price': (1.1 + i*0.1) if (self._rng.random() <= self.field_coverage) else None,
            }
        meta = {'index': index, 'expiry': str(expiry)}
        return quotes, meta
    # Unified collectors may call get_option_instruments + enrich_with_quotes instead of get_option_chain
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        # Apply coverage by truncating strike list deterministically from the head
        emit_count = max(1, int(len(strikes) * self.coverage)) if strikes else 0
        strikes_emit = list(strikes)[:emit_count]
        return [
            {
                'index': index_symbol,
                'expiry': str(expiry_date),
                'strike': s,
                'instrument_type': 'CE' if i % 2 == 0 else 'PE'
            }
            for i, s in enumerate(strikes_emit)
        ]
    def enrich_with_quotes(self, instruments):
        enriched = {}
        for i, inst in enumerate(instruments):
            strike = inst['strike']
            typ = inst['instrument_type']
            token = f"SYNTH|{int(strike)}|{typ}"
            enriched[token] = {
                'instrument_type': typ,
                'strike': strike,
                'bid': 1.0 + i*0.1,
                'ask': 1.2 + i*0.1,
                'oi': 10 + i,
                'volume': 5 + i,
                'avg_price': (1.1 + i*0.1) if (self._rng.random() <= self.field_coverage) else None,
            }
        return enriched

    # Allow external ramp of coverage fraction (strike) & field coverage
    def ramp_coverage(self, delta: float):
        if delta <= 0:
            return
        self.coverage = min(1.0, self.coverage + delta)

    def set_field_coverage(self, frac: float):
        self.field_coverage = max(0.0, min(1.0, frac))

class _ProviderFacade:
    """Facade wrapper presenting expected interface (so code can call providers.get_index_data etc.)."""
    def __init__(self, provider):
        self._p = provider
    def get_index_data(self, index):
        return self._p.get_index_data(index)
    def list_expiries(self, index):
        return self._p.list_expiries(index)
    def get_option_chain(self, index, expiry):
        return self._p.get_option_chain(index, expiry)
    def get_atm_strike(self, index):
        # Simple static ATM approximation for synthetic chain
        return 100.0
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        return self._p.get_option_instruments(index_symbol, expiry_date, strikes)
    def enrich_with_quotes(self, instruments):
        return self._p.enrich_with_quotes(instruments)

class _InMemoryCsvSink:
    """Minimal CSV sink stub implementing write_options_data expected by persist layer.

    Stores last metrics payload so adaptive profiling can still reason about PCR,
    but avoids filesystem writes.
    """
    def __init__(self):
        self.writes = 0
        self.last_metrics = None
        self.allowed_expiry_dates = set()

    def write_options_data(self, index, expiry, options_data, timestamp, *, index_price=None, index_ohlc=None,
                            suppress_overview=False, return_metrics=False, expiry_rule_tag=None, **_):  # noqa: D401
        self.writes += 1
        # Compute lightweight PCR (put OI / call OI)
        call_oi = 0.0; put_oi = 0.0
        for q in options_data.values():
            t = (q.get('instrument_type') or q.get('type') or '').upper()
            oi_val = float(q.get('oi',0) or 0)
            if t == 'CE':
                call_oi += oi_val
            elif t == 'PE':
                put_oi += oi_val
        pcr = put_oi / call_oi if call_oi > 0 else 0.0
        if return_metrics:
            self.last_metrics = {
                'expiry_code': expiry_rule_tag or str(expiry),
                'pcr': pcr,
                'day_width': 0,
                'timestamp': timestamp,
            }
            return self.last_metrics
        return None

    # Overview snapshot writer used by unified collectors after all expiries
    def write_overview_snapshot(self, *_, **__):  # pragma: no cover - no-op
        return None

class _DummyInfluxSink:
    def write_points(self, *_, **__):
        pass

class _DummyMetrics:
    def __init__(self):
        self.collection_cycle_in_progress = type('G', (), {'set': lambda self,x: None})()
    def __getattr__(self, item):
        # Return no-op callables for any metric methods used
        return lambda *a, **k: None


def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', default='NIFTY')
    ap.add_argument('--cycles', type=int, default=1)
    ap.add_argument('--report', type=int, default=40)
    ap.add_argument('--disable-events', action='store_true')
    ap.add_argument('--open-market', action='store_true')
    ap.add_argument('--force-open', action='store_true', help='Set G6_FORCE_MARKET_OPEN=1 (bypass market hours logic)')
    ap.add_argument('--itm', type=int, default=10, help='Requested strikes ITM (synthetic)')
    ap.add_argument('--otm', type=int, default=10, help='Requested strikes OTM (synthetic)')
    ap.add_argument('--step', type=int, default=50, help='Strike step size')
    ap.add_argument('--coverage', type=float, default=1.0, help='Strike coverage fraction (0-1). <1.0 simulates PARTIAL low_strike scenario')
    ap.add_argument('--low-strike-trigger', action='store_true', help='Shortcut: set coverage to 0.4 of requested strikes to trigger adaptive & partial_reason')
    ap.add_argument('--coverage-step', type=float, default=0.0, help='Increment coverage each *next* cycle (simulate improving provider depth)')
    ap.add_argument('--field-coverage', type=float, default=1.0, help='Fraction of options given avg_price (controls field coverage ratio)')
    ap.add_argument('--seed', type=int, default=None, help='RNG seed for deterministic field coverage sampling')
    return ap.parse_args()


def main():
    args = _parse_args()

    if args.disable_events:
        os.environ['G6_DISABLE_STRUCT_EVENTS'] = '1'
    if args.open_market:
        # Bypass market-open gating (test accommodation flag reused) for deterministic runs
        os.environ['G6_SNAPSHOT_TEST_MODE'] = '1'
    if args.force_open:
        os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    if args.low_strike_trigger:
        args.coverage = 0.4

    indices = [s.strip() for s in args.indices.split(',') if s.strip()]
    if not indices:
        print('No indices specified', file=sys.stderr)
        sys.exit(2)

    # Minimal CycleContext (reuse defaults; adapt if needed for deeper profiling)
    # Build minimal context
    dummy_provider = _DummyProvider(args.itm, args.otm, args.step, args.coverage, args.field_coverage, seed=args.seed)
    facade = _ProviderFacade(dummy_provider)
    index_params = {idx: {'strikes_itm': args.itm, 'strikes_otm': args.otm} for idx in indices}
    ctx = CycleContext(index_params=index_params, providers=facade, csv_sink=_InMemoryCsvSink(), influx_sink=_DummyInfluxSink(), metrics=_DummyMetrics())
    ctx.indices = indices  # type: ignore[attr-defined]

    profiler = cProfile.Profile()
    profiler.enable()
    start = time.time()
    # We invoke run_unified_collectors directly; it internally creates its own CycleContext.
    # Use pieces from our constructed ctx (index_params, providers, sinks) for realism if extended later.
    from src.collectors.helpers.status_reducer import derive_partial_reason  # local import for on-demand use
    last_itm = index_params[indices[0]]['strikes_itm'] if indices else None
    last_otm = index_params[indices[0]]['strikes_otm'] if indices else None
    for cycle_num in range(1, args.cycles + 1):
        # Monkeypatch unified_collectors._resolve_expiry to always return synthetic provider expiry
        import src.collectors.unified_collectors as uc  # type: ignore
        if not hasattr(uc, '_orig_resolve_expiry_for_profile'):
            uc._orig_resolve_expiry_for_profile = uc._resolve_expiry  # type: ignore[attr-defined]
            def _profile_resolve_expiry(index_symbol, expiry_rule, providers, metrics, concise_mode):  # noqa: D401
                return dummy_provider._expiry
            uc._resolve_expiry = _profile_resolve_expiry  # type: ignore
        result = run_unified_collectors(
            index_params=ctx.index_params,
            providers=ctx.providers,
            csv_sink=ctx.csv_sink,
            influx_sink=ctx.influx_sink,
            metrics=ctx.metrics,
            build_snapshots=False,
        )
        # Extract first index / first expiry coverage for summary (sufficient for synthetic single-expiry use)
        strike_cov = field_cov = status = partial_reason = None
        try:
            idx_structs = (result or {}).get('indices') or []
            if idx_structs:
                first_idx = idx_structs[0]
                status = first_idx.get('status')
                expiries = first_idx.get('expiries') or []
                if expiries:
                    first_exp = expiries[0]
                    strike_cov = first_exp.get('strike_coverage')
                    field_cov = first_exp.get('field_coverage')
                    if first_exp.get('status') == 'PARTIAL':
                        partial_reason = derive_partial_reason(first_exp)
        except Exception:
            pass
        # Detect adaptive expansion by comparing current vs previous
        cur_itm = index_params[indices[0]]['strikes_itm'] if indices else None
        cur_otm = index_params[indices[0]]['strikes_otm'] if indices else None
        expanded = (cur_itm != last_itm) or (cur_otm != last_otm)
        if expanded:
            expand_note = f"strikes_itm {last_itm}->{cur_itm} strikes_otm {last_otm}->{cur_otm}"
        else:
            expand_note = f"strikes_itm {cur_itm} strikes_otm {cur_otm}"
        print(
            f"CYCLE {cycle_num} | {expand_note} strike_cov {(strike_cov or 0):.2f} field_cov {(field_cov or 0):.2f} status {status or '-'} reason {partial_reason or '-'}"
        )
        last_itm, last_otm = cur_itm, cur_otm
        # Ramp coverage for next cycle BEFORE next invocation (except after final cycle)
        if cycle_num < args.cycles and args.coverage_step > 0:
            dummy_provider.ramp_coverage(args.coverage_step)
        # Field coverage stays constant; could extend with a --field-coverage-step if ever needed
    elapsed = time.time() - start
    profiler.disable()

    # Optional one-shot expiry_map profiling on full synthetic universe (outside cycle loop)
    if os.environ.get('G6_PROFILE_EXPIRY_MAP','0').lower() in ('1','true','yes','on') and _build_expiry_map:
        try:
            strikes_full = [100 - args.step * i for i in range(args.itm,0,-1)] + [100] + [100 + args.step * i for i in range(1,args.otm+1)]
            full_universe = [
                {'expiry': dummy_provider._expiry, 'strike': s, 'instrument_type': ('CE' if i % 2 == 0 else 'PE')}
                for i, s in enumerate(strikes_full)
            ]
            _t_em = time.time(); mapping, stats = _build_expiry_map(full_universe)  # type: ignore
            em_elapsed = (time.time() - _t_em) * 1000.0
            print(f"[expiry_map_profile_total] unique={len(mapping)} total={stats['total']} invalid={stats['invalid_expiry']} t_ms={em_elapsed:.2f}")
        except Exception as e:  # pragma: no cover
            print(f"[expiry_map_profile_total] error={e}")

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumtime')
    ps.print_stats(args.report)

    print('\n=== Profiling Summary ===')
    print(f'Cycles: {args.cycles}')
    print(f'Indices: {indices}')
    print(f'Elapsed: {elapsed:.3f}s')
    print(f'Events disabled: {bool(args.disable_events)}')
    print(f'Strike req (ITM/OTM): {args.itm}/{args.otm} step={args.step} coverage_start={args.coverage} coverage_step={args.coverage_step}')
    print(f'Field coverage frac: {args.field_coverage}')
    print(f'Force open: {args.force_open}')

    # Highlight a few hot symbols explicitly if present
    HOT_SYMBOLS = [
        'derive_partial_reason',
        'adaptive_retry',
        'option_match_stats',
        'emit_option_match_stats',
        'emit_cycle_status_summary',
    ]
    text = s.getvalue()
    print('\n=== Hot Symbol Filter (grep) ===')
    for sym in HOT_SYMBOLS:
        for line in text.splitlines():
            if sym in line:
                print(line)
                break
    print('\n=== Top (first block) ===')
    print('\n'.join(text.splitlines()[: args.report + 5]))


if __name__ == '__main__':  # pragma: no cover
    main()
