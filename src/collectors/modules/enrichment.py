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
from typing import Any, Dict, List
import time, logging

logger = logging.getLogger(__name__)

__all__ = ["enrich_quotes"]

# Lightweight exception imports (soft); if unavailable they are treated as generic
try:  # pragma: no cover - defensive
    from src.collectors.unified_collectors import NoQuotesError  # type: ignore
except Exception:  # pragma: no cover
    class NoQuotesError(Exception):  # type: ignore
        pass

try:  # pragma: no cover
    from src.collectors.unified_collectors import handle_collector_error  # type: ignore
except Exception:  # pragma: no cover
    def handle_collector_error(exc: Exception, component: str, index_name: str, context: Dict[str, Any]):  # type: ignore
        logger.debug("handle_collector_error_fallback", exc_info=True)


def enrich_quotes(index_symbol: str, expiry_rule: str, expiry_date, instruments: List[Dict[str, Any]], providers: Any, metrics: Any) -> Dict[str, Any]:
    start = time.time()
    enriched_data: Dict[str, Any] = {}
    try:
        enriched_data = providers.enrich_with_quotes(instruments)
    except (NoQuotesError,) as enrich_err:  # domain-specific path
        handle_collector_error(
            enrich_err,
            component="collectors.unified_collectors",
            index_name=index_symbol,
            context={
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
