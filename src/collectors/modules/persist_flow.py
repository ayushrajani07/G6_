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

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # mypy-only imports
    from src.collectors.persist_result import PersistResult  # pragma: no cover
else:
    class _PersistResultStub:  # lightweight runtime placeholder
        def __init__(self, option_count: int = 0, pcr: Any = None, metrics_payload: Any = None, failed: bool = True) -> None:  # pragma: no cover
            self.option_count = option_count
            self.pcr = pcr
            self.metrics_payload = metrics_payload
            self.failed = failed
    # During runtime (non-TYPE_CHECKING) we expose the stub so callers can still construct a
    # PersistResult-like object in defensive paths without importing the heavy real class.
    # No type: ignore needed because mypy never executes this branch.
    PersistResult = _PersistResultStub
try:  # pragma: no cover
    from src.collectors.helpers.persist import persist_with_context
except Exception:  # pragma: no cover
    def persist_with_context(*a: Any, **kw: Any) -> PersistResult:  # fallback
        raise RuntimeError("persist_with_context unavailable")

TraceFn = Callable[[str], None] | Callable[[str, Any], None]


def run_persist_flow(
    ctx: Any,
    enriched_data: dict[str, dict[str, Any]],
    expiry_ctx: Any,
    index_ohlc: Any,
    allowed_expiry_dates: set[Any],
    trace: Callable[..., None],
    concise_mode: bool,
) -> PersistResult:
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
            sink.allowed_expiry_dates = allowed_expiry_dates
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
            return PersistResult(option_count=0, pcr=None, metrics_payload=None, failed=True)
        except Exception:
            raise

    # Trace hook (unchanged semantics)
    try:
        trace('persist_done', index=expiry_ctx.index_symbol, rule=expiry_ctx.expiry_rule, options=result.option_count, failed=result.failed)
    except Exception:  # pragma: no cover
        logger.debug('persist_flow_trace_failed', exc_info=True)

    return result

__all__ = ["run_persist_flow"]
