from src.collectors.helpers.status_reducer import compute_expiry_status, derive_partial_reason, get_status_thresholds


def test_partial_reason_low_strike_only(monkeypatch):
    strike_thr, field_thr = get_status_thresholds()
    rec = {
        'options': 10,
        'strike_coverage': strike_thr * 0.8,  # below
        'field_coverage': field_thr + 0.05,   # above
        'synthetic_fallback': False,
    }
    status = compute_expiry_status(rec)
    assert status == 'PARTIAL'
    assert derive_partial_reason(rec) == 'low_strike'


def test_partial_reason_low_field_only():
    strike_thr, field_thr = get_status_thresholds()
    rec = {
        'options': 10,
        'strike_coverage': strike_thr + 0.05,  # above
        'field_coverage': field_thr * 0.7,     # below
        'synthetic_fallback': False,
    }
    assert compute_expiry_status(rec) == 'PARTIAL'
    assert derive_partial_reason(rec) == 'low_field'


def test_partial_reason_low_both():
    strike_thr, field_thr = get_status_thresholds()
    rec = {
        'options': 5,
        'strike_coverage': strike_thr * 0.5,
        'field_coverage': field_thr * 0.5,
        'synthetic_fallback': False,
    }
    assert compute_expiry_status(rec) == 'PARTIAL'
    assert derive_partial_reason(rec) == 'low_both'


def test_partial_reason_none_when_ok():
    strike_thr, field_thr = get_status_thresholds()
    rec = {
        'options': 5,
        'strike_coverage': strike_thr + 0.01,
        'field_coverage': field_thr + 0.01,
        'synthetic_fallback': False,
    }
    assert compute_expiry_status(rec) == 'OK'
    assert derive_partial_reason(rec) is None


def test_partial_reason_unknown_missing_metrics():
    rec = {
        'options': 3,
        'synthetic_fallback': False,
        # missing coverage metrics triggers PARTIAL via fallback? compute_expiry_status returns existing status if provided
        'status': 'PARTIAL'
    }
    assert derive_partial_reason(rec) == 'unknown'
