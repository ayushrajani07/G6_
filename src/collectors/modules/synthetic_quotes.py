"""Synthetic quote fallback REMOVED (Aggressive cleanup 2025-10-08).

This module is retained only as an inert stub to avoid import errors during a
short deprecation window. All functions now return empty results / no-ops.
Remove this file after 2025-11-01.
"""
from __future__ import annotations

from typing import Any

__all__ = ["build_synthetic_quotes", "record_synthetic_metrics"]

def build_synthetic_quotes(instruments: list[dict[str, Any]]) -> dict[str, Any]:  # pragma: no cover - stub
    return {}

def record_synthetic_metrics(ctx: Any, index_symbol: str, expiry_date: Any) -> None:  # pragma: no cover - stub
    return None
