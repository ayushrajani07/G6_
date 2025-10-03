"""Synthetic fallback quote generation & classification helpers.

Extracted from unified_collectors to reduce core loop size.
"""
from __future__ import annotations
import time, logging
from typing import Dict, Any, Iterable

logger = logging.getLogger(__name__)

__all__ = ["generate_synthetic_quotes", "classify_expiry_result"]

def generate_synthetic_quotes(instruments: Iterable[Dict[str, Any]]):
    """Deprecated wrapper (B4) – use src.synthetic.strategy.build_synthetic_quotes.

    Retained temporarily for backward imports outside unified path. Emits a one-time
    warning then delegates. Remove after confirming no external imports (target: >=7 days).
    """
    try:
        from src.utils.deprecations import emit_deprecation  # type: ignore
        if not getattr(generate_synthetic_quotes, "_warned", False):  # type: ignore[attr-defined]
            emit_deprecation(
                'synthetic-generate_synthetic_quotes',
                'generate_synthetic_quotes is deprecated; import build_synthetic_quotes from src.synthetic.strategy'
            )
            setattr(generate_synthetic_quotes, "_warned", True)
        from src.synthetic.strategy import build_synthetic_quotes as _bsq  # local import
        return _bsq(instruments)
    except Exception:
        logger.debug('Synthetic quote generation failure (deprecated wrapper)', exc_info=True)
        # Fall back to legacy minimal structure for resilience
        synth_quotes: Dict[str, Dict[str, Any]] = {}
        gen_ts = time.time()
        try:
            for inst in instruments:
                sym = inst.get('tradingsymbol') or inst.get('symbol') or ''
                exch = inst.get('exchange') or 'NFO'
                key = f"{exch}:{sym}" if sym else f"{exch}:{inst.get('strike','?')}:{inst.get('instrument_type','?')}"
                strike_val = inst.get('strike') or 0
                inst_type = (inst.get('instrument_type') or inst.get('type') or '')
                synth_quotes[key] = {
                    'last_price': 0.0,
                    'volume': 0,
                    'oi': 0,
                    'timestamp': gen_ts,
                    'ohlc': {'open':0,'high':0,'low':0,'close':0},
                    'strike': strike_val,
                    'instrument_type': inst_type,
                    'synthetic_quote': True,
                }
        except Exception:
            logger.debug('Synthetic quote generation fallback failure', exc_info=True)
        return synth_quotes

def classify_expiry_result(expiry_rec: Dict[str, Any], enriched_data: Dict[str, Any]):
    """Attach basic classification fields to expiry_rec.

    Currently conservative: if synthetic_fallback True => mark status synthetic; else
    status ok if options>0 else empty. Future: incorporate coverage ratios.
    """
    try:
        options = len(enriched_data)
        expiry_rec['options'] = options
        if expiry_rec.get('synthetic_fallback'):
            expiry_rec['status'] = 'SYNTH'
        elif options == 0:
            expiry_rec['status'] = 'EMPTY'
        else:
            expiry_rec['status'] = 'OK'
    except Exception:  # pragma: no cover
        logger.debug('Expiry classification failed', exc_info=True)
    return expiry_rec
