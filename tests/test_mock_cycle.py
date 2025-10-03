import json

def test_mock_single_cycle(run_mock_cycle, monkeypatch):
    monkeypatch.setenv('G6_USE_MOCK_PROVIDER','1')
    data = run_mock_cycle(cycles=1, interval=2)
    assert isinstance(data, dict)
    assert data.get('cycle') in (0,1)
    ts = data.get('timestamp')
    assert isinstance(ts, str) and ts.endswith('Z'), f"Timestamp not UTC Z format: {ts}"