#!/usr/bin/env python
"""Placeholder CI validation for cleanup hygiene.

Future expansion:
  * Compare inventory against baseline to detect added temp-debug files.
  * Enforce max dead-code growth delta.
  * Verify env var catalog up to date.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None

def main() -> int:
    # Optional pre-run: regenerate coverage if requested
    if os.getenv('G6_RUN_COVERAGE') == '1':
        cov_xml = ROOT / 'coverage.xml'
        try:
            print('[validate-cleanup] coverage pre-run: invoking pytest with coverage')
            # Minimal coverage over src + scripts; quiet output
            subprocess.run([
                sys.executable,
                '-m','pytest','-q',
                '--cov=src','--cov=scripts','--cov-report=xml','--cov-report=term-missing:skip-covered'
            ], cwd=ROOT, check=False)
            if cov_xml.exists():
                print('[validate-cleanup] coverage pre-run complete (coverage.xml updated)')
            else:
                print('[validate-cleanup] WARN: coverage pre-run did not produce coverage.xml')
        except Exception as e:  # pragma: no cover
            print('[validate-cleanup] WARN: coverage pre-run failed', e)
    inventory = load_json(ROOT / 'tools' / 'cleanup_inventory.json') or {}
    env_vars = load_json(ROOT / 'tools' / 'env_vars.json') or {}
    inv_count = len(inventory.get('inventory', []))
    env_count = len(env_vars.get('env_vars', []))
    print(f"[validate-cleanup] inventory_entries={inv_count} env_vars={env_count}")

    # --- Coverage Gate (non-regression) ---
    # Env vars:
    #   G6_COVERAGE_MIN_PCT   (float, default 45.0) absolute floor (initialized to current baseline ~45%).
    #                         Increment via ratchet (e.g. +2pp per week) instead of a large jump to 70%.
    #   G6_COVERAGE_MAX_DROP  (float, default 3.0) allowed percentage-point drop vs baseline (slightly looser early).
    # Baseline stored in tools/coverage_baseline.json as {"line_coverage_pct": <float>}
    cov_min = float(os.getenv('G6_COVERAGE_MIN_PCT', '45.0') or 45.0)
    cov_max_drop = float(os.getenv('G6_COVERAGE_MAX_DROP', '3.0') or 3.0)
    cov_report = ROOT / 'coverage.xml'
    baseline_path = ROOT / 'tools' / 'coverage_baseline.json'
    current_cov = None
    if cov_report.exists():
        try:
            # Parse Cobertura-style line-rate attr on root <coverage ... line-rate="0.8234" />
            txt = cov_report.read_text(encoding='utf-8', errors='ignore')
            m = re.search(r'line-rate="([0-9]*\.?[0-9]+)"', txt)
            if m:
                current_cov = round(float(m.group(1)) * 100.0, 2)
        except Exception:
            current_cov = None
    if current_cov is not None:
        base_data = load_json(baseline_path) or {}
        baseline_cov = base_data.get('line_coverage_pct')
        if baseline_cov is None:
            # Establish baseline (first run)
            try:
                baseline_path.parent.mkdir(parents=True, exist_ok=True)
                baseline_path.write_text(json.dumps({'line_coverage_pct': current_cov}, indent=2), encoding='utf-8')
                print(f"[validate-cleanup] coverage_baseline_created pct={current_cov}")
            except Exception:
                print("[validate-cleanup] WARN: failed to write coverage baseline", file=sys.stderr)
            baseline_cov = current_cov
        print(f"[validate-cleanup] coverage_current={current_cov:.2f}% baseline={baseline_cov:.2f}% min={cov_min:.2f}% max_drop={cov_max_drop:.2f}pp")
        # Absolute floor
        if current_cov < cov_min:
            print(f"[validate-cleanup] FAIL: coverage {current_cov:.2f}% below min {cov_min:.2f}%")
            return 1
        # Drop detection
        drop = baseline_cov - current_cov
        if drop > cov_max_drop:
            print(f"[validate-cleanup] FAIL: coverage drop {drop:.2f}pp exceeds allowed {cov_max_drop:.2f}pp (baseline {baseline_cov:.2f}% -> current {current_cov:.2f}%)")
            return 1
    else:
        print("[validate-cleanup] coverage.xml missing or unparsable; skipping coverage gate (will enforce once available)")

    # Dead code scan enforcement (Phase A light): run script, honor budget if set.
    budget = int(os.getenv('G6_DEAD_CODE_BUDGET', '0'))
    scan_cmd = [sys.executable, '-m', 'scripts.cleanup.dead_code_scan']
    if budget:
        print(f"[validate-cleanup] dead_code_budget={budget}")
    try:
        result = subprocess.run(scan_cmd, cwd=ROOT, capture_output=True, text=True)
    except Exception as e:  # pragma: no cover
        print('[validate-cleanup] dead code scan failed to start', e, file=sys.stderr)
        return 2
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        # propagate failure (either budget exceed or new items)
        sys.stderr.write(result.stderr)
        print('[validate-cleanup] FAIL: dead code policy violation')
        return 1
    print('[validate-cleanup] dead code scan OK')

    # Orphan tests gate
    orphan_cmd = [sys.executable, '-m', 'scripts.cleanup.orphan_tests']
    try:
        oproc = subprocess.run(orphan_cmd, cwd=ROOT, capture_output=True, text=True)
    except Exception as e:  # pragma: no cover
        print('[validate-cleanup] orphan test scan failed to start', e, file=sys.stderr)
        return 2
    if oproc.returncode != 0:
        sys.stdout.write(oproc.stdout)
        sys.stderr.write(oproc.stderr)
        print('[validate-cleanup] FAIL: orphan tests detected')
        return 1
    print('[validate-cleanup] orphan tests OK')

    # Env var catalog freshness gate
    env_cmd = [sys.executable, '-m', 'scripts.cleanup.env_catalog_check']
    env_proc = subprocess.run(env_cmd, cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(env_proc.stdout)
    if env_proc.returncode != 0:
        sys.stderr.write(env_proc.stderr)
        print('[validate-cleanup] FAIL: env catalog freshness')
        return 1
    print('[validate-cleanup] env catalog OK')

    # Docs index freshness gate
    doc_cmd = [sys.executable, '-m', 'scripts.cleanup.doc_index_check']
    doc_proc = subprocess.run(doc_cmd, cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(doc_proc.stdout)
    if doc_proc.returncode != 0:
        sys.stderr.write(doc_proc.stderr)
        print('[validate-cleanup] FAIL: docs index freshness')
        return 1
    print('[validate-cleanup] docs index OK')

    print('[validate-cleanup] all gates passed')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
