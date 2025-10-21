#!/usr/bin/env python
"""Pre-commit hook: validate all G6_ env vars referenced in tracked code are documented.
Fast version of tests/test_env_doc_coverage.py (no baseline regen, minimal output).
Exits non-zero on first governance violation.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_FILE = ROOT / 'docs' / 'env_dict.md'
BASELINE_FILE = ROOT / 'tests' / 'env_doc_baseline.txt'
TEST_FILE = ROOT / 'tests' / 'test_env_doc_coverage.py'

ALLOWLIST = {'G6_DISABLE_PER_OPTION_METRICS','G6_MEMORY_TIER_OVERRIDE','G6_TRACE_METRICS'}  # proposed only

SCAN_DIRS = [ROOT / 'src', ROOT / 'scripts', ROOT / 'tests']
PATTERN = re.compile(r'G6_[A-Z0-9_]+')

def collect_tokens() -> set[str]:
    found: set[str] = set()
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for p in base.rglob('*'):
            if p.is_dir():
                continue
            if '__pycache__' in p.parts:
                continue
            if p.suffix.lower() not in {'.py','.md','.sh','.bat','.ps1','.ini','.txt'}:
                continue
            try:
                text=p.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for m in PATTERN.findall(text):
                found.add(m)
    return found

def main() -> int:
    if not DOC_FILE.exists():
        print(f"ERROR: Missing documentation file {DOC_FILE}", file=sys.stderr)
        return 1
    doc_text = DOC_FILE.read_text(encoding='utf-8')
    baseline = set()
    if BASELINE_FILE.exists():
        for line in BASELINE_FILE.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            baseline.add(line)
    tokens = collect_tokens()
    missing = sorted([t for t in tokens if t not in ALLOWLIST and t not in doc_text])
    if missing:
        print("Undocumented environment variables detected:\n  - " + '\n  - '.join(missing[:20]), file=sys.stderr)
        print(f"Count: {len(missing)} (showing up to 20). Update docs/env_dict.md.", file=sys.stderr)
        return 1
    # Strict enforcement: baseline must be empty to avoid drift
    if baseline:
        print(f"Baseline file not empty ({len(baseline)} entries) – CI expects zero. Remove entries after documenting.", file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
