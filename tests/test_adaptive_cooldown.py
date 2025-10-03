import os
import pytest
from src.metrics import setup_metrics_server  # facade import
from src.adaptive.logic import evaluate_and_apply


def test_adaptive_cooldown_flap_prevention(monkeypatch):
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER','1')
    monkeypatch.setenv('G6_ADAPTIVE_MAX_SLA_BREACH_STREAK','1')
    monkeypatch.setenv('G6_ADAPTIVE_MIN_HEALTH_CYCLES','1')
    monkeypatch.setenv('G6_ADAPTIVE_DEMOTE_COOLDOWN','2')
    monkeypatch.setenv('G6_ADAPTIVE_PROMOTE_COOLDOWN','3')
    metrics,_ = setup_metrics_server(reset=True)
    # Seed starting mode full
    setattr(metrics, '_adaptive_current_mode', 0)

    # Simulate consecutive SLA breaches to trigger demote only once due to cooldown
    for i in range(3):
        # Increment SLA breach counter manually to simulate breach
        if not hasattr(metrics, 'cycle_sla_breach'):
            pytest.skip('SLA breach metric gated off')
        # Use counter's inc
        try:
            metrics.cycle_sla_breach.inc()
        except Exception:
            pass
        evaluate_and_apply(['NIFTY'])
    mode_after_breaches = getattr(metrics, '_adaptive_current_mode', None)
    assert mode_after_breaches == 1, 'Should demote only once despite repeated breaches within cooldown'

    # Now simulate healthy cycles to attempt promote but respect promote cooldown
    # Need enough healthy cycles (min_health=1) but also respect promote_cooldown=3
    for _ in range(2):
        evaluate_and_apply(['NIFTY'])
    # Still within promote cooldown window -> no promote yet
    assert getattr(metrics, '_adaptive_current_mode', None) == 1
    # Additional cycles to exceed promote cooldown
    for _ in range(2):
        evaluate_and_apply(['NIFTY'])
    assert getattr(metrics, '_adaptive_current_mode', None) == 0, 'Should promote after cooldown and healthy cycles'
