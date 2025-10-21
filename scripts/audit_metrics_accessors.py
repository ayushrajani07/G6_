#!/usr/bin/env python
"""Audit for direct prometheus_client usage bypassing generated accessors.

Heuristics:
- Flag imports: from prometheus_client import ... OR import prometheus_client
- Allowlist: everything inside src/metrics/ (infrastructure layer) & scripts/gen_metrics*.py
- Report files under src/ (outside metrics) that reference Counter/Gauge/Summary/Histogram directly.

Exit code: 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'src'
ALLOW_METRIC_NAMES = {"Counter","Gauge","Summary","Histogram","CollectorRegistry","start_http_server"}
ALLOW_PATH_PREFIXES = {str((SRC / 'metrics').resolve())}
ALLOWED_FILES = {str((ROOT / 'scripts' / 'gen_metrics.py').resolve())}

violations: list[tuple[str, str, int]] = []  # (file, symbol, line)

for py in SRC.rglob('*.py'):
    rp = str(py.resolve())
    if any(rp.startswith(pref) for pref in ALLOW_PATH_PREFIXES):
        continue
    try:
        tree = ast.parse(py.read_text(encoding='utf-8'), filename=str(py))
    except Exception:
        continue
    class Visitor(ast.NodeVisitor):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path
        def visit_Import(self, node: ast.Import) -> None:
            violations.extend(
                (self.path, 'prometheus_client', node.lineno)
                for n in node.names
                if n.name == 'prometheus_client'
            )
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module == 'prometheus_client':
                violations.extend(
                    (self.path, n.name, node.lineno)
                    for n in node.names
                    if n.name in ALLOW_METRIC_NAMES
                )
    Visitor(rp).visit(tree)

if violations:
    print("Direct prometheus_client usage found (should use generated accessors):")
    for f, sym, ln in violations:
        rel = Path(f).relative_to(ROOT)
        print(f"  {rel}:{ln}: {sym}")
    sys.exit(1)
else:
    print("Accessor audit clean (no direct prometheus_client usage outside allowed paths).")
