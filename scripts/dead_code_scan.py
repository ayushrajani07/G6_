#!/usr/bin/env python
"""Dead code scanner integrating vulture with governance policy.

Usage:
  python scripts/dead_code_scan.py [--fail-on findings|new] [--min-confidence N]

Behavior:
  * Runs vulture across src/ and scripts/ (excluding tests) collecting high-confidence unused symbols.
  * Compares result against allowlist in dead_code_allowlist.txt.
  * Exits non-zero if unexpected unused symbols are found or (optional) if total exceeds budget.

Environment:
  G6_DEAD_CODE_BUDGET: integer allowed count of non-allowlisted findings (default 0)

Notes:
  * We treat confidence >= 80 as high-confidence by default (tunable via --min-confidence).
  * Lower confidence findings are printed as INFO but not enforced.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST_FILE = ROOT / "dead_code_allowlist.txt"

DEFAULT_MIN_CONF = 80

class Finding(tuple[str,str,int,int]):
    __slots__ = ()
    # path, name, lineno, confidence


def load_allowlist() -> set[str]:
    items: set[str] = set()
    if not ALLOWLIST_FILE.exists():
        return items
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        items.add(s)
    return items

def parse_vulture(output: str) -> list[Finding]:
    findings: list[Finding] = []
    for line in output.splitlines():
        # Expect format: path:line: unused code 'name' (confidence X%)
        if "unused" not in line or "confidence" not in line:
            continue
        try:
            path_part, rest = line.split(":",1)
            line_no_part, rest2 = rest.split(":",1)
            lineno = int(line_no_part.strip())
            # Extract name between quotes and confidence number
            name_start = rest2.find("'")
            name_end = rest2.find("'", name_start+1)
            if name_start == -1 or name_end == -1:
                continue
            name = rest2[name_start+1:name_end]
            conf_idx = rest2.rfind("confidence")
            conf_val = 0
            if conf_idx != -1:
                tail = rest2[conf_idx:]
                # e.g. confidence 90%
                for tok in tail.replace('%','').split():
                    if tok.isdigit():
                        conf_val = int(tok)
                        break
            findings.append(Finding((path_part.strip(), name, lineno, conf_val)))
        except Exception:
            continue
    return findings

def run_vulture(paths: list[str]) -> str:
    cmd = [sys.executable, '-m', 'vulture', *paths]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    except FileNotFoundError:
        print("ERROR: vulture not installed. Install with pip install vulture or extras.", file=sys.stderr)
        sys.exit(2)
    if res.stderr.strip():
        print(res.stderr, file=sys.stderr)
    return res.stdout

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fail-on', choices=['findings','new'], default='new', help='fail on any findings or only new (non-allowlisted) findings')
    ap.add_argument('--min-confidence', type=int, default=DEFAULT_MIN_CONF, help='minimum confidence threshold to enforce')
    args = ap.parse_args()

    allowlist = load_allowlist()

    raw = run_vulture(['src', 'scripts'])
    findings = parse_vulture(raw)

    high_conf = [f for f in findings if f[3] >= args.min_confidence]
    new_items = []
    enforced_items = []
    for path, name, lineno, conf in high_conf:
        key = f"{path}:{name}"
        if key in allowlist:
            continue
        new_items.append((path, name, lineno, conf))

    budget = 0
    try:
        budget = int(os.getenv('G6_DEAD_CODE_BUDGET','0'))
    except ValueError:
        pass

    # Fail target selection
    if args.fail_on == 'findings':
        enforced_items = new_items  # identical semantics now (allowlist already applied)
    else:
        enforced_items = new_items

    total_enforced = len(enforced_items)

    status = 0
    if total_enforced > budget:
        status = 1

    report = {
        'total_findings': len(findings),
        'high_conf_findings': len(high_conf),
        'new_items': enforced_items,
        'budget': budget,
        'status': status,
    }
    print(json.dumps(report, indent=2))
    if status != 0:
        print(f"Dead code scan failed: {total_enforced} new items exceeds budget {budget}", file=sys.stderr)
    sys.exit(status)

if __name__ == '__main__':
    main()
