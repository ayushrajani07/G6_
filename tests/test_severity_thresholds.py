import os
import pytest
from src.adaptive import severity


def _reset_state():
    # Clear internal caches between tests for deterministic behavior
    severity._RULES_CACHE = None  # type: ignore
    severity._STREAKS.clear()  # type: ignore

@pytest.fixture(autouse=True)
def _reset_between_tests():
    severity._RULES_CACHE = None  # type: ignore
    severity._STREAKS.clear()  # type: ignore
    yield


def test_classify_boundaries_default_rules(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "1")
    monkeypatch.delenv("G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK", raising=False)
    _reset_state()
    # interpolation_high
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.10}) == "info"
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.50}) == "warn"
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.69}) == "warn"
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.70}) == "critical"
    # risk_delta_drift (abs)
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": 0.01}) == "info"
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": 0.05}) == "warn"
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": -0.09}) == "warn"
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": -0.10}) == "critical"
    # bucket_util_low (inverted)
    assert severity.classify({"type": "bucket_util_low", "utilization": 0.90}) == "info"
    assert severity.classify({"type": "bucket_util_low", "utilization": 0.74}) == "warn"
    assert severity.classify({"type": "bucket_util_low", "utilization": 0.60}) == "critical"
    assert severity.classify({"type": "bucket_util_low", "utilization": 0.50}) == "critical"


def test_min_streak_gating(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "1")
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK", "3")
    _reset_state()
    # Provide consecutive warn-level interpolation_high values; first two suppressed to info
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.55}) == "info"
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.56}) == "info"
    # Third occurrence crosses streak threshold -> warn
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.57}) == "warn"
    # Critical threshold should still respect streak once satisfied
    assert severity.classify({"type": "interpolation_high", "interpolated_fraction": 0.80}) == "critical"


def test_override_rules_env(monkeypatch):
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY", "1")
    # Tighten risk_delta_drift warn to 0.02 critical 0.03
    monkeypatch.setenv("G6_ADAPTIVE_ALERT_SEVERITY_RULES", '{"risk_delta_drift": {"warn": 0.02, "critical": 0.03}}')
    _reset_state()
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": 0.01}) == "info"
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": 0.02}) == "warn"
    assert severity.classify({"type": "risk_delta_drift", "drift_pct": 0.031}) == "critical"
