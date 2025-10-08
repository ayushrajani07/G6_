"""Deprecated synthetic fallback module.

All functionality removed (2025-10 aggressive cleanup). This stub preserves the
public signature of ensure_synthetic_quotes but performs no synthetic generation
and always returns the original data with early_return=False (never marking
synthetic_fallback). Remove this file after downstream dependencies are updated.
"""
from __future__ import annotations
from typing import Any, Dict, List, Callable, Tuple

__all__ = ["ensure_synthetic_quotes"]

def ensure_synthetic_quotes(
    enriched_data: Dict[str, Any],
    instruments: List[Dict[str, Any]],
    *,
    index_symbol: str,
    expiry_rule: str,
    expiry_date,
    trace: Callable[..., Any],
    generate_synthetic_quotes: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
    expiry_rec: Dict[str, Any],
    handle_error: Callable[[Exception], Any],
) -> Tuple[Dict[str, Any], bool]:  # pragma: no cover - inert
    return enriched_data, False
