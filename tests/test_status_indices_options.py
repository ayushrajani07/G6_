import json

def test_status_indices_include_options_field(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    for idx, payload in data['indices_info'].items():
        assert 'options' in payload, f"Missing 'options' for index {idx}"
