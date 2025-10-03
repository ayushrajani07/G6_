import os
from src.collectors.parity_harness import capture_parity_snapshot

def test_parity_harness_v3_includes_groups(monkeypatch):
    monkeypatch.setenv('G6_PARITY_INCLUDE_REASON_GROUPS','1')
    snap_summary = {
        'partial_reason_totals': {'low_strike':2,'prefilter_clamp':1,'unknown':3},
        'partial_reason_groups': {
            'coverage_low': {'total':2,'reasons':{'low_strike':2}},
            'prefilter': {'total':1,'reasons':{'prefilter_clamp':1}},
            'other': {'total':3,'reasons':{'unknown':3}},
        },
        'partial_reason_group_order': ['coverage_low','prefilter','other']
    }
    unified = {'indices': [], 'snapshot_summary': snap_summary}
    res = capture_parity_snapshot(unified)
    assert res['version'] in (3,4)  # v4: deprecated harness (hash removed)
    assert res['partial_reason_group_totals'] == {'coverage_low':2,'other':3,'prefilter':1}
    assert res['partial_reason_group_order'] == ['coverage_low','prefilter','other']

def test_parity_harness_v3_groups_disabled(monkeypatch):
    monkeypatch.setenv('G6_PARITY_INCLUDE_REASON_GROUPS','0')
    snap_summary = {
        'partial_reason_totals': {'low_field':1},
        'partial_reason_groups': {
            'coverage_low': {'total':1,'reasons':{'low_field':1}},
        },
        'partial_reason_group_order': ['coverage_low']
    }
    res = capture_parity_snapshot({'indices': [], 'snapshot_summary': snap_summary})
    assert 'partial_reason_group_totals' not in res
