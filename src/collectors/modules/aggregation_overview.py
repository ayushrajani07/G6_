"""Aggregation Overview Module.

Consolidates per-index overview aggregation + snapshot emission (PCR snapshot +
representative day width) previously handled by `aggregation_emitter`.

This is a straight rename/move to align naming with future additional
aggregation responsibilities (e.g., per-expiry aggregation rollups, advanced
PCR metrics). Behavior intentionally unchanged.

Public API:
    emit_overview_aggregation(ctx, index_symbol, pcr_snapshot, aggregation_state, per_index_ts, expected_expiries)
        -> (representative_day_width, snapshot_base_time)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["emit_overview_aggregation"]


def emit_overview_aggregation(
    ctx: Any,
    index_symbol: str,
    pcr_snapshot: dict[str, Any] | None,
    aggregation_state: Any,
    per_index_ts: Any,
    expected_expiries: Any,
) -> tuple[int, Any]:
    representative_day_width = getattr(aggregation_state, 'representative_day_width', 0)
    snapshot_base_time = getattr(aggregation_state, 'snapshot_base_time', None) or per_index_ts
    try:
        if pcr_snapshot:
            try:
                ctx.csv_sink.write_overview_snapshot(
                    index_symbol,
                    pcr_snapshot,
                    snapshot_base_time,
                    representative_day_width,
                    expected_expiries=expected_expiries,
                )
                if ctx.influx_sink:
                    try:
                        ctx.influx_sink.write_overview_snapshot(
                            index_symbol,
                            pcr_snapshot,
                            snapshot_base_time,
                            representative_day_width,
                            expected_expiries=expected_expiries,
                        )
                    except Exception as ie:  # pragma: no cover
                        logger.debug(f"Influx overview snapshot failed for {index_symbol}: {ie}")
            except Exception as inner:
                logger.error(f"Failed to write aggregated overview snapshot for {index_symbol}: {inner}")
    except Exception:  # pragma: no cover
        logger.debug("aggregation_overview_unexpected_failure", exc_info=True)
    return representative_day_width, snapshot_base_time
