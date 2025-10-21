"""Detect orphaned test files.

Improved Heuristics (v2): A test file is considered an orphan ONLY if:
    * It exists and matches pattern test_*.py
    * It is NOT a deliberate module-level tombstone (single module-level pytest.skip(..., allow_module_level=True))
    * It has no local project imports (scripts/ or src/)
    * It contains neither pytest marks nor any assert statements
    * (Optional reinforcement) It has zero executed coverage lines when coverage.json present
    * It is not an intentional empty placeholder with a documented future removal date (detected via date YYYY-MM-DD in a skip string)

The goal is to reduce false positives so governance noise is minimized.

Outputs JSON list to stdout: [{"path": <rel>, "reasons": [...]}]
Exit code 0 if none, 1 if orphans found.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_PATTERN = re.compile(r'^test_.*\\.py$')

def load_coverage_lines() -> set[tuple[str,int]]:
    cov_file = ROOT / 'coverage.json'  # optional
    if not cov_file.exists():
        return set()
    try:
        data = json.loads(cov_file.read_text(encoding='utf-8'))
    except Exception:
        return set()
    lines: set[tuple[str,int]] = set()
    files = data.get('files') or {}
    for fname, meta in files.items():
        executed = meta.get('executed_lines') or []
        # Normalize path to project relative if possible
        rel = Path(fname)
        if rel.is_absolute():
            try:
                rel = rel.relative_to(ROOT)
            except ValueError:
                pass
        for ln in executed:
            lines.add((str(rel), ln))
    return lines

from typing import Any

def analyze_test(path: Path, executed: set[tuple[str,int]]) -> dict[str, Any] | None:
    try:
        txt = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return None
    # Empty file heuristic
    if not txt.strip():
        # Empty file provides no value; mark orphan directly
        return {"path": str(path.relative_to(ROOT)), "reasons": ["empty_file"]}
    # Tombstone skip detection: module-level pytest.skip with allow_module_level=True
    # If file only contains import pytest + single pytest.skip(...) treat as intentional tombstone (NOT orphan)
    normalized = re.sub(r'\s+', ' ', txt.strip())
    tombstone_pattern = re.compile(r'^import pytest\s+pytest\.skip\(.*allow_module_level=True.*\)$')
    if tombstone_pattern.match(normalized):
        # Detect future removal date for optional reporting (YYYY-MM-DD)
        mdate = re.search(r'(20[0-9]{2}-[01][0-9]-[0-3][0-9])', normalized)
        # Not classified as orphan; governance can separately list tombstones if desired
        return None
    reasons: list[str] = []
    try:
        tree = ast.parse(txt, filename=str(path))
    except Exception:
        # Malformed tests are not considered orphan; they should fail separately
        return None
    imports_local = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.startswith(('scripts', 'src')):
                    imports_local = True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(('scripts', 'src')):
                imports_local = True
    if not imports_local:
        reasons.append('no_local_imports')
    if 'pytest.mark' not in txt and '@pytest.mark' not in txt:
        reasons.append('no_pytest_marks')
    if 'assert ' not in txt:
        reasons.append('no_asserts')
    # coverage heuristic
    if executed:
        prefix = str(path.relative_to(ROOT))
        any_exec = any(fname == prefix for (fname, _ln) in executed)
        if not any_exec:
            reasons.append('no_coverage_hits')
    # Determine orphan threshold: must include structural emptiness (no_local_imports) and at least two other signals
    if 'no_local_imports' in reasons and len(reasons) >= 3:
        return {"path": str(path.relative_to(ROOT)), "reasons": reasons}
    return None

def main() -> int:
    executed = load_coverage_lines()
    orphans = []
    tests_dir = ROOT / 'tests'
    if not tests_dir.exists():
        print('[]')
        return 0
    for p in tests_dir.glob('test_*.py'):
        if not p.exists():
            continue
        res = analyze_test(p, executed)
        if res:
            orphans.append(res)
    if orphans:
        json.dump(orphans, sys.stdout, indent=2)
        sys.stdout.write('\n')
        return 1
    print('[]')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
