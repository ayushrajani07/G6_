import json, os, sys, subprocess, pathlib, pytest

pytestmark = pytest.mark.optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'dead_code_scan.py'

@pytest.mark.skipif(not SCRIPT.exists(), reason="dead_code_scan script missing")
def test_dead_code_scan_clean(monkeypatch):
    if not os.getenv('G6_RUN_DEAD_CODE_SCAN'):
        pytest.skip('Set G6_RUN_DEAD_CODE_SCAN=1 to run dead code governance test')
    env = os.environ.copy()
    env.setdefault('G6_DEAD_CODE_BUDGET','0')
    proc = subprocess.run([sys.executable, str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.returncode == 0, f"Dead code scan failed: rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}"
    data = json.loads(proc.stdout)
    assert data['status'] == 0
    assert not data['new_items'], f"Unexpected dead code items: {data['new_items']}"