"""Collector error bridge.

Centralizes repetitive `handle_collector_error` invocation patterns used by
`unified_collectors` so the core flow becomes slimmer and future refactors can
swap routing or enrich context in one place.

All helpers swallow exceptions defensively to avoid secondary failures in the
error path. Logging behavior mirrors prior inline usage.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

try:  # direct import if available
    from src.error_handling import handle_collector_error
except Exception:  # pragma: no cover
    # Fallback: dynamic import or None
    try:
        _m = importlib.import_module('src.error_handling')
        handle_collector_error = getattr(_m, 'handle_collector_error', None)
    except Exception:
        handle_collector_error = None

logger = logging.getLogger(__name__)

__all__ = [
    'report_instrument_fetch_error',
    'report_quote_enrich_error',
    'report_no_instruments',
    'report_atm_fallback_error',
]

_COMPONENT = "collectors.unified_collectors"


def _safe_handle(exc: Exception, context: dict[str, Any]) -> None:
    if handle_collector_error is None:  # pragma: no cover
        logger.debug("handle_collector_error_unavailable", exc_info=True)
        return
    try:
        handle_collector_error(exc, component=_COMPONENT, index_name=context.get('index',''), context=context)
    except Exception:  # pragma: no cover
        logger.debug("collector_error_bridge_failure", exc_info=True)


def report_instrument_fetch_error(exc: Exception, index: str, rule: str, expiry: Any, strike_count: int) -> None:
    _safe_handle(exc, {"stage": "get_option_instruments", "rule": rule, "expiry": str(expiry), "strike_count": strike_count, "index": index})


def report_quote_enrich_error(exc: Exception, index: str, rule: str, expiry: Any, instrument_count: int) -> None:
    _safe_handle(exc, {"stage": "enrich_with_quotes", "rule": rule, "expiry": str(expiry), "instrument_count": instrument_count, "index": index})




def report_no_instruments(index: str, rule: str, expiry: Any, strikes: Any, exc_type: type[Exception]) -> None:
    try:
        exc = exc_type(f"No instruments for {index} expiry {expiry} (rule: {rule}) with strikes={strikes}")
    except Exception:  # pragma: no cover
        exc = Exception(f"No instruments for {index} expiry {expiry} (rule: {rule})")
    _safe_handle(exc, {"stage": "get_option_instruments", "rule": rule, "expiry": str(expiry), "strikes": strikes, "index": index})


def report_atm_fallback_error(exc: Exception, index: str) -> None:
    _safe_handle(exc, {"stage": "atm_strike", "fallback": True, "index": index})
