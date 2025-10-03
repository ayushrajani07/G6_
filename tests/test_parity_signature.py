"""Parity signature tests for legacy vs pipeline collector outputs.

Validates:
- Reduced structures match between legacy and pipeline for deterministic provider.
- Signatures identical when reduced identical.
- Minor float jitter within tolerance does not produce drift diff.
- Structural change (index removed) triggers categorized diff.
"""
from __future__ import annotations

import os
import copy
from pathlib import Path

from src.collectors.unified_collectors import run_unified_collectors
from src.parity.signature import build_reduced, compute_signature, diff_reduced
from tests.test_pipeline_parity_basic import DeterministicProvider  # reuse provider utility


def _run(mode: str):
    # mode: 'legacy' or 'pipeline'
    index_params = {
        'NIFTY': {
            'symbol': 'NIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 2,
            'strikes_otm': 2,
        },
        'BANKNIFTY': {
            'symbol': 'BANKNIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        }
    }
    provider = DeterministicProvider()
    prev_pipeline = os.environ.get('G6_PIPELINE_COLLECTOR')
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    try:
        if mode == 'pipeline':
            os.environ['G6_PIPELINE_COLLECTOR'] = '1'
        else:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        return run_unified_collectors(index_params, provider, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)
    finally:
        if prev_pipeline is None:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        else:
            os.environ['G6_PIPELINE_COLLECTOR'] = prev_pipeline
        os.environ.pop('G6_FORCE_MARKET_OPEN', None)


def test_parity_signature_identical():
    legacy = _run('legacy')
    pipeline = _run('pipeline')
    assert isinstance(legacy, dict) and isinstance(pipeline, dict), "collector outputs must be dicts"
    r_legacy = build_reduced(legacy)  # type: ignore[arg-type]
    r_pipeline = build_reduced(pipeline)  # type: ignore[arg-type]
    assert diff_reduced(r_legacy, r_pipeline) == []
    assert compute_signature(r_legacy) == compute_signature(r_pipeline)


def test_parity_float_jitter_tolerated():
    legacy = _run('legacy')
    pipeline = _run('pipeline')
    assert isinstance(legacy, dict) and isinstance(pipeline, dict)
    r_legacy = build_reduced(legacy)  # type: ignore[arg-type]
    r_pipeline = build_reduced(pipeline)  # type: ignore[arg-type]
    # Introduce tiny jitter within tolerance to a numeric aggregate
    if 'options_total' in r_pipeline:
        r_pipeline['options_total'] = r_pipeline['options_total'] * (1.0 + 5e-7)  # within default rtol 1e-6
    assert diff_reduced(r_legacy, r_pipeline) == []


def test_parity_detects_missing_index():
    legacy = _run('legacy')
    pipeline = _run('pipeline')
    assert isinstance(legacy, dict) and isinstance(pipeline, dict)
    r_legacy = build_reduced(legacy)  # type: ignore[arg-type]
    r_pipeline = build_reduced(pipeline)  # type: ignore[arg-type]
    # Remove one index entry from pipeline reduced
    if 'indices' in r_pipeline and len(r_pipeline['indices']) > 1:
        r_pipeline['indices'].pop()  # remove last
        r_pipeline['indices_count'] = len(r_pipeline['indices'])
    diffs = diff_reduced(r_legacy, r_pipeline)
    assert any(d['category'] in ('set_size_mismatch', 'field_value_drift') for d in diffs), diffs
