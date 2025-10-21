"""Phase 6: Quote Enrichment Extraction

Parity-focused extraction of the legacy `_enrich_quotes` helper from
`unified_collectors.py`. This module centralizes quote enrichment so that the
pipeline orchestrator can invoke a stable API without reaching back into the
monolith.

Responsibilities:
- Invoke provider `enrich_with_quotes` with a list of instrument dicts.
- Handle known domain exceptions (NoQuotesError) via shared error handler.
- Record latency via metrics.mark_api_call (if provided) mirroring legacy semantics.
- Return an `enriched_data` mapping (symbol/contract identifier -> quote payload).

Future Enhancements:
- Add optional batch retry / fallback tier logic.
- Pluggable synthetic quote generation (currently remains in legacy module; pipeline still defers synthetic fallback for now).

The synthetic fallback generation and preventive validation stage remain in the
legacy path until subsequent extraction phases; this module stays minimal.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["enrich_quotes"]

def _resolve_noquotes_error() -> type[Exception]:  # pragma: no cover - trivial resolution
    try:
        mod = import_module('src.collectors.unified_collectors')
        cls = getattr(mod, 'NoQuotesError', None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls
    except Exception:
        pass
    return Exception


def _resolve_handle_error() -> Callable[[Exception, str, str, dict[str, Any]], Any]:  # pragma: no cover - wrapper
    try:
        mod = import_module('src.collectors.unified_collectors')
        fn = getattr(mod, 'handle_collector_error', None)
        if callable(fn):
            def _adapter(exc: Exception, component: str, index_name: str, context: dict[str, Any]) -> Any:
                try:
                    return fn(exc, component=component, index_name=index_name, context=context)
                except TypeError:
                    try:
                        return fn(exc, component, index_name, context)
                    except Exception:
                        return None
            return _adapter
    except Exception:
        pass
    def _fallback(exc: Exception, component: str, index_name: str, context: dict[str, Any]) -> None:
        logger.debug("handle_collector_error_fallback", exc_info=True)
        return None
    return _fallback


def enrich_quotes(index_symbol: str, expiry_rule: str, expiry_date: Any, instruments: list[dict[str, Any]], providers: Any, metrics: Any) -> dict[str, Any]:
    start = time.time()
    enriched_data: dict[str, Any] = {}
    NoQuotesError = _resolve_noquotes_error()
    handle_collector_error = _resolve_handle_error()
    try:
        enriched_data = providers.enrich_with_quotes(instruments)
    except NoQuotesError as enrich_err:  # domain-specific path
        handle_collector_error(
            enrich_err,
            "collectors.unified_collectors",
            index_symbol,
            {
                "stage": "enrich_with_quotes",
                "rule": expiry_rule,
                "expiry": str(expiry_date),
                "instrument_count": len(instruments),
            },
        )
        enriched_data = {}
    except Exception as enrich_err:  # unexpected failure
        import traceback
        tb = traceback.format_exc(limit=3)
        logger.error(
            f"Unexpected quote enrich error {index_symbol} {expiry_rule}: {enrich_err} | type={type(enrich_err).__name__} tb_snip={tb.strip().replace('\n',' | ')}"
        )
        enriched_data = {}
    elapsed = time.time() - start
    if metrics and hasattr(metrics, "mark_api_call"):
        try:
            metrics.mark_api_call(success=bool(enriched_data), latency_ms=elapsed * 1000.0)
        except Exception:
            logger.debug("metrics_mark_api_call_failed_enrich", exc_info=True)
    return enriched_data
