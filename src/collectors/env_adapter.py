from __future__ import annotations

"""Environment adapter for collectors.

Provides consistent helpers to parse environment variables with sane defaults
and shared truthy semantics. Centralizes behavior to simplify testing and
future governance (e.g., lint for direct os.getenv usage).
"""
import os
from collections.abc import Callable

_TRUTHY = {"1","true","yes","on","y"}

def get_str(name: str, default: str = "") -> str:
    try:
        v = os.getenv(name)
        if v is None:
            return default
        return v
    except Exception:
        return default

def get_bool(name: str, default: bool = False) -> bool:
    try:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in _TRUTHY
    except Exception:
        return default

def get_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if v is None or str(v).strip() == "":
            return default
        return int(str(v).strip())
    except Exception:
        return default

def get_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except Exception:
        return default

def get_csv(name: str, default: list[str] | None = None, *, sep: str = ",", transform: Callable[[str], str] | None = None) -> list[str]:
    try:
        v = os.getenv(name)
        if v is None:
            return list(default or [])
        parts = [p.strip() for p in v.split(sep) if p.strip()]
        if transform:
            parts = [transform(p) for p in parts]
        return parts
    except Exception:
        return list(default or [])

__all__ = [
    "get_str",
    "get_bool",
    "get_int",
    "get_float",
    "get_csv",
]
