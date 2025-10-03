import json

def test_mock_dashboard_short(run_mock_cycle, monkeypatch):
    monkeypatch.setenv('G6_USE_MOCK_PROVIDER','1')
    monkeypatch.setenv('G6_FORCE_UNICODE','1')
    monkeypatch.setenv('G6_LIVE_PANEL','1')
    monkeypatch.setenv('G6_FANCY_CONSOLE','1')
    data = run_mock_cycle(cycles=1, interval=3)
    assert 'cycle' in data and 'timestamp' in data and data['timestamp'].endswith('Z')
