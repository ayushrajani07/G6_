import os
import importlib
import time

from src.metrics import get_metrics  # facade import


def _reset_followups(monkeypatch, reload_severity: bool = False):
    # Ensure fresh module state by reloading after env set. Optionally reload severity to apply new rules.
    if reload_severity:
        import src.adaptive.severity as severity  # type: ignore
        # Clear cached rules/state to ensure env-driven rules apply deterministically
        if hasattr(severity, '_RULES_CACHE'):
            try:
                severity._RULES_CACHE = None  # type: ignore
            except Exception:  # pragma: no cover
                pass
        if hasattr(severity, '_DECAY_STATE'):
            try:
                severity._DECAY_STATE.clear()  # type: ignore
            except Exception:
                pass
        importlib.reload(severity)
    import src.adaptive.followups as f  # noqa
    importlib.reload(f)
    return f


def test_followups_suppression(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')  # low so single feed triggers quickly
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','120')
    f = _reset_followups(monkeypatch, reload_severity=True)
    # First trigger
    f.feed('NIFTY', interpolated_fraction=0.5)
    alerts1 = f.get_and_clear_alerts()
    assert len(alerts1) == 1
    # Immediate second trigger should be suppressed (same type/severity/index)
    f.feed('NIFTY', interpolated_fraction=0.6)
    alerts2 = f.get_and_clear_alerts()
    assert alerts2 == []


def test_followups_weight_accumulation_and_pressure(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','0')  # disable suppression for weight test
    # Weight window small for deterministic purge
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHT_WINDOW','2')
    # Provide weights: interpolation_high critical gets weight 2, warn 1
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHTS','{"interpolation_high":{"critical":2,"warn":1}}')
    # Enable severity so enrichment assigns severity based on fraction (configure simple rule)
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.2,"critical":0.4}}')
    f = _reset_followups(monkeypatch, reload_severity=True)
    # Trigger critical (weight 2)
    f.feed('NIFTY', interpolated_fraction=0.5)
    w1 = f.get_weight_pressure()
    assert w1 >= 2
    # Sleep to allow old weight to age out then trigger another
    time.sleep(2.1)
    f.feed('NIFTY', interpolated_fraction=0.45)
    w2 = f.get_weight_pressure()
    # Old weight event should have been purged, new weight present
    assert 1 <= w2 <= 3


def test_followups_weight_controller_demote(monkeypatch):
    # Configure controller + weights to ensure demotion path 'followups_weight'
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER','1')
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','0')
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHT_WINDOW','60')
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHTS','{"interpolation_high":{"critical":5}}')
    monkeypatch.setenv('G6_FOLLOWUPS_DEMOTE_THRESHOLD','5')
    # Severity rules to classify as critical
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.2,"critical":0.3}}')
    import src.adaptive.followups as f
    import src.adaptive.logic as logic
    # Reload severity first so followups enrichment sees updated rules
    import src.adaptive.severity as severity
    if hasattr(severity, '_RULES_CACHE'):
        severity._RULES_CACHE = None  # type: ignore
    importlib.reload(severity)
    importlib.reload(f)
    importlib.reload(logic)
    # Trigger one high interpolation alert (critical weight 5 >= threshold)
    f.feed('NIFTY', interpolated_fraction=0.5)
    # Evaluate controller (single index)
    logic.evaluate_and_apply(['NIFTY'])
    m = get_metrics()
    # Verify mode demoted at least one level
    assert getattr(m,'_adaptive_current_mode',0) in (1,2)
    # Weight pressure persists until window expires
    assert f.get_weight_pressure() >= 5


