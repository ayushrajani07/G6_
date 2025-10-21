"""
Symbol utilities for G6 Platform
Standardized symbol handling.
"""

from __future__ import annotations

from typing import TypedDict


class _IndexInfo(TypedDict):
    display: str
    strike_step: int
    segment: str
    exchange: str

# Keyed by root symbol
INDEX_INFO: dict[str, _IndexInfo] = {
    # ... existing entries replaced below
}

INDEX_INFO.update({
    "NIFTY": _IndexInfo(display="Nifty 50", strike_step=50, segment="NFO-OPT", exchange="NSE"),
    "BANKNIFTY": _IndexInfo(display="Bank Nifty", strike_step=100, segment="NFO-OPT", exchange="NSE"),
    "FINNIFTY": _IndexInfo(display="Fin Nifty", strike_step=50, segment="NFO-OPT", exchange="NSE"),
    "MIDCPNIFTY": _IndexInfo(display="Midcap Nifty", strike_step=25, segment="NFO-OPT", exchange="NSE"),
    "SENSEX": _IndexInfo(display="Sensex", strike_step=100, segment="BFO-OPT", exchange="BSE"),
})

class NormalizedSymbol(TypedDict):
    root: str
    display: str
    strike_step: int
    segment: str
    exchange: str


def normalize_symbol(symbol: str) -> NormalizedSymbol:
    """
    Normalize a trading symbol to canonical form.
    
    Args:
        symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY")
        
    Returns:
        Dictionary with normalized symbol information
    """
    if not symbol:
        return NormalizedSymbol(root="UNKNOWN", display="Unknown", strike_step=50, segment="NFO-OPT", exchange="NSE")

    # Convert to uppercase and remove whitespace
    clean = symbol.strip().upper()

    # Check for exact matches
    if clean in INDEX_INFO:
        info = INDEX_INFO[clean]
        return NormalizedSymbol(root=clean, display=info["display"], strike_step=info["strike_step"], segment=info["segment"], exchange=info["exchange"])

    # Check for partial matches
    for key, info in INDEX_INFO.items():
        if clean.startswith(key):
            return NormalizedSymbol(root=key, display=info["display"], strike_step=info["strike_step"], segment=info["segment"], exchange=info["exchange"])

    # Default case
    return NormalizedSymbol(root=clean, display=clean, strike_step=50, segment="NFO-OPT", exchange="NSE")

def get_segment(symbol: str) -> str | None:
    """Get segment for a symbol."""
    norm = normalize_symbol(symbol)
    return norm.get("segment")

def get_exchange(symbol: str) -> str:
    """Get exchange for a symbol."""
    norm = normalize_symbol(symbol)
    return norm.get("exchange", "NSE")

def get_strike_step(symbol: str) -> int:
    """Get strike step for a symbol."""
    norm = normalize_symbol(symbol)
    return norm.get("strike_step", 50)

def get_display_name(symbol: str) -> str:
    """Get display name for a symbol."""
    norm = normalize_symbol(symbol)
    return norm.get("display", symbol)
