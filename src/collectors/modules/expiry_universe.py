"""Phase 2: Expiry universe extraction.

This module wraps (and will eventually supersede) the legacy helper
`helpers.expiry_map.build_expiry_map`. For now we import and re-export the
same implementation to guarantee parity.

Future Enhancements (later phases):
- Add caching / memoization layer keyed by provider universe digest.
- Integrate metrics emission directly (timing, invalid counts) decoupled from
  caller.
- Provide richer stats schema (percentiles of instruments per expiry).
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from typing import Any, cast

# Re-use existing implementation to ensure byte-for-byte behavior
from src.collectors.helpers.expiry_map import build_expiry_map as _legacy_build_expiry_map  # noqa: F401

__all__ = ["build_expiry_map"]

def build_expiry_map(instruments: Iterable[dict[str, Any]]) -> tuple[dict[_dt.date, list[dict[str, Any]]], dict[str, Any]]:
  res = _legacy_build_expiry_map(instruments)
  return cast(tuple[dict[_dt.date, list[dict[str, Any]]], dict[str, Any]] , res)
