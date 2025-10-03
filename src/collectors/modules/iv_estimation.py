"""IV Estimation extraction module.

Wraps legacy `_iv_estimation_block` to provide a stable boundary for the
collector pipeline. Performs optional implied volatility estimation prior to
Greeks computation when enabled.

Public API:
    run_iv_estimation(ctx, enriched_data, index_symbol, expiry_rule, expiry_date,
                      index_price, greeks_calculator, estimate_iv_enabled,
                      risk_free_rate, iv_max_iterations, iv_min, iv_max, iv_precision)

Behavior:
- Calls underlying block only if estimate_iv_enabled and greeks_calculator present
  (mirrors legacy guard usage in unified_collectors where trace emission also
  depended on both conditions).
- Emits trace via imported `_trace` helper if available.
- Silently logs debug on failure (never raises to main loop).
"""
from __future__ import annotations
from typing import Any
import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from src.collectors.helpers.iv_greeks import iv_estimation_block as _iv_estimation_block  # type: ignore
except Exception:  # pragma: no cover
    def _iv_estimation_block(*a, **k):  # type: ignore
        return None

__all__ = ["run_iv_estimation"]


def run_iv_estimation(ctx, enriched_data: dict, index_symbol: str, expiry_rule: str, expiry_date: Any, index_price: float | None,
                      greeks_calculator, estimate_iv_enabled: bool, risk_free_rate: float | None,
                      iv_max_iterations: int | None, iv_min: float | None, iv_max: float | None, iv_precision: float | None):
    if not (estimate_iv_enabled and greeks_calculator):
        return
    try:
        _iv_estimation_block(ctx, enriched_data, index_symbol, expiry_rule, expiry_date, index_price, greeks_calculator,
                             estimate_iv_enabled, risk_free_rate, iv_max_iterations, iv_min, iv_max, iv_precision)
        try:
            from src.broker.kite.tracing import trace  # type: ignore
            trace("iv_estimation_done", index=index_symbol, rule=expiry_rule)
        except Exception:
            pass
    except Exception:
        logger.debug("iv_estimation_failed", exc_info=True)
