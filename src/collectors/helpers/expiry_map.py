"""Expiry map builder (B1: Pre-Index Expiry Map).

Build a mapping from expiry_date -> list[InstrumentRecord] (dicts) for a raw
provider instrument universe. This centralizes grouping so downstream code
avoids repeated O(N) scans per expiry.

Contract:
- Input: iterable of instrument dicts. Each dict must expose an expiry field
  accessible via key lookup. We attempt several common keys to stay robust.
- Output: (mapping, stats) where mapping is {expiry_date: [instrument,...]} and
  stats is a dict including counters for diagnostics & tests.

Edge Handling:
- Instruments missing an expiry or with unparsable expiry are counted under
  'invalid_expiry' and skipped.
- Expiry normalization accepts date / datetime / string ISO (YYYY-MM-DD) / any
  object with .date() attribute returning date.

Performance:
- Single pass over input. Appends are O(1). No sorting (caller may sort keys if
  deterministic ordering needed).

Non-Goals:
- No caching across cycles (call site decides lifecycle).
- No mutation of instrument records (passed through as-is).

Environment Flags (future placeholders):
- G6_EXPIRY_MAP_STRICT=1 -> raise on invalid expiry rather than skip (not enabled now).

"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from typing import Any

__all__ = ["build_expiry_map"]

_EXPIRY_KEYS = ("expiry", "expiry_date", "exp", "exdate")


def _normalize_expiry(raw) -> _dt.date | None:
    if raw is None:
        return None
    # Already date
    if isinstance(raw, _dt.date) and not isinstance(raw, _dt.datetime):
        return raw
    # Datetime -> date
    if isinstance(raw, _dt.datetime):
        try:
            return raw.date()
        except Exception:
            return None
    # String ISO
    if isinstance(raw, str):
        s = raw.strip()
        # Expect YYYY-MM-DD minimal validation
        if len(s) == 10 and s[4] == '-' and s[7] == '-':
            y, m, d = s.split('-')
            if y.isdigit() and m.isdigit() and d.isdigit():
                try:
                    return _dt.date(int(y), int(m), int(d))
                except Exception:
                    return None
        return None  # unrecognized string format
    # Object with date() method
    if hasattr(raw, 'date'):
        try:
            val = raw.date()
            if isinstance(val, _dt.date):
                return val
        except Exception:
            return None
    return None


def build_expiry_map(instruments: Iterable[dict[str, Any]]) -> tuple[dict[_dt.date, list[dict[str, Any]]], dict[str, Any]]:
    mapping: dict[_dt.date, list[dict[str, Any]]] = {}
    total = 0
    invalid = 0
    for inst in instruments:
        total += 1
        expiry_val = None
        # Try common keys
        for k in _EXPIRY_KEYS:
            if k in inst:
                expiry_val = inst.get(k)
                if expiry_val is not None:
                    break
        exp_norm = _normalize_expiry(expiry_val)
        if exp_norm is None:
            invalid += 1
            continue
        bucket = mapping.get(exp_norm)
        if bucket is None:
            bucket = []
            mapping[exp_norm] = bucket
        bucket.append(inst)
    stats = {
        'total': total,
        'unique_expiries': len(mapping),
        'invalid_expiry': invalid,
        'valid': total - invalid,
        'avg_per_expiry': ( (total - invalid) / len(mapping) ) if mapping else 0.0,
    }
    return mapping, stats
