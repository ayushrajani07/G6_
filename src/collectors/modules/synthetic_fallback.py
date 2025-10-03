"""Synthetic quotes fallback extraction.

Verbatim lift of the legacy block inside `expiry_processor.process_expiry` that
conditionally generates synthetic quotes when enrichment returned an empty map.

Contract:
    ensure_synthetic_quotes(enriched_data, instruments, *, index_symbol, expiry_rule,
                            expiry_date, trace, generate_synthetic_quotes, expiry_rec,
                            handle_error) -> (enriched_data, early_return: bool)

Behavior:
 1. If `enriched_data` already truthy: returns unchanged, early_return=False.
 2. Else builds synthetic via provided `generate_synthetic_quotes(instruments)`.
    - If synthetic produced: logs + traces + sets `expiry_rec['synthetic_fallback']=True`.
    - If still empty: logs warning, invokes `handle_error(NoQuotesError(...))` and
      returns (enriched_data, early_return=True) so caller can exit preserving
      original early-return semantics.

Dependencies injected to keep this module pure and avoid tight coupling.
"""
from __future__ import annotations
from typing import Any, Dict, List, Callable, Tuple
import logging

from src.utils.exceptions import NoQuotesError

logger = logging.getLogger(__name__)

__all__ = ["ensure_synthetic_quotes"]


def ensure_synthetic_quotes(
    enriched_data: Dict[str, Any],
    instruments: List[Dict[str, Any]],
    *,
    index_symbol: str,
    expiry_rule: str,
    expiry_date,
    trace: Callable[..., Any],
    generate_synthetic_quotes: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
    expiry_rec: Dict[str, Any],
    handle_error: Callable[[Exception], Any],
) -> Tuple[Dict[str, Any], bool]:
    """Apply synthetic fallback logic.

    Returns (possibly_modified_enriched_map, early_return_flag).
    """
    if enriched_data:  # fast path unchanged
        return enriched_data, False
    try:
        synthetic = generate_synthetic_quotes(instruments)
    except Exception as gen_err:  # defensive – legacy did not expect raise here
        logger.debug("synthetic_generation_failed", exc_info=True)
        synthetic = {}
    if synthetic:
        trace('synthetic_quotes_fallback', index=index_symbol, rule=expiry_rule, count=len(synthetic))
        logger.warning(
            "Synthetic quotes generated for %s %s count=%s (fallback path)",
            index_symbol,
            expiry_rule,
            len(synthetic),
        )
        try:
            expiry_rec['synthetic_fallback'] = True
        except Exception:
            logger.debug('synthetic_flag_set_failed', exc_info=True)
        return synthetic, False
    # No quotes and synthetic empty – mirror legacy warning + error bridge
    logger.warning(
        "No quote data available for %s expiry %s (and synthetic fallback empty)",
        index_symbol,
        expiry_date,
    )
    try:
        handle_error(
            NoQuotesError(
                f"No quotes returned for {index_symbol} expiry {expiry_date} (rule: {expiry_rule}); instruments={len(instruments)}"
            )
        )
    except Exception:
        logger.debug('handle_error_failed', exc_info=True)
    return enriched_data, True
