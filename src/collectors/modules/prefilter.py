"""Prefilter (instrument clamp) module.

Extracted from unified_collectors Phase 6 refactor. Provides a single
function `apply_prefilter_clamp` that enforces the G6_PREFILTER_* env
semantics and returns (possibly truncated) instrument list plus optional
metadata for downstream augmentation.

Behavioral parity requirements:
- Honor G6_PREFILTER_MAX_INSTRUMENTS (default 2500, min floor 50)
- Skip when G6_PREFILTER_DISABLE=1
- Emit struct event via helpers.struct_events.emit_prefilter_clamp (best-effort)
- Return clamp_meta tuple (original_count, dropped_count, max_allowed, strict_flag) or None
- Strict mode (G6_PREFILTER_CLAMP_STRICT=1) noted in metadata for later partial_reason assignment

This module is intentionally side-effect minimal except for the optional
struct event emission, which mirrors legacy logic for observability.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

ClampMeta = tuple[int, int, int, bool]


def apply_prefilter_clamp(index_symbol: str, expiry_rule: str, expiry_date: Any, instruments: Sequence[dict]) -> tuple[list[dict], ClampMeta | None]:
    """Apply prefilter clamp logic.

    Parameters
    ----------
    index_symbol : str
        Index being processed.
    expiry_rule : str
        Rule identifier (e.g. this_week, next_week).
    expiry_date : Any
        Resolved expiry date (date or str) for logging.
    instruments : Sequence[dict]
        Raw instrument list from provider.

    Returns
    -------
    (clamped_instruments, clamp_meta)
        clamp_meta is (original_count, dropped_count, max_allowed, strict_flag) or None if no clamp applied.
    """
    disable = os.environ.get('G6_PREFILTER_DISABLE','').lower() in ('1','true','yes','on')
    if disable or not instruments:
        return list(instruments), None

    max_env = os.environ.get('G6_PREFILTER_MAX_INSTRUMENTS')
    strict = os.environ.get('G6_PREFILTER_CLAMP_STRICT','0').lower() in ('1','true','yes','on')
    try:
        max_allowed = int(max_env) if max_env else 2500
    except ValueError:
        max_allowed = 2500
    if max_allowed < 50:
        max_allowed = 50

    original_count = len(instruments)
    if original_count <= max_allowed:
        return list(instruments), None

    kept = list(instruments[:max_allowed])
    dropped_count = original_count - max_allowed

    # Emit struct event (best-effort)
    try:  # pragma: no cover - observability path
        import importlib
        _m = importlib.import_module('src.collectors.helpers.struct_events')
        emit_prefilter_clamp = getattr(_m, 'emit_prefilter_clamp', None)
        if callable(emit_prefilter_clamp):
            emit_prefilter_clamp(
            index=index_symbol,
            expiry=str(expiry_date),
            rule=expiry_rule,
            original_count=original_count,
            kept_count=len(kept),
            dropped_count=dropped_count,
            max_allowed=max_allowed,
            strategy='head',
            disabled=False,
            strict=strict,
            )
    except Exception:
        logger.debug("emit_prefilter_clamp_failed", exc_info=True)

    return kept, (original_count, dropped_count, max_allowed, strict)

__all__ = ["apply_prefilter_clamp", "ClampMeta"]
