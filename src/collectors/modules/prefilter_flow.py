"""Prefilter clamp flow wrapper.

Provides a resilient front-end around `apply_prefilter_clamp` replicating the
multi-layered try/except structure previously embedded in `expiry_processor`.

API:
    run_prefilter_clamp(index_symbol, expiry_rule, expiry_date, instruments) -> (instruments, clamp_meta)

Behavior:
  - Honors disable flag (handled inside apply_prefilter_clamp) but protects against
    any unexpected exceptions, logging a debug trace and returning the original
    instrument list with clamp_meta=None.
  - Never raises; mirrors legacy defensive posture.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ClampMeta = tuple[int, int, int, bool]

__all__ = ["run_prefilter_clamp"]


def run_prefilter_clamp(index_symbol: str, expiry_rule: str, expiry_date: Any, instruments: list[dict]) -> tuple[list[dict], ClampMeta | None]:
    try:
        from src.collectors.modules.prefilter import apply_prefilter_clamp
    except Exception:  # pragma: no cover - import error path
        logger.debug('prefilter_module_import_failed', exc_info=True)
        return instruments, None
    try:
        return apply_prefilter_clamp(index_symbol, expiry_rule, expiry_date, instruments)
    except Exception:
        logger.debug('prefilter_apply_failed', exc_info=True)
        return instruments, None
