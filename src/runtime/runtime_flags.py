"""Centralized runtime flags parsing.

Loads environment-driven feature toggles once; exposes a lightweight dataclass
for injection into hot paths (provider filtering). Avoids repeated os.getenv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TRUE_SET = {'1','true','yes','on'}

def _is_true(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.lower() in TRUE_SET

@dataclass(slots=True)
class RuntimeFlags:
    match_mode: str
    underlying_strict: bool
    safe_mode: bool
    enable_forward_fallback: bool
    enable_backward_fallback: bool
    trace_collector: bool
    trace_option_match: bool
    prefilter_disabled: bool

    @classmethod
    def load(cls) -> RuntimeFlags:
        return cls(
            match_mode=os.environ.get('G6_SYMBOL_MATCH_MODE','strict').strip().lower(),
            underlying_strict=_is_true(os.environ.get('G6_SYMBOL_MATCH_UNDERLYING_STRICT'), True if os.environ.get('G6_SYMBOL_MATCH_UNDERLYING_STRICT') is not None else True),
            safe_mode=_is_true(os.environ.get('G6_SYMBOL_MATCH_SAFEMODE'), True),
            enable_forward_fallback=_is_true(os.environ.get('G6_ENABLE_NEAREST_EXPIRY_FALLBACK'), True),
            enable_backward_fallback=_is_true(os.environ.get('G6_ENABLE_BACKWARD_EXPIRY_FALLBACK'), True),
            trace_collector=_is_true(os.environ.get('G6_TRACE_COLLECTOR')),  # default False
            trace_option_match=_is_true(os.environ.get('G6_TRACE_OPTION_MATCH')),  # default False
            prefilter_disabled=_is_true(os.environ.get('G6_DISABLE_PREFILTER')),  # default False
        )

# Lightweight module-level singleton cache (reloadable manually if needed)
_cached: RuntimeFlags | None = None

def get_flags(force_reload: bool = False) -> RuntimeFlags:
    global _cached  # noqa: PLW0603
    if force_reload or _cached is None:
        _cached = RuntimeFlags.load()
    return _cached
