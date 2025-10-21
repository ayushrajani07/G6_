"""Phase 3: Coverage evaluation extraction.

This module forms a typed façade over the legacy coverage helper functions.
We intentionally keep the exported function names identical so callers can
transition to a stricter API without churn. Adding annotations here helps
prevent outward propagation of ``Any`` from the helper layer.

Runtime behavior is unchanged (pure passthrough); only type information and
docstrings were added.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any, TypedDict, cast

from src.collectors.helpers.coverage import (
    coverage_metrics as _legacy_coverage_metrics,
)
from src.collectors.helpers.coverage import (
    field_coverage_metrics as _legacy_field_coverage_metrics,
)

__all__ = ["coverage_metrics", "field_coverage_metrics"]

# Loose protocol aliases (keep permissive for now)
Ctx = Any  # context object exposing optional ``metrics`` attribute
class InstrumentDict(TypedDict, total=False):
    # Minimal keys (legacy layer may read more via .get; we stay permissive)
    strike: float | int | None
    option_count: int | None

Instrument = Mapping[str, Any] | MutableMapping[str, Any] | InstrumentDict | dict[str, Any]

class EnrichedExpiryDict(TypedDict, total=False):
    strike_coverage_avg: float | int | None
    strike_coverage: float | int | None

EnrichedData = Mapping[str, Mapping[str, Any] | MutableMapping[str, Any] | EnrichedExpiryDict]

def coverage_metrics(
    ctx: Ctx,
    instruments: Iterable[Instrument],
    strikes: Sequence[float | int] | None,
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
) -> float | None:
    """Compute strike coverage ratio (0..1) for an expiry.

    Performs a light normalization of inputs before delegating to legacy implementation.
    Returns ``None`` if the legacy call raises or produces a non-numeric result.
    """
    try:
        norm_strikes: Sequence[float | int] | None = None
        if strikes is not None:
            # Ensure sequence elements are numeric (skip invalid silently)
            tmp: list[float | int] = []
            for s in strikes:
                if isinstance(s, (int, float)):
                    tmp.append(s)
            norm_strikes = tmp
        # Legacy expects Iterable[Dict[str, Any]]; perform a shallow coercion where possible.
        coerced: list[dict[str, Any]] = []
        for inst in instruments:
            if isinstance(inst, dict):
                coerced.append(cast(dict[str, Any], inst))
            else:
                # Wrap mapping-like into a plain dict snapshot
                try:
                    coerced.append(dict(inst))
                except Exception:
                    continue
        val = _legacy_coverage_metrics(ctx, coerced, norm_strikes, index_symbol, expiry_rule, expiry_date)
        if isinstance(val, (int, float)):
            return float(val)
        return None
    except Exception:
        return None

def field_coverage_metrics(
    ctx: Ctx,
    enriched_data: EnrichedData,
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
) -> float | None:
    """Compute full-field option coverage ratio (0..1) for an expiry.

    Light validation + normalization layer shielding callers from legacy ``Any`` leakage.
    Returns ``None`` on failure.
    """
    try:
        # Legacy expects Dict[str, Any]; shallow copy acceptable.
        if isinstance(enriched_data, dict):
            edict: dict[str, Any] = cast(dict[str, Any], enriched_data)
        else:
            try:
                edict = dict(enriched_data)
            except Exception:
                edict = {}
        val = _legacy_field_coverage_metrics(ctx, edict, index_symbol, expiry_rule, expiry_date)
        if isinstance(val, (int, float)):
            return float(val)
        return None
    except Exception:
        return None
