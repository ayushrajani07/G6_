import os, sys, json, tempfile, pathlib
from importlib import reload

def test_mock_single_cycle(monkeypatch):
    # Ensure repo root on path
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    status_dir = root / 'data' / 'runtime_status'
    status_dir.mkdir(parents=True, exist_ok=True)
    status_file = status_dir / 'pytest_mock_status.json'
    if status_file.exists():
        status_file.unlink()
    # Force mock provider
    monkeypatch.setenv('G6_USE_MOCK_PROVIDER', '1')
    # Build argv for unified_main
    argv = [
        'unified_main',
        '--config', 'config/g6_config.json',
        '--run-once',
        '--mock-data',
        '--interval', '2',
        '--runtime-status-file', str(status_file),
        '--metrics-reset',
        '--metrics-custom-registry',
        '--log-level', 'WARNING',
    ]
    monkeypatch.setenv('PYTHONPATH', '.')
    old_argv = sys.argv
    try:
        sys.argv = argv
        from src import unified_main
        # Reload in case environment flags influence import-time behavior
        reload(unified_main)
        rc = unified_main.main()
    finally:
        sys.argv = old_argv
    assert rc in (0, None)
    assert status_file.exists(), "Status file not created in mock run"
    data = json.loads(status_file.read_text())
    assert isinstance(data, dict)
    assert data.get('cycle') == 1 or data.get('cycle') == 0
    ts = data.get('timestamp')
    assert isinstance(ts, str) and ts.endswith('Z'), f"Timestamp not UTC Z format: {ts}"