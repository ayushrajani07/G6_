import json
import subprocess
import sys
from pathlib import Path

CLI = Path('scripts/g6.py')


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_g6_help_lists_subcommands():
    r = run_cli('--help')
    assert r.returncode == 0
    out = r.stdout.lower()
    for sub in ['summary','simulate','panels-bridge','integrity','bench','retention-scan','version']:
        assert sub in out, f"Subcommand {sub} missing from help output"


def test_g6_version_outputs_schema_version():
    r = run_cli('version')
    assert r.returncode == 0
    assert 'schema_version' in r.stdout.lower()
    assert 'g6 cli version' in r.stdout.lower()
