"""Persistence flow wrapper.

Extracted from inline block in expiry_processor to reduce its cyclomatic complexity
while preserving exact behavior (zero drift mandate).

Responsibilities:
- Optionally attach allowed_expiry_dates to csv sink
- Invoke persist_with_context (CSV + Influx + metrics emission chain)
- Emit trace hook
- Return PersistResult unchanged
- Provide lightweight aggregation payload pass-through (metrics_payload subset)

NOTE: This module intentionally keeps logic minimal; any future enhancements
(e.g., batching, async IO, retry policies) can be layered here without touching
expiry_processor again.
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Callable, Set
import logging

logger = logging.getLogger(__name__)

try:  # local import guarding
    from src.collectors.helpers.persist import persist_with_context
    from src.collectors.persist_result import PersistResult
except Exception:  # pragma: no cover
    PersistResult = object  # type: ignore
    def persist_with_context(*a, **kw):  # type: ignore
        raise RuntimeError("persist_with_context unavailable")

TraceFn = Callable[[str], None] | Callable[[str, Any], None]


def run_persist_flow(
    ctx,
    enriched_data: Dict[str, Dict[str, Any]],
    expiry_ctx,
    index_ohlc: Any,
    allowed_expiry_dates: Set[Any],
    trace: Callable[..., None],
    concise_mode: bool,
) -> 'PersistResult':
    """Execute persistence & metrics emission.

    Parameters
    ----------
    ctx : CollectorContext-like
        Holds sinks & metrics.
    enriched_data : mapping[str, dict]
        Option data (already enriched).
    expiry_ctx : ExpiryContext
        Bundle of per-expiry identifiers & flags.
    index_ohlc : Any
        OHLC reference for index.
    allowed_expiry_dates : set
        Propagated to csv sink if attribute present (legacy expectation).
    trace : callable
        Structured trace hook (like _trace) for diagnostic logs.
    concise_mode : bool
        Controls verbosity of log level for summary line.

    Returns
    -------
    PersistResult
        Same object as original helper returned; caller inspects .failed / .metrics_payload.
    """
    # Attach allowed expiries if sink supports it (legacy side effect)
    sink = getattr(ctx, 'csv_sink', None)
    if sink is not None:
        try:
            setattr(sink, 'allowed_expiry_dates', allowed_expiry_dates)
        except Exception:  # pragma: no cover
            logger.debug('persist_flow_set_allowed_expiry_dates_failed', exc_info=True)

    # Emit pre-write verbose line (mirrors previous behavior)
    try:
        if not concise_mode:
            logger.info(f"Writing {len(enriched_data)} records to CSV sink")
        else:
            logger.debug(f"Writing {len(enriched_data)} records to CSV sink")
    except Exception:  # pragma: no cover
        pass

    try:
        result = persist_with_context(ctx, enriched_data, expiry_ctx, index_ohlc)
    except Exception:  # pragma: no cover - defensive catch (should already be handled inside helper)
        logger.error('persist_flow_unexpected_exception', exc_info=True)
        # Fabricate a failed PersistResult while avoiding import churn
        try:
            return PersistResult(option_count=0, pcr=None, metrics_payload=None, failed=True)  # type: ignore
        except Exception:
            raise

    # Trace hook (unchanged semantics)
    try:
        trace('persist_done', index=expiry_ctx.index_symbol, rule=expiry_ctx.expiry_rule, options=result.option_count, failed=result.failed)
    except Exception:  # pragma: no cover
        logger.debug('persist_flow_trace_failed', exc_info=True)

    return result

__all__ = ["run_persist_flow"]
