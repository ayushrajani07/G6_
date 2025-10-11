import subprocess, sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_ROOT = _THIS_DIR
for _ in range(6):  # ascend to find scripts directory
    if (_ROOT / 'scripts' / 'parity_weight_study.py').exists():
        break
    _ROOT = _ROOT.parent
SCRIPT = _ROOT / 'scripts' / 'parity_weight_study.py'

def run_cmd(args):
    return subprocess.run([sys.executable, str(SCRIPT), '--synthetic', '5', '--noise', '0.02', '--seed', '42'] + args, capture_output=True, text=True)

def test_emit_env_line():
    r = run_cmd(['--weights-only', '--emit-env'])
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip().splitlines()[-1]
    assert line.startswith('G6_PARITY_COMPONENT_WEIGHTS=')
    kvs = line.split('=',1)[1].split(',')
    parsed = {}
    for kv in kvs:
        k,v = kv.split('=')
        parsed[k]=float(v)
    s = sum(parsed.values())
    assert abs(s-1.0) < 1e-6

def test_apply_out(tmp_path):
    out_env = tmp_path / 'weights.env'
    r = run_cmd(['--weights-only', '--apply-out', str(out_env)])
    assert r.returncode == 0
    assert out_env.exists()
    content = out_env.read_text().strip()
    assert content.startswith('G6_PARITY_COMPONENT_WEIGHTS=')
