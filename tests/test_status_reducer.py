import pytest
from src.collectors.helpers.status_reducer import compute_expiry_status, aggregate_cycle_status

def test_compute_expiry_status_empty():
    assert compute_expiry_status({'options':0}) == 'EMPTY'

def test_compute_expiry_status_ok():
    rec = {'options':10,'strike_coverage':0.9,'field_coverage':0.8}
    assert compute_expiry_status(rec) == 'OK'

def test_compute_expiry_status_partial_on_strike():
    rec = {'options':10,'strike_coverage':0.5,'field_coverage':0.9}
    assert compute_expiry_status(rec) == 'PARTIAL'

def test_compute_expiry_status_partial_on_field():
    rec = {'options':10,'strike_coverage':0.9,'field_coverage':0.4}
    assert compute_expiry_status(rec) == 'PARTIAL'

def test_aggregate_cycle_status_all_empty():
    assert aggregate_cycle_status([{'status':'EMPTY'},{'status':'EMPTY'}]) == 'EMPTY'

def test_aggregate_cycle_status_all_ok():
    assert aggregate_cycle_status([{'status':'OK'},{'status':'OK'}]) == 'OK'

def test_aggregate_cycle_status_partial():
    assert aggregate_cycle_status([{'status':'OK'},{'status':'PARTIAL'}]) == 'PARTIAL'

def test_env_override_thresholds_strike(monkeypatch):
    # Lower strike threshold so a previously PARTIAL on strike becomes OK
    rec = {'options':10,'strike_coverage':0.5,'field_coverage':0.9}
    assert compute_expiry_status(rec) == 'PARTIAL'
    monkeypatch.setenv('G6_STRIKE_COVERAGE_OK', '0.4')
    assert compute_expiry_status(rec) == 'OK'

def test_env_override_thresholds_field(monkeypatch):
    rec = {'options':10,'strike_coverage':0.9,'field_coverage':0.4}
    assert compute_expiry_status(rec) == 'PARTIAL'
    monkeypatch.setenv('G6_FIELD_COVERAGE_OK', '0.3')
    assert compute_expiry_status(rec) == 'OK'

def test_env_override_invalid_values_ignored(monkeypatch):
    rec = {'options':10,'strike_coverage':0.74,'field_coverage':0.54}
    # Just below defaults, should be PARTIAL
    assert compute_expiry_status(rec) == 'PARTIAL'
    # Set invalid values (out of range and non-float) -> should remain PARTIAL
    monkeypatch.setenv('G6_STRIKE_COVERAGE_OK', '1.5')
    monkeypatch.setenv('G6_FIELD_COVERAGE_OK', 'abc')
    assert compute_expiry_status(rec) == 'PARTIAL'
