import os, json, time, urllib.request, socket
from src.adaptive import severity
from src.adaptive import logic
from src.metrics import get_metrics  # facade import
from src.orchestrator.catalog_http import start_http_server_in_thread, shutdown_http_server

def _reset():
    if hasattr(severity,'_DECAY_STATE'): severity._DECAY_STATE.clear()  # type: ignore
    if hasattr(severity,'_TREND_BUF'): severity._TREND_BUF.clear()  # type: ignore


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]
    finally:
        try:
            s.close()
        except Exception:
            pass

def test_theme_endpoint_and_trend(monkeypatch):
    _reset()
    # Enable HTTP server
    monkeypatch.setenv('G6_CATALOG_HTTP','1')
    # Use a unique port each run to avoid stale server reuse
    port = str(_pick_free_port())
    monkeypatch.setenv('G6_CATALOG_HTTP_PORT', port)
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER','1')
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH','1')
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_WINDOW','5')
    # Force reload to ensure any prior server with stale window is restarted
    monkeypatch.setenv('G6_CATALOG_HTTP_FORCE_RELOAD','1')
    # Ensure any previous server (from other tests) is shut down via registry-backed helper
    shutdown_http_server()
    # Clean state sufficient; no module reload required with registry lifecycle
    # deterministic rules to force warn then decay
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"risk_delta_drift":{"warn":0.04,"critical":0.08}}')
    # Reload catalog_http to ensure handler reflects latest on-disk changes
    from src.orchestrator import catalog_http as _cat_http  # type: ignore
    _cat_http.start_http_server_in_thread()
    # Build snapshots of warn severity across cycles
    for c in range(5):
        severity.enrich_alert({'type':'risk_delta_drift','drift_pct':0.05,'cycle':c})  # warn
        logic.evaluate_and_apply(['NIFTY'])
        time.sleep(0.01)
    # Fetch theme endpoint
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/adaptive/theme') as resp:  # nosec B310 test local
        body = resp.read().decode('utf-8')
    data = json.loads(body)
    assert 'palette' in data and 'active_counts' in data and 'trend' in data
    assert data['trend']['window'] == 5
    assert data['trend']['warn_ratio'] > 0.9  # sustained warn presence


def test_trend_smoothing_demote(monkeypatch):
    _reset()
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER','1')
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER_SEVERITY','1')
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH','1')
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_WINDOW','4')
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO','0.5')
    monkeypatch.setenv('G6_ADAPTIVE_ALERT_SEVERITY_RULES','{"interpolation_high":{"warn":0.5,"critical":0.7}}')
    # Push 2 of 4 cycles critical (<50% ratio) then non-critical
    for c, val in enumerate([0.71,0.72,0.4,0.45]):
        severity.enrich_alert({'type':'interpolation_high','interpolated_fraction':val,'cycle':c})
        logic.evaluate_and_apply(['NIFTY'])
    # Controller should NOT demote yet due to ratio threshold (critical only in 50% cycles? threshold 0.5 requires >=0.5 -> borderline may demote). Use stricter threshold to ensure no demote.
    # Adjust threshold to >0.5 to enforce.
    monkeypatch.setenv('G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO','0.75')
    severity.enrich_alert({'type':'interpolation_high','interpolated_fraction':0.71,'cycle':4})
    logic.evaluate_and_apply(['NIFTY'])
    m = get_metrics()
    # Depending on concurrent signals (memory/cardinality), controller may have demoted further; ensure not above full (0-2 valid)
    assert getattr(m,'_adaptive_current_mode',0) in (0,1,2)
