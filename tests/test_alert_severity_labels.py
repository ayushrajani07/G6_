import os, json
from src.collectors.modules.alerts_core import aggregate_alerts, derive_severity_map

def _make_indices():
    return [
        {
            'index': 'ALPHA',
            'failures': 1,
            'status': 'EMPTY',
            'expiries': [
                {'status': 'EMPTY', 'strike_coverage': 0.2, 'field_coverage': 0.1},
                {'status': 'OK', 'strike_coverage': 0.5, 'field_coverage': 0.4},
            ],
        }
    ]

def test_alert_severity_default_mapping(monkeypatch):
    monkeypatch.delenv('G6_ALERT_SEVERITY_MAP', raising=False)
    summ = aggregate_alerts(_make_indices())
    d = summ.to_dict()
    sev = d.get('alerts_severity') or {}
    # Core categories should have a severity
    for cat in ['index_failure','index_empty','expiry_empty','low_strike_coverage','low_field_coverage','low_both_coverage']:
        assert cat in sev
        assert sev[cat] in ('info','warning','critical')
    assert sev['index_failure'] == 'critical'
    assert sev['index_empty'] == 'critical'


def test_alert_severity_env_override(monkeypatch):
    override = {'index_failure':'warning','low_field_coverage':'critical'}
    monkeypatch.setenv('G6_ALERT_SEVERITY_MAP', json.dumps(override))
    summ = aggregate_alerts(_make_indices())
    sev = summ.to_dict().get('alerts_severity') or {}
    assert sev['index_failure'] == 'warning'
    assert sev['low_field_coverage'] == 'critical'


def test_alert_severity_helper_direct():
    cats = {'index_failure':0,'custom_future':0}
    sev = derive_severity_map(cats)
    assert sev['index_failure'] == 'critical'
    # Unknown future category defaults to warning
    assert sev['custom_future'] == 'warning'
