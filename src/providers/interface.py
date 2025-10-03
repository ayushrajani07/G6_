#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Typed provider interface for the G6 platform.

This defines the minimal surface that the Providers facade relies on. Concrete
implementations may offer more methods; adapters can normalize them as needed.
"""
from __future__ import annotations

from typing import Protocol, Dict, List, Tuple, Any, Optional
from datetime import date


class Provider(Protocol):
    """Minimal provider protocol used by the Providers facade and collectors."""

    def close(self) -> None:
        ...

    # Quotes / Prices
    def get_quote(self, instruments: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Return quotes keyed by "EXCHANGE:SYMBOL" with at least last_price/ohlc when available."""
        ...

    def get_ltp(self, instruments: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Return last traded price mapping keyed by "EXCHANGE:SYMBOL" with last_price field."""
        ...

    # Options discovery
    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> date:
        ...

    def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: List[int]) -> List[Dict[str, Any]]:
        ...

    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: List[int]) -> List[Dict[str, Any]]:
        ...


__all__ = ["Provider"]
