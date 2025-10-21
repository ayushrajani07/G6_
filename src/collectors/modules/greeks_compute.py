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

import importlib
import logging
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    # Import real helper; fallback to no-op on failure
    from src.collectors.helpers.greeks import compute_greeks_block as _compute_greeks_block_raw
except Exception:  # pragma: no cover
    def _compute_greeks_block_raw(*a: Any, **k: Any) -> None:
        return None

# Provide a typed callable view that accepts our EnrichedData Mapping to avoid Dict invariance issues
_ComputeGreeksBlockSig = Callable[[Any, Mapping[str, MutableMapping[str, Any]], str, str, Any, Any, Any, float, bool, Any, Any], None]
_compute_greeks_block = cast(_ComputeGreeksBlockSig, _compute_greeks_block_raw)

OptionRecord = MutableMapping[str, Any]
EnrichedData = Mapping[str, OptionRecord]

class GreeksCalculatorLike(Protocol):  # minimal surface; expanded later as needed
    # Legacy calculator is passed through; we only require it be truthy for gating
    ...  # pragma: no cover

__all__ = ["run_greeks_compute", "ExpiryCtx", "GreeksCalculatorLike", "EnrichedData", "OptionRecord"]

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


def run_greeks_compute(
    ctx: Any,
    enriched_data: EnrichedData,
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
    per_index_ts: Any,
    greeks_calculator: GreeksCalculatorLike | Any | None,
    risk_free_rate: float | None,
    local_compute_greeks: bool,
    allow_per_option_metrics: bool,
    mp_manager: Any,
    mem_flags: Any,
    index_price: float | None = None,
) -> None:
    """Compute greeks for an expiry, mutating ``enriched_data`` in place.

    Behavior mirrors legacy block: silent debug logging on failure; optional
    trace emission when local compute is enabled and calculator present.

    Parameters kept intentionally loose (Any) where upstream types are still
    dynamic; future tightening can replace Any with Protocols.
    """
    # Build context dataclass (mirrors legacy ExpiryContext minimal subset)
    expiry_ctx = ExpiryCtx(
        index_symbol=index_symbol,
        expiry_rule=expiry_rule,
        expiry_date=expiry_date,
        collection_time=per_index_ts,
        # Use provided upstream index price when available
        index_price=index_price,
        risk_free_rate=risk_free_rate,
        compute_greeks=local_compute_greeks,
        allow_per_option_metrics=allow_per_option_metrics,
    )
    try:
        _compute_greeks_block(ctx, enriched_data, expiry_ctx.index_symbol, expiry_ctx.expiry_rule, expiry_ctx.expiry_date,
                              expiry_ctx.index_price, greeks_calculator, expiry_ctx.risk_free_rate or 0.0,
                              expiry_ctx.compute_greeks, mp_manager, mem_flags)
        if local_compute_greeks and greeks_calculator:
            # Optional trace emission without static import to keep mypy clean
            try:
                mod = importlib.import_module("src.broker.kite.tracing")
                trace = getattr(mod, "trace", None)
                if callable(trace):
                    trace("greeks_compute_done", index=index_symbol, rule=expiry_rule)
            except Exception:
                pass
    except Exception:
        logger.debug("greeks_compute_failed", exc_info=True)


def index_price_is_nan(index_symbol: str, enriched_data: EnrichedData, greeks_calculator: GreeksCalculatorLike | Any | None) -> bool:
    """Deprecated placeholder retained for backward compatibility.

    Always returns False; scheduled for removal once index price logic added.
    """
    return False
