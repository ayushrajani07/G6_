"""SSE / diff merge helpers (Phase 1 extraction).

Objective: decouple panel diff application logic from runtime loop so that
unified loop or future network-driven event sources can reuse consistent
merging semantics.

Current Scope: Provide a pure function merge_panel_diff(base, delta) that
applies additions / updates / removals for simple dict/list structures used
in panel JSON payloads. This is intentionally conservative; deep/nested
structures fallback to overwrite semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REMOVAL_SENTINEL = object()


def merge_panel_diff(base: Any, delta: Any) -> Any:
    """Merge a delta structure into base producing a new merged object.

    Rules (initial pragmatic set):
    - If types differ, return delta (replacement).
    - For dicts:
        * Keys with value == None in delta mean delete key (if present).
        * Keys with value being a REMOVAL_SENTINEL (internal) also delete.
        * Otherwise recursively merge.
    - For lists:
        * If delta list shorter and not empty & contains only primitives: replace.
        * If both lists of dicts and lengths differ modestly (< 50 items), attempt index-wise merge up to min length then append remaining tail from longer.
        * Else replace.
    - For primitives: return delta.
    Defensive: never mutate input arguments.
    """
    # Fast path identity
    if delta is base:
        return delta
    # Type mismatch -> replace
    if type(base) is not type(delta):  # noqa: E721
        return _clone(delta)
    if isinstance(base, dict):
        result: dict[str, Any] = {}
        # start from base
        for k, v in base.items():
            result[k] = _clone(v)
        # apply delta
        for k, v in delta.items():
            if v is None or v is REMOVAL_SENTINEL:
                result.pop(k, None)
                continue
            bv = base.get(k)
            result[k] = merge_panel_diff(bv, v) if k in base else _clone(v)
        return result
    if isinstance(base, list):
        if not base or not delta:
            return _clone(delta)
        # homogenous dict list smallish heuristic
        if (all(isinstance(x, Mapping) for x in base) and all(isinstance(x, Mapping) for x in delta)
                and len(base) < 200 and len(delta) < 200):
            merged = []
            for i in range(min(len(base), len(delta))):
                merged.append(merge_panel_diff(base[i], delta[i]))
            if len(delta) > len(base):
                for i in range(len(base), len(delta)):
                    merged.append(_clone(delta[i]))
            # If delta shorter, we intentionally truncate to delta length to respect explicit shrink
            return merged
        # Fallback replacement semantics
        return _clone(delta)
    # primitives
    return _clone(delta)


def _clone(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [ _clone(x) for x in v ]
    if isinstance(v, dict):
        return { k: _clone(x) for k, x in v.items() }
    return v  # treat unknown objects as immutable

__all__ = ["merge_panel_diff", "REMOVAL_SENTINEL"]
