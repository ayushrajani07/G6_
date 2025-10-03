import json
import subprocess
import sys
from pathlib import Path

PYTHON = sys.executable
SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'panels_integrity_check.py'
REPO_ROOT = SCRIPT.parent.parent


def run_cli(args):
    cmd = [PYTHON, str(SCRIPT), *args]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def write_panel(dir_path: Path, name: str, data):
    panel = {"panel": name, "updated_at": 1, "data": data}
    (dir_path / f"{name}_panel.json").write_text(json.dumps(panel), encoding='utf-8')
    return panel


def canon_data(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def sha256_hex(data):
    import hashlib
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def build_manifest(dir_path: Path, panels: dict):
    hashes = {}
    for name, panel in panels.items():
        hashes[f"{name}_panel.json"] = sha256_hex(canon_data(panel['data']))
    manifest = {"panels": list(panels.keys()), "hashes": hashes}
    (dir_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def test_cli_ok(tmp_path):
    pdir = tmp_path / 'panels'
    pdir.mkdir()
    panels = {
        'alpha': write_panel(pdir, 'alpha', {"x": 1}),
        'beta': write_panel(pdir, 'beta', [1,2,3]),
    }
    build_manifest(pdir, panels)

    code, out, err = run_cli(['--panels-dir', str(pdir), '--strict'])
    assert code == 0, (code, out, err)
    assert 'OK' in out or 'issues' in out  # human or json output fallback


def test_cli_mismatch_strict(tmp_path):
    pdir = tmp_path / 'panels'
    pdir.mkdir()
    panels = {
        'alpha': write_panel(pdir, 'alpha', {"x": 1}),
    }
    build_manifest(pdir, panels)
    # Corrupt alpha
    write_panel(pdir, 'alpha', {"x": 2})

    code, out, err = run_cli(['--panels-dir', str(pdir), '--strict', '--json'])
    assert code == 1, (code, out, err)
    data = json.loads(out)
    assert data['count'] == 1
    assert list(data['issues'].values()) == ['mismatch']


def test_cli_non_strict_allows_mismatch(tmp_path):
    pdir = tmp_path / 'panels'
    pdir.mkdir()
    panels = {
        'alpha': write_panel(pdir, 'alpha', {"x": 1}),
    }
    build_manifest(pdir, panels)
    # Corrupt
    write_panel(pdir, 'alpha', {"x": 9})

    code, out, err = run_cli(['--panels-dir', str(pdir)])
    # Non-strict should not fail build (exit 0)
    assert code == 0, (code, out, err)
    assert 'alpha_panel.json' in out
