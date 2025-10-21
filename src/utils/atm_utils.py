"""ATM rounding helpers leveraging centralized index registry.

Provides a single function atm_round(index_symbol, price) that snaps a raw
index price to the nearest valid strike based on the configured step size.
Falls back gracefully to 50 if registry unavailable.
"""
from __future__ import annotations


def atm_round(index_symbol: str, price: float) -> float:
    if not isinstance(price, (int, float)) or price <= 0:
        return 0.0
    step = 50.0
    try:
        from src.utils.index_registry import get_index_meta
        meta = get_index_meta(index_symbol)
        if meta.step > 0:
            step = float(meta.step)
    except Exception:
        pass
    return round(float(price)/step)*step

__all__ = ["atm_round"]
