"""Tests for anomaly / churn metrics in summary_metrics.

Simulates several cycles with varying changed panel counts to ensure churn
ratio, anomaly counter, and streak gauge behave as expected.
"""
from __future__ import annotations

from scripts.summary import summary_metrics as sm


def test_churn_metrics_progression(monkeypatch):
    sm.reset_for_tests()
    # Force threshold low for deterministic anomaly triggering
    monkeypatch.setenv("G6_SUMMARY_CHURN_WARN_RATIO", "0.25")
    # Cycle 1: 1/10 changed => ratio 0.1 (below threshold)
    r1 = sm.record_churn(1, 10)
    snap1 = sm.snapshot()
    assert abs(r1 - 0.1) < 1e-6
    assert snap1['gauge'].get('g6_summary_panel_churn_ratio', -1) == r1
    assert snap1['counter'].get(('g6_summary_panel_churn_anomalies_total',()), 0) == 0
    assert snap1['gauge'].get('g6_summary_panel_high_churn_streak', -1) == 0
    # Cycle 2: 4/10 changed => ratio 0.4 (>= threshold) anomaly + streak=1
    r2 = sm.record_churn(4, 10)
    snap2 = sm.snapshot()
    assert abs(r2 - 0.4) < 1e-6
    assert snap2['counter'][( 'g6_summary_panel_churn_anomalies_total', () )] == 1
    assert snap2['gauge']['g6_summary_panel_high_churn_streak'] == 1
    # Cycle 3: 5/10 => ratio 0.5 anomaly + streak=2
    r3 = sm.record_churn(5, 10)
    snap3 = sm.snapshot()
    assert snap3['counter'][( 'g6_summary_panel_churn_anomalies_total', () )] == 2
    assert snap3['gauge']['g6_summary_panel_high_churn_streak'] == 2
    # Cycle 4: 0/10 => ratio 0.0 (streak reset)
    r4 = sm.record_churn(0, 10)
    snap4 = sm.snapshot()
    assert snap4['gauge']['g6_summary_panel_high_churn_streak'] == 0
    # sanity: ratios monotonic per cycle call outputs
    assert [r1, r2, r3, r4] == [0.1, 0.4, 0.5, 0.0]
