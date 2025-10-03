import datetime as dt
from src.collectors.helpers.struct_events import _compute_reason_totals

def test_compute_reason_totals_counts():
    indices = [
        {
            'index': 'NIFTY',
            'expiries': [
                {'status': 'PARTIAL', 'partial_reason': 'low_strike'},
                {'status': 'PARTIAL', 'partial_reason': 'low_field'},
                {'status': 'PARTIAL', 'partial_reason': 'low_field'},
                {'status': 'PARTIAL', 'partial_reason': 'low_both'},
                {'status': 'OK'},
            ],
        },
        {
            'index': 'BANKNIFTY',
            'expiries': [
                {'status': 'PARTIAL', 'partial_reason': 'unknown'},
                {'status': 'EMPTY'},
                {'status': 'PARTIAL', 'partial_reason': 'not-a-known'},  # falls into unknown
            ],
        },
    ]
    totals = _compute_reason_totals(indices)
    assert totals == {
        'low_strike': 1,
        'low_field': 2,
        'low_both': 1,
        'unknown': 2,
    }

def test_compute_reason_totals_empty():
    assert _compute_reason_totals([]) == {'low_strike':0,'low_field':0,'low_both':0,'unknown':0}
