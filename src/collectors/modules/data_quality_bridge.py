"""Data Quality bridge extraction.

Encapsulates initialization and invocation of DataQualityChecker operations.

Public API:
    get_dq_checker() -> DataQualityChecker | None
    run_option_quality(dq, options_data) -> (valid, issues)
    run_expiry_consistency(dq, options_data, index_price, expiry_rule) -> list[str]
    run_index_quality(dq, index_price, index_ohlc) -> (is_valid, issues)

All functions are best-effort; any exception is caught and logged at debug level.
"""
from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)

try:  # protected import
    from src.utils.data_quality import DataQualityChecker as _RealDQ  # pragma: no cover
except Exception:  # pragma: no cover
    _RealDQ = None  # type: ignore[assignment]

class DataQualityChecker:  # runtime facade wrapping real or stub
    def __init__(self, *a: Any, **k: Any) -> None:  # pragma: no cover - pass-through
        if _RealDQ is not None:
            try:
                self._impl = _RealDQ(*a, **k)
            except Exception:
                self._impl = None
        else:
            self._impl = None

    # Delegate methods with graceful fallback
    def validate_options_data(self, *a: Any, **k: Any) -> tuple[dict[str, Any], list[str]]:  # pragma: no cover
        if self._impl is not None:
            return cast(tuple[dict[str, Any], list[str]], self._impl.validate_options_data(*a, **k))
        return {}, ['dq_unavailable']

    def check_expiry_consistency(self, *a: Any, **k: Any) -> list[str]:  # pragma: no cover
        if self._impl is not None:
            return cast(list[str], self._impl.check_expiry_consistency(*a, **k))
        return ['dq_unavailable']

    def validate_index_data(self, *a: Any, **k: Any) -> tuple[bool, list[str]]:  # pragma: no cover
        if self._impl is not None:
            return cast(tuple[bool, list[str]], self._impl.validate_index_data(*a, **k))
        return False, ['dq_unavailable']

__all__ = [
    'get_dq_checker',
    'run_option_quality',
    'run_expiry_consistency',
    'run_index_quality',
]

def get_dq_checker() -> DataQualityChecker | None:  # pragma: no cover (thin wrapper)
    """Instantiate a DataQualityChecker if available.

    Returns None if import or construction fails; failures are suppressed to
    keep collection resilient.
    """
    try:
        return DataQualityChecker()
    except Exception:
        logger.debug('dq_checker_init_failed', exc_info=True)
        return None

def run_option_quality(dq: DataQualityChecker | None, options_data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate per-option data returning a (possibly filtered) mapping and issue list."""
    if dq is None:
        return {}, []
    try:
        valid, issues = dq.validate_options_data(options_data)
        if not isinstance(valid, dict):
            valid = {}
        if not isinstance(issues, list):
            issues = ['dq_internal_malformed']
        return valid, issues
    except Exception:
        logger.debug('dq_validate_options_failed', exc_info=True)
        return {}, ['dq_internal_error']

def run_expiry_consistency(
    dq: DataQualityChecker | None,
    options_data: dict[str, Any],
    index_price: float | None,
    expiry_rule: str | None,
) -> list[str]:
    """Run expiry-level consistency checks, returning issue codes (empty if OK)."""
    if dq is None:
        return []
    try:
        res = dq.check_expiry_consistency(options_data, index_price=index_price, expiry_rule=expiry_rule)
        if isinstance(res, list):
            return [str(r) for r in res]
        return []
    except Exception:
        logger.debug('dq_expiry_consistency_failed', exc_info=True)
        return ['dq_consistency_internal_error']

def run_index_quality(
    dq: DataQualityChecker | None,
    index_price: float | None,
    index_ohlc: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Validate index-level aggregates returning (is_valid, issues)."""
    if dq is None:
        return True, []
    try:
        ok, issues = dq.validate_index_data(index_price, index_ohlc=index_ohlc)
        if not isinstance(ok, bool):
            ok = False
        if not isinstance(issues, list):
            issues = ['dq_index_internal_malformed']
        return ok, issues
    except Exception:
        logger.debug('dq_index_quality_failed', exc_info=True)
        return False, ['dq_index_internal_error']
