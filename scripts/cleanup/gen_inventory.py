#!/usr/bin/env python
"""Generate a project inventory with heuristic classifications.

Outputs JSON to tools/cleanup_inventory.json (create tools/ if missing).

Classification heuristics are intentionally conservative (favor false negatives).
Refine over time; avoid deleting based solely on this output.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / 'tools'
OUTPUT_DIR.mkdir(exist_ok=True)
OUT_FILE = OUTPUT_DIR / 'cleanup_inventory.json'

PYTHON_ROOTS = ['src', 'scripts', 'tests']
DOC_EXTS = {'.md'}
CODE_EXTS = {'.py', '.sh', '.ps1', '.bat', '.toml', '.ini', '.yml', '.yaml'}

EXCLUDE_DIR_PREFIXES = {
    '.venv', '.git', '.idea', '.vscode', '__pycache__', 'build', 'dist', 'archive', 'tools',
}
EXCLUDE_PATH_CONTAINS = {
    '/__pycache__/', '/.mypy_cache/', '/.pytest_cache/', '/.ruff_cache/',
}
EXCLUDE_TOP_LEVEL = {'coverage.xml', '.coverage'}
EXCLUDE_DATA_DIRS = {'data/panels', 'data/runtime_status.json'}  # runtime artifacts

def sha256(path: Path) -> str:
    try:
        with path.open('rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return '0'*16

def _excluded(p: Path) -> bool:
    rel = p.as_posix()
    # top level excludes
    if p.name in EXCLUDE_TOP_LEVEL and p.parent == ROOT:
        return True
    parts = rel.split('/')
    for comp in parts:
        if comp in EXCLUDE_DIR_PREFIXES:
            return True
    for needle in EXCLUDE_PATH_CONTAINS:
        if needle in rel:
            return True
    # Data dirs (panels) - skip heavy ephemeral content
    for d in EXCLUDE_DATA_DIRS:
        if rel.startswith(d):
            return True
    return False

def discover_files() -> Iterator[Path]:
    for p in ROOT.rglob('*'):
        if not p.is_file():
            continue
        if _excluded(p):
            continue
        # Only inventory code/docs of interest
        if p.suffix not in CODE_EXTS and p.suffix not in DOC_EXTS:
            continue
        yield p

def classify(path: Path, rel: str) -> list[str]:
    tags: list[str] = []
    name = path.name.lower()
    # Docs
    if path.suffix in DOC_EXTS:
        if 'wave' in name or 'phase' in name or 'scope' in name:
            tags.append('docs-legacy')
        else:
            tags.append('docs-active')
    # Temp / debug
    if name.startswith(('temp_', 'debug_')) or name.startswith('list_lines'):
        tags.append('temp-debug')
    # Python core detection (simple): under src/
    if rel.startswith('src/') and path.suffix == '.py':
        tags.append('core')
    # Tests
    if rel.startswith('tests/') and path.suffix == '.py':
        tags.append('test')
    # Infra
    if path.name in {'pyproject.toml','pytest.ini','ruff.toml','requirements.txt','mypy.ini'}:
        tags.append('infra')
    return tags

def build_import_graph(py_files: list[Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for pf in py_files:
        rel = pf.as_posix()
        if not rel.endswith('.py'): continue
        try:
            tree = ast.parse(pf.read_text(encoding='utf-8'), filename=rel)
        except Exception:
            continue
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.add(n.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        graph[rel] = imports
    return graph

def main() -> int:
    files = list(discover_files())
    inventory: list[dict[str, Any]] = []
    py_files = [p for p in files if p.suffix == '.py']
    graph = build_import_graph(py_files)
    tag_counts: dict[str, int] = {}
    candidate_count = 0
    for p in files:
        try:
            rel = p.resolve().relative_to(ROOT).as_posix()
        except Exception:
            # Skip files outside the repository root (e.g., symlink targets, coverage artifacts one level up)
            continue
        tags = classify(p, rel)
        size = p.stat().st_size if p.exists() else 0
        entry: dict[str, Any] = {
            'path': rel,
            'size': size,
            'hash': sha256(p),
            'tags': tags,
        }
        if p.suffix == '.py':
            # simple candidate-remove heuristic: no inbound references + not a test + not under src/__init__ root naming
            module_name = Path(rel).stem
            inbound = sum(1 for mods in graph.values() if module_name in mods)
            entry['import_inbound'] = inbound
            if 'test' not in tags and 'core' not in tags and inbound == 0:
                # ensure list[str] and append tag
                tlist = entry.setdefault('tags', [])
                if isinstance(tlist, list):
                    tlist.append('candidate-remove')
                else:
                    entry['tags'] = ['candidate-remove']
                candidate_count += 1
        for t in entry['tags']:
            if isinstance(t, str):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        inventory.append(entry)
    payload: dict[str, Any] = {'inventory': inventory, 'summary': {'total': len(inventory), 'tags': tag_counts, 'candidate_remove': candidate_count}}
    with OUT_FILE.open('w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    print(f"[cleanup] wrote {OUT_FILE} entries={len(inventory)} candidates={candidate_count}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
