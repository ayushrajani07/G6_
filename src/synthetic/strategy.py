"""Unified synthetic strategy module (B4).

Provides a single entrypoint for synthetic index fallback and quote generation.

Goals:
- Centralize deterministic synthetic ATM / price selection (using index_registry metadata).
- Provide helpers for synthetic strike ladder & option instrument fabrication (if needed later).
- Encapsulate quote fabrication heuristics (currently minimal placeholders) with timing metadata.

Public API:
  build_synthetic_index_context(index_symbol) -> SyntheticIndexContext
  build_synthetic_quotes(instruments) -> dict[key->quote]
  synthesize_index_price(index_symbol, price, atm) -> (price, atm, used)

Determinism: Pure functions rely only on index symbol & registry baseline; no randomness.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

class _IndexMetaLike(Protocol):  # minimal protocol for typing
    step: float
    synthetic_atm: float
    symbol: str

try:
    from src.utils.index_registry import get_index_meta  # type: ignore
except Exception:  # pragma: no cover
    def get_index_meta(symbol: str) -> _IndexMetaLike:  # type: ignore
        class _Tmp:
            def __init__(self, sym: str):
                self.step = 50.0
                self.synthetic_atm = 20000.0
                self.symbol = sym
        return _Tmp(symbol)

@dataclass(frozen=True)
class SyntheticIndexContext:
    symbol: str
    step: float
    base_price: float  # synthetic index price injected when real price invalid
    atm: float         # rounded ATM (nearest step)

__all__ = [
    'SyntheticIndexContext',
    'build_synthetic_index_context',
    'synthesize_index_price',
    'build_synthetic_quotes',
]

def build_synthetic_index_context(index_symbol: str) -> SyntheticIndexContext:
    meta = get_index_meta(index_symbol)
    step = float(getattr(meta, 'step', 50.0) or 50.0)
    base_price = float(getattr(meta, 'synthetic_atm', 20000))
    # Round base price to nearest step for ATM
    try:
        atm = round(base_price/step)*step
    except Exception:
        atm = base_price
    return SyntheticIndexContext(symbol=index_symbol.upper(), step=step, base_price=base_price, atm=atm)

def synthesize_index_price(index_symbol: str, index_price, atm_strike) -> tuple[float, float, bool]:
    """Return (index_price, atm, used_synthetic) substituting deterministic synthetic values if needed."""
    used = False
    if (not isinstance(index_price, (int,float)) or index_price <= 0) and (not isinstance(atm_strike,(int,float)) or atm_strike <= 0):
        ctx = build_synthetic_index_context(index_symbol)
        index_price = ctx.base_price
        atm_strike = ctx.atm
        used = True
        logger.debug("SYNTH_STRATEGY index=%s price=%s atm=%s step=%s", ctx.symbol, index_price, atm_strike, ctx.step)
    return float(index_price or 0), float(atm_strike or 0), used

def build_synthetic_quotes(instruments: Iterable[dict[str, Any]]):
    """Fabricate placeholder quotes for a set of option instruments.

    Mirrors previous generate_synthetic_quotes but under strategy namespace for future
    extensibility (e.g., volume pattern injection, skew shaping, or randomized seeds behind flag).
    """
    out: dict[str, dict[str, Any]] = {}
    ts = time.time()
    try:
        for inst in instruments:
            sym = inst.get('tradingsymbol') or inst.get('symbol') or ''
            exch = inst.get('exchange') or 'NFO'
            key = f"{exch}:{sym}" if sym else f"{exch}:{inst.get('strike','?')}:{inst.get('instrument_type','?')}"
            out[key] = {
                'last_price': 0.0,
                'volume': 0,
                'oi': 0,
                'timestamp': ts,
                'ohlc': {'open':0,'high':0,'low':0,'close':0},
                'strike': inst.get('strike') or 0,
                'instrument_type': inst.get('instrument_type') or inst.get('type') or '',
                'synthetic_quote': True,
            }
    except Exception:
        logger.debug('Synthetic quote fabrication failure', exc_info=True)
    return out
