#!/usr/bin/env python3
"""
Fail CI if non-test files deep-import the legacy module 'src.metrics.metrics'.
Allowed:
- Any file under tests/** (tests may intentionally import legacy path)
- This script itself

Exit codes:
- 0: No violations
- 2: Violations found
- 3: Script error
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    re.compile(r"^\s*from\s+src\.metrics\.metrics\s+import\b"),
    re.compile(r"^\s*import\s+src\.metrics\.metrics\b"),
    re.compile(r"importlib\.import_module\(\s*['\"]src\.metrics\.metrics['\"]\s*\)"),
    re.compile(r"^\s*from\s+src\.metrics\s+import\s+metrics\b"),
]

ALLOWED_DIRS = {os.path.join(ROOT, 'tests')}
ALLOWED_FILES = {
    os.path.join(ROOT, 'scripts', 'check_no_deep_metrics_imports.py'),
}

IGNORED_DIRS = {
    '.git', '.github', '.venv', 'venv', 'env', 'node_modules', '__pycache__'
}

VIOLATIONS: list[tuple[str,int,str]] = []

try:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Prune ignored dirs
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        # Skip allowed directory trees (tests)
        if any(os.path.commonpath([dirpath, allow]) == allow for allow in ALLOWED_DIRS):
            continue
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            fpath = os.path.join(dirpath, fn)
            if fpath in ALLOWED_FILES:
                continue
            rel = os.path.relpath(fpath, ROOT)
            try:
                with open(fpath, encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, start=1):
                        for pat in PATTERNS:
                            if pat.search(line):
                                VIOLATIONS.append((rel, i, line.rstrip()))
                                break
            except Exception as e:
                print(f"[check-no-deep-metrics] WARN: failed to read {rel}: {e}", file=sys.stderr)
except Exception as e:
    print(f"[check-no-deep-metrics] ERROR: scan failed: {e}", file=sys.stderr)
    sys.exit(3)

if VIOLATIONS:
    print("Deep import violations detected (non-test files):")
    for rel, ln, src in VIOLATIONS:
        print(f" - {rel}:{ln}: {src}")
    print("\nUse: 'from src.metrics import <symbol>' or dynamic 'importlib.import_module(\"src.metrics\")'.")
    sys.exit(2)
else:
    print("No deep import violations found.")
    sys.exit(0)
