import json, os, subprocess, sys, tempfile, time, pathlib

PYTHON = sys.executable
ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_unified(extra_args):
    cmd = [PYTHON, '-m', 'src.unified_main'] + extra_args
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_mock_provider_cycle_creates_status_file():
    with tempfile.TemporaryDirectory() as tmp:
        status_path = pathlib.Path(tmp) / 'status.json'
        # Run one cycle with mock data and status file
        res = run_unified(['--mock-data', '--run-once', '--runtime-status-file', str(status_path), '--interval', '1'])
        assert res.returncode == 0, res.stderr
        assert status_path.exists(), 'Status file not created'
        data = json.loads(status_path.read_text())
        assert 'cycle' in data and data['cycle'] >= 1
        assert 'indices_info' in data
        # Validate mock LTP present for at least one index
        any_ltp = any(isinstance(v.get('ltp'), (int, float)) for v in data['indices_info'].values())
        assert any_ltp, 'No numeric LTP in indices_info'


def test_mock_provider_flag_skips_auth():
    # A crude heuristic: run with mock and ensure no auth failure text in stderr
    with tempfile.TemporaryDirectory() as tmp:
        status_path = pathlib.Path(tmp) / 'status.json'
        res = run_unified(['--mock-data', '--run-once', '--runtime-status-file', str(status_path), '--interval', '1'])
        stderr_lower = res.stderr.lower()
        assert 'unable to obtain a valid kite token' not in stderr_lower
        assert res.returncode == 0
