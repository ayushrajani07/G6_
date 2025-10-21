"""Central index metadata registry (R1).

Provides a single authoritative source for per-index configuration:
  - display name
  - default strike step size
  - exchange pool / preferred option segment
  - synthetic base ATM (fallback heuristics)
  - weekly expiry weekday (0=Mon..6=Sun)

Other modules should import from here instead of repeating literals.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexMeta:
    symbol: str
    display: str
    step: float
    exchange_pool: str  # e.g. NFO, BFO
    weekly_dow: int     # 0=Mon..6=Sun
    synthetic_atm: int

# Canonical registry
_INDEXES: dict[str, IndexMeta] = {
    "NIFTY": IndexMeta("NIFTY", "Nifty 50", 50.0, "NFO", 3, 24800),
    "BANKNIFTY": IndexMeta("BANKNIFTY", "Bank Nifty", 100.0, "NFO", 3, 54000),
    "FINNIFTY": IndexMeta("FINNIFTY", "Fin Nifty", 50.0, "NFO", 1, 25950),
    "MIDCPNIFTY": IndexMeta("MIDCPNIFTY", "Midcap Nifty Select", 50.0, "NFO", 3, 12000),
    "SENSEX": IndexMeta("SENSEX", "BSE Sensex", 100.0, "BFO", 4, 81000),
}

def get_index_meta(symbol: str) -> IndexMeta:
    s = (symbol or "").upper()
    meta = _INDEXES.get(s)
    if meta:
        # Allow env override of step per index (preserve prior mechanism)
        try:
            ov_key = f"G6_STRIKE_STEP_{s}"
            if ov_key in os.environ:
                step_val = float(os.environ[ov_key])
                if step_val > 0 and step_val != meta.step:
                    return IndexMeta(meta.symbol, meta.display, step_val, meta.exchange_pool, meta.weekly_dow, meta.synthetic_atm)
        except Exception:
            pass
        return meta
    # Fallback generic (treat as 50 step, NFO Thursday)
    return IndexMeta(s, s.title(), 50.0, "NFO", 3, 20000)

__all__ = ["IndexMeta", "get_index_meta"]
