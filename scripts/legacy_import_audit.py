#!/usr/bin/env python
"""Audit script to list remaining imports / references to legacy unified_main.

Usage:
  python scripts/legacy_import_audit.py [--fail-on warn|error]

Classification rules (heuristic):
- parity: path under tests/ and filename contains 'parity' or 'deprecation' or 'legacy'
- orchestrator_bridge: file under src/orchestrator/ importing load_config / run_collection_cycle
- deprecated_script: file under scripts/ importing unified_main directly
- util_transitional: file under src/utils or src/tools performing dynamic launch / version extraction
- core: the module src/unified_main.py itself
- doc: occurrences inside archived/ or comment-only contexts (best-effort skipped here)

Exit codes:
  0 success (or acceptable findings)
  2 fail (if --fail-on threshold exceeded)

The script intentionally avoids heavy parsing; it provides a fast signal for CI gating.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / 'src', ROOT / 'tests', ROOT / 'scripts']
PATTERN = re.compile(r'(^|\b)(src\.)?unified_main(\b|\.)')

# Simple line sniff to ignore obvious comments only lines
COMMENT_PREFIXES = ('#', '"""', "'''")


def classify(path: Path) -> str:
    p = path.as_posix()
    if p.endswith('src/unified_main.py'):
        return 'core'
    if '/tests/' in p:
        if any(k in p for k in ('parity', 'deprecation', 'legacy')):
            return 'parity'
        return 'parity'
    if '/src/orchestrator/' in p:
        return 'orchestrator_bridge'
    if '/scripts/' in p:
        return 'deprecated_script'
    if '/src/utils/' in p or '/src/tools/' in p:
        return 'util_transitional'
    return 'unknown'


SEVERITY = {
    'core': 'info',
    'parity': 'info',
    'orchestrator_bridge': 'info',
    'deprecated_script': 'warn',
    'util_transitional': 'warn',
    'unknown': 'warn',
}


def scan():
    results = []
    for base in TARGETS:
        if not base.exists():
            continue
        for path in base.rglob('*.py'):
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if 'unified_main' not in text:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if 'unified_main' not in line:
                    continue
                if line.strip().startswith(COMMENT_PREFIXES):
                    continue
                if PATTERN.search(line):
                    cls = classify(path)
                    results.append({
                        'file': path.relative_to(ROOT).as_posix(),
                        'line': i,
                        'code': line.strip()[:160],
                        'class': cls,
                        'severity': SEVERITY.get(cls, 'warn'),
                    })
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fail-on', choices=['warn','error','none'], default='none')
    ap.add_argument('--json', action='store_true', help='Emit raw JSON results')
    args = ap.parse_args()
    results = scan()
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Found {len(results)} unified_main reference(s)")
        for r in results:
            print(f"{r['file']}:{r['line']} [{r['class']}|{r['severity']}] {r['code']}")
    # Determine highest severity present
    has_warn = any(r['severity'] == 'warn' for r in results)
    if args.fail_on == 'warn' and has_warn:
        return 2
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
