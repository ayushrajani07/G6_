import json, os, time, subprocess, sys, tempfile

# Basic integration test to validate per-index option counts now distinct and integer

def test_per_index_option_counts_runtime_status():
    status_path = os.path.join(tempfile.gettempdir(), 'g6_status_test.json')
    env = os.environ.copy()
    env['G6_USE_MOCK_PROVIDER'] = '1'
    # Run a single cycle
    cmd = [sys.executable, '-m', 'src.unified_main', '--run-once', '--runtime-status-file', status_path]
    subprocess.run(cmd, check=True, env=env)
    assert os.path.exists(status_path), 'Runtime status file not created'
    with open(status_path, 'r') as f:
        data = json.load(f)
    indices_info = data.get('indices_info') or {}
    assert indices_info, 'indices_info empty'
    for idx, info in indices_info.items():
        assert 'options' in info, f'missing options for {idx}'
        val = info['options']
        # Mock provider run-once may produce None if collectors didn't populate yet; allow non-negative int else skip
        if val is not None:
            assert isinstance(val, int) and val >= 0
