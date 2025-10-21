"""Deprecated synthetic fallback module.

All functionality removed (2025-10 aggressive cleanup). This stub preserves the
public signature of ensure_synthetic_quotes but performs no synthetic generation
and always returns the original data with early_return=False (never marking
synthetic_fallback). Remove this file after downstream dependencies are updated.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["ensure_synthetic_quotes"]

def ensure_synthetic_quotes(
    enriched_data: dict[str, Any],
    instruments: list[dict[str, Any]],
    *,
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
    trace: Callable[..., Any],
    generate_synthetic_quotes: Callable[[list[dict[str, Any]]], dict[str, Any]],
    expiry_rec: dict[str, Any],
    handle_error: Callable[[Exception], Any],
) -> tuple[dict[str, Any], bool]:  # pragma: no cover - inert
    return enriched_data, False
