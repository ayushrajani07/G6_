"""Greeks computation extraction module.

Encapsulates the greeks computation block from unified_collectors, standardizing
expiry context construction and trace emission while preserving in-place
mutation of enriched option records.

Public API:
    run_greeks_compute(ctx, enriched_data, index_symbol, expiry_rule, expiry_date,
                       per_index_ts, greeks_calculator, risk_free_rate,
                       local_compute_greeks, allow_per_option_metrics, mp_manager, mem_flags)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from src.collectors.helpers.iv_greeks import compute_greeks_block as _compute_greeks_block  # type: ignore
except Exception:  # pragma: no cover
    def _compute_greeks_block(*a, **k):  # type: ignore
        return None

__all__ = ["run_greeks_compute", "ExpiryCtx"]

@dataclass
class ExpiryCtx:
    index_symbol: str
    expiry_rule: str
    expiry_date: Any
    collection_time: Any
    index_price: float | None
    risk_free_rate: float | None
    compute_greeks: bool
    allow_per_option_metrics: bool


def run_greeks_compute(ctx, enriched_data: dict, index_symbol: str, expiry_rule: str, expiry_date: Any, per_index_ts, greeks_calculator,
                       risk_free_rate: float | None, local_compute_greeks: bool, allow_per_option_metrics: bool,
                       mp_manager, mem_flags):
    # Build context dataclass (mirrors legacy ExpiryContext minimal subset)
    expiry_ctx = ExpiryCtx(
        index_symbol=index_symbol,
        expiry_rule=expiry_rule,
        expiry_date=expiry_date,
        collection_time=per_index_ts,
        index_price=None if index_price_is_nan(index_symbol, enriched_data, greeks_calculator) else None,  # placeholder; real logic may expand later
        risk_free_rate=risk_free_rate,
        compute_greeks=local_compute_greeks,
        allow_per_option_metrics=allow_per_option_metrics,
    )
    try:
        _compute_greeks_block(ctx, enriched_data, expiry_ctx.index_symbol, expiry_ctx.expiry_rule, expiry_ctx.expiry_date,
                              expiry_ctx.index_price, greeks_calculator, expiry_ctx.risk_free_rate or 0.0,
                              expiry_ctx.compute_greeks, mp_manager, mem_flags)
        if local_compute_greeks and greeks_calculator:
            try:
                from src.broker.kite.tracing import trace  # type: ignore
                trace("greeks_compute_done", index=index_symbol, rule=expiry_rule)
            except Exception:
                pass
    except Exception:
        logger.debug("greeks_compute_failed", exc_info=True)


def index_price_is_nan(index_symbol: str, enriched_data: dict, greeks_calculator) -> bool:
    # Placeholder hook for future expansion (e.g., validating index_price upstream)
    return False
