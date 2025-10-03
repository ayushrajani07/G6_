import json

def test_per_index_option_counts_runtime_status(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    indices_info = data.get('indices_info') or {}
    assert indices_info, 'indices_info empty'
    for idx, info in indices_info.items():
        assert 'options' in info, f'missing options for {idx}'
        val = info['options']
        if val is not None:
            assert isinstance(val, int) and val >= 0
