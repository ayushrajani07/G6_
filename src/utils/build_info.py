"""Helpers for computing and registering build metadata.

Provides stable hashing for configuration, extraction of version and git commit
information, and a convenience wrapper that feeds the existing
`metrics.register_build_info` helper.

Design goals:
 - Zero hard dependency on GitPython (pure file reads / env fallbacks).
 - No failure propagation: all helpers return 'unknown' on error.
 - Deterministic config hash: JSON canonicalization (sorted keys) + sha256.
 - Extensible: future fields (build_time, dirty flag) can be added without
   breaking existing metric labels (would require new metric if label set changes).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def _read_git_head(repo_root: str) -> str | None:
    head_path = os.path.join(repo_root, '.git', 'HEAD')
    try:
        with open(head_path, encoding='utf-8') as f:
            ref = f.read().strip()
        if ref.startswith('ref:'):
            ref_rel = ref.split(' ', 1)[1].strip()
            ref_file = os.path.join(repo_root, '.git', ref_rel)
            try:
                with open(ref_file, encoding='utf-8') as rf:
                    return rf.read().strip()[:40]
            except Exception:
                return None
        # Detached HEAD contains commit directly
        if len(ref) >= 7:
            return ref[:40]
    except Exception:
        return None
    return None

def compute_git_commit(repo_root: str | None = None) -> str:
    # Env override highest priority
    env_commit = os.environ.get('G6_GIT_COMMIT')
    if env_commit:
        return env_commit[:40]
    root = repo_root or os.getcwd()
    commit = _read_git_head(root)
    return commit or 'unknown'

def compute_version() -> str:
    env_version = os.environ.get('G6_VERSION')
    if env_version:
        return env_version
    try:
        from src.version import get_version  # type: ignore
        return get_version()
    except Exception:
        return 'unknown'

def compute_config_hash(config: Any) -> str:
    """Compute a stable sha256 hash of the raw config structure.

    Accepts either a ConfigWrapper-like object exposing .raw or a plain dict.
    Unknown structures return 'unknown'.
    """
    try:
        if hasattr(config, 'raw'):
            cfg = config.raw
        else:
            cfg = config
        if not isinstance(cfg, dict):  # pragma: no cover - defensive
            return 'unknown'
        blob = json.dumps(cfg, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]
    except Exception:  # pragma: no cover - defensive
        return 'unknown'

def gather_build_info(config: Any, repo_root: str | None = None) -> tuple[str,str,str]:
    """Return (version, git_commit, config_hash)."""
    return compute_version(), compute_git_commit(repo_root), compute_config_hash(config)

def auto_register_build_info(metrics, config: Any, repo_root: str | None = None):
    """Compute build info tuple and register metric if metrics object present."""
    try:
        if metrics is None:
            return
        from src.metrics import register_build_info  # facade import
        version, commit, cfg_hash = gather_build_info(config, repo_root)
        register_build_info(metrics, version=version, git_commit=commit, config_hash=cfg_hash)
    except Exception:  # pragma: no cover
        pass

__all__ = [
    'compute_git_commit', 'compute_version', 'compute_config_hash',
    'gather_build_info', 'auto_register_build_info'
]
