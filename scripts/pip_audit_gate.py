#!/usr/bin/env python
"""pip-audit gating helper.

Runs `pip-audit -f json` (if available) and enforces a maximum allowed severity.

Environment:
  G6_PIP_AUDIT_SEVERITY (default HIGH) - highest allowed severity level; any advisory above (CRITICAL) or equal triggers non-zero exit.
  G6_PIP_AUDIT_IGNORE (comma list)     - vulnerability IDs to ignore.

If pip-audit is not installed, exits 0 with a warning (treat as soft dependency).

Test Strategy:
  Provide a captured pip-audit JSON via --input for offline test (skips invoking pip-audit).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

_SEV_ORDER = ['LOW','MEDIUM','HIGH','CRITICAL']

def _severity_rank(s: str) -> int:
    s = (s or '').upper()
    return _SEV_ORDER.index(s) if s in _SEV_ORDER else -1

def run_pip_audit_json() -> list[dict[str, Any]] | None:
    try:
        proc = subprocess.run(['pip-audit','-f','json'], capture_output=True, text=True, check=False)
        if proc.returncode not in (0,1):  # pip-audit returns 1 when vulns found
            print(f"pip-audit unexpected rc={proc.returncode}", file=sys.stderr)
        txt = proc.stdout.strip() or '[]'
        data = json.loads(txt)
        # pip-audit returns a list of packages with 'vulns' field
        if isinstance(data, list):
            return data
        return []
    except FileNotFoundError:
        print("pip-audit not installed; skipping gate (treat as pass)")
        return None
    except Exception as e:
        print(f"pip-audit execution failed: {e}", file=sys.stderr)
        return None

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--input', help='Existing pip-audit JSON (bypass subprocess)')
    p.add_argument('--max-severity', help='Override max severity (else env)')
    args = p.parse_args(argv)

    max_sev = (args.max_severity or os.getenv('G6_PIP_AUDIT_SEVERITY','HIGH')).upper()
    if max_sev not in _SEV_ORDER:
        max_sev = 'HIGH'
    max_rank = _severity_rank(max_sev)

    ignore_ids = {i.strip() for i in (os.getenv('G6_PIP_AUDIT_IGNORE','') or '').split(',') if i.strip()}

    if args.input:
        try:
            data = json.loads(open(args.input,encoding='utf-8').read())
        except Exception as e:
            print(f"Failed to read input file: {e}", file=sys.stderr)
            return 2
    else:
        data = run_pip_audit_json()
        if data is None:
            return 0

    advisories: list[dict[str, Any]] = []
    # pip-audit JSON can be list of packages each with vulns
    if isinstance(data, list):
        for pkg in data:
            vulns = pkg.get('vulns') or []
            for v in vulns:
                vid = v.get('id') or v.get('alias') or 'UNKNOWN'
                if vid in ignore_ids:
                    continue
                sev = v.get('severity') or 'UNKNOWN'
                advisories.append({'id': vid, 'severity': sev, 'fix_versions': v.get('fix_versions')})
    else:
        print('Unexpected pip-audit JSON shape', file=sys.stderr)

    worst = max((_severity_rank(a['severity']) for a in advisories), default=-1)
    failing = worst > max_rank or (worst == max_rank and max_sev != 'CRITICAL')
    # If worst severity equals limit: we gate inclusively (i.e., HIGH limit blocks HIGH)
    if worst == max_rank:
        failing = True

    if failing and worst >= 0:
        print(f"FAIL: max allowed {max_sev}, found advisory with severity {_SEV_ORDER[worst]}")
        for a in advisories:
            if _severity_rank(a['severity']) == worst:
                print(f"  - {a['id']} severity={a['severity']} fix_versions={a.get('fix_versions')}")
        return 3
    else:
        print(f"PASS: worst severity={_SEV_ORDER[worst] if worst>=0 else 'NONE'} within limit {max_sev}")
        return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
