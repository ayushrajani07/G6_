import json


def test_runtime_status_contains_expected_keys(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    required = {"timestamp","cycle","elapsed","interval","sleep_sec","indices","indices_info"}
    missing = required - set(data.keys())
    assert not missing, f"Missing keys: {missing}"
    assert isinstance(data['indices_info'], dict)
    assert all(isinstance(v, dict) and 'ltp' in v for v in data['indices_info'].values())
