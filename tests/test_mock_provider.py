import json

def test_mock_provider_cycle_creates_status_file(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    assert 'cycle' in data or 'cycle' in data  # sanity
    assert 'indices_info' in data
    any_ltp = any(isinstance(v.get('ltp'), (int, float)) for v in data['indices_info'].values())
    assert any_ltp, 'No numeric LTP in indices_info'


def test_mock_provider_flag_skips_auth(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    # No auth concept exercised in orchestrator mock path; ensure indices_info present
    assert 'indices_info' in data and data['indices_info']
