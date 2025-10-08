"""Deprecated synthetic helpers module (synthetic fallback removed).

Retained only as a no-op shim so imports do not fail during deprecation window.
All synthetic quote generation and status classification tied to synthetic
fallback were removed in the 2025-10 cleanup.
"""
from __future__ import annotations
from typing import Dict, Any, Iterable

__all__ = ["generate_synthetic_quotes", "classify_expiry_result"]

def generate_synthetic_quotes(instruments: Iterable[Dict[str, Any]]):  # pragma: no cover - deprecated
    return {}

def classify_expiry_result(expiry_rec: Dict[str, Any], enriched_data: Dict[str, Any]):  # pragma: no cover - deprecated
    expiry_rec.setdefault('options', len(enriched_data))
    return expiry_rec
