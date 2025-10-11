import os
from src.collectors.pipeline.anomaly import maybe_emit_alert_parity_anomaly

BASE_PARITY = {
    'version': 2,
    'score': 0.95,
    'components': {'index_count': 1.0, 'alerts': 0.9},
    'details': {
        'alerts': {
            'categories': {
                'critical': {'legacy': 2, 'pipeline': 4, 'weight': 1.0, 'diff_norm': 1.0},
                'warning': {'legacy': 5, 'pipeline': 6, 'weight': 1.0, 'diff_norm': 0.2},
                'info': {'legacy': 1, 'pipeline': 1, 'weight': 1.0, 'diff_norm': 0.0},
            },
            'weighted_diff_norm': 0.35,
        }
    }
}


def test_anomaly_emitted_when_threshold_met(monkeypatch):
    monkeypatch.setenv('G6_PARITY_ALERT_ANOMALY_THRESHOLD', '0.3')
    monkeypatch.setenv('G6_PARITY_ALERT_ANOMALY_MIN_TOTAL', '3')
    emitted = maybe_emit_alert_parity_anomaly(BASE_PARITY)
    assert emitted is True


def test_anomaly_not_emitted_when_below_threshold(monkeypatch):
    monkeypatch.setenv('G6_PARITY_ALERT_ANOMALY_THRESHOLD', '0.5')
    monkeypatch.setenv('G6_PARITY_ALERT_ANOMALY_MIN_TOTAL', '3')
    emitted = maybe_emit_alert_parity_anomaly(BASE_PARITY)
    assert emitted is False


def test_anomaly_disabled(monkeypatch):
    monkeypatch.setenv('G6_PARITY_ALERT_ANOMALY_THRESHOLD', '-1')
    emitted = maybe_emit_alert_parity_anomaly(BASE_PARITY)
    assert emitted is False
