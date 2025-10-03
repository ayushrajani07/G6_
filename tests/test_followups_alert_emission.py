import os
import importlib


def test_followups_alert_emission_with_severity(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.5')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','2')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.55,"critical":0.65}}')
    import src.adaptive.followups as f
    importlib.reload(f)
    f.feed('IDX', interpolated_fraction=0.60)  # streak 1
    f.feed('IDX', interpolated_fraction=0.70)  # triggers (>= critical)
    alerts = f.get_and_clear_alerts()
    assert alerts, 'No alerts emitted'
    types = {a['type'] for a in alerts}
    assert 'interpolation_high' in types
    # Severity should be present and critical given fraction 0.70 >= 0.65
    sev = {a.get('severity') for a in alerts if a['type']=='interpolation_high'}
    assert 'critical' in sev


def test_followups_risk_drift_alert(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_RISK_WINDOW','4')
    monkeypatch.setenv('G6_FOLLOWUPS_RISK_DRIFT_PCT','0.10')
    monkeypatch.setenv('G6_FOLLOWUPS_RISK_MIN_OPTIONS','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"risk_delta_drift":{"warn":0.05,"critical":0.09}}')
    import src.adaptive.followups as f
    importlib.reload(f)
    f.feed('IDX', notional_delta=100.0, option_count=10)
    f.feed('IDX', notional_delta=105.0, option_count=10)
    f.feed('IDX', notional_delta=108.0, option_count=10)
    f.feed('IDX', notional_delta=120.0, option_count=10)  # triggers drift
    alerts = f.get_and_clear_alerts()
    drift = [a for a in alerts if a['type']=='risk_delta_drift']
    assert drift, 'No risk drift alert emitted'
    assert any('severity' in a for a in drift)


def test_followups_bucket_util_alert(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_BUCKET_THRESHOLD','0.8')
    monkeypatch.setenv('G6_FOLLOWUPS_BUCKET_CONSEC','2')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"bucket_util_low":{"warn":0.75,"critical":0.65}}')
    import src.adaptive.followups as f
    importlib.reload(f)
    f.feed('IDX', interpolated_fraction=0.0, bucket_utilization=0.70)  # 1 below threshold
    f.feed('IDX', interpolated_fraction=0.0, bucket_utilization=0.60)  # triggers
    alerts = f.get_and_clear_alerts()
    buk = [a for a in alerts if a['type']=='bucket_util_low']
    assert buk, 'No bucket util alert emitted'
    # utilization 0.60 <= critical 0.65 should mark critical severity
    assert any(a.get('severity')=='critical' for a in buk)
