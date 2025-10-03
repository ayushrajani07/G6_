"""Compatibility shim for older imports.

Older code referenced `src.providers.kite_provider`. The implementation
now lives under `src.broker.kite_provider`. Import and re-export here
so legacy references continue to work without changing call sites.
"""
from __future__ import annotations

try:
    # Re-export everything from the canonical module
    from src.broker.kite_provider import *  # type: ignore  # noqa: F401,F403
except Exception as _e:  # pragma: no cover - defensive
    # Provide a helpful error hint if the broker module is missing
    raise ImportError(
        "src.providers.kite_provider is a shim. Expected src.broker.kite_provider to exist."
    ) from _e
