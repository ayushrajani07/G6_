"""Phase 3: Strike depth computation extraction.

For now this module provides a thin wrapper around the existing `_build_strikes`
utility imported inside `unified_collectors.py`. The goal is to establish an
abstraction point so future adaptive logic / alternative strategies can plug in
without touching the orchestrator.
"""
from __future__ import annotations

# We intentionally import the same underlying builder to guarantee parity.
try:
    from src.utils.strikes import build_strikes as _legacy_build_strikes
except Exception:  # pragma: no cover
    _legacy_build_strikes = None

__all__ = ["compute_strike_universe"]

def compute_strike_universe(atm: float, n_itm: int, n_otm: int, index_symbol: str, *, scale: float | None = None) -> tuple[list[float], dict]:
    """Return (strike_list, meta) with meta carrying diagnostic info.

    Meta fields (stable contract for future metrics/tests):
      - count
      - atm
      - itm
      - otm
      - scale_applied
    """
    if not isinstance(atm, (int, float)) or atm <= 0:
        return [], {"count": 0, "atm": atm, "itm": n_itm, "otm": n_otm, "scale_applied": scale}
    if _legacy_build_strikes is None:
        # Fallback simplified generation; mirrors fallback path in unified collectors
        step = 100.0 if index_symbol in ('BANKNIFTY','SENSEX') else 50.0
        arr: list[float] = []
        for i in range(1, n_itm + 1):
            arr.append(float(atm - i*step))
        arr.append(float(atm))
        for i in range(1, n_otm + 1):
            arr.append(float(atm + i*step))
        strikes = sorted(arr)
    else:
        strikes = _legacy_build_strikes(atm, n_itm, n_otm, index_symbol, scale=scale)
    return strikes, {"count": len(strikes), "atm": atm, "itm": n_itm, "otm": n_otm, "scale_applied": scale}
