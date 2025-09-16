# -*- coding: utf-8 -*-
"""
Symbol utilities for G6 Platform
Standardized symbol handling.
"""

from __future__ import annotations

from typing import Dict, Optional

# Index information
INDEX_INFO = {
    "NIFTY": {
        "display": "Nifty 50",
        "strike_step": 50,
        "segment": "NFO-OPT",
        "exchange": "NSE"
    },
    "BANKNIFTY": {
        "display": "Bank Nifty",
        "strike_step": 100,
        "segment": "NFO-OPT",
        "exchange": "NSE"
    },
    "FINNIFTY": {
        "display": "Fin Nifty",
        "strike_step": 50,
        "segment": "NFO-OPT",
        "exchange": "NSE"
    },
    "MIDCPNIFTY": {
        "display": "Midcap Nifty",
        "strike_step": 25,
        "segment": "NFO-OPT",
        "exchange": "NSE"
    },
    "SENSEX": {
        "display": "Sensex",
        "strike_step": 100,
        "segment": "BFO-OPT",
        "exchange": "BSE"
    }
}

def normalize_symbol(symbol: str) -> Dict[str, str]:
    """
    Normalize a trading symbol to canonical form.
    
    Args:
        symbol: Trading symbol (e.g., "NIFTY", "BANKNIFTY")
        
    Returns:
        Dictionary with normalized symbol information
    """
    if not symbol:
        return {
            "root": "UNKNOWN",
            "display": "Unknown",
            "strike_step": 50,
            "segment": "NFO-OPT",
            "exchange": "NSE"
        }
    
    # Convert to uppercase and remove whitespace
    clean = symbol.strip().upper()
    
    # Check for exact matches
    if clean in INDEX_INFO:
        return {
            "root": clean,
            **INDEX_INFO[clean]
        }
    
    # Check for partial matches
    for key, info in INDEX_INFO.items():
        if clean.startswith(key):
            return {
                "root": key,
                **info
            }
    
    # Default case
    return {
        "root": clean,
        "display": clean,
        "strike_step": 50,
        "segment": "NFO-OPT",
        "exchange": "NSE"
    }

def get_segment(symbol: str) -> Optional[str]:
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