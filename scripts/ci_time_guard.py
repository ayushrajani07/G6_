#!/usr/bin/env python3
"""CI Time Guard

Fast pre-commit / CI script to enforce time handling rules without running full test suite.
Rules:
  - Forbid 'datetime.utcnow(' anywhere.
  - Flag naive 'datetime.now()' unless line contains '# local-ok' or passes an explicit timezone.
Exit non-zero on violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_UTCNOW = 'datetime.utcnow('
NAIVE_NOW_RE = re.compile(r"datetime\.now\(\)")
ALLOW_COMMENT = '# local-ok'

ROOT = Path(__file__).resolve().parents[1]

utcnow_offenders: list[str] = []
naive_offenders: list[str] = []

for path in ROOT.rglob('*.py'):
    low = str(path).lower()
    if '.venv' in low or 'site-packages' in low:
        continue
    text = path.read_text(encoding='utf-8', errors='ignore')
    if FORBIDDEN_UTCNOW in text:
        utcnow_offenders.append(str(path))
    # skip timeutils definition file
    if path.name == 'timeutils.py':
        continue
    for m in NAIVE_NOW_RE.finditer(text):
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]
        if ALLOW_COMMENT in line:
            continue
        naive_offenders.append(f"{path}:{line.strip()}")

if utcnow_offenders or naive_offenders:
    if utcnow_offenders:
        print('Forbidden datetime.utcnow() found in:')
        for f in utcnow_offenders:
            print('  -', f)
    if naive_offenders:
        print('Naive datetime.now() (add # local-ok if intentional display use):')
        for f in naive_offenders:
            print('  -', f)
    sys.exit(1)
print('[OK] Time guard passed.')
