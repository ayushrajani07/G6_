"""Data Quality flow wrapper.

Encapsulates the paired option quality + expiry consistency checks that were
inline inside `expiry_processor.process_expiry`. Goal: reduce branching noise
and centralize defensive error handling while preserving logging semantics.

API:
    apply_data_quality(dq_checker, dq_enabled, enriched_data, *, index_symbol,
                       expiry_rule, index_price, expiry_rec,
                       run_option_quality, run_expiry_consistency, logger) -> None

Behavior Notes (mirrors legacy):
  - Skips entirely if dq_checker falsy, dq_enabled False, or enriched_data empty.
  - If option issues present: stores list in expiry_rec['dq_issues'] and logs debug.
  - If consistency issues present: stores list in expiry_rec['dq_consistency'] and logs debug.
  - All exceptions suppressed with debug log.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["apply_data_quality"]


def apply_data_quality(
    dq_checker: Any,
    dq_enabled: bool,
    enriched_data: dict[str, Any],
    *,
    index_symbol: str,
    expiry_rule: str,
    index_price: float | None,
    expiry_rec: dict[str, Any],
    run_option_quality: Callable[..., Any],
    run_expiry_consistency: Callable[..., Any],
) -> None:
    if not (dq_checker and dq_enabled and enriched_data):
        return
    # Option quality
    try:
        _dq_valid, _dq_issues = run_option_quality(dq_checker, enriched_data)
        if _dq_issues:
            expiry_rec['dq_issues'] = list(_dq_issues)
            logger.debug(
                "DQ option issues index=%s rule=%s issues=%s",
                index_symbol,
                expiry_rule,
                _dq_issues[:6],
            )
    except Exception:
        logger.debug('dq_option_quality_failed', exc_info=True)
    # Expiry consistency
    try:
        _cons_issues = run_expiry_consistency(dq_checker, enriched_data, index_price, expiry_rule)
        if _cons_issues:
            expiry_rec['dq_consistency'] = list(_cons_issues)
            logger.debug(
                "DQ expiry consistency issues index=%s rule=%s issues=%s",
                index_symbol,
                expiry_rule,
                _cons_issues,
            )
    except Exception:
        logger.debug('dq_expiry_consistency_failed', exc_info=True)
