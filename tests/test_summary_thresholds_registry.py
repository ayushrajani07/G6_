import os, json
from scripts.summary.thresholds import T, dump_effective, reset_for_tests

def test_defaults_present():
    reset_for_tests()
    assert T.get('dq.warn') == 85.0
    assert T.get('dq.error') == 70.0
    eff = dump_effective()
    assert eff['dq.warn'] == 85.0
    assert eff['dq.error'] == 70.0


def test_override_via_env(monkeypatch):
    reset_for_tests()
    overrides = {"dq.warn": 82, "dq.error": 68, "mem.tier2.mb": "900"}
    monkeypatch.setenv('G6_SUMMARY_THRESH_OVERRIDES', json.dumps(overrides))
    # Force reload by accessing
    assert T.dq_warn == 82
    assert T.dq_error == 68
    assert T.get('mem.tier2.mb') == 900.0


def test_unknown_key_grace():
    reset_for_tests()
    # Unknown returns default fallback
    assert T.get('nonexistent.key', 123) == 123


def test_attribute_mapping():
    reset_for_tests()
    assert T.dq_warn == 85.0
    assert T.stream_stale_warn_sec == 60.0
