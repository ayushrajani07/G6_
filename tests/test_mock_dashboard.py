import os, sys, json, pathlib, time
from importlib import reload

def test_mock_dashboard_short(monkeypatch):
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    status_file = root / 'data' / 'runtime_status' / 'dashboard_status_test.json'
    if status_file.exists():
        status_file.unlink()
    monkeypatch.setenv('G6_USE_MOCK_PROVIDER','1')
    monkeypatch.setenv('G6_FORCE_UNICODE','1')
    monkeypatch.setenv('G6_LIVE_PANEL','1')
    monkeypatch.setenv('G6_FANCY_CONSOLE','1')
    # We'll invoke unified_main once (cycle limit simulated via run-once)
    argv = [
        'unified_main',
        '--config','config/g6_config.json',
        '--run-once',
        '--mock-data',
        '--interval','3',
        '--runtime-status-file', str(status_file),
        '--status-poll','1.0',
        '--log-level','WARNING',
        '--metrics-reset',
        '--metrics-custom-registry',
    ]
    old = sys.argv
    try:
        sys.argv = argv
        from src import unified_main
        reload(unified_main)
        rc = unified_main.main()
    finally:
        sys.argv = old
    assert rc in (0, None)
    assert status_file.exists(), 'dashboard status file missing'
    data = json.loads(status_file.read_text())
    assert 'cycle' in data and 'timestamp' in data and data['timestamp'].endswith('Z')
