#!/usr/bin/env python3
"""
Lightweight checker: flags try/except blocks that only log without using the
central error handling helpers. This is a heuristic to help prevent regressions.

Usage:
  python scripts/check_logging_only_try.py [path...]

Exit code 1 if any suspicious blocks are found.
"""
from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

CENTRAL_FUNCS = {
    'handle_ui_error', 'handle_data_error', 'handle_api_error', 'handle_critical_error',
    'handle_collector_error', 'handle_provider_error', 'handle_data_collection_error',
    'try_with_central_handler', 'handle_error'
}


class TryExceptVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.suspicious: list[tuple[int, str]] = []

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        for handler in node.handlers:
            # Consider only generic Exception handlers for now
            if handler.type is None or getattr(getattr(handler.type, 'id', None), 'lower', lambda: '')() in {'exception', 'baseexception'}:
                calls = [n for n in ast.walk(handler) if isinstance(n, ast.Call)]
                names = set()
                for c in calls:
                    func = c.func
                    if isinstance(func, ast.Attribute):
                        names.add(func.attr)
                    elif isinstance(func, ast.Name):
                        names.add(func.id)
                has_central = any(n in CENTRAL_FUNCS for n in names)
                only_logs = any(n in {'error', 'warning', 'info', 'debug'} for n in names) and not has_central
                if only_logs:
                    self.suspicious.append((handler.lineno, 'except block only logs, no central handling'))
        self.generic_visit(node)


def iter_py_files(paths: Iterable[str]) -> Iterable[Path]:
    if not paths:
        paths = ['src', 'scripts']
    for p in paths:
        path = Path(p)
        if path.is_file() and path.suffix == '.py':
            yield path
        elif path.is_dir():
            for f in path.rglob('*.py'):
                # Skip virtual envs or caches
                if any(part in {'.venv', 'venv', '__pycache__'} for part in f.parts):
                    continue
                yield f


def main(argv: list[str]) -> int:
    rc = 0
    for file in iter_py_files(argv[1:]):
        try:
            tree = ast.parse(file.read_text(encoding='utf-8'))
        except Exception:
            continue
        v = TryExceptVisitor(str(file))
        v.visit(tree)
        for lineno, msg in v.suspicious:
            print(f"{file}:{lineno}: {msg}")
            rc = 1
    return rc


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
