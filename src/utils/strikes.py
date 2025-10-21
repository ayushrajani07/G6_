"""Strike generation utilities.

Centralizes strike list construction to keep legacy collectors and the new
pipeline path consistent. Previously duplicated logic existed in:
  - collectors/unified_collectors._build_strikes
  - orchestrator/cycle (pipeline branch inline approximation)

Design goals:
  * Deterministic ordering (ascending)
  * Index-specific step sizing (BANKNIFTY/SENSEX use 100, others 50 by default)
  * Graceful handling of invalid ATM or counts (returns empty list)
  * Optional adaptive scale factor application (pre-rounded, min depth guards)
  * Extensible via env overrides for custom step (e.g. G6_STRIKE_STEP_<INDEX>)

Public API:
  build_strikes(atm: float, n_itm: int, n_otm: int, index_symbol: str, *,
                step: float | None = None,
                min_strikes: int = 0,
                scale: float | None = None) -> list[float]

Edge cases:
  - atm <= 0 -> []
  - n_itm/n_otm <= 0 -> still include ATM if atm>0 (ensures at least one strike)
  - scale provided -> apply to n_itm/n_otm then round and clamp >=1 if original >0

Future extensions (not implemented now):
  - Custom per-index rounding rules
  - Dynamic step adjustment based on ATM magnitude (tiers)
"""
from __future__ import annotations

import os

__all__ = ["build_strikes"]

_DEF_WIDE_STEP = 100.0
_DEF_NARROW_STEP = 50.0  # retained as legacy fallback if registry unavailable


def _env_step_override(index_symbol: str) -> float | None:
    key = f"G6_STRIKE_STEP_{index_symbol.upper()}"
    try:
        if key in os.environ:
            val = float(os.environ[key])
            if val > 0:
                return val
    except Exception:
        pass
    return None


def build_strikes(
    atm: float,
    n_itm: int,
    n_otm: int,
    index_symbol: str,
    *,
    step: float | None = None,
    min_strikes: int = 0,
    scale: float | None = None,
) -> list[float]:
    """Return ascending strike list centered on ATM.

    Parameters
    ----------
    atm : float
        At-the-money strike (already normalized/rounded externally).
    n_itm : int
        Number of ITM strikes below ATM.
    n_otm : int
        Number of OTM strikes above ATM.
    index_symbol : str
        Index code (determines default step heuristic).
    step : float, optional
        Explicit step override. If None, heuristic + env override used.
    min_strikes : int, default 0
        Minimum total strikes (excluding enforced ATM) post generation; if generated
        list shorter and atm valid, returns just [atm]. (Reserved for future use)
    scale : float, optional
        Apply scale factor to n_itm/n_otm (used by adaptive depth logic); only applies
        when original count > 0.
    """
    if atm is None or atm <= 0:
        return []
    try:
        _n_itm = int(n_itm or 0)
        _n_otm = int(n_otm or 0)
    except Exception:
        return [float(atm)]
    if scale and scale > 0:
        if _n_itm > 0:
            _n_itm = max(1, int(round(_n_itm * scale)))
        if _n_otm > 0:
            _n_otm = max(1, int(round(_n_otm * scale)))
    if step is None:
        # First env override, then registry meta, finally legacy heuristic
        step = _env_step_override(index_symbol)
        if step is None:
            try:
                from src.utils.index_registry import get_index_meta  # local import to avoid cycles
                step = float(get_index_meta(index_symbol).step)
            except Exception:
                step = _DEF_WIDE_STEP if index_symbol.upper() in ("BANKNIFTY","SENSEX") else _DEF_NARROW_STEP
    if step <= 0:
        step = _DEF_NARROW_STEP
    strikes: list[float] = []
    for i in range(1, _n_itm + 1):
        strikes.append(float(atm - i*step))
    strikes.append(float(atm))
    for i in range(1, _n_otm + 1):
        strikes.append(float(atm + i*step))
    strikes = sorted(set(strikes))
    if min_strikes and len(strikes) < min_strikes and atm > 0:
        return [float(atm)]
    return strikes