def test_panels_followups_recent_integration(monkeypatch):
    # Build a panel with followups recent entries present
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','0')
    monkeypatch.setenv('G6_FOLLOWUPS_PANEL_LIMIT','5')
    import src.adaptive.followups as f
    importlib.reload(f)
    # Generate several alerts
    for frac in (0.2,0.3,0.4,0.5,0.6,0.7):
        f.feed('NIFTY', interpolated_fraction=frac)
    # Provide status object with adaptive_alerts list (drained alerts list used elsewhere)
    status = {"adaptive_alerts": f.get_recent_alerts(20)}
    from src.panels.factory import build_panels
    class _Stub:
        def get_provider_data(self): return {}
        def get_resources_data(self): return {}
        def get_cycle_data(self): return {}
        def get_indices_data(self): return {}
        def get_health_data(self): return {}
    panels = build_panels(_Stub(), status)  # type: ignore[arg-type]
    aa = panels.get('adaptive_alerts')
    assert aa and isinstance(aa, dict)
    fr = aa.get('followups_recent')
    assert fr and isinstance(fr, list)
    # Limited to panel limit (5)
    assert len(fr) <= 5
    # Entries have expected keys subset
    sample = fr[-1]
    assert 'type' in sample and 'severity' in sample and 'ts' in sample


def test_followups_event_dispatch(monkeypatch, tmp_path):
    # Configure events to write to temp file
    events_path = tmp_path / 'events.log'
    monkeypatch.setenv('G6_EVENTS_LOG_PATH', str(events_path))
    monkeypatch.setenv('G6_FOLLOWUPS_EVENTS','1')
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    import src.events.event_log as event_log
    importlib.reload(event_log)
    import src.adaptive.followups as f
    importlib.reload(f)
    f.feed('BANKNIFTY', interpolated_fraction=0.9)
    # Drain to ensure alert emitted
    _ = f.get_and_clear_alerts()
    # Flush wait
    time.sleep(0.05)
    content = events_path.read_text(encoding='utf-8')
    assert 'followup_alert' in content
    assert 'BANKNIFTY' in content
    # Context should include interpolated_fraction
    assert 'interpolated_fraction' in content


def test_followups_escalation_bypass(monkeypatch):
    """Warn suppressed then critical should bypass suppression within window; later equal severity suppressed."""
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','300')
    # Custom severity rules: warn at 0.2, critical at 0.4
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.2,"critical":0.4}}')
    import src.adaptive.followups as f
    importlib.reload(f)
    # Trigger warn
    f.feed('NIFTY', interpolated_fraction=0.25)
    a1 = f.get_and_clear_alerts()
    assert len(a1) == 1 and a1[0].get('severity') == 'warn'
    # Trigger another warn (suppressed)
    f.feed('NIFTY', interpolated_fraction=0.23)
    a2 = f.get_and_clear_alerts()
    assert a2 == []
    # Trigger escalation (critical) should bypass suppression
    f.feed('NIFTY', interpolated_fraction=0.5)
    a3 = f.get_and_clear_alerts()
    assert len(a3) == 1 and a3[0].get('severity') == 'critical'
    # Another critical immediately suppressed (same severity)
    f.feed('NIFTY', interpolated_fraction=0.55)
    a4 = f.get_and_clear_alerts()
    assert a4 == []


def test_followups_weight_pressure_gauge(monkeypatch):
    monkeypatch.setenv('G6_FOLLOWUPS_ENABLED','1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_THRESHOLD','0.1')
    monkeypatch.setenv('G6_FOLLOWUPS_INTERP_CONSEC','1')
    monkeypatch.setenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','0')
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHTS','{"interpolation_high":{"critical":3}}')
    monkeypatch.setenv('G6_FOLLOWUPS_WEIGHT_WINDOW','60')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.2,"critical":0.3}}')
    import src.adaptive.followups as f
    importlib.reload(f)
    f.feed('BANKNIFTY', interpolated_fraction=0.5)  # critical weight 3
    w = f.get_weight_pressure()
    assert w >= 3
    # Inspect prometheus registry for gauge value
    from prometheus_client import REGISTRY
    found = False
    for fam in REGISTRY.collect():
        if fam.name == 'g6_followups_weight_pressure':
            for s in fam.samples:
                # Counter families also produce _created; ensure we capture gauge sample
                if s.name == 'g6_followups_weight_pressure':
                    assert s.value >= 3
                    found = True
    assert found, 'weight pressure gauge not found'
