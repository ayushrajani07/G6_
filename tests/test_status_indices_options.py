import json, tempfile, subprocess, sys, pathlib

PYTHON = sys.executable
ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_status_indices_include_options_field():
    with tempfile.TemporaryDirectory() as tmp:
        status_path = pathlib.Path(tmp) / 'status.json'
        cmd = [PYTHON, '-m', 'src.unified_main', '--mock-data', '--run-once', '--interval', '1', '--runtime-status-file', str(status_path)]
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert res.returncode == 0, res.stderr
        data = json.loads(status_path.read_text())
        for idx, payload in data['indices_info'].items():
            assert 'options' in payload, f"Missing 'options' for index {idx}"
