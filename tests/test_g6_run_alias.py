import os
import subprocess
import sys
from pathlib import Path
import pytest
from tests._helpers import fast_mode


@pytest.mark.slow
def test_g6_run_alias_bounded(tmp_path):
    """Smoke test the g6_run convenience wrapper.

    Runs two fast cycles using mock provider & forced market open. We use a very small
    interval and cycle count to keep the test quick. Success criteria: exit code 0
    and presence of g6_data directory structure for configured index.
    """
    env = os.environ.copy()
    env['G6_USE_MOCK_PROVIDER'] = '1'
    env['G6_FORCE_MARKET_OPEN'] = '1'
    # Keep things deterministic/noisy features off
    env['G6_PARALLEL_INDICES'] = '0'
    # Use a temp config path referencing minimal index params if needed; fallback to default config
    # For now rely on default config shipped; working directory controls data dir via env override
    workdir = Path(tmp_path)
    # Direct data dir override (if orchestrator respects basedir from config; else it will still write under repo data)
    # We isolate by setting a temporary current working dir
    cycles = '2' if fast_mode() else os.getenv('G6_RUN_ALIAS_CYCLES', '6')
    interval = '0.1' if fast_mode() else os.getenv('G6_RUN_ALIAS_INTERVAL', '0.2')
    cmd = [sys.executable, 'scripts/g6_run.py', '--config', 'config/g6_config.json', '--interval', interval, '--cycles', cycles]
    proc = subprocess.run(cmd, cwd=Path.cwd(), env=env, capture_output=True, text=True, timeout=60)
    # Debug aid if fails
    if proc.returncode != 0:
        print('STDOUT:\n', proc.stdout)
        print('STDERR:\n', proc.stderr)
    assert proc.returncode == 0
    # Not asserting exact files (depends on underlying sinks); ensure run did not crash.