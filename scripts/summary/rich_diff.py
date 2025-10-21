"""Compatibility wrapper for panel hashing (to be removed).

Delegates to `scripts.summary.hashing.compute_all_panel_hashes` while preserving
the historical function name `compute_panel_hashes` used by existing imports and
tests. New code should import from `scripts.summary.hashing` instead.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .hashing import PANEL_KEYS, compute_all_panel_hashes  # re-export


def compute_panel_hashes(status: Mapping[str, Any] | None, *, domain: Any | None = None) -> dict[str,str]:
    return compute_all_panel_hashes(status, domain=domain)

__all__ = ["compute_panel_hashes", "PANEL_KEYS"]
