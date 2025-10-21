#!/usr/bin/env python3
"""Smoke test for pipeline rollout gating & shadow comparator.

Runs unified collectors in three modes (legacy, shadow, primary) using a
minimal deterministic dummy provider and prints a compact JSON summary so
operators can visually confirm structural parity / diff wiring.

Usage:
  python scripts/smoke_rollout_modes.py

Optional env:
  G6_FORCE_MARKET_OPEN=1 (recommended for deterministic coverage)
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any


# Minimal embedded provider (avoid test imports)
class _Prov:
    def __init__(self):
        self._ltp = 123.0
    def get_index_data(self, index):
        return self._ltp, {}
    def get_atm_strike(self, index):
        return int(self._ltp)
    def get_expiry_dates(self, index):
        return [datetime.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        out = []
        for s in strikes:
            out.append({'symbol': f"{index}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
            out.append({'symbol': f"{index}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        data: dict[str, Any] = {}
        for inst in instruments:
            data[inst['symbol']] = {
                'oi': 10,
                'instrument_type': inst['instrument_type'],
                'strike': inst['strike'],
                'expiry': None,
            }
        return data

from src.collectors.unified_collectors import run_unified_collectors  # type: ignore

INDEX_PARAMS = {
  'SMOKEIDX': {
    'enable': True,
    'expiries': ['this_week'],
    'strikes_itm': 1,
    'strikes_otm': 1,
  }
}

CSV_SINK = type('Csv', (), {'write_options_data': lambda *a, **k: None, 'write_overview_snapshot': lambda *a, **k: None})()


def _run(mode: str | None):
    if mode:
        os.environ['G6_PIPELINE_ROLLOUT'] = mode
    else:
        os.environ.pop('G6_PIPELINE_ROLLOUT', None)
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    res = run_unified_collectors(index_params=INDEX_PARAMS, providers=_Prov(), csv_sink=CSV_SINK, influx_sink=None, compute_greeks=False, estimate_iv=False, build_snapshots=False)
    summary = {
        'mode': mode or 'legacy',
        'status': res.get('status'),
        'indices_processed': res.get('indices_processed'),
        'have_shadow': 'shadow' in res,
    }
    if 'shadow' in res:
        summary['shadow_severity'] = res['shadow']['diff']['severity']
        summary['shadow_counts_diffs'] = len(res['shadow']['diff']['counts'])
    if res.get('snapshot_summary'):
        summary['alerts_total'] = res['snapshot_summary'].get('alerts_total')
    return summary


def main():
    out = {
      'legacy': _run(None),
      'shadow': _run('shadow'),
      'primary': _run('primary'),
    }
    print(json.dumps(out, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
