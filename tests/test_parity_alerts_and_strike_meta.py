"""Parity test for newly added alert summary & strike coverage metadata.

Ensures legacy and pipeline collectors expose identical alert_* field sets and
stable coverage averages within float tolerance, preventing silent drift.
"""
from __future__ import annotations

import os
from math import isclose

from src.collectors.unified_collectors import run_unified_collectors
from tests.test_pipeline_parity_basic import DeterministicProvider  # reuse deterministic provider


def _run(pipeline: bool):
    params = {
        'NIFTY': {
            'symbol': 'NIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 2,
            'strikes_otm': 2,
        }
    }
    prov = DeterministicProvider()
    prev_flag = os.environ.get('G6_PIPELINE_COLLECTOR')
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    try:
        if pipeline:
            os.environ['G6_PIPELINE_COLLECTOR'] = '1'
        else:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        return run_unified_collectors(params, prov, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)
    finally:
        if prev_flag is None:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        else:
            os.environ['G6_PIPELINE_COLLECTOR'] = prev_flag
        os.environ.pop('G6_FORCE_MARKET_OPEN', None)


def test_parity_alert_fields_and_strike_meta():
    legacy = _run(False)
    pipeline = _run(True)
    # Directly inspect legacy/pipeline dict outputs (parity harness removed)
    l_snap = legacy  # type: ignore[assignment]
    p_snap = pipeline  # type: ignore[assignment]
    # Alert field sets identical if present
    l_alerts = set((l_snap.get('alerts') or {}).keys())
    p_alerts = set((p_snap.get('alerts') or {}).keys())
    assert l_alerts == p_alerts
    # Composite alerts_total parity
    if 'alerts_total' in l_snap or 'alerts_total' in p_snap:
        assert l_snap.get('alerts_total') == p_snap.get('alerts_total')
    # Partial reason totals parity (keys + aggregate sum)
    l_pr = l_snap.get('partial_reason_totals') or {}
    p_pr = p_snap.get('partial_reason_totals') or {}
    assert set(l_pr.keys()) == set(p_pr.keys())
    assert sum(l_pr.values()) == sum(p_pr.values())
    # Coverage averages close (may be identical; tolerate tiny float jitter)
    for k in ('strike_coverage_avg_mean','field_coverage_avg_mean'):
        if k in l_snap or k in p_snap:
            assert k in l_snap and k in p_snap
            assert isclose(float(l_snap[k]), float(p_snap[k]), rel_tol=1e-9, abs_tol=1e-9)