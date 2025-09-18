import json, pathlib, sys, subprocess, tempfile

PYTHON = sys.executable
ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_one_cycle(status_path: pathlib.Path):
    cmd = [PYTHON, '-m', 'src.unified_main', '--mock-data', '--run-once', '--interval', '1', '--runtime-status-file', str(status_path)]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_runtime_status_contains_expected_keys():
    with tempfile.TemporaryDirectory() as tmp:
        status_path = pathlib.Path(tmp) / 'status.json'
        res = run_one_cycle(status_path)
        assert res.returncode == 0, res.stderr
        data = json.loads(status_path.read_text())
        required = {"timestamp","cycle","elapsed","interval","sleep_sec","indices","indices_info"}
        missing = required - set(data.keys())
        assert not missing, f"Missing keys: {missing}"
        # indices_info should map index -> dict with ltp key (may be None if retrieval failed)
        assert isinstance(data['indices_info'], dict)
        assert all(isinstance(v, dict) and 'ltp' in v for v in data['indices_info'].values())
