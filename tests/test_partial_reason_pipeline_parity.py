import os
from src.collectors.unified_collectors import run_unified_collectors
from tests.test_pipeline_parity_basic import DeterministicProvider

"""Test that partial_reason_totals remain consistent between legacy and pipeline paths.

This focuses specifically on the aggregated partial_reason_totals field after the
Phase 7 snapshot_core refactor to ensure both paths surface identical tallies for
an induced scenario containing PARTIAL expiries with different underlying reasons.
"""

def _configure_params():
    # configure two indices so that we exercise multi-index aggregation path
    return {
        'NIFTY': {
            'symbol': 'NIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        },
        'BANKNIFTY': {
            'symbol': 'BANKNIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        }
    }


def _run(mode: str):
    params = _configure_params()
    prov = DeterministicProvider()
    # Force open market for determinism
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    if mode == 'pipeline':
        os.environ['G6_PIPELINE_COLLECTOR'] = '1'
    else:
        os.environ.pop('G6_PIPELINE_COLLECTOR', None)
    res = run_unified_collectors(params, prov, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)
    return res


def test_partial_reason_totals_parity():
    prev_pipeline = os.environ.get('G6_PIPELINE_COLLECTOR')
    prev_force_open = os.environ.get('G6_FORCE_MARKET_OPEN')
    try:
        legacy = _run('legacy')
        pipeline = _run('pipeline')
    finally:
        # restore env
        if prev_pipeline is None:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        else:
            os.environ['G6_PIPELINE_COLLECTOR'] = prev_pipeline
        if prev_force_open is None:
            os.environ.pop('G6_FORCE_MARKET_OPEN', None)
        else:
            os.environ['G6_FORCE_MARKET_OPEN'] = prev_force_open
    assert isinstance(legacy, dict) and isinstance(pipeline, dict), "collector outputs must be dicts"
    # Both should expose partial_reason_totals key (may be None if no PARTIAL expiries)
    l_tot = legacy.get('partial_reason_totals') if isinstance(legacy, dict) else None
    p_tot = pipeline.get('partial_reason_totals') if isinstance(pipeline, dict) else None
    # Accept either both None (no partials) or identical dicts
    if l_tot is None or p_tot is None:
        assert l_tot == p_tot, "One path produced partial_reason_totals while the other did not"
    else:
        assert l_tot == p_tot, f"partial_reason_totals mismatch legacy={l_tot} pipeline={p_tot}"
