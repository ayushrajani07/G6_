"""Environment flag helpers.

Consolidates the common pattern of interpreting environment variables as boolean
feature flags using the canonical truthy set {"1","true","yes","on"} (case-insensitive).

Usage examples:
    from src.utils.env_flags import is_truthy_env
    if is_truthy_env('G6_ENABLE_FOO'):
        ...

Includes small convenience helpers for negative gating and cached lookups.
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from functools import lru_cache

TRUTHY_SET: set[str] = {"1","true","yes","on"}

@lru_cache(maxsize=256)
def _normalized(name: str) -> str:
    return name.upper()

def is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in TRUTHY_SET

def is_truthy_env(name: str, default: str | None = None) -> bool:
    return is_truthy(os.getenv(name, default or ''))

def is_falsy_env(name: str, default: str | None = None) -> bool:
    return not is_truthy_env(name, default)

def any_truthy_env(names: Iterable[str]) -> bool:
    return any(is_truthy_env(n) for n in names)

__all__ = [
    'TRUTHY_SET',
    'is_truthy',
    'is_truthy_env',
    'is_falsy_env',
    'any_truthy_env',
]
