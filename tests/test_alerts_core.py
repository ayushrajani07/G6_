from src.collectors.modules.alerts_core import aggregate_alerts

def test_alerts_core_mixed():
    indices = [
        {
            'index': 'NIFTY',
            'failures': 1,
            'status': 'OK',
            'expiries': [
                {'status': 'OK', 'strike_coverage': 0.55, 'field_coverage': 0.40},
                {'status': 'EMPTY', 'strike_coverage': None, 'field_coverage': None, 'synthetic_quotes': True},
            ],
        },
        {
            'index': 'BANKNIFTY',
            'failures': 0,
            'status': 'EMPTY',
            'expiries': [
                {'status': 'EMPTY', 'strike_coverage': 0.9, 'field_coverage': 0.9},
            ],
        },
    ]
    summary = aggregate_alerts(indices, strike_cov_min=0.6, field_cov_min=0.5)
    d = summary.to_dict()
    alerts = d['alerts']
    # Expected counts (per-expiry granularity)
    assert alerts['index_failure'] == 1
    assert alerts['index_empty'] == 1
    assert alerts['expiry_empty'] == 2  # one from each index
    assert alerts['low_strike_coverage'] == 1
    assert alerts['low_field_coverage'] == 1
    assert alerts['low_both_coverage'] == 1
    # Synthetic usage counter removed – legacy key fixed at 0
    assert alerts['synthetic_quotes_used'] == 0
    assert d['alerts_total'] == sum(alerts.values())


def test_alerts_core_no_alerts():
    indices = [
        {
            'index': 'FINNIFTY',
            'failures': 0,
            'status': 'OK',
            'expiries': [
                {'status': 'OK', 'strike_coverage': 0.9, 'field_coverage': 0.95},
            ],
        }
    ]
    summary = aggregate_alerts(indices)
    d = summary.to_dict()
    assert d['alerts_total'] == 0
    for v in d['alerts'].values():
        assert v == 0
