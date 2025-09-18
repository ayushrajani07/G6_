"""Optional test: validate-status CLI command via dev_tools.

Ensures that the dev_tools validate-status subcommand returns success (0)
for a runtime status file produced by a short mock run. This exercises
subprocess invocation and schema validation integration end-to-end.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.optional


def test_dev_tools_validate_status(run_mock_cycle, tmp_path):
    status_path = tmp_path / 'status.json'
    # Run 2 cycles to ensure cycle counter increments >1
    data = run_mock_cycle(cycles=2, interval=1)
    # Persist the status JSON to the temp path for CLI consumption
    status_path.write_text(json.dumps(data))

    cmd = [sys.executable, 'scripts/dev_tools.py', 'validate-status', '--file', str(status_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print('STDOUT:', r.stdout)
    print('STDERR:', r.stderr)
    assert r.returncode == 0, f"validate-status failed: {r.stdout} {r.stderr}"
    assert 'VALID' in r.stdout
