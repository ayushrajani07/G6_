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
from typing import Any, Dict, Tuple, List
import logging

logger = logging.getLogger(__name__)

try:  # protected import
    from src.utils.data_quality import DataQualityChecker  # type: ignore
except Exception:  # pragma: no cover
    DataQualityChecker = None  # type: ignore

__all__ = [
    'get_dq_checker',
    'run_option_quality',
    'run_expiry_consistency',
    'run_index_quality',
]

def get_dq_checker():  # pragma: no cover (thin wrapper)
    try:
        return DataQualityChecker() if DataQualityChecker else None
    except Exception:
        logger.debug('dq_checker_init_failed', exc_info=True)
        return None

def run_option_quality(dq, options_data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    if not dq:
        return {}, []
    try:
        return dq.validate_options_data(options_data)
    except Exception:
        logger.debug('dq_validate_options_failed', exc_info=True)
        return {}, ['dq_internal_error']

def run_expiry_consistency(dq, options_data: Dict[str, Any], index_price: float | None, expiry_rule: str | None):
    if not dq:
        return []
    try:
        return dq.check_expiry_consistency(options_data, index_price=index_price, expiry_rule=expiry_rule)
    except Exception:
        logger.debug('dq_expiry_consistency_failed', exc_info=True)
        return ['dq_consistency_internal_error']

def run_index_quality(dq, index_price, index_ohlc=None):
    if not dq:
        return True, []
    try:
        return dq.validate_index_data(index_price, index_ohlc=index_ohlc)
    except Exception:
        logger.debug('dq_index_quality_failed', exc_info=True)
        return False, ['dq_index_internal_error']
