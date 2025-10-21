"""Coverage core (Phase 8).

Provides pure aggregation over per-expiry coverage metrics and rolls them up to
index-level summaries. This sits above the lower level coverage metric
functions (coverage_eval / helpers.coverage) and below snapshot building.

Design goals:
- Pure (no side-effects, no logging except debug on unexpected data)
- Safe with partial / missing fields; treats absent metrics as None
- Deterministic averaging (excludes None values from averages)

Public API:
    compute_index_coverage(index_symbol, expiries: list[dict]) -> dict
      Returns structure with per-expiry normalized records and rollup fields.

Expiry input expectation (best-effort):
  Each expiry record may contain:
    - 'rule' (string) optional
    - 'options' (int) option count (0 if missing)
    - 'strike_coverage' (float) optional
    - 'field_coverage' (float) optional

We do not attempt to recompute coverage if fields are missing; caller can
populate via coverage_eval earlier in the pipeline. This module focuses on
normalization + aggregation only.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

Rollup = dict[str, Any]


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f):  # pragma: no cover
            return None
        return f
    except Exception:  # pragma: no cover
        return None


def compute_index_coverage(index_symbol: str, expiries: Iterable[Mapping[str, Any] | dict[str, Any]]) -> Rollup:
    """Aggregate per-expiry coverage metrics into an index-level rollup.

    Parameters
    ----------
    index_symbol: str
        Symbol of the index (e.g., NIFTY)
    expiries: Iterable[Mapping[str, Any]]
        Sequence of expiry dict-like objects possibly containing keys:
        'rule'|'expiry_rule', 'options', 'strike_coverage', 'field_coverage'.

    Returns
    -------
    Rollup dict with keys:
      index, expiries_evaluated, expiries_with_options, options_total,
      strike_coverage_avg, field_coverage_avg, per_expiry (list[dict]), status.
    """
    per_expiry: list[dict[str, Any]] = []
    options_total = 0
    strike_values: list[float] = []
    field_values: list[float] = []
    expiries_with_options = 0

    expiries_list = list(expiries or [])
    for ex in expiries_list:
        rule = ex.get('rule') or ex.get('expiry_rule') or 'unknown'
        opts = ex.get('options')
        try:
            opts_int = int(opts) if opts is not None else 0
        except Exception:  # pragma: no cover
            opts_int = 0
        if opts_int > 0:
            expiries_with_options += 1
        options_total += opts_int
        sc = _safe_float(ex.get('strike_coverage'))
        fc = _safe_float(ex.get('field_coverage'))
        if sc is not None:
            strike_values.append(sc)
        if fc is not None:
            field_values.append(fc)
        per_expiry.append({
            'rule': rule,
            'options': opts_int,
            'strike_coverage': sc,
            'field_coverage': fc,
        })

    def _avg(vals: list[float]) -> float | None:
        if not vals:
            return None
        return sum(vals) / len(vals)

    rollup: Rollup = {
        'index': index_symbol,
        'expiries_evaluated': len(expiries_list),
        'expiries_with_options': expiries_with_options,
        'options_total': options_total,
        'strike_coverage_avg': _avg(strike_values),
        'field_coverage_avg': _avg(field_values),
        'per_expiry': per_expiry,
        'status': 'OK' if options_total > 0 else 'EMPTY',
    }
    return rollup

__all__ = ["compute_index_coverage"]
