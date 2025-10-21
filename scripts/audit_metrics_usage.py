#!/usr/bin/env python3
"""
Audit direct metrics usage across the repo.

Finds imports/usages of src.metrics.metrics (registry/server) and Prometheus HTTP reads
so we can migrate reads to the centralized MetricsAdapter where appropriate.

Usage:
  python scripts/audit_metrics_usage.py [root_dir]

Exit code is always 0; this is a reporting tool only.
"""
from __future__ import annotations

import os
import re
import sys

PATTERNS: list[tuple[str, str]] = [
    (r"from\s+src\.metrics\.metrics\s+import\s+", "LEGACY direct import from src.metrics.metrics (migrate to facade)"),
    (r"importlib\.import_module\(['\"]src\.metrics\.metrics['\"]\)", "LEGACY dynamic import of src.metrics.metrics"),
    (r"get_metrics_singleton\s*\(", "registry singleton access (writes/reads)"),
    (r"setup_metrics_server\s*\(", "metrics server bootstrap"),
    (r"requests\.get\([^)]*/metrics", "direct Prometheus HTTP call"),
]

EXCLUDE_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.vscode', 'logs'}


def should_scan(path: str) -> bool:
    parts = set(path.replace("\\", "/").split("/"))
    return not (parts & EXCLUDE_DIRS)


def scan_file(path: str) -> list[tuple[int, str, str]]:
    results: list[tuple[int, str, str]] = []
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            text = f.read()
        for pat, desc in PATTERNS:
            for m in re.finditer(pat, text):
                # get line number
                line_no = text.count('\n', 0, m.start()) + 1
                # extract line content
                line_start = text.rfind('\n', 0, m.start()) + 1
                line_end = text.find('\n', m.end())
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end].strip()
                results.append((line_no, desc, line))
    except Exception:
        pass
    return results


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    root = os.path.abspath(root)
    findings = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # filter dirs in-place
        dirnames[:] = [d for d in dirnames if should_scan(os.path.join(dirpath, d))]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            if not should_scan(full):
                continue
            hits = scan_file(full)
            if hits:
                rel = os.path.relpath(full, root)
                findings[rel] = hits

    if not findings:
        print("No direct metrics usage found.")
        return 0

    print("Metrics usage audit:\n")
    for file, hits in sorted(findings.items()):
        print(f"- {file}")
        for line_no, desc, line in hits:
            print(f"  L{line_no:>4}: {desc}\n          {line}")
    print("\nLegend:")
    for _, desc in PATTERNS:
        print(f" - {desc}")
    print("\nGuidance:")
    print(" - Prefer facade imports: from src.metrics import get_metrics, setup_metrics_server")
    print(" - Limit direct registry mutation to producer modules;")
    print("   readers should consume derived adapters where available")
    print(" - Dynamic imports of 'src.metrics.metrics' are deprecated;")
    print("   use importlib.import_module('src.metrics') if indirection required")
    print(" - Consider adding a CI guard to fail on newly introduced legacy imports")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
