import json, subprocess, sys
from pathlib import Path

CLI = Path('scripts/g6.py')

def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_bench_json_output():
    r = run_cli('bench','--json')
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert 'import_src_sec' in data and 'registry_init_sec' in data and 'total_sec' in data
    assert data['import_src_sec'] >= 0


def test_diagnostics_output():
    r = run_cli('diagnostics')
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert 'governance' in data
    assert 'panel_schema_version' in data
    assert 'cli_version' in data
