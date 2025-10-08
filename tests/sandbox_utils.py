"""Test sandbox provisioning helpers.

Centralizes logic previously embedded in pytest fixtures to ensure that
when tests (or subprocess-invoked scripts inside tests) change the CWD
to a temporary sandbox, required project assets are present:

  - scripts/: core CLI and utility scripts exercised by tests
  - docs/: minimal docs subset for fallback generation invariants
  - PYTHONPATH: repo root injected so `python -c` and script invocations
    can import `src` without manipulating sys.path manually.

Exported functions:
  provision_sandbox(path: Path) -> None
  ensure_pythonpath(root: Path) -> None

Environment Overrides:
  G6_DISABLE_SANDBOX_PROVISION=1 -> skip all provisioning (debug aid)

This module deliberately avoids pytest imports to keep it usable from
both fixtures and ad-hoc debug scripts.
"""
from __future__ import annotations

from pathlib import Path
import os, shutil
from typing import Iterable

REQUIRED_SCRIPTS: tuple[str, ...] = (
    'g6.py',
    'g6_run.py',
    'check_integrity.py',
    'run_orchestrator_loop.py',
    'benchmark_cycles.py',
    'expiry_matrix.py',
    'metrics_import_bench.py',
)

REQUIRED_DOCS: tuple[str, ...] = (
    'DEPRECATIONS.md',
    'env_dict.md',
    'metrics_spec.yaml',
)

YES = {'1','true','yes','on'}

def ensure_pythonpath(root: Path) -> None:
    """Ensure repo root is on PYTHONPATH for subprocess imports.

    Safe & idempotent: does nothing if already present or disabled.
    """
    if os.environ.get('G6_DISABLE_SANDBOX_PROVISION','').lower() in YES:
        return
    try:
        root_str = str(root)
        sep = ';' if os.name == 'nt' else ':'
        cur = os.environ.get('PYTHONPATH','')
        parts = [p for p in cur.split(sep) if p]
        if root_str not in parts:
            os.environ['PYTHONPATH'] = root_str + (sep + cur if cur else '')
    except Exception:
        pass

def _copy_missing(src_dir: Path, dst_dir: Path, names: Iterable[str]) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        s = src_dir / name
        d = dst_dir / name
        if d.exists() or not s.exists():
            continue
        try:
            shutil.copy2(s, d)
        except Exception:
            pass

def _write_doc_placeholder(dst: Path, doc_name: str) -> None:
    try:
        if doc_name == 'metrics_spec.yaml':
            dst.write_text('- name: g6_collection_cycles\n  type: counter\n  labels: []\n  group: core\n  stability: stable\n  description: cycles (autogen sandbox)\n', encoding='utf-8')
        elif doc_name == 'env_dict.md':
            dst.write_text('# Environment Variables (autogen sandbox)\nG6_COLLECTION_CYCLES: placeholder\n', encoding='utf-8')
        elif doc_name == 'DEPRECATIONS.md':
            dst.write_text('# Deprecated Execution Paths (sandbox)\n', encoding='utf-8')
    except Exception:
        pass

def provision_sandbox(path: Path, root: Path | None = None) -> None:
    """Populate required scripts/docs into sandbox directory.

    Parameters
    ----------
    path : Path
        Target sandbox directory (usually current working directory
        after a test chdir).
    root : Path | None
        Explicit repository root. If None, inferred as parent of this file's parent.
    """
    if os.environ.get('G6_DISABLE_SANDBOX_PROVISION','').lower() in YES:
        return
    try:
        root = root or Path(__file__).resolve().parents[1]
        scripts_root = root / 'scripts'
        docs_root = root / 'docs'
        # Scripts
        _copy_missing(scripts_root, path / 'scripts', REQUIRED_SCRIPTS)
        # Docs (copy or placeholder)
        doc_dir = path / 'docs'
        doc_dir.mkdir(parents=True, exist_ok=True)
        for doc in REQUIRED_DOCS:
            dst = doc_dir / doc
            if dst.exists():
                continue
            src = docs_root / doc
            if src.exists():
                try:
                    dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
                except Exception:
                    pass
            else:
                _write_doc_placeholder(dst, doc)
    except Exception:
        pass

__all__ = [
    'provision_sandbox',
    'ensure_pythonpath',
    'REQUIRED_SCRIPTS',
    'REQUIRED_DOCS',
]