"""Centralized path and environment utilities for G6 Platform.

Provides helpers to:
- Determine project root
- Resolve relative paths safely
- Ensure data subdirectories exist
- (Optionally) inject project root into sys.path exactly once
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Optional

@lru_cache(maxsize=1)
def get_project_root() -> str:
    """Return absolute path to project root (directory containing top-level markers).

    Detection strategy:
    - Start from this file's directory and walk upward until a directory containing
      one of known markers (requirements.txt, .git, README, config folder) is found.
    - Fallback to two levels above this file.
    """
    start = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    current = start
    markers = {'.git', 'requirements.txt', 'DEPLOYMENT_GUIDE.md', 'config'}
    while True:
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # filesystem root
            return start
        current = parent


def ensure_sys_path() -> None:
    """Ensure project root is on sys.path exactly once."""
    root = get_project_root()
    if root not in sys.path:
        # Prepend so local code overrides globally installed packages with same names
        sys.path.insert(0, root)


def resolve_path(path: str, create: bool = False) -> str:
    """Resolve a path relative to project root unless already absolute.

    Args:
        path: Input path (absolute or relative).
        create: If True, create the directory (for directory paths) or parent dir (if path seems like a file).
    """
    if not path:
        raise ValueError("Path cannot be empty")
    if os.path.isabs(path):
        resolved = path
    else:
        resolved = os.path.abspath(os.path.join(get_project_root(), path))

    if create:
        # Heuristic: treat as directory if no extension
        target_dir = resolved if not os.path.splitext(resolved)[1] else os.path.dirname(resolved)
        os.makedirs(target_dir, exist_ok=True)
    return resolved


def data_subdir(*parts: str, create: bool = True) -> str:
    """Resolve a path inside the canonical data directory (data/).

    Example: data_subdir('g6_data', 'NIFTY') -> <root>/data/g6_data/NIFTY
    """
    rel = os.path.join('data', *parts)
    return resolve_path(rel, create=create)


__all__ = [
    'get_project_root',
    'ensure_sys_path',
    'resolve_path',
    'data_subdir',
]
