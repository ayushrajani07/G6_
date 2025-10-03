import logging
import re

from contextlib import contextmanager
from io import StringIO

from src.collectors.helpers.struct_events import (
    emit_option_match_stats,
    emit_cycle_status_summary,
    emit_zero_data,
    emit_instrument_prefilter_summary,
)

@contextmanager
def capture_logs(level=logging.INFO):
    logger = logging.getLogger('src.collectors.helpers.struct_events')
    old_level = logger.level
    logger.setLevel(level)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_emit_option_match_stats_basic():
    with capture_logs() as cap:
        emit_option_match_stats(
            index='NIFTY',
            expiry='2025-10-02',
            rule='this_week',
            strike_count=10,
            legs=20,
            ce_legs=10,
            pe_legs=10,
            strike_min=24000,
            strike_max=25000,
            step=50,
            sample=['24000','24500','25000'],
            ce_per_strike=1.0,
            pe_per_strike=1.0,
            synthetic=False,
            strike_coverage=0.8,
            field_coverage=0.6,
        )
    out = cap.getvalue()
    assert 'STRUCT option_match_stats' in out
    assert '"strike_cov":0.8' in out.replace(' ', '')
    assert '"field_cov":0.6' in out.replace(' ', '')


def test_emit_cycle_status_summary():
    indices = [
        {
            'index': 'NIFTY',
            'status': 'OK',
            'expiries': [
                {'rule': 'this_week', 'status': 'OK', 'strike_coverage': 0.9, 'field_coverage': 0.7, 'options': 20, 'synthetic_fallback': False},
                {'rule': 'next_week', 'status': 'PARTIAL', 'strike_coverage': 0.5, 'field_coverage': 0.4, 'options': 10, 'synthetic_fallback': False},
            ],
        }
    ]
    with capture_logs() as cap:
        emit_cycle_status_summary(cycle_ts=1234567890, duration_s=3.21, indices=indices, index_count=1)
    out = cap.getvalue()
    assert 'STRUCT cycle_status_summary' in out
    # Ensure expiry status totals present
    assert '"expiry_status_totals"' in out
    assert re.search(r'"partial":1', out)


def test_emit_zero_data():
    with capture_logs() as cap:
        emit_zero_data(index='NIFTY', expiry='2025-10-02', rule='this_week', atm=24800, strike_count=21)
    out = cap.getvalue()
    assert 'STRUCT zero_data' in out
    assert '"event":"zero_data_expiry"' in out


def test_emit_instrument_prefilter_summary():
    with capture_logs() as cap:
        emit_instrument_prefilter_summary(
            index='NIFTY',
            expiry='2025-10-02',
            rule='this_week',
            total_raw=500,
            prefiltered=120,
            option_candidates=500,
            ce=60,
            pe=60,
            rejects={'prefilter_rejected': 380},
            latency_ms=12.34,
            contamination=False,
            contamination_samples=None,
        )
    out = cap.getvalue()
    assert 'STRUCT instrument_prefilter_summary' in out
    assert '"total_raw":500' in out.replace(' ','')
    assert '"prefiltered":120' in out.replace(' ','')
