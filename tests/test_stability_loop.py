"""Test the stability loop harness (Stage 2 facade parity version).

We limit cycles for speed and assert:
    - Report JSON created with expected top-level keys
    - Modes executed include legacy, pipeline, parity (default modes)
    - Parity mode reports mismatch count (should be 0 for deterministic provider)
"""
from __future__ import annotations

import json, os, pathlib, sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import subprocess


def test_stability_loop_smoke(tmp_path):
    report_path = tmp_path / 'stability_report.json'
    cmd = [sys.executable, 'scripts/stability_loop.py', '--indices', 'NIFTY,BANKNIFTY', '--cycles', '2', '--out', str(report_path)]
    env = os.environ.copy()
    # Ensure deterministic conditions; disable async enrichment to reduce variance
    env.pop('G6_ENRICH_ASYNC', None)
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert report_path.exists(), 'report not created'
    data: Any = json.loads(report_path.read_text())
    assert 'results' in data and isinstance(data['results'], dict)
    # legacy, pipeline, parity should be present by default
    for m in ('legacy','pipeline','parity'):
        assert m in data['results']
        t = data['results'][m]['timing']
        assert t['mean_s'] >= 0
    # Parity mismatch cycles should be zero with deterministic provider
    parity = data['results']['parity']
    assert parity.get('parity_mismatch_cycles', 0) == 0
